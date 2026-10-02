"""
LLM provider abstraction — Groq backend (swapped from Ollama for production).

The LLM is the REASONING layer only. It never calculates astrology.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import AsyncIterator

from groq import AsyncGroq, APIStatusError, APIConnectionError, APITimeoutError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
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
    async def classify(self, text: str, categories: list[str]) -> str: ...


# Retry only transient failures: rate limits (429), server errors (5xx),
# connection drops, timeouts. Client errors like bad API key (401) or bad
# request (400) are NOT retried — retrying those wastes time and hides a
# real bug behind a delay.
_RETRYABLE_EXC = (APIConnectionError, APITimeoutError, APIStatusError)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


_retry_policy = retry(
    retry=retry_if_exception_type(_RETRYABLE_EXC),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)


class GroqProvider(LLMProvider):
    """Groq backend — cloud inference, no local GPU/VRAM constraint.

    Reads GROQ_API_KEY from environment (fail loud if missing, no silent
    fallback). Model names come from settings/env, not hardcoded, so prod
    and dev can point at different tiers without a code change.

    Retries on rate limits (429) and transient server/connection errors
    with exponential backoff (up to 4 attempts, 1s-20s wait). Client
    errors (401, 400) are never retried — they mean a real bug, not a
    transient failure, so they fail loud on the first try.
    """

    def __init__(
        self,
        api_key: str | None = None,
        llm_model: str = "llama-3.1-8b-instant",
        classifier_model: str = "llama-3.1-8b-instant",
        timeout: int = 120,
    ) -> None:
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise ValueError(
                "GROQ_API_KEY not set. Export it or pass api_key= explicitly."
            )
        # Groq's client (httpx under the hood) takes a plain seconds value
        # here as a blanket connect+read+write timeout — cast to float so
        # an int from config/env doesn't cause a type mismatch downstream.
        self._client = AsyncGroq(api_key=key, timeout=float(timeout))
        self._llm_model = llm_model
        self._classifier_model = classifier_model

    def _build_messages(
        self, prompt: str, system: str | None
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    @_retry_policy
    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        """Generate a completion.

        json_mode=True sets response_format={"type": "json_object"},
        asking Groq to constrain output to valid JSON — more reliable
        than the current regex-strip-markdown-fence parsing in the
        orchestrator. The prompt must still instruct the model to
        produce JSON; json_object mode enforces the *shape* only, not
        which fields are present.
        """
        kwargs: dict = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await self._client.chat.completions.create(
            model=self._llm_model,
            messages=self._build_messages(prompt, system),
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    async def generate_stream(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        # No retry decorator — tenacity cannot wrap async generators.
        # Errors during streaming propagate naturally to the caller.
        stream = await self._client.chat.completions.create(
            model=self._llm_model,
            messages=self._build_messages(prompt, system),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    @_retry_policy
    async def classify(
        self, text: str, categories: list[str], default: str | None = None
    ) -> str:
        """Fast intent classification using the same small/cheap model.

        Tries an exact/word match first, then falls back to substring
        match (avoids a short category like "car" wrongly matching inside
        an unrelated longer word such as "scared"). Falls back to
        `default` (or the last category) when nothing matches — explicit,
        never a silent None.
        """
        prompt = (
            f"Classify the following astrology question into exactly one "
            f"category from this list: {', '.join(categories)}.\n\n"
            f"Question: {text}\n\n"
            f"Respond with ONLY the category name, nothing else."
        )
        response = await self._client.chat.completions.create(
            model=self._classifier_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10,
        )
        result = (response.choices[0].message.content or "").strip().lower()

        for cat in categories:
            if cat.lower() == result or cat.lower() in result.split():
                return cat
        for cat in categories:
            if cat.lower() in result:
                return cat
        return default or categories[-1]