"""LLM providers: Groq model failover with cool-downs, the backup provider, and how the routes report 'busy'."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from groq import APIConnectionError, APIStatusError
from httpx import ASGITransport, AsyncClient

from app.llm import provider
from app.llm.provider import (FallbackProvider, GroqProvider, LLMBusyError, OpenAICompatibleProvider, build_provider)
from app.main import app
from app.security.auth import require_api_key

REQ = httpx.Request("POST", "https://api.groq.com/x")


def status_error(code: int, retry_after: str | None = None) -> APIStatusError:
    headers = {"retry-after": retry_after} if retry_after else {}
    return APIStatusError(f"org_01 secret {code}", response=httpx.Response(code, request=REQ, headers=headers), body=None)


class FakeCompletions:
    """Plays back a script per model: a string is an answer, an Exception is raised, a list streams tokens."""

    def __init__(self, script: dict):
        self.script = {model: list(outcomes) for model, outcomes in script.items()}    # outcomes are used in order
        self.calls: list[dict] = []

    async def create(self, **kw):
        self.calls.append(kw)
        queue = self.script[kw["model"]]
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, Exception):
            raise outcome
        if kw.get("stream"):
            return self._stream(outcome)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))])

    async def _stream(self, tokens):
        yield SimpleNamespace(choices=[])                       # usage chunks carry no choices
        for token in tokens:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=token))])
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))])


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.t

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def make_groq(monkeypatch, script, fallbacks=("model-b",), primary="model-a", clock=None):
    completions = FakeCompletions(script)
    created = {}

    def factory(**kw):
        created.update(kw)
        return SimpleNamespace(chat=SimpleNamespace(completions=completions))

    monkeypatch.setattr(provider, "AsyncGroq", factory)
    clock = clock or Clock()
    groq = GroqProvider(api_key="k", llm_model=primary, classifier_model=primary, fallback_models=fallbacks,
                        clock=clock, sleep=clock.sleep)
    return groq, completions, clock, created


class TestGroqFailover:
    async def test_the_primary_model_is_used_when_it_works(self, monkeypatch):
        groq, comp, _, created = make_groq(monkeypatch, {"model-a": ["answer a"], "model-b": ["answer b"]})
        assert await groq.generate("hi") == "answer a"
        assert [c["model"] for c in comp.calls] == ["model-a"]
        assert created["max_retries"] == 0                            # the SDK must not sleep through rate limits

    async def test_a_rate_limit_moves_to_the_next_model_at_once(self, monkeypatch):
        groq, comp, clock, _ = make_groq(monkeypatch, {"model-a": [status_error(429, "30")], "model-b": ["answer b"]})
        assert await groq.generate("hi") == "answer b"
        assert [c["model"] for c in comp.calls] == ["model-a", "model-b"]
        assert clock.slept == []                                      # no waiting around

    async def test_a_limited_model_is_skipped_until_its_cooldown_ends(self, monkeypatch):
        groq, comp, clock, _ = make_groq(monkeypatch, {"model-a": [status_error(429, "30"), "back"], "model-b": ["answer b"]})
        await groq.generate("one")
        await groq.generate("two")
        assert [c["model"] for c in comp.calls] == ["model-a", "model-b", "model-b"]
        clock.t += 31
        assert await groq.generate("three") == "back"
        assert comp.calls[-1]["model"] == "model-a"

    async def test_when_every_model_is_limited_it_waits_once_if_a_model_frees_up_soon(self, monkeypatch):
        groq, comp, clock, _ = make_groq(monkeypatch, {"model-a": [status_error(429, "3"), "late answer"],
                                                       "model-b": [status_error(429, "5")]})
        assert await groq.generate("hi") == "late answer"
        assert clock.slept and 2.9 < clock.slept[0] < 3.2             # waited for the soonest model, no longer

    async def test_a_long_wait_is_reported_as_busy_instead(self, monkeypatch):
        groq, _, clock, _ = make_groq(monkeypatch, {"model-a": [status_error(429, "40")], "model-b": [status_error(429, "50")]})
        with pytest.raises(LLMBusyError):
            await groq.generate("hi")
        assert clock.slept == []

    async def test_busy_errors_do_not_expose_provider_details(self, monkeypatch):
        groq, *_ = make_groq(monkeypatch, {"model-a": [status_error(429, "40")], "model-b": [status_error(429, "40")]})
        with pytest.raises(LLMBusyError) as err:
            await groq.generate("hi")
        assert "org_01" not in str(err.value)

    async def test_a_bad_key_is_a_bug_not_a_busy_signal(self, monkeypatch):
        groq, comp, _, _ = make_groq(monkeypatch, {"model-a": [status_error(401)], "model-b": ["x"]})
        with pytest.raises(APIStatusError):
            await groq.generate("hi")
        assert len(comp.calls) == 1

    async def test_a_retired_model_is_dropped_for_ten_minutes(self, monkeypatch):
        groq, comp, clock, _ = make_groq(monkeypatch, {"model-a": [status_error(404), "x"], "model-b": ["answer b"]})
        await groq.generate("one")
        clock.t += 300
        await groq.generate("two")
        assert [c["model"] for c in comp.calls] == ["model-a", "model-b", "model-b"]
        clock.t += 400
        await groq.generate("three")
        assert comp.calls[-1]["model"] == "model-a"

    async def test_server_errors_and_dropped_connections_try_the_next_model(self, monkeypatch):
        groq, comp, _, _ = make_groq(monkeypatch, {"model-a": [status_error(503)], "model-b": ["answer b"]})
        assert await groq.generate("hi") == "answer b"
        groq2, comp2, _, _ = make_groq(monkeypatch, {"model-a": [APIConnectionError(request=REQ)], "model-b": ["answer b"]})
        assert await groq2.generate("hi") == "answer b"

    async def test_a_model_that_returns_nothing_is_skipped(self, monkeypatch):
        groq, comp, _, _ = make_groq(monkeypatch, {"model-a": ["   "], "model-b": ["real answer"]})
        assert await groq.generate("hi") == "real answer"

    async def test_a_request_one_model_rejects_goes_to_the_next(self, monkeypatch):
        groq, _, _, _ = make_groq(monkeypatch, {"model-a": [status_error(400)], "model-b": ["fine"]})
        assert await groq.generate("hi", json_mode=True) == "fine"

    async def test_reasoning_models_get_room_and_low_effort_but_others_do_not(self, monkeypatch):
        groq, comp, _, _ = make_groq(monkeypatch, {"qwen-x": [status_error(429, "30")], "openai/gpt-oss-20b": ["ok"]},
                                     primary="qwen-x", fallbacks=("openai/gpt-oss-20b",))
        await groq.generate("hi", max_tokens=900)
        qwen, oss = comp.calls
        assert qwen["max_tokens"] == 900 and "extra_body" not in qwen
        assert oss["max_tokens"] == 1536 and oss["extra_body"] == {"reasoning_effort": "low"}

    async def test_json_mode_and_messages_are_passed_through(self, monkeypatch):
        groq, comp, _, _ = make_groq(monkeypatch, {"model-a": ['{"a": 1}'], "model-b": ["x"]})
        await groq.generate("question", system="be wise", temperature=0.1, json_mode=True)
        call = comp.calls[0]
        assert call["response_format"] == {"type": "json_object"} and call["temperature"] == 0.1
        assert call["messages"] == [{"role": "system", "content": "be wise"}, {"role": "user", "content": "question"}]

    async def test_duplicate_and_blank_model_names_are_ignored(self, monkeypatch):
        groq, comp, _, _ = make_groq(monkeypatch, {"model-a": [status_error(429, "30")]}, fallbacks=("model-a", "", "model-a"))
        with pytest.raises(LLMBusyError):
            await groq.generate("hi")
        assert len(comp.calls) == 1

    def test_a_missing_key_fails_loudly(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(ValueError):
            GroqProvider(api_key=None)


class TestGroqStreaming:
    async def collect(self, groq, **kw):
        return [t async for t in groq.generate_stream("hi", **kw)]

    async def test_tokens_stream_and_empty_chunks_are_ignored(self, monkeypatch):
        groq, *_ = make_groq(monkeypatch, {"model-a": [["Na", "ma", "ste"]], "model-b": [["x"]]})
        assert await self.collect(groq) == ["Na", "ma", "ste"]

    async def test_a_rate_limit_while_opening_the_stream_uses_the_next_model(self, monkeypatch):
        groq, comp, _, _ = make_groq(monkeypatch, {"model-a": [status_error(429, "30")], "model-b": [["ok"]]})
        assert await self.collect(groq) == ["ok"]
        assert comp.calls[-1]["stream"] is True

    async def test_busy_everywhere_raises_before_any_token(self, monkeypatch):
        groq, *_ = make_groq(monkeypatch, {"model-a": [status_error(429, "30")], "model-b": [status_error(429, "30")]})
        with pytest.raises(LLMBusyError):
            await self.collect(groq)


class TestClassify:
    async def test_classify_uses_the_pool_and_matches_whole_words(self, monkeypatch):
        groq, comp, _, _ = make_groq(monkeypatch, {"model-a": [status_error(429, "30")], "model-b": ["Career."]})
        assert await groq.classify("will I get promoted", ["love", "career", "health"]) == "career"
        assert comp.calls[-1]["max_tokens"] == 10

    async def test_classify_falls_back_to_the_default(self, monkeypatch):
        groq, *_ = make_groq(monkeypatch, {"model-a": ["something else"], "model-b": ["x"]})
        assert await groq.classify("?", ["love", "career"], default="general") == "general"
        assert await groq.classify("?", ["love", "career"]) == "career"

    async def test_a_whole_word_match_beats_a_substring_match(self, monkeypatch):
        groq, *_ = make_groq(monkeypatch, {"model-a": ["scar"], "model-b": ["x"]})
        assert await groq.classify("?", ["car", "scar"]) == "scar"                 # not "car" hiding inside "scar"

    async def test_a_substring_is_still_accepted_when_nothing_matches_exactly(self, monkeypatch):
        groq, *_ = make_groq(monkeypatch, {"model-a": ["marriage-related"], "model-b": ["x"]})
        assert await groq.classify("?", ["career", "marriage"]) == "marriage"


def backup(handler, **kw) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider("https://backup.example/v1/", "secret-key", "big-model",
                                    transport=httpx.MockTransport(handler), **kw)


class TestBackupProvider:
    async def test_generate_calls_chat_completions_with_a_bearer_key(self):
        seen = {}

        def handler(request):
            seen.update(url=str(request.url), auth=request.headers["authorization"], body=json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

        assert await backup(handler).generate("question", system="sys", temperature=0.2, max_tokens=50, json_mode=True) == "hello"
        assert seen["url"] == "https://backup.example/v1/chat/completions" and seen["auth"] == "Bearer secret-key"
        assert seen["body"] == {"model": "big-model", "temperature": 0.2, "max_tokens": 50,
                                "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "question"}],
                                "response_format": {"type": "json_object"}}

    @pytest.mark.parametrize("response", [
        httpx.Response(429, json={"error": "rate"}), httpx.Response(500, text="oops"),
        httpx.Response(200, text="not json"), httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]}),
    ])
    async def test_every_failure_is_reported_as_busy(self, response):
        with pytest.raises(LLMBusyError):
            await backup(lambda request: response).generate("q")

    async def test_a_network_error_is_reported_as_busy(self):
        def handler(request):
            raise httpx.ConnectError("no route")

        with pytest.raises(LLMBusyError):
            await backup(handler).generate("q")

    async def test_streaming_reads_server_sent_events(self):
        sse = ('data: {"choices":[{"delta":{"content":"Na"}}]}\n\n: keep-alive\n\ndata: not json\n\n'
               'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\ndata: {"choices":[{"delta":{"content":"maste"}}]}\n\n'
               'data: [DONE]\n\ndata: {"choices":[{"delta":{"content":"IGNORED"}}]}\n\n')
        provider_ = backup(lambda request: httpx.Response(200, text=sse))
        assert [t async for t in provider_.generate_stream("q")] == ["Na", "maste"]

    async def test_a_failed_stream_open_is_busy(self):
        with pytest.raises(LLMBusyError):
            [t async for t in backup(lambda request: httpx.Response(503, text="down")).generate_stream("q")]

    async def test_classify(self):
        provider_ = backup(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "love"}}]}))
        assert await provider_.classify("q", ["career", "love"]) == "love"

    def test_all_three_settings_are_required(self):
        with pytest.raises(ValueError):
            OpenAICompatibleProvider("", "key", "model")


class Primary:
    def __init__(self, generate=None, stream=None):
        self._generate, self._stream = generate, stream

    async def generate(self, *a, **kw):
        if isinstance(self._generate, Exception):
            raise self._generate
        return self._generate

    async def generate_stream(self, *a, **kw):
        for item in self._stream:
            if isinstance(item, Exception):
                raise item
            yield item

    async def classify(self, *a, **kw):
        if isinstance(self._generate, Exception):
            raise self._generate
        return self._generate


class TestFallbackProvider:
    async def test_the_secondary_answers_when_the_primary_is_busy(self):
        both = FallbackProvider(Primary(LLMBusyError("busy")), Primary("from backup"))
        assert await both.generate("q") == "from backup"
        assert await both.classify("q", ["a"]) == "from backup"

    async def test_the_primary_is_preferred_and_other_errors_are_not_hidden(self):
        assert await FallbackProvider(Primary("main"), Primary("backup")).generate("q") == "main"
        with pytest.raises(ValueError):
            await FallbackProvider(Primary(ValueError("bug")), Primary("backup")).generate("q")

    async def test_a_stream_switches_over_only_before_the_first_token(self):
        both = FallbackProvider(Primary(stream=[LLMBusyError("busy")]), Primary(stream=["b1", "b2"]))
        assert [t async for t in both.generate_stream("q")] == ["b1", "b2"]
        mid = FallbackProvider(Primary(stream=["a1", LLMBusyError("died")]), Primary(stream=["b1"]))
        got = []
        with pytest.raises(LLMBusyError):
            async for token in mid.generate_stream("q"):
                got.append(token)
        assert got == ["a1"]                                          # never a half answer followed by a different one

    async def test_an_empty_stream_just_ends(self):
        assert [t async for t in FallbackProvider(Primary(stream=[]), Primary(stream=["x"])).generate_stream("q")] == []


class TestBuildProvider:
    def settings(self, **kw):
        base = dict(groq_api_key="k", groq_model="model-a", groq_classifier_model="model-a",
                    groq_fallback_models=["model-b"], llm_fallback_base_url="", llm_fallback_api_key="", llm_fallback_model="")
        return SimpleNamespace(**{**base, **kw})

    def test_groq_only_by_default(self, monkeypatch):
        monkeypatch.setattr(provider, "AsyncGroq", lambda **kw: MagicMock())
        built = build_provider(self.settings())
        assert isinstance(built, GroqProvider) and built._models == ["model-a", "model-b"]

    def test_a_complete_backup_configuration_adds_the_fallback(self, monkeypatch):
        monkeypatch.setattr(provider, "AsyncGroq", lambda **kw: MagicMock())
        built = build_provider(self.settings(llm_fallback_base_url="https://x/v1", llm_fallback_api_key="k", llm_fallback_model="m"))
        assert isinstance(built, FallbackProvider)

    def test_a_half_configured_backup_is_ignored(self, monkeypatch):
        monkeypatch.setattr(provider, "AsyncGroq", lambda **kw: MagicMock())
        assert isinstance(build_provider(self.settings(llm_fallback_base_url="https://x/v1")), GroqProvider)

    def test_the_default_pool_includes_a_second_model(self):
        from app.config import Settings

        assert Settings(_env_file=None).groq_fallback_models == ["openai/gpt-oss-20b"]


@pytest.fixture
async def client():
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30) as ac:
        yield ac
    app.dependency_overrides.clear()


BIRTH = {"name": "T", "date_of_birth": "1990-08-15", "time_of_birth": "14:30", "timezone": "Asia/Kolkata",
         "latitude": 19.076, "longitude": 72.8777}


class TestRoutesTreatBusyAsUnavailable:
    async def test_every_ai_route_answers_503_when_nothing_can_answer(self, client):
        orch = MagicMock()
        orch.run.side_effect = LLMBusyError("org_01 internal detail")
        with patch("app.api.routes_chat.get_orchestrator", return_value=orch), \
             patch("app.api.routes_prediction.get_orchestrator", return_value=orch), \
             patch("app.api.routes_kundli.get_orchestrator", return_value=orch):
            for path, body in (("/api/chat/", {"question": "hi"}),
                               ("/api/prediction/", {"birth_data": BIRTH, "topic": "career"}),
                               ("/api/kundli/predict", {"birth_data": BIRTH, "topic": "career"})):
                r = await client.post(path, json=body)
                assert r.status_code == 503, path
                assert "org_01" not in r.text and "busy" in r.json()["detail"]

    async def test_a_stream_reports_busy_in_its_error_event(self, client):
        async def boom(**_kw):
            raise LLMBusyError("detail")
            yield  # pragma: no cover

        orch = MagicMock()
        orch.run_chat_stream = boom
        with patch("app.api.routes_chat.get_orchestrator", return_value=orch):
            r = await client.post("/api/chat/stream", json={"question": "hi"})
        events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
        assert next(e for e in events if e["type"] == "error")["message"].startswith("The AI service is busy")
