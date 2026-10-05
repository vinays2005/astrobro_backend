"""
LLM providers. The LLM is the REASONING layer only: it never calculates astrology.

Groq's free tier limits tokens per minute PER MODEL. The Groq provider therefore keeps a small pool of models and,
when one is rate limited, moves to the next at once instead of waiting; the limited model is skipped for a short
cool-down. An optional second provider (any OpenAI-compatible endpoint: Cerebras, Gemini, OpenRouter, ...) takes
over when every Groq model is busy. When nothing can answer, LLMBusyError is raised and the routes reply 503.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

import httpx
import structlog
from groq import APIConnectionError, APIStatusError, APITimeoutError, AsyncGroq

logger = structlog.get_logger()

DEFAULT_COOLDOWN = 20.0          # seconds a rate-limited model is skipped when the provider gives no hint
MAX_COOLDOWN = 90.0
MAX_WAIT_FOR_MODEL = 6.0         # how long we will wait once for the soonest model to free up
BACKUP_TIMEOUT = 25.0            # a backup that has not answered in this long is treated as busy
GONE_COOLDOWN = 600.0            # a model that no longer exists is not asked again for ten minutes


class LLMBusyError(Exception):
    """Every configured model is rate limited or unavailable right now."""


class _EmptyAnswer(Exception):
    pass


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str: ...

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]: ...

    @abstractmethod
    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str: ...


def _messages(prompt: str, system: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _classify_prompt(text: str, categories: list[str]) -> str:
    return (
        f"Classify the following astrology question into exactly one "
        f"category from this list: {', '.join(categories)}.\n\n"
        f"Question: {text}\n\n"
        f"Respond with ONLY the category name, nothing else."
    )


def _pick_category(answer: str, categories: list[str], default: str | None) -> str:
    """Exact or whole-word match first, then substring (so "car" does not match inside "scared")."""
    result = answer.strip().lower()
    for cat in categories:
        if cat.lower() == result or cat.lower() in result.split():
            return cat
    for cat in categories:
        if cat.lower() in result:
            return cat
    return default or categories[-1]


def _unique(models: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for m in models:
        if m and m not in seen:
            seen.append(m)
    return seen


def _retry_after(exc: APIStatusError) -> float:
    try:
        return min(max(float(exc.response.headers.get("retry-after", "")), 1.0), MAX_COOLDOWN)
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_COOLDOWN


def _model_kwargs(model: str, max_tokens: int) -> dict:
    """gpt-oss models think before answering: keep that short and leave room so the answer is not cut off."""
    if "gpt-oss" in model:
        return {"max_tokens": max(max_tokens, 1536), "extra_body": {"reasoning_effort": "low"}}
    return {"max_tokens": max_tokens}


class GroqProvider(LLMProvider):
    """Groq backend with a pool of models and per-model cool-downs.

    Reads GROQ_API_KEY from the environment (fail loud if missing). Model names come from settings, not code.
    The SDK's own retries are switched off (`max_retries=0`) so that a 429 moves straight to the next model
    rather than sleeping.
    """

    def __init__(
        self,
        api_key: str | None = None,
        llm_model: str = "qwen/qwen3.8-27b",
        classifier_model: str = "qwen/qwen3.8-27b",
        timeout: int = 120,
        fallback_models: Sequence[str] = (),
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise ValueError("GROQ_API_KEY not set. Export it or pass api_key= explicitly.")
        self._client = AsyncGroq(api_key=key, timeout=float(timeout), max_retries=0)
        self._models = _unique([llm_model, *fallback_models])
        self._classifier_models = _unique([classifier_model, *fallback_models])
        self._cooldown_until: dict[str, float] = {}
        self._clock = clock
        self._sleep = sleep

    # ── model pool ────────────────────────────────────────────────────────────

    def _cooling(self, model: str) -> bool:
        return self._cooldown_until.get(model, 0.0) > self._clock()

    def _cool(self, model: str, seconds: float) -> None:
        self._cooldown_until[model] = self._clock() + seconds

    def _soonest_wait(self, models: list[str]) -> float | None:
        waits = [self._cooldown_until[m] - self._clock() for m in models if self._cooling(m)]
        return min(waits) if waits else None

    async def _run(self, models: list[str], call: Callable[[str], Awaitable]):
        """Return the first success of `call(model)` over the models that are not cooling down."""
        last: Exception | None = None
        for attempt in range(2):
            for model in models:
                if self._cooling(model):
                    continue
                try:
                    return await call(model)
                except APIStatusError as exc:
                    last = exc
                    status = exc.status_code
                    if status in (401, 403):
                        raise                                    # a bad key is a bug, not a busy signal
                    if status == 429:
                        self._cool(model, _retry_after(exc))
                    elif status == 404:
                        self._cool(model, GONE_COOLDOWN)
                    elif status >= 500:
                        self._cool(model, 5.0)
                    logger.warning("llm_model_skipped", model=model, status=status)
                except (APIConnectionError, APITimeoutError) as exc:
                    last = exc
                    self._cool(model, 5.0)
                    logger.warning("llm_model_unreachable", model=model, error=type(exc).__name__)
                except _EmptyAnswer as exc:
                    last = exc
                    logger.warning("llm_model_empty_answer", model=model)
            wait = self._soonest_wait(models)
            if attempt == 0 and wait is not None and wait <= MAX_WAIT_FOR_MODEL:
                await self._sleep(wait + 0.05)                   # the soonest model is almost free: wait for it once
                continue
            break
        raise LLMBusyError("All language models are busy right now.") from last

    # ── generation ────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        """json_mode=True asks for a JSON object (the prompt must still describe the shape)."""
        messages = _messages(prompt, system)

        async def call(model: str) -> str:
            kwargs = _model_kwargs(model, max_tokens)
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = await self._client.chat.completions.create(
                model=model, messages=messages, temperature=temperature, **kwargs)
            text = response.choices[0].message.content or ""
            if not text.strip():
                raise _EmptyAnswer(model)
            return text

        return await self._run(self._models, call)

    async def generate_stream(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Streams tokens. Failover happens only while opening the stream; once tokens flow, errors propagate."""
        messages = _messages(prompt, system)

        async def open_stream(model: str):
            return await self._client.chat.completions.create(
                model=model, messages=messages, temperature=temperature, stream=True, **_model_kwargs(model, max_tokens))

        stream = await self._run(self._models, open_stream)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str:
        prompt = _classify_prompt(text, categories)

        async def call(model: str) -> str:
            response = await self._client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], temperature=0.0,
                **_model_kwargs(model, 10))
            answer = response.choices[0].message.content or ""
            if not answer.strip():
                raise _EmptyAnswer(model)
            return answer

        return _pick_category(await self._run(self._classifier_models, call), categories, default)


