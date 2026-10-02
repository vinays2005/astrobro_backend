"""
Agent orchestrator — routes queries to minimum necessary agents.

Routing:
  simple factual  → Kundli → Response
  topic analysis  → Kundli → Rules → RAG → Prediction → Verify → Response
  dasha question  → Kundli → Dasha → Response
  chat follow-up  → (reuse chart) → RAG → Response
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from app.agents.state import AstrologyState
from app.astrology.engine import AstrologyEngine, Chart
from app.config import get_settings
from app.llm.provider import GroqProvider, LLMProvider
from app.llm.prompts import (
    CHAT_PROMPT,
    PREDICTION_PROMPT,
    SYSTEM_ASTROLOGER,
    VERIFICATION_PROMPT,
)
from app.rag.retrieval import HybridRetriever
from app.rules.engine import RuleEngine
from app.security.sanitization import wrap_evidence_list

QueryType = Literal["topic_analysis", "simple_factual", "chat"]

_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "marriage":     ["marriage", "marry", "spouse", "wedding", "partner", "relationship"],
    "career":       ["career", "job", "profession", "work", "business", "promotion"],
    "finance":      ["money", "wealth", "finance", "income", "gain", "rich", "savings"],
    "education":    ["education", "study", "exam", "degree", "college", "learning"],
    "health":       ["health", "disease", "illness", "body", "sick", "medicine"],
    "children":     ["child", "children", "son", "daughter", "baby", "pregnant"],
    "property":     ["property", "house", "land", "flat", "real estate"],
    "travel":       ["travel", "journey", "foreign", "abroad", "visa"],
    "spirituality": ["spiritual", "meditation", "moksha", "dharma", "liberation", "karma"],
}

_SIMPLE_PATTERNS: list[str] = [
    "moon sign", "lagna", "ascendant", "nakshatra",
    "rashi", "sun sign", "what sign", "which house",
]


class AgentOrchestrator:
    """
    Single entry point for all AI astrology queries.

    All expensive components (LLM, RAG, rules) are lazily initialised
    and reused across calls.
    """

    def __init__(
        self,
        engine: AstrologyEngine | None = None,
        llm: LLMProvider | None = None,
        retriever: HybridRetriever | None = None,
        rules: RuleEngine | None = None,
    ) -> None:
        # __init__ accepts the LLMProvider abstraction, not the concrete
        # GroqProvider — callers (tests, a future non-Groq backend) can
        # inject any implementation. Only the *default* instantiated below
        # is Groq-specific.
        _s = get_settings()
        self._engine = engine or AstrologyEngine()
        self._llm = llm or GroqProvider(
            api_key=_s.groq_api_key or os.environ.get("GROQ_API_KEY"),
            llm_model=_s.groq_model or os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant"),
            classifier_model=_s.groq_classifier_model or os.environ.get(
                "GROQ_CLASSIFIER_MODEL", "llama-3.1-8b-instant"
            ),
        )
        self._retriever = retriever or HybridRetriever(
            embedding_model=_s.embedding_model,
            qdrant_url=_s.qdrant_url,
            qdrant_api_key=_s.qdrant_api_key,
            collection_name=_s.books_collection,
            embedding_dimension=_s.embedding_dimension,
            reranker_enabled=_s.reranker_enabled,
        )
        self._rules = rules or RuleEngine()

    async def run(
        self,
        user_input: str,
        birth_data: dict | None = None,
        existing_chart: dict | None = None,
        topic_hint: str | None = None,
        conversation_history: list[dict] | None = None,
        force_chat: bool = False,
    ) -> dict:
        """Main entry point. Returns structured JSON response.

        force_chat=True pins routing to the chat pipeline regardless of
        topic keywords, so callers that require ChatResponse (answer field)
        never get routed into the prediction-shaped _full_pipeline output.

        existing_chart, when given, is a pre-built chart dict (the same
        shape _chart_to_dict produces) from a prior call in this
        conversation. Passing it skips the swiss-ephemeris recalculation —
        useful for chat follow-ups where the birth chart hasn't changed.
        birth_data still takes priority if both are given, since an
        explicit birth_data on this call means the caller wants a fresh
        chart (e.g. the user edited their birth details).
        """
        state = AstrologyState(
            request_id=str(uuid.uuid4()),
            user_input=user_input,
            topic=topic_hint,
        )

        # 1. Build chart — recalculate from birth_data, reuse existing_chart,
        # or skip entirely if neither is given.
        chart: Chart | None = None
        if birth_data:
            try:
                chart = self._engine.calculate_chart(
                    dt=self._parse_birth_datetime(birth_data),
                    lat=float(birth_data["latitude"]),
                    lon=float(birth_data["longitude"]),
                    tz=birth_data.get("timezone", "Asia/Kolkata"),
                )
                state.set("kundli", "chart", self._chart_to_dict(chart))
                state.set("kundli", "dasha", chart.current_dasha)
            except Exception as exc:
                state.append_error(f"chart_calculation: {exc}")
        elif existing_chart:
            # Reuse a chart computed earlier in this conversation. It's
            # already a dict (not a typed Chart), so it feeds state/prompts
            # for the chat and simple-factual paths, but _full_pipeline
            # below still requires a freshly-calculated Chart object (it
            # needs rule-engine access to typed planet/house data) — so a
            # topic_analysis query with only existing_chart, no birth_data,
            # falls through to chat instead. That's the intended trade-off
            # for chat follow-ups: cheap reuse for conversation, exact
            # recalculation for a real prediction request.
            state.set("kundli", "chart", existing_chart)
            state.set("kundli", "dasha", existing_chart.get("current_dasha") or {})

        # 2. Classify topic
        if state.topic is None:
            state.topic = self._classify_topic(user_input)

        # 3. Route
        query_type: QueryType = "chat" if force_chat else self._query_type(user_input)

        if query_type == "topic_analysis" and chart is not None:
            await self._full_pipeline(state, chart, conversation_history or [])
        elif query_type == "simple_factual":
            await self._simple_response(state)
        else:
            await self._chat_pipeline(state, chart, conversation_history or [])

        return state.final_response or {
            "request_id": state.request_id,
            "error": "No response generated",
            "errors": state.errors,
        }

    # ── Pipelines ─────────────────────────────────────────────

    async def _full_pipeline(
        self, state: AstrologyState, chart: Chart, history: list[dict]
    ) -> None:
        """Kundli → Rules → RAG → LLM prediction → Verification → Response."""

        topic = state.topic or "general"
        if topic != "general":
            rule_results = self._rules.evaluate(chart, topic)
            state.set("rules", "rule_results", [
                {
                    "rule_id": r.rule_id,
                    "matched": r.matched,
                    "strength": r.strength,
                    "interpretation": r.interpretation,
                    "factors": r.factors,
                }
                for r in rule_results
            ])

        evidence = await self._retriever.retrieve(
            query=f"{topic} {state.user_input}",
            top_k=8,
            rerank_top_k=4,
        )
        for chunk in evidence:
            state.retrieved_evidence.append({
                "text": chunk.text,
                "metadata": chunk.metadata,
                "score": chunk.score,
            })

        chart_json = json.dumps(state.chart or {}, indent=2, default=str)
        dasha_json = json.dumps(state.dasha or {}, indent=2, default=str)
        rules_json = json.dumps(state.rule_results, indent=2, default=str)
        evidence_wrapped = wrap_evidence_list(state.retrieved_evidence)

        prompt = PREDICTION_PROMPT.format(
            chart_json=chart_json,
            dasha_json=dasha_json,
            rules_json=rules_json,
            evidence_json=evidence_wrapped,
            question=state.user_input,
            topic=topic,
        )

        # json_mode=True — Groq returns clean JSON, no fence stripping needed
        raw = await self._llm.generate(
            prompt,
            system=SYSTEM_ASTROLOGER,
            json_mode=True,
            max_tokens=1200,
        )
        interpretation = self._parse_json_response(raw)

        verify_prompt = VERIFICATION_PROMPT.format(
            interpretation_json=json.dumps(interpretation, indent=2),
            chart_json=chart_json,
            dasha_json=dasha_json,
            rules_json=rules_json,
        )
        # json_mode=True — verification is also a structured JSON response
        verify_raw = await self._llm.generate(
            verify_prompt,
            system=SYSTEM_ASTROLOGER,
            json_mode=True,
            max_tokens=600,
        )
        verification = self._parse_json_response(verify_raw)

        if not verification.get("verified", True) and "corrected_interpretation" in verification:
            interpretation = verification["corrected_interpretation"]

        state.set("response", "final_response", {
            "request_id": state.request_id,
            "topic": topic,
            **interpretation,
            "verification": {
                "verified": verification.get("verified"),
                "issues": verification.get("issues", []),
            },
            "disclaimer": "Vedic astrology interpretation. Not a substitute for professional advice.",
            "errors": state.errors,
        })

    async def _simple_response(self, state: AstrologyState) -> None:
        """Quick factual answer from chart data — no LLM needed."""
        chart = state.chart or {}
        asc = chart.get("ascendant", {})
        planets = chart.get("planets", {})
        moon = planets.get("Moon", {})

        answer = (
            f"Your ascendant (Lagna) is {asc.get('sign', 'unknown')} "
            f"and Moon sign is {moon.get('sign', 'unknown')} "
            f"in {moon.get('nakshatra', 'unknown')} nakshatra."
        )

        state.set("response", "final_response", {
            "request_id": state.request_id,
            "topic": "chart_facts",
            "answer": answer,
            "sources": [],
            "errors": state.errors,
        })

    async def _chat_pipeline(
        self, state: AstrologyState, chart: Chart | None, history: list[dict]
    ) -> None:
        """Conversational: RAG → LLM chat → Response."""
        evidence = await self._retriever.retrieve(
            query=state.user_input, top_k=6, rerank_top_k=3
        )
        for chunk in evidence:
            state.retrieved_evidence.append({
                "text": chunk.text,
                "metadata": chunk.metadata,
            })

        chart_json = json.dumps(state.chart or {}, indent=2, default=str)
        dasha_json = json.dumps(state.dasha or {}, indent=2, default=str)
        evidence_wrapped = wrap_evidence_list(state.retrieved_evidence)

        prompt = CHAT_PROMPT.format(
            chart_json=chart_json,
            dasha_json=dasha_json,
            evidence_json=evidence_wrapped,
            history_json=json.dumps(history[-4:], indent=2),
            question=state.user_input,
        )

        # json_mode=True — chat response also expects structured JSON
        raw = await self._llm.generate(
            prompt,
            system=SYSTEM_ASTROLOGER,
            temperature=0.4,
            json_mode=True,
            max_tokens=900,
        )
        result = self._parse_json_response(raw)

        # Guarantee `answer` exists regardless of what keys the LLM emits —
        # ChatResponse requires it. Falls back to `summary` or a stringified
        # dump so a malformed LLM reply never causes a 500 at serialization.
        if "answer" not in result:
            result["answer"] = result.pop("summary", None) or json.dumps(result)

        state.set("response", "final_response", {
            "request_id": state.request_id,
            **result,
            "errors": state.errors,
            "disclaimer": "Vedic astrology guidance. Consult a professional for major decisions.",
        })

    async def run_chat_stream(
        self,
        user_input: str,
        birth_data: dict | None = None,
        conversation_history: list[dict] | None = None,
    ):
        """
        Streaming chat pipeline — yields raw LLM tokens as they arrive.

        Unlike run() + fake word-splitting, this uses Groq's streaming API
        so the first token reaches the client in ~1s instead of ~2 minutes.
        Cannot use json_mode=True (Groq streaming doesn't support it), so
        the response is plain text; callers assemble it into `answer`.
        """
        chart_dict: dict = {}
        dasha: dict = {}
        if birth_data:
            try:
                chart = self._engine.calculate_chart(
                    dt=self._parse_birth_datetime(birth_data),
                    lat=float(birth_data["latitude"]),
                    lon=float(birth_data["longitude"]),
                    tz=birth_data.get("timezone", "Asia/Kolkata"),
                )
                chart_dict = self._chart_to_dict(chart)
                dasha = chart.current_dasha
            except Exception:
                pass

        try:
            evidence_chunks = await self._retriever.retrieve(
                query=user_input, top_k=6, rerank_top_k=3
            )
            evidence_list = [{"text": c.text, "metadata": c.metadata} for c in evidence_chunks]
        except Exception:
            evidence_list = []

        chart_json = json.dumps(chart_dict, indent=2, default=str)
        dasha_json = json.dumps(dasha, indent=2, default=str)
        evidence_wrapped = wrap_evidence_list(evidence_list)
        history = (conversation_history or [])[-4:]

        prompt = CHAT_PROMPT.format(
            chart_json=chart_json,
            dasha_json=dasha_json,
            evidence_json=evidence_wrapped,
            history_json=json.dumps(history, indent=2),
            question=user_input,
        )

        async for token in self._llm.generate_stream(
            prompt,
            system=SYSTEM_ASTROLOGER,
            temperature=0.4,
            max_tokens=900,
        ):
            yield token

    # ── Routing helpers ───────────────────────────────────────

    def _classify_topic(self, text: str) -> str:
        lower = text.lower()
        for topic, keywords in _TOPIC_KEYWORDS.items():
            if any(k in lower for k in keywords):
                return topic
        return "general"

    def _query_type(self, text: str) -> QueryType:
        lower = text.lower()
        if any(p in lower for p in _SIMPLE_PATTERNS):
            return "simple_factual"
        topic = self._classify_topic(text)
        if topic != "general":
            return "topic_analysis"
        return "chat"

    # ── Utilities ─────────────────────────────────────────────

    def _parse_birth_datetime(self, birth_data: dict) -> datetime:
        dob = birth_data["date_of_birth"]
        tob = birth_data.get("time_of_birth", "12:00")
        return datetime.fromisoformat(f"{dob}T{tob}:00")

    def _chart_to_dict(self, chart: Chart) -> dict:
        return {
            "ascendant": chart.ascendant,
            "planets": {
                name: {
                    "sign": p.sign, "degree": p.sign_degree, "house": p.house,
                    "nakshatra": p.nakshatra, "nakshatra_pada": p.nakshatra_pada,
                    "nakshatra_lord": p.nakshatra_lord,
                    "retrograde": p.retrograde, "combust": p.combust,
                    "dignity": p.dignity, "dignity_score": p.dignity_score,
                }
                for name, p in chart.planets.items()
            },
            "houses": [
                {"number": h.number, "sign": h.sign, "lord": h.lord, "occupants": h.occupants}
                for h in chart.houses
            ],
            "yogas": chart.yogas,
            "nakshatra_moon": {
                "name": chart.nakshatra_moon.name,
                "pada": chart.nakshatra_moon.pada,
                "lord": chart.nakshatra_moon.lord,
            },
        }

    def _parse_json_response(self, raw: str) -> dict:
        """Parse LLM JSON response. Safety net — kept even with json_mode=True
        because a retry-without-json-mode fallback or a provider hiccup could
        still emit fenced text. Fail loud on parse error."""
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {exc}\nRaw: {raw[:500]}") from exc