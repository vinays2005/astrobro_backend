"""Consultations: starting, accepting, minute-by-minute billing, ending, refunds, messages, reviews. Time is controlled."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import get_settings
from app.database.connection import session_scope
from app.database.models import Astrologer, ConsultSession
from app.services import accounts, astrologers, consult, wallet
from app.services.errors import ServiceError
from tests.market_helpers import (RATE, T0, at, balance, bill, earnings, end, fund, get_session, ledger_totals, make_astrologer,
                                  make_client, new_uid, person, say, start, start_and_accept)

EARNED = RATE * 70 // 100                                                  # the astrologer's share of a minute (30% commission)


async def code_of(awaitable) -> str:
    with pytest.raises(ServiceError) as err:
        await awaitable
    return err.value.code


class TestStarting:
    async def test_a_request_is_created_with_the_price_and_commission_fixed(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start(client, astro, topic="  Will I change jobs?  ", birth_data={"name": "A"})
        assert s.status == "requested" and s.rate_paise_per_min == RATE and s.commission_percent == 30
        assert s.topic == "Will I change jobs?" and s.birth_snapshot == {"name": "A"}
        async with session_scope() as db:
            await astrologers.update_profile(db, astro.uid, {"chat_rate_paise": 9000})
        assert (await get_session(s.id)).rate_paise_per_min == RATE        # a later price change does not touch it

    async def test_the_terms_must_be_accepted_first(self):
        client, astro = await make_client(terms=False), await make_astrologer()
        assert await code_of(start(client, astro)) == "terms_required"

    async def test_the_astrologer_must_be_approved_and_online(self):
        client = await make_client()
        assert await code_of(start(client, await make_astrologer(approved=False))) == "not_found"
        assert await code_of(start(client, await make_astrologer(online=False))) == "astrologer_offline"
        quiet = await make_astrologer(now=T0)
        assert await code_of(start(client, quiet, now=at(minutes=5))) == "astrologer_offline"      # heartbeat went stale

    async def test_unknown_astrologer_modes_and_self_consultation(self):
        client = await make_client()
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.start_session(db, client, "nobody", "chat", now=T0)
        assert err.value.status == 404
        astro = await make_astrologer()
        assert await code_of(start(client, astro, "video")) == "mode_not_offered"
        assert await code_of(start(client, astro, "telepathy")) == "bad_mode"
        astro_as_client = astro
        async with session_scope() as db:
            await accounts.accept_terms(db, astro_as_client)
        assert await code_of(start(astro_as_client, astro)) == "self_consult"

    async def test_the_wallet_must_cover_the_minimum_session(self):
        astro = await make_astrologer()
        need = RATE * get_settings().consult_min_minutes
        poor = await make_client(need - 1)
        with pytest.raises(ServiceError) as err:
            await start(poor, astro)
        assert err.value.code == "insufficient_balance" and err.value.status == 402
        assert err.value.extra == {"needed_paise": need, "balance_paise": need - 1}
        assert (await start(await make_client(need), astro)).status == "requested"

    async def test_one_open_consultation_per_user(self):
        client, astro, other = await make_client(), await make_astrologer(), await make_astrologer()
        await start(client, astro)
        assert await code_of(start(client, other)) == "already_in_session"

    async def test_an_unanswered_request_does_not_block_the_user_for_ever(self):
        client, astro, other = await make_client(), await make_astrologer(), await make_astrologer()
        old = await start(client, astro)
        later = at(seconds=get_settings().consult_request_ttl_seconds + 5)
        async with session_scope() as db:
            await astrologers.set_presence(db, other.uid, True, later)
        assert (await start(client, other, now=later)).status == "requested"
        assert (await get_session(old.id)).status == "expired"

    async def test_blocked_accounts_cannot_start(self):
        from app.database.models import Account

        client, astro = await make_client(), await make_astrologer()
        async with session_scope() as db:
            (await db.get(Account, client.uid)).is_blocked = True
        assert await code_of(start(client, astro)) == "blocked"


class TestAcceptingAndBilling:
    async def test_accepting_charges_the_first_minute_and_pays_the_astrologer_their_share(self):
        client, astro = await make_client(20_000), await make_astrologer()
        s = await start_and_accept(client, astro)
        assert s.status == "active" and s.billed_minutes == 1 and s.charged_paise == RATE and s.astrologer_earned_paise == EARNED
        assert await balance(client.uid) == 20_000 - RATE
        assert await earnings(astro.uid) == EARNED
        assert (await ledger_totals(s.id)) == {"charged": RATE, "refunded": 0, "earned": EARNED}

    async def test_the_commission_is_taken_from_every_minute_and_rounding_never_overpays(self):
        astro = await make_astrologer(chat=999)                              # 999 * 70 // 100 = 699 (the platform keeps the odd paisa)
        client = await make_client()
        s = await start_and_accept(client, astro)
        assert s.astrologer_earned_paise == 699 and s.charged_paise - s.astrologer_earned_paise == 300

    async def test_minutes_are_charged_as_they_start(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        assert (await bill(s.id, at(59))).billed_minutes == 1                # still inside minute one
        assert (await bill(s.id, at(60))).billed_minutes == 2                # minute two has started
        assert (await bill(s.id, at(185))).billed_minutes == 4
        assert (await bill(s.id, at(185))).billed_minutes == 4               # asking again charges nothing more
        assert await balance(client.uid) == 20_000 - 4 * RATE
        assert await earnings(astro.uid) == 4 * EARNED

    async def test_a_second_accept_and_a_stranger_cannot_accept(self):
        client, astro, stranger = await make_client(), await make_astrologer(), await make_astrologer()
        s = await start(client, astro)
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.accept_session(db, stranger.uid, s.id, now=T0)
        assert err.value.status == 404
        async with session_scope() as db:
            await consult.accept_session(db, astro.uid, s.id, now=T0)
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.accept_session(db, astro.uid, s.id, now=T0)
        assert err.value.code == "not_pending"
        assert await balance(client.uid) == 20_000 - RATE                    # charged once

    async def test_an_old_request_cannot_be_accepted(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start(client, astro)
        late = at(seconds=get_settings().consult_request_ttl_seconds + 1)
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.accept_session(db, astro.uid, s.id, now=late)
        assert err.value.code == "expired" and err.value.status == 410
        assert await balance(client.uid) == 20_000

    async def test_a_user_who_can_no_longer_pay_gets_a_declined_session_and_no_charge(self):
        client, astro = await make_client(RATE * 5), await make_astrologer()
        s = await start(client, astro)
        async with session_scope() as db:                                    # they spend the money before the astrologer answers
            await wallet.debit(db, client.uid, RATE * 5, "adjustment", "admin", new_uid("spend"))
        async with session_scope() as db:
            out = await consult.accept_session(db, astro.uid, s.id, now=T0)
        assert out.status == "declined" and out.end_reason == "insufficient_balance"
        assert await earnings(astro.uid) == 0

    async def test_a_busy_astrologer_cannot_accept_a_second_consultation_and_nothing_is_charged(self):
        first, second, astro = await make_client(), await make_client(), await make_astrologer()
        await start_and_accept(first, astro)
        s2 = await start(second, astro)
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.accept_session(db, astro.uid, s2.id, now=T0)
        assert err.value.code == "astrologer_busy"
        assert await balance(second.uid) == 20_000                           # the charge was rolled back with the refusal
        assert (await get_session(s2.id)).status == "requested"

    async def test_decline_and_cancel(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start(client, astro)
        async with session_scope() as db:
            assert (await consult.decline_session(db, astro.uid, s.id, now=T0)).status == "declined"
        s2 = await start(client, astro)
        async with session_scope() as db:
            assert (await consult.cancel_request(db, client.uid, s2.id, now=T0)).status == "cancelled"
        assert await balance(client.uid) == 20_000
        s3 = await start_and_accept(client, astro)
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.cancel_request(db, client.uid, s3.id, now=T0)
        assert err.value.code == "not_pending"

    async def test_running_out_of_money_ends_the_session_when_the_next_minute_cannot_be_paid(self):
        client, astro = await make_client(RATE * 5), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(astro.uid, s.id, "Namaste", T0)
        out = await bill(s.id, at(minutes=5, seconds=10))                    # minute 6 would start: only 5 were paid for
        assert out.status == "ended" and out.end_reason == "insufficient_balance" and out.ended_by == "system"
        assert out.billed_minutes == 5 and out.ended_at == at(minutes=5)     # ends where the money ran out, not later
        assert await balance(client.uid) == 0 and await earnings(astro.uid) == 5 * EARNED

    async def test_nobody_can_run_past_three_hours(self):
        astro = await make_astrologer(chat=500)
        client = await make_client(500 * 200)
        s = await start_and_accept(client, astro)
        await say(astro.uid, s.id, "Namaste", T0)
        out = await bill(s.id, at(minutes=181))
        assert out.status == "ended" and out.end_reason == "max_duration" and out.billed_minutes == 180
        assert out.ended_at == at(minutes=180)

    async def test_ending_bills_the_minute_in_progress_first(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(astro.uid, s.id, "Namaste", T0)
        out = await end(client.uid, s.id, at(130))                           # two minutes and ten seconds: three minutes started
        assert out.status == "ended" and out.ended_by == "user" and out.end_reason == "completed" and out.billed_minutes == 3
        assert await balance(client.uid) == 20_000 - 3 * RATE

    async def test_either_side_can_end_and_ending_twice_is_harmless(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(astro.uid, s.id, "Namaste", T0)
        first = await end(astro.uid, s.id, at(10))
        again = await end(client.uid, s.id, at(500))
        assert first.ended_by == "astrologer" and again.ended_by == "astrologer" and again.ended_at == first.ended_at
        assert await balance(client.uid) == 20_000 - RATE

    async def test_ending_a_waiting_request_cancels_or_declines_it(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start(client, astro)
        assert (await end(client.uid, s.id, T0)).status == "cancelled"
        s2 = await start(client, astro)
        assert (await end(astro.uid, s2.id, T0)).status == "declined"

    async def test_strangers_see_nothing(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.end_session(db, new_uid(), s.id, now=T0)
        assert err.value.status == 404 and err.value.code == "not_found"

    async def test_statistics_follow_finished_sessions(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(astro.uid, s.id, "Namaste", T0)
        await end(client.uid, s.id, at(70))
        async with session_scope() as db:
            a = await db.get(Astrologer, astro.uid)
        assert a.sessions_count == 1 and a.minutes_total == 2


class TestRefunds:
    async def test_a_chat_the_astrologer_never_answered_is_refunded_in_full(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        out = await end(client.uid, s.id, at(100))                           # two minutes billed, no reply
        assert out.billed_minutes == 2 and out.refunded_paise == 2 * RATE
        assert await balance(client.uid) == 20_000
        assert await earnings(astro.uid) == 0
        assert (await ledger_totals(s.id)) == {"charged": 2 * RATE, "refunded": 2 * RATE, "earned": 0}

    async def test_a_chat_that_was_answered_is_not_refunded(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(astro.uid, s.id, "Namaste, tell me your question")
        out = await end(client.uid, s.id, at(10))
        assert out.refunded_paise == 0 and await balance(client.uid) == 20_000 - RATE

    async def test_the_users_own_messages_do_not_count_as_an_answer(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(client.uid, s.id, "Hello? Is anyone there?")
        assert (await end(client.uid, s.id, at(10))).refunded_paise == RATE

    async def test_calls_are_not_refunded_automatically(self):
        client, astro = await make_client(), await make_astrologer(call=2000)
        s = await start_and_accept(client, astro, "call")
        assert (await end(client.uid, s.id, at(10))).refunded_paise == 0

    async def test_a_refunded_consultation_cannot_be_reviewed(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        await end(client.uid, s.id, at(10))
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.add_review(db, client.uid, s.id, 5, "great")
        assert err.value.code == "not_reviewable"

    async def test_a_refund_after_a_system_ending_also_returns_the_money(self):
        client, astro = await make_client(RATE * 5), await make_astrologer()
        s = await start_and_accept(client, astro)
        out = await bill(s.id, at(minutes=5, seconds=5))                     # ran out of money and nobody ever replied
        assert out.end_reason == "insufficient_balance" and out.refunded_paise == 5 * RATE
        assert await balance(client.uid) == RATE * 5


class TestMoneyIsAlwaysConsistent:
    async def test_the_books_balance_after_a_busy_mix_of_sessions(self):
        astro = await make_astrologer()
        results = []
        for i in range(4):
            client = await make_client(RATE * 12)
            s = await start_and_accept(client, astro)
            if i % 2 == 0:
                await say(astro.uid, s.id, "Namaste")
            minutes = 2 + i
            await end(client.uid, s.id, at(minutes=minutes, seconds=5))
            results.append((client, s.id))
        owed = await earnings(astro.uid)
        users_paid = earned_total = 0
        for client, sid in results:
            totals = await ledger_totals(sid)
            net = totals["charged"] - totals["refunded"]
            users_paid += net
            earned_total += totals["earned"]
            assert await balance(client.uid) == RATE * 12 - net              # no money appeared or vanished for the user
            assert totals["earned"] == net * 70 // 100                       # exactly the astrologer's share of what stuck
        assert owed == earned_total
        assert owed <= users_paid                                           # the astrologer is never owed more than users paid


class TestMessages:
    async def test_both_sides_can_talk_while_the_session_is_active(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(client.uid, s.id, "I was born on 15-08-1990 at 14:30 in Mumbai. When will I marry?")
        await say(astro.uid, s.id, "Your seventh house is strong.")
        async with session_scope() as db:
            msgs, view = await consult.messages_after(db, client.uid, s.id, 0)
        assert [m["kind"] for m in msgs] == ["system", "text", "text"]       # "Consultation started" comes first
        assert view["status"] == "active" and view["role"] == "user"
        async with session_scope() as db:
            later, _ = await consult.messages_after(db, astro.uid, s.id, msgs[1]["id"])
        assert [m["body"] for m in later] == ["Your seventh house is strong."]

    async def test_messages_need_an_active_chat_between_the_two_people(self):
        client, astro = await make_client(), await make_astrologer(call=2000)
        waiting = await start(client, astro)
        assert await code_of(say(client.uid, waiting.id, "hi")) == "session_ended"
        async with session_scope() as db:
            await consult.cancel_request(db, client.uid, waiting.id, now=T0)
        s = await start_and_accept(client, astro)
        assert await code_of(say(new_uid(), s.id, "hi")) == "not_found"
        await end(client.uid, s.id, at(10))
        assert await code_of(say(client.uid, s.id, "still there?")) == "session_ended"
        call = await start_and_accept(client, astro, "call")
        assert await code_of(say(client.uid, call.id, "hi")) == "not_a_chat"

    @pytest.mark.parametrize("text,code", [("", "empty_message"), ("   ", "empty_message"), ("x" * 2001, "too_long"),
                                           ("call me 9876543210", "contact_blocked"), ("me@mail.com", "contact_blocked"),
                                           ("visit www.example.com", "contact_blocked")])
    async def test_empty_long_and_contact_messages_are_refused(self, text, code):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        assert await code_of(say(client.uid, s.id, text)) == code

    async def test_contact_blocking_can_be_switched_off(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "block_contact_sharing", False)
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        assert (await say(client.uid, s.id, "call me 9876543210")).body == "call me 9876543210"

    async def test_a_session_out_of_money_stops_accepting_messages(self):
        client, astro = await make_client(RATE * 5), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(astro.uid, s.id, "Namaste")
        assert await code_of(say(client.uid, s.id, "one more thing", at(minutes=6))) == "session_ended"

    async def test_activity_resets_the_idle_clock(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(client.uid, s.id, "hello", at(300))
        assert (await get_session(s.id)).last_activity_at == at(300)


class TestSweep:
    async def run(self, now):
        async with session_scope() as db:
            return await consult.sweep(db, now=now)

    async def test_unanswered_requests_expire_but_fresh_ones_stay(self):
        client, other, astro = await make_client(), await make_client(), await make_astrologer()
        old = await start(client, astro, now=T0)
        ttl = get_settings().consult_request_ttl_seconds
        async with session_scope() as db:
            await astrologers.set_presence(db, astro.uid, True, at(ttl))        # still checking in two minutes later
        fresh = await start(other, astro, now=at(ttl))
        counts = await self.run(at(ttl + 1))
        assert counts["expired"] >= 1
        assert (await get_session(old.id)).status == "expired" and (await get_session(fresh.id)).status == "requested"

    async def test_the_sweeper_bills_running_sessions(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        async with session_scope() as db:
            await astrologers.set_presence(db, astro.uid, True, at(150))     # still checking in
        await self.run(at(150))
        assert (await get_session(s.id)).billed_minutes == 3

    async def test_a_chat_nobody_writes_in_is_closed_as_idle(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        await say(astro.uid, s.id, "Namaste", T0)
        idle = get_settings().consult_idle_timeout_seconds
        async with session_scope() as db:
            await astrologers.set_presence(db, astro.uid, True, at(idle + 20))
        await self.run(at(idle + 20))
        out = await get_session(s.id)
        assert out.status == "ended" and out.end_reason == "idle" and out.ended_by == "system"

    async def test_a_call_is_not_closed_for_silence(self):
        client, astro = await make_client(RATE * 100), await make_astrologer(call=RATE)
        s = await start_and_accept(client, astro, "call")
        async with session_scope() as db:
            await astrologers.set_presence(db, astro.uid, True, at(minutes=15))
        await self.run(at(minutes=15))
        assert (await get_session(s.id)).status == "active"

    async def test_an_astrologer_who_vanishes_ends_the_session_and_the_user_is_refunded(self):
        client, astro = await make_client(), await make_astrologer(now=T0)
        s = await start_and_accept(client, astro)
        await self.run(at(seconds=consult.ASTROLOGER_SILENCE_SECONDS + 30))
        out = await get_session(s.id)
        assert out.status == "ended" and out.end_reason == "astrologer_offline" and out.refunded_paise == out.charged_paise > 0
        assert await balance(client.uid) == 20_000

    async def test_quiet_astrologers_are_marked_offline(self):
        astro = await make_astrologer(now=T0)
        await self.run(at(astrologers.PRESENCE_TTL_SECONDS + 1))
        async with session_scope() as db:
            assert (await db.get(Astrologer, astro.uid)).is_online is False

    async def test_a_sweep_with_nothing_to_do_is_quiet(self):
        counts = await self.run(at(minutes=1))
        assert set(counts) == {"expired", "ended", "offline"}


class TestReviewsAndReports:
    async def finished(self, rate=RATE):
        client, astro = await make_client(), await make_astrologer(chat=rate)
        s = await start_and_accept(client, astro)
        await say(astro.uid, s.id, "Namaste")
        await end(client.uid, s.id, at(30))
        return client, astro, s

    async def test_the_client_can_review_once_and_the_rating_updates(self):
        client, astro, s = await self.finished()
        async with session_scope() as db:
            await consult.add_review(db, client.uid, s.id, 4, "Very helpful")
        async with session_scope() as db:
            a = await db.get(Astrologer, astro.uid)
            assert (a.rating_avg, a.rating_count) == (4.0, 1)
            with pytest.raises(ServiceError) as err:
                await consult.add_review(db, client.uid, s.id, 5, None)
        assert err.value.code == "already_reviewed"

    async def test_the_average_over_several_clients(self):
        astro = await make_astrologer()
        for rating in (5, 4, 3):
            client = await make_client()
            s = await start_and_accept(client, astro)
            await say(astro.uid, s.id, "Namaste")
            await end(client.uid, s.id, at(30))
            async with session_scope() as db:
                await consult.add_review(db, client.uid, s.id, rating, None)
        async with session_scope() as db:
            a = await db.get(Astrologer, astro.uid)
        assert a.rating_count == 3 and a.rating_avg == pytest.approx(4.0)

    async def test_review_rules(self):
        client, astro, s = await self.finished()
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.add_review(db, astro.uid, s.id, 5, "I am great")        # the astrologer cannot review themselves
            assert err.value.code == "not_the_client"
            for bad in (0, 6):
                with pytest.raises(ServiceError):
                    await consult.add_review(db, client.uid, s.id, bad, None)
            with pytest.raises(ServiceError) as err:
                await consult.add_review(db, client.uid, s.id, 5, "call 9876543210 for a discount")
            assert err.value.code == "contact_blocked"
        live_client = await make_client()
        live = await start_and_accept(live_client, astro)
        async with session_scope() as db:
            with pytest.raises(ServiceError) as err:
                await consult.add_review(db, live_client.uid, live.id, 5, None)       # not finished yet
        assert err.value.code == "not_reviewable"

    async def test_abuse_reports_name_the_other_person(self):
        client, astro, s = await self.finished()
        async with session_scope() as db:
            by_client = await consult.report_abuse(db, client.uid, s.id, "abuse", " rude ")
            by_astro = await consult.report_abuse(db, astro.uid, s.id, "spam", None)
            assert (by_client.target_uid, by_client.details) == (astro.uid, "rude")
            assert by_astro.target_uid == client.uid
            with pytest.raises(ServiceError):
                await consult.report_abuse(db, client.uid, s.id, "boring", None)
            with pytest.raises(ServiceError) as err:
                await consult.report_abuse(db, new_uid(), s.id, "abuse", None)
        assert err.value.status == 404


class TestViews:
    async def test_participants_see_different_things(self):
        client, astro = await make_client(), await make_astrologer(call=2000)
        s = await start_and_accept(client, astro, "call")
        now = at(30)
        user_view = consult.session_view(await get_session(s.id), "user", now)
        astro_view = consult.session_view(await get_session(s.id), "astrologer", now)
        assert "user_uid" not in user_view and "birth_data" not in user_view
        assert astro_view["user_uid"] == client.uid and astro_view["earned_paise"] == 2000 * 70 // 100
        assert user_view["join_url"].startswith("https://meet.jit.si/astrobro-") and user_view["paid_until"] is not None

    async def test_the_join_link_exists_only_while_a_call_is_active(self):
        client, astro = await make_client(), await make_astrologer(call=2000)
        s = await start_and_accept(client, astro, "call")
        await end(client.uid, s.id, at(5))
        assert consult.session_view(await get_session(s.id), "user", at(10))["join_url"] is None

    async def test_a_waiting_request_reads_as_expired_once_its_time_is_up(self):
        client, astro = await make_client(), await make_astrologer()
        s = await get_session((await start(client, astro)).id)
        assert consult.effective_status(s, at(10)) == "requested"
        assert consult.effective_status(s, at(seconds=get_settings().consult_request_ttl_seconds + 1)) == "expired"

    async def test_my_sessions_lists_by_role(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start_and_accept(client, astro)
        async with session_scope() as db:
            mine = await consult.my_sessions(db, client.uid, "user")
            theirs = await consult.my_sessions(db, astro.uid, "astrologer")
            nothing = await consult.my_sessions(db, client.uid, "astrologer")
        assert [x["id"] for x in mine] == [s.id] and [x["id"] for x in theirs] == [s.id] and nothing == []

    async def test_the_astrologer_inbox(self):
        client, other, astro = await make_client(), await make_client(), await make_astrologer()
        s = await start(client, astro)
        async with session_scope() as db:
            inbox = await consult.astrologer_inbox(db, astro.uid, now=T0)
        assert [r["id"] for r in inbox["requests"]] == [s.id] and inbox["active"] is None
        async with session_scope() as db:
            await consult.accept_session(db, astro.uid, s.id, now=T0)
        async with session_scope() as db:
            inbox = await consult.astrologer_inbox(db, astro.uid, now=T0)
        assert inbox["requests"] == [] and inbox["active"]["id"] == s.id
