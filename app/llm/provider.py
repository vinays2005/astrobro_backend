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
    """Use the secondary provider whenever the primary reports LLMBusyError."""

    def __init__(self, primary: LLMProvider, secondary: LLMProvider) -> None:
        self._primary = primary
        self._secondary = secondary

    async def generate(self, prompt: str, system: str | None = None, temperature: float = 0.3,
                       max_tokens: int = 2048, json_mode: bool = False) -> str:
        try:
            return await self._primary.generate(prompt, system, temperature, max_tokens, json_mode)
        except LLMBusyError:
            logger.warning("llm_secondary_used", call="generate")
            return await self._secondary.generate(prompt, system, temperature, max_tokens, json_mode)

    async def generate_stream(self, prompt: str, system: str | None = None, temperature: float = 0.3,
                              max_tokens: int = 2048) -> AsyncIterator[str]:
        stream = self._primary.generate_stream(prompt, system, temperature, max_tokens)
        try:
            first = await anext(stream)
        except StopAsyncIteration:
            return
        except LLMBusyError:
            logger.warning("llm_secondary_used", call="stream")
            async for token in self._secondary.generate_stream(prompt, system, temperature, max_tokens):
                yield token
            return
        yield first
        async for token in stream:
            yield token

    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str:
        try:
            return await self._primary.classify(text, categories, default)
        except LLMBusyError:
            return await self._secondary.classify(text, categories, default)


def build_provider(settings) -> LLMProvider:
    """Groq with its model pool, plus a backup provider when LLM_FALLBACK_* is configured."""
    groq = GroqProvider(
        api_key=settings.groq_api_key or os.environ.get("GROQ_API_KEY"),
        llm_model=settings.groq_model,
        classifier_model=settings.groq_classifier_model,
        fallback_models=settings.groq_fallback_models,
    )
    if settings.llm_fallback_base_url and settings.llm_fallback_api_key and settings.llm_fallback_model:
        return FallbackProvider(groq, OpenAICompatibleProvider(
            settings.llm_fallback_base_url, settings.llm_fallback_api_key, settings.llm_fallback_model))
    return groq
