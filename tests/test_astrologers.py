"""Astrologer profiles: applying, approval, presence and the public directory."""
from __future__ import annotations

import pytest

from app.database.connection import session_scope
from app.database.models import Astrologer
from app.services import astrologers
from app.services.errors import ServiceError
from tests.market_helpers import RATE, T0, at, make_astrologer, new_uid, person


async def apply_as(user, **overrides):
    data = {"name": "Acharya Sharma", "bio": "20 years of practice", "languages": ["Hindi", "hindi", " English "],
            "specialties": ["Marriage", "Career"], "experience_years": 20, "chat_rate_paise": 1500}
    data.update(overrides)
    async with session_scope() as db:
        return await astrologers.apply(db, user, data)


class TestApplying:
    async def test_an_application_starts_pending_and_offline(self):
        a = await apply_as(person())
        assert a.status == "pending" and a.is_online is False
        assert a.languages == ["Hindi", "English"]                         # tidied and de-duplicated
        assert a.chat_rate_paise == 1500 and a.call_rate_paise is None

    async def test_at_least_one_priced_mode_is_required(self):
        with pytest.raises(ServiceError) as err:
            await apply_as(person(), chat_rate_paise=None)
        assert err.value.code == "no_rates"

    @pytest.mark.parametrize("rate", [0, 499, 50_001, -5])
    async def test_prices_must_be_reasonable(self, rate):
        with pytest.raises(ServiceError) as err:
            await apply_as(person(), chat_rate_paise=rate)
        assert err.value.code in ("bad_rate", "no_rates")

    async def test_applying_twice_is_refused_until_rejected(self):
        user = person()
        await apply_as(user)
        with pytest.raises(ServiceError) as err:
            await apply_as(user)
        assert err.value.code == "already_applied"
        async with session_scope() as db:
            await astrologers.set_status(db, user.uid, "rejected", "Please add your experience")
        again = await apply_as(user, name="Acharya Sharma Ji")
        assert again.status == "pending" and again.status_note is None and again.name == "Acharya Sharma Ji"

    async def test_payout_and_photo_details_are_checked(self):
        for bad in ({"payout_upi": "not-a-upi"}, {"photo_url": "http://insecure.example/a.jpg"}):
            with pytest.raises(ServiceError):
                await apply_as(person(), **bad)
        a = await apply_as(person(), payout_upi="pandit@okbank", photo_url="https://cdn.example/a.jpg")
        assert a.payout_upi == "pandit@okbank"


class TestApproval:
    async def test_only_sensible_status_changes_are_allowed(self):
        user = person()
        await apply_as(user)
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await astrologers.set_status(db, user.uid, "suspended")      # a pending person cannot be suspended
            assert err.value.code == "bad_transition"
            a = await astrologers.set_status(db, user.uid, "approved")
        assert a.status == "approved" and a.approved_at is not None
        async with session_scope() as db:
            a = await astrologers.set_status(db, user.uid, "suspended", "Complaints")
            assert a.status == "suspended" and a.is_online is False and a.status_note == "Complaints"
            assert (await astrologers.set_status(db, user.uid, "approved")).status == "approved"

    async def test_unknown_astrologer(self):
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await astrologers.set_status(db, "nobody", "approved")
        assert err.value.status == 404


class TestPresence:
    async def test_only_approved_astrologers_can_go_online(self):
        user = await make_astrologer(approved=False)
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await astrologers.set_presence(db, user.uid, True)
        assert err.value.status == 403

    async def test_online_means_a_recent_heartbeat(self):
        user = await make_astrologer(now=T0)
        async with session_scope() as db:
            a = await db.get(Astrologer, user.uid)
            assert astrologers.is_online(a, at(30)) is True
            assert astrologers.is_online(a, at(astrologers.PRESENCE_TTL_SECONDS + 1)) is False   # went quiet: not online

    async def test_going_offline(self):
        user = await make_astrologer()
        async with session_scope() as db:
            await astrologers.set_presence(db, user.uid, False, T0)
            assert astrologers.is_online(await db.get(Astrologer, user.uid), T0) is False

    async def test_polling_keeps_an_online_astrologer_present(self):
        user = await make_astrologer(now=T0)
        async with session_scope() as db:
            await astrologers.touch(db, user.uid, at(80))
            assert astrologers.is_online(await db.get(Astrologer, user.uid), at(150)) is True

    async def test_polling_does_not_bring_an_offline_astrologer_online(self):
        user = await make_astrologer(online=False)
        async with session_scope() as db:
            await astrologers.touch(db, user.uid, T0)
            assert astrologers.is_online(await db.get(Astrologer, user.uid), T0) is False


