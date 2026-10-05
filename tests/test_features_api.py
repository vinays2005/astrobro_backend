"""HTTP-level tests for the feature endpoints: routing, validation, auth, language and voice."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.llm.prompts import SYSTEM_ASTROLOGER, system_prompt
from app.main import app
from app.security.auth import require_api_key
from app.services import languages, speech

BIRTH = {"name": "Arjun", "date_of_birth": "1990-08-15", "time_of_birth": "14:30", "timezone": "Asia/Kolkata",
         "latitude": 19.076, "longitude": 72.8777}
BIRTH2 = {"name": "Meera", "date_of_birth": "1992-03-02", "time_of_birth": "09:10", "timezone": "Asia/Kolkata",
          "latitude": 28.6139, "longitude": 77.2090}


@pytest.fixture
async def client():
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=120) as ac:
        yield ac
    app.dependency_overrides.clear()


class TestRouting:
    def test_all_feature_paths_are_registered(self):
        paths = {r.path for r in app.routes}
        expected = {
            "/api/horoscope/all", "/api/horoscope/{sign}", "/api/horoscope/personal", "/api/transit/current",
            "/api/transit/natal", "/api/transit/sade-sati", "/api/transit/events", "/api/dasha/timeline",
            "/api/dosha/analyze", "/api/remedies/personal", "/api/remedies/planet/{planet}", "/api/remedies/doshas",
            "/api/kundli/match", "/api/kundli/match/detailed", "/api/love/calculate", "/api/numerology/profile",
            "/api/numerology/compatibility", "/api/numerology/daily", "/api/tarot/draw", "/api/tarot/daily",
            "/api/tarot/cards", "/api/tarot/cards/{card_id}", "/api/tarot/spreads", "/api/vastu/analyze",
            "/api/vastu/guidelines", "/api/muhurat/types", "/api/muhurat/find", "/api/calendar/festivals",
            "/api/calendar/upcoming", "/api/calendar/today", "/api/intent/classify", "/api/intent/categories",
            "/api/voice/transcribe", "/api/notifications/feed", "/api/languages", "/api/features", "/api/panchang",
        }
        assert expected <= paths, expected - paths


class TestAuth:
    async def test_new_endpoints_require_the_api_key(self, monkeypatch):
        import app.security.auth as auth
        monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key="s3cret"))
        app.dependency_overrides.clear()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for path in ("/api/horoscope/all", "/api/features", "/api/languages", "/api/tarot/spreads", "/api/muhurat/types"):
                assert (await c.get(path)).status_code == 401, path
            assert (await c.get("/api/horoscope/all", headers={"X-API-Key": "wrong"})).status_code == 401
            assert (await c.get("/api/horoscope/all", headers={"X-API-Key": "s3cret"})).status_code == 200
            assert (await c.post("/api/intent/classify", json={"text": "hi"})).status_code == 401


class TestHoroscopeApi:
    async def test_sign_and_all(self, client):
        r = await client.get("/api/horoscope/Mesha?period=weekly&date=2026-10-05")
        assert r.status_code == 200 and r.json()["sign"] == "Aries" and len(r.json()["daily"]) == 7
        allr = (await client.get("/api/horoscope/all")).json()
        assert len(allr["signs"]) == 12 and {s["sign"] for s in allr["signs"]} == set(__import__("app.astrology.constants", fromlist=["SIGNS"]).SIGNS)

    async def test_errors(self, client):
        assert (await client.get("/api/horoscope/ophiuchus")).status_code == 404
        assert (await client.get("/api/horoscope/leo?period=decade")).status_code == 422
        assert (await client.get("/api/horoscope/leo?tz=Mars/Olympus")).status_code == 422
        assert (await client.get("/api/horoscope/leo?date=not-a-date")).status_code == 422

    async def test_personal(self, client):
        r = await client.post("/api/horoscope/personal", json={"birth_data": BIRTH, "period": "today", "date": "2026-10-05"})
        body = r.json()
        assert r.status_code == 200 and body["personal"]["natal"]["moon_sign"] == "Taurus"
        assert body["personal"]["tara_bala"]["tara"] and body["personal"]["dasha"]["mahadasha"]["lord"] == "Jupiter"

    async def test_bad_birth_details(self, client):
        bad = {**BIRTH, "latitude": 200}
        assert (await client.post("/api/horoscope/personal", json={"birth_data": bad})).status_code == 422
        bad2 = {**BIRTH, "timezone": "Nowhere/Land"}      # unknown tz silently becomes UTC in the engine: still a valid chart
        assert (await client.post("/api/dasha/timeline", json={"birth_data": bad2})).status_code in (200, 400)


class TestChartApis:
    async def test_transits(self, client):
        cur = (await client.get("/api/transit/current")).json()
        assert len(cur["planets"]) == 9 and cur["moon_phase"]
        nat = (await client.post("/api/transit/natal", json={"birth_data": BIRTH, "date": "2026-10-05"})).json()
        assert len(nat["from_moon"]) == 9 and nat["natal"]["lagna"] == "Scorpio" and "scores" in nat
        ss = (await client.post("/api/transit/sade-sati", json={"birth_data": BIRTH})).json()
        assert ss["moon_sign"] == "Taurus" and ss["active"] is False
        ev = (await client.get("/api/transit/events?start=2026-10-05&days=45&planets=Jupiter")).json()
        assert any(e["title"] == "Jupiter enters Leo" for e in ev["events"])
        assert (await client.get("/api/transit/events?planets=Vulcan")).status_code == 422
        assert (await client.get("/api/transit/events?days=9999")).status_code == 422

    async def test_dasha(self, client):
        r = (await client.post("/api/dasha/timeline", json={"birth_data": BIRTH, "depth": "praty", "years_ahead": 10})).json()
        assert r["current"]["mahadasha"]["lord"] == "Jupiter" and len(r["mahadashas"]) == 9
        assert any(a.get("pratyantardashas") for m in r["mahadashas"] for a in m.get("antardashas", []))
        maha_only = (await client.post("/api/dasha/timeline", json={"birth_data": BIRTH, "depth": "maha"})).json()
        assert "antardashas" not in maha_only["mahadashas"][0]

    async def test_dosha_and_remedies(self, client):
        d = (await client.post("/api/dosha/analyze", json={"birth_data": BIRTH})).json()
        assert {"Manglik (Kuja) Dosha", "Kaal Sarp Dosha", "Sade Sati"} <= {x["name"] for x in d["doshas"]}
        assert d["remedies"] and d["disclaimer"]
        nor = (await client.post("/api/dosha/analyze", json={"birth_data": BIRTH, "include_remedies": False})).json()
        assert "remedies" not in nor
        r = (await client.post("/api/remedies/personal", json={"birth_data": BIRTH})).json()
        assert r["running_dasha"]["mahadasha"] == "Jupiter" and r["remedies"] and "dosha_remedies" in r
        assert (await client.get("/api/remedies/planet/saturn")).json()["mantra"]["beej"].startswith("Om Pram")
        assert (await client.get("/api/remedies/planet/vulcan")).status_code == 404

    async def test_matching(self, client):
        r = await client.post("/api/kundli/match/detailed", json={"person1": BIRTH, "person2": BIRTH2})
        body = r.json()
        assert r.status_code == 200 and body["boy"]["name"] == "Arjun" and body["girl"]["name"] == "Meera"
        swapped = (await client.post("/api/kundli/match/detailed",
                                     json={"person1": BIRTH, "person2": BIRTH2, "person1_role": "bride"})).json()
        assert swapped["girl"]["name"] == "Arjun" and swapped["boy"]["name"] == "Meera"
        old = (await client.post("/api/kundli/match", json={"person1": BIRTH, "person2": BIRTH2})).json()
        assert old["max_score"] == 36 and set(old["breakdown"]) == {"varna", "vashya", "tara", "yoni", "graha_maitri",
                                                                    "gana", "bhakut", "nadi"}
        assert old["person1"]["moon_sign"] == "Taurus"

    async def test_love(self, client):
        plain = (await client.post("/api/love/calculate", json={"name1": "Arjun", "name2": "Meera"})).json()
        assert "astrological" not in plain and plain["flames"]["result"]
        full = (await client.post("/api/love/calculate", json={"name1": "A", "name2": "M", "birth1": BIRTH, "birth2": BIRTH2})).json()
        assert "astrological" in full
        assert (await client.post("/api/love/calculate", json={"name1": "", "name2": "x"})).status_code == 422


class TestDivinationApis:
    async def test_numerology(self, client):
        p = (await client.post("/api/numerology/profile", json={"name": "Arjun Sharma", "date_of_birth": "1990-08-15", "date": "2026-10-05"})).json()
        assert p["life_path"]["number"] == 6 and p["indian"]["mulank"] == 6
        assert (await client.post("/api/numerology/profile", json={"name": "x", "date_of_birth": "1990-13-45"})).status_code == 422
        odd = await client.post("/api/numerology/profile", json={"name": "A", "date_of_birth": "1990-08-15"})
        assert odd.status_code == 200 and odd.json()["personality"]["number"] is None
        hindi = await client.post("/api/numerology/profile", json={"name": "राम", "date_of_birth": "1990-08-15"})
        assert hindi.status_code == 422 and "English letters" in hindi.json()["detail"]
        pair = await client.post("/api/numerology/compatibility", json={"person1": {"name": "123", "date_of_birth": "1990-08-15"},
                                                                       "person2": {"name": "B", "date_of_birth": "1992-03-02"}})
        assert pair.status_code == 422
        c = await client.post("/api/numerology/compatibility", json={"person1": {"name": "A", "date_of_birth": "1990-08-15"},
                                                                    "person2": {"name": "B", "date_of_birth": "1992-03-02"}})
        assert c.status_code == 200 and 0 <= c.json()["score"] <= 100
        assert (await client.get("/api/numerology/daily?date_of_birth=1990-08-15&date=2026-10-05")).json()["number"] in range(1, 10)

    async def test_tarot(self, client):
        assert len((await client.get("/api/tarot/spreads")).json()["spreads"]) == 7
        assert (await client.get("/api/tarot/cards")).json()["count"] == 78
        assert (await client.get("/api/tarot/cards?arcana=major")).json()["count"] == 22
        assert (await client.get("/api/tarot/cards?suit=cups")).json()["count"] == 14
        assert (await client.get("/api/tarot/cards/major-16")).json()["name"] == "The Tower"
        assert (await client.get("/api/tarot/cards/nope")).status_code == 404
        a = (await client.post("/api/tarot/draw", json={"spread": "love", "seed": "x1", "question": "Will it work?"})).json()
        b = (await client.post("/api/tarot/draw", json={"spread": "love", "seed": "x1", "question": "Will it work?"})).json()
        assert a == b and len(a["readings"]) == 5 and "ai_interpretation" not in a
        assert (await client.post("/api/tarot/draw", json={"spread": "tower_of_babel"})).status_code == 422
        d1 = (await client.get("/api/tarot/daily?user_key=u1&date=2026-10-05")).json()
        assert d1 == (await client.get("/api/tarot/daily?user_key=u1&date=2026-10-05")).json()

    async def test_tarot_ai_interpretation_and_graceful_failure(self, client, monkeypatch):
        import app.agents.singleton as singleton
        ok = SimpleNamespace(_llm=SimpleNamespace(generate=AsyncMock(return_value="  A balanced reading.  ")))
        monkeypatch.setattr(singleton, "get_orchestrator", lambda: ok)
        r = (await client.post("/api/tarot/draw", json={"spread": "single", "seed": 1, "interpret": True, "language": "hindi"})).json()
        assert r["ai_interpretation"] == "A balanced reading."
        assert "Hindi" in ok._llm.generate.call_args.kwargs["system"]

        broken = SimpleNamespace(_llm=SimpleNamespace(generate=AsyncMock(side_effect=RuntimeError("org_01 limit"))))
        monkeypatch.setattr(singleton, "get_orchestrator", lambda: broken)
        r2 = await client.post("/api/tarot/draw", json={"spread": "single", "seed": 1, "interpret": True})
        assert r2.status_code == 200 and r2.json()["ai_interpretation"] is None and "org_01" not in r2.text

    async def test_vastu(self, client):
        r = (await client.post("/api/vastu/analyze", json={"entrance_facing": "North-East", "rooms": {"kitchen": "NE", "toilet": "NW"}})).json()
        assert [f["room"] for f in r["needs_attention"]] == ["kitchen"] and r["overall_score"] > 0
        assert (await client.post("/api/vastu/analyze", json={})).status_code == 422
        assert (await client.post("/api/vastu/analyze", json={"rooms": {"kitchen": "UP"}})).status_code == 422
        assert (await client.post("/api/vastu/analyze", json={"rooms": {"moat": "N"}})).status_code == 422
        assert set((await client.get("/api/vastu/guidelines")).json()) == {"directions", "rooms", "general_tips"}


class TestCalendarApis:
    async def test_muhurat(self, client):
        types = (await client.get("/api/muhurat/types")).json()["events"]
        assert len(types) == 11
        r = (await client.post("/api/muhurat/find", json={"event": "marriage", "start_date": "2026-11-21", "end_date": "2027-01-10"})).json()
        assert r["suitable_days"] >= 1 and r["best_days"][0]["windows"]
        assert (await client.post("/api/muhurat/find", json={"event": "bogus", "start_date": "2026-11-21", "end_date": "2027-01-10"})).status_code == 422
        assert (await client.post("/api/muhurat/find", json={"event": "marriage", "start_date": "2026-01-01", "end_date": "2026-12-31"})).status_code == 422
        assert (await client.post("/api/muhurat/find", json={"event": "puja", "start_date": "2026-10-05", "end_date": "2026-10-06", "timezone": "Mars/Base"})).status_code == 422
        assert (await client.post("/api/muhurat/find", json={"event": "puja", "start_date": "2026-10-05", "end_date": "2026-10-06", "latitude": 123})).status_code == 422

    async def test_festivals(self, client):
        nov = (await client.get("/api/calendar/festivals?year=2026&month=11")).json()
        assert any(e["name"].startswith("Diwali") and e["date"] == "2026-11-08" for e in nov["events"])
        assert all(e["date"].startswith("2026-11") for e in nov["events"])
        only = (await client.get("/api/calendar/festivals?year=2026&kind=sankranti")).json()
        assert only["count"] == 12
        assert (await client.get("/api/calendar/festivals?year=1700")).status_code == 422
        assert (await client.get("/api/calendar/festivals?year=2026&kind=party")).status_code == 422
        up = (await client.get("/api/calendar/upcoming?days=30")).json()
        assert up["from"] <= up["to"] and all(up["from"] <= e["date"] <= up["to"] for e in up["events"])

    async def test_today_summary(self, client):
        t = (await client.get("/api/calendar/today?date=2026-11-08")).json()
        assert t["weekday"] == "Sunday" and t["month"]["amanta"] == "Ashwin" and t["vikram_samvat"] == 2083
        assert any(e["key"] == "diwali" for e in t["events_today"]) and t["sunrise"] != "--:--"

    async def test_panchang_route_exposes_lunar_fields(self, client):
        p = (await client.get("/api/panchang?date=2026-10-05&lat=28.6139&lon=77.2090")).json()
        assert p["calendar"]["masa"] == "Bhadrapada" and p["calendar"]["masa_purnimanta"] == "Ashwin"
        assert p["sun_moon"]["sunrise"] == "06:15" and p["calendar"]["moon_phase"]


class TestAssistantApis:
    async def test_intent(self, client):
        r = (await client.post("/api/intent/classify", json={"text": "When will I get married?"})).json()
        assert r["category"] == "marriage" and "kundli_milan" in r["suggested_modules"]
        crisis = (await client.post("/api/intent/classify", json={"text": "I want to end my life"})).json()
        assert crisis["category"] == "support" and crisis["safety"]["level"] == "crisis"
        assert (await client.post("/api/intent/classify", json={"text": ""})).status_code == 422
        assert (await client.post("/api/intent/classify", json={"text": "x" * 1001})).status_code == 422
        assert len((await client.get("/api/intent/categories")).json()["categories"]) >= 15

    async def test_notification_feed(self, client):
        r = (await client.post("/api/notifications/feed", json={"birth_data": BIRTH, "start_date": "2026-10-25", "days": 20})).json()
        assert r["count"] == len(r["items"]) and r["moon_sign"] == "Taurus"
        assert sum(i["type"] == "daily_horoscope" for i in r["items"]) == 14
        assert (await client.post("/api/notifications/feed", json={"birth_data": BIRTH, "days": 400})).status_code == 422

    async def test_languages_and_features(self, client):
        langs = (await client.get("/api/languages")).json()["languages"]
        assert len(langs) == 13 and {l["code"] for l in langs} >= {"en", "hi", "ta", "ur", "or"}
        assert next(l for l in langs if l["code"] == "or")["speech_input"] is False
        feats = (await client.get("/api/features")).json()
        assert feats["total"] == sum(feats["by_status"].values())
        ids = {f["id"] for g in feats["groups"].values() for f in g}
        assert {"ai_chat", "horoscope", "muhurat", "tarot", "human_consultation"} <= ids
        marketplace = [f for f in feats["groups"]["Marketplace"]]
        assert marketplace and all(f["status"] == "out_of_scope" for f in marketplace)
        live = [f for g in feats["groups"].values() for f in g if f["status"] == "live"]
        routes = {r.path for r in app.routes}
        for f in live:
            for ep in f["endpoints"]:
                path = ep.split(" ", 1)[1].rstrip("/")
                assert path in routes or path + "/" in routes, (f["id"], ep)


class TestLanguageSupport:
    def test_english_leaves_the_prompt_unchanged(self):
        assert system_prompt("english") == system_prompt(None) == SYSTEM_ASTROLOGER == system_prompt("EN")

    def test_non_english_adds_a_language_rule(self):
        hi = system_prompt("Hindi")
        assert hi.startswith(SYSTEM_ASTROLOGER) and "Hindi" in hi and "Devanagari" in hi and "JSON keys" in hi
        assert "JSON keys" not in system_prompt("hi", json_output=False)

    def test_language_resolution(self):
        assert languages.resolve("हिन्दी")[0] == "hi" and languages.resolve("TAMIL")[0] == "ta"
        assert languages.resolve("klingon") is None and languages.is_english("klingon")
        assert languages.whisper_code("odia") is None and languages.whisper_code("hindi") == "hi"

    async def test_chat_routes_pass_the_language_to_the_orchestrator(self, client, monkeypatch):
        import app.api.routes_chat as rc
        orch = MagicMock()
        orch.run = AsyncMock(return_value={"request_id": "r", "answer": "ok", "topic": "general", "sources": [],
                                           "follow_up_questions": [], "errors": [], "disclaimer": ""})

        async def stream(**kw):
            stream.kw = kw
            yield "namaste"

        orch.run_chat_stream = stream
        monkeypatch.setattr(rc, "get_orchestrator", lambda: orch)
        await client.post("/api/chat/", json={"question": "hi", "language": "hindi"})
        assert orch.run.call_args.kwargs["language"] == "hindi"
        r = await client.post("/api/chat/stream", json={"question": "hi", "language": "tamil"})
        assert r.status_code == 200 and stream.kw["language"] == "tamil"

    async def test_prediction_request_accepts_language(self, client, monkeypatch):
        import app.api.routes_prediction as rp
        orch = MagicMock()
        orch.run = AsyncMock(return_value={"topic": "career"})
        monkeypatch.setattr(rp, "get_orchestrator", lambda: orch)
        r = await client.post("/api/prediction/", json={"birth_data": BIRTH, "topic": "career", "language": "marathi"})
        assert r.status_code == 200 and orch.run.call_args.kwargs["language"] == "marathi"


class TestVoice:
    def _settings(self, monkeypatch, key="k"):
        monkeypatch.setattr(speech, "get_settings", lambda: SimpleNamespace(groq_api_key=key, groq_stt_model="whisper-test"))

    async def test_validation_errors(self, monkeypatch):
        self._settings(monkeypatch)
        for data, name, status in [(b"", "a.m4a", 400), (b"x" * (speech.MAX_AUDIO_BYTES + 1), "a.m4a", 413), (b"abc", "a.txt", 415)]:
            with pytest.raises(speech.SpeechError) as e:
                await speech.transcribe(data, name)
            assert e.value.status == status
        self._settings(monkeypatch, key="")
        with pytest.raises(speech.SpeechError) as e:
            await speech.transcribe(b"abc", "a.m4a")
        assert e.value.status == 503

    async def test_successful_transcription_passes_language(self, monkeypatch):
        self._settings(monkeypatch)
        create = AsyncMock(return_value=SimpleNamespace(text="  mera naam Arjun hai ", language="hindi", duration=2.5))
        fake = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
        monkeypatch.setattr(speech, "AsyncGroq", lambda **kw: fake)
        out = await speech.transcribe(b"audio-bytes", "q.webm", "Hindi")
        assert out == {"text": "mera naam Arjun hai", "language": "hindi", "duration_seconds": 2.5, "empty": False}
        assert create.call_args.kwargs["language"] == "hi" and create.call_args.kwargs["model"] == "whisper-test"
        await speech.transcribe(b"audio-bytes", "q.webm", "Odia")
        assert "language" not in create.call_args.kwargs

    async def test_provider_errors_are_generic(self, monkeypatch):
        import httpx
        from groq import APIStatusError
        self._settings(monkeypatch)
        req = httpx.Request("POST", "https://api.groq.com/x")
        err = APIStatusError("org_01SECRET quota", response=httpx.Response(429, request=req), body=None)
        fake = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=AsyncMock(side_effect=err))))
        monkeypatch.setattr(speech, "AsyncGroq", lambda **kw: fake)
        with pytest.raises(speech.SpeechError) as e:
            await speech.transcribe(b"abc", "a.mp3")
        assert e.value.status == 503 and "org_01" not in e.value.message

    async def test_endpoint_maps_speech_errors_and_success(self, client, monkeypatch):
        import app.api.routes_assistant as ra
        monkeypatch.setattr(ra.speech, "transcribe", AsyncMock(return_value={"text": "hello", "language": "en",
                                                                              "duration_seconds": 1.0, "empty": False}))
        files = {"file": ("q.m4a", b"123", "audio/mp4")}
        ok = await client.post("/api/voice/transcribe", files=files, data={"language": "english"})
        assert ok.status_code == 200 and ok.json()["text"] == "hello"
        monkeypatch.setattr(ra.speech, "transcribe", AsyncMock(side_effect=speech.SpeechError(415, "Unsupported audio type.")))
        bad = await client.post("/api/voice/transcribe", files=files)
        assert bad.status_code == 415 and bad.json()["detail"] == "Unsupported audio type."
        assert (await client.post("/api/voice/transcribe")).status_code == 422