class OpenAICompatibleProvider(LLMProvider):
    """Any server that speaks the OpenAI chat-completions API (Cerebras, Gemini, OpenRouter, Together, ...).

    Every failure that means "cannot answer right now" is raised as LLMBusyError so a FallbackProvider can react.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not (base_url and api_key and model):
            raise ValueError("base_url, api_key and model are all required")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._model = model
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def generate(self, prompt: str, system: str | None = None, temperature: float = 0.3,
                       max_tokens: int = 2048, json_mode: bool = False) -> str:
        body: dict = {"model": self._model, "messages": _messages(prompt, system), "temperature": temperature,
                      "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            async with self._client() as client:
                resp = await client.post(self._url, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise LLMBusyError(f"Backup provider unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            logger.warning("llm_backup_error", status=resp.status_code, body=resp.text[:200])
            raise LLMBusyError(f"Backup provider answered {resp.status_code}")
        try:
            text = resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMBusyError("Backup provider sent an unreadable answer") from exc
        if not text.strip():
            raise LLMBusyError("Backup provider sent an empty answer")
        return text

    async def generate_stream(self, prompt: str, system: str | None = None, temperature: float = 0.3,
                              max_tokens: int = 2048) -> AsyncIterator[str]:
        body = {"model": self._model, "messages": _messages(prompt, system), "temperature": temperature,
                "max_tokens": max_tokens, "stream": True}
        try:
            async with self._client() as client:
                async with client.stream("POST", self._url, json=body, headers=self._headers) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        logger.warning("llm_backup_error", status=resp.status_code, body=resp.text[:200])
                        raise LLMBusyError(f"Backup provider answered {resp.status_code}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            choices = json.loads(payload).get("choices") or []
                        except ValueError:
                            continue
                        delta = (choices[0].get("delta") or {}).get("content") if choices else None
                        if delta:
                            yield delta
        except httpx.HTTPError as exc:
            raise LLMBusyError(f"Backup provider unreachable: {type(exc).__name__}") from exc

    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str:
        answer = await self.generate(_classify_prompt(text, categories), temperature=0.0, max_tokens=20)
        return _pick_category(answer, categories, default)


class FallbackProvider(LLMProvider):
    """Ask the primary first; when it reports LLMBusyError, try each backup in order.

    A backup that just failed is skipped for BACKUP_COOLDOWN seconds, so a slow or used-up free tier does not add
    its delay to every chat. The primary is always asked first (Groq keeps its own per-model cool-downs).
    A stream switches provider only before its first token, never in the middle of an answer.
    """

    BACKUP_COOLDOWN = 30.0
    BACKUP_MAX_INFLIGHT = 4       # a backup already answering this many chats hands new ones to the next backup

    def __init__(self, primary: LLMProvider, *backups: LLMProvider,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not backups:
            raise ValueError("FallbackProvider needs at least one backup")
        self._primary = primary
        self._backups = list(backups)
        self._skip_until: dict[int, float] = {}
        self._inflight: dict[int, int] = {}
        self._clock = clock

    def _ready(self) -> list[tuple[int, LLMProvider]]:
        """Backups in the order to try: not cooling and not full first (in configured order), then the rest."""
        now = self._clock()
        order = list(enumerate(self._backups))
        free = [(i, b) for i, b in order
                if self._skip_until.get(i, 0.0) <= now and self._inflight.get(i, 0) < self.BACKUP_MAX_INFLIGHT]
        full = [(i, b) for i, b in order
                if self._skip_until.get(i, 0.0) <= now and self._inflight.get(i, 0) >= self.BACKUP_MAX_INFLIGHT]
        return free + sorted(full, key=lambda ib: self._inflight.get(ib[0], 0)) or order   # all cooling: try anyway

    def _failed(self, index: int, call: str) -> None:
        self._skip_until[index] = self._clock() + self.BACKUP_COOLDOWN
        logger.warning("llm_backup_failed", backup=index + 1, call=call)

    async def _through_backups(self, call: str, run: Callable[[LLMProvider], Awaitable], hold: bool = False):
        """Returns (backup index, result). With hold=True the backup stays counted as busy until release() is called
        (a stream is in flight for its whole length)."""
        last: LLMBusyError | None = None
        for index, backup in self._ready():
            self._inflight[index] = self._inflight.get(index, 0) + 1
            try:
                result = await run(backup)
                logger.warning("llm_backup_used", backup=index + 1, call=call)
                if not hold:
                    self._inflight[index] -= 1
                return index, result
            except LLMBusyError as exc:
                self._inflight[index] -= 1
                last = exc
                self._failed(index, call)
            except BaseException:
                self._inflight[index] -= 1
                raise
        raise LLMBusyError("Every language model and backup is busy right now.") from last

    async def generate(self, prompt: str, system: str | None = None, temperature: float = 0.3,
                       max_tokens: int = 2048, json_mode: bool = False) -> str:
        try:
            return await self._primary.generate(prompt, system, temperature, max_tokens, json_mode)
        except LLMBusyError:
            return (await self._through_backups(
                "generate", lambda b: b.generate(prompt, system, temperature, max_tokens, json_mode)))[1]

    async def generate_stream(self, prompt: str, system: str | None = None, temperature: float = 0.3,
                              max_tokens: int = 2048) -> AsyncIterator[str]:
        stream = self._primary.generate_stream(prompt, system, temperature, max_tokens)
        try:
            first = await anext(stream)
        except StopAsyncIteration:
            return
        except LLMBusyError:
            async def open_backup(backup: LLMProvider):
                backup_stream = backup.generate_stream(prompt, system, temperature, max_tokens)
                return backup_stream, await anext(backup_stream)      # the first token proves the backup works

            try:
                index, (backup_stream, token) = await self._through_backups("stream", open_backup, hold=True)
            except StopAsyncIteration:
                return
            try:
                yield token
                async for token in backup_stream:
                    yield token
            finally:
                self._inflight[index] -= 1
            return
        yield first
        async for token in stream:
            yield token

    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str:
        try:
            return await self._primary.classify(text, categories, default)
        except LLMBusyError:
            return (await self._through_backups("classify", lambda b: b.classify(text, categories, default)))[1]


def backup_configs(settings) -> list[tuple[str, str, str]]:
    """The complete (base_url, api_key, model) backups, in order: LLM_FALLBACK_*, then LLM_FALLBACK2_*, LLM_FALLBACK3_*.
    A half-filled set is ignored."""
    out = []
    for prefix in ("llm_fallback", "llm_fallback2", "llm_fallback3"):
        url, key, model = (getattr(settings, f"{prefix}_{part}", "") for part in ("base_url", "api_key", "model"))
        if url and key and model:
            out.append((url, key, model))
    return out


def build_provider(settings) -> LLMProvider:
    """Groq with its model pool, then every configured backup provider in order (see backup_configs)."""
    groq = GroqProvider(
        api_key=settings.groq_api_key or os.environ.get("GROQ_API_KEY"),
        llm_model=settings.groq_model,
        classifier_model=settings.groq_classifier_model,
        fallback_models=settings.groq_fallback_models,
    )
    backups = [OpenAICompatibleProvider(url, key, model, timeout=BACKUP_TIMEOUT) for url, key, model in backup_configs(settings)]
    return FallbackProvider(groq, *backups) if backups else groq