class TestProfileUpdates:
    async def test_partial_updates_keep_the_rest(self):
        user = await make_astrologer(chat=1000, call=2000)
        async with session_scope() as db:
            a = await astrologers.update_profile(db, user.uid, {"bio": "New bio", "chat_rate_paise": 1200})
        assert a.bio == "New bio" and a.chat_rate_paise == 1200 and a.call_rate_paise == 2000

    async def test_a_mode_can_be_switched_off_but_not_all_of_them(self):
        user = await make_astrologer(chat=1000, call=2000)
        async with session_scope() as db:
            a = await astrologers.update_profile(db, user.uid, {"call_rate_paise": None})
            assert a.call_rate_paise is None
            with pytest.raises(ServiceError) as err:
                await astrologers.update_profile(db, user.uid, {"chat_rate_paise": None})
        assert err.value.code == "no_rates"

    async def test_non_astrologers_cannot_update(self):
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await astrologers.update_profile(db, new_uid(), {"bio": "x"})
        assert err.value.status == 404


class TestDirectory:
    async def listing(self, **kw):
        async with session_scope() as db:
            return await astrologers.directory(db, now=T0, **kw)

    async def test_only_approved_astrologers_are_listed_and_privately_held_fields_stay_hidden(self):
        listed = await make_astrologer(name="Listed Pandit")
        await make_astrologer(approved=False, name="Pending Pandit")
        out = await self.listing(limit=50)
        names = [i["name"] for i in out["items"]]
        assert "Listed Pandit" in names and "Pending Pandit" not in names
        item = next(i for i in out["items"] if i["uid"] == listed.uid)
        assert set(item) == {"uid", "name", "bio", "photo_url", "languages", "specialties", "experience_years",
                             "rates_paise_per_min", "online", "rating", "rating_count", "sessions_count"}
        assert item["rates_paise_per_min"] == {"chat": RATE} and item["online"] is True

    async def test_filters(self):
        tamil = await make_astrologer(languages=("Tamil",), specialties=("Vastu",), call=2500)
        offline = await make_astrologer(languages=("Tamil",), online=False)
        uids = lambda out: {i["uid"] for i in out["items"]}  # noqa: E731
        assert {tamil.uid, offline.uid} <= uids(await self.listing(language="tamil", limit=50))
        assert tamil.uid in uids(await self.listing(specialty="VASTU", limit=50))
        assert tamil.uid in uids(await self.listing(mode="call", limit=50))
        assert offline.uid not in uids(await self.listing(language="Tamil", online_only=True, limit=50))
        assert uids(await self.listing(language="Klingon")) == set()

    async def test_online_astrologers_come_first_then_the_best_rated(self):
        quiet = await make_astrologer(online=False)
        busy = await make_astrologer(online=True)
        async with session_scope() as db:
            (await db.get(Astrologer, quiet.uid)).rating_avg = 5.0
            (await db.get(Astrologer, quiet.uid)).rating_count = 10
        order = [i["uid"] for i in (await self.listing(language="English", limit=50))["items"]]
        assert order.index(busy.uid) < order.index(quiet.uid)

    async def test_sorting_and_paging(self):
        cheap = await make_astrologer(chat=600, languages=("Sortlang",), experience=1)
        dear = await make_astrologer(chat=9000, languages=("Sortlang",), experience=30)
        low = [i["uid"] for i in (await self.listing(language="Sortlang", sort="price_low"))["items"]]
        high = [i["uid"] for i in (await self.listing(language="Sortlang", sort="price_high"))["items"]]
        assert low == [cheap.uid, dear.uid] and high == [dear.uid, cheap.uid]
        exp = [i["uid"] for i in (await self.listing(language="Sortlang", sort="experience"))["items"]]
        assert exp == [dear.uid, cheap.uid]
        page = await self.listing(language="Sortlang", sort="price_low", limit=1, offset=1)
        assert page["total"] == 2 and [i["uid"] for i in page["items"]] == [dear.uid]

    async def test_a_bad_sort_is_rejected(self):
        with pytest.raises(ServiceError):
            await self.listing(sort="nonsense")

    def test_list_cleaning(self):
        assert astrologers.clean_list(["a", "A", " b  c ", "", None, "x" * 99], limit=3, max_len=5) == ["a", "b c", "xxxxx"]
