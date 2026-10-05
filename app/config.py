"""Application configuration from environment variables."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "AstroBro AI"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    secret_key: str = "change-me"
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "deepseek-r1:7b"
    ollama_classifier_model: str = "qwen2.5:1.5b"
    ollama_timeout: int = 120
    ollama_num_ctx: int = 4096
    ollama_num_gpu: int = 20
    ollama_keep_alive: str = "5m"

    # Embeddings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Reranker (CrossEncoder removed — used PyTorch which OOM-killed Railway)
    reranker_enabled: bool = False
    reranker_model: str = ""
    reranker_top_k: int = 5

    # Vector DB
    vector_db: Literal["qdrant"] = "qdrant"
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    books_collection: str = "vedic_books"
    # Separate collection for specialist books (tarot, numerology, Vastu, festivals, calendar, lore);
    # only questions on those topics read it. Empty disables it.
    specialist_collection: str = "specialist_books"

    # Astrology
    ayanamsa: str = "LAHIRI"
    house_system: str = "W"
    dasha_system: str = "vimshottari"

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/astrobro.db"

    # LLM provider keys (read from env/Railway, never hardcoded)
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    groq_classifier_model: str = "qwen/qwen3.8-27b"
    # Long-form PDF sections need ~3k output tokens; qwen's on-demand OTPM cap is 1000.
    groq_report_model: str = "openai/gpt-oss-120b"
    groq_stt_model: str = "whisper-large-v3-turbo"
    # Groq limits tokens per minute PER MODEL, so a rate-limited chat moves to the next model in this list at once.
    # Set GROQ_FALLBACK_MODELS to a comma-separated list, or leave it empty to use only GROQ_MODEL.
    groq_fallback_models: Annotated[list[str], NoDecode] = ["openai/gpt-oss-20b"]
    # Optional second provider for when every Groq model is busy: any OpenAI-compatible endpoint, for example
    # Cerebras (https://api.cerebras.ai/v1) or Gemini (https://generativelanguage.googleapis.com/v1beta/openai).
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""
    # More backups, tried in order after the first: LLM_FALLBACK2_* and LLM_FALLBACK3_* (for example NVIDIA NIM,
    # https://integrate.api.nvidia.com/v1, and OpenRouter, https://openrouter.ai/api/v1). Each needs all three values.
    llm_fallback2_base_url: str = ""
    llm_fallback2_api_key: str = ""
    llm_fallback2_model: str = ""
    llm_fallback3_base_url: str = ""
    llm_fallback3_api_key: str = ""
    llm_fallback3_model: str = ""

    # Episodic memory: signed-in users' earlier questions are recalled in new chats (see app/services/memory.py)
    chat_memory_enabled: bool = True

    # Razorpay
    razorpay_key_id: str = ""      # rzp_test_... or rzp_live_...
    razorpay_key_secret: str = ""  # from Razorpay dashboard

    # Report generation
    # When True: paid PDF is granted without payment verification (dev/pre-launch mode)
    # Set to False once Razorpay keys are live and verified
    auto_approve_payments: bool = False
    paid_report_price: int = 4900   # ₹49 in paise

    # Security
    rate_limit_per_minute: int = 60
    api_key: str = ""  # X-API-Key header — empty = disabled (dev), set in prod

    # Identity: Firebase Auth ID tokens (see app/security/identity.py)
    firebase_project_id: str = "astro-bro-96380"
    # False = also accept requests that carry only the API key (older app versions). Set REQUIRE_ID_TOKEN=true
    # once the new app is out, so every AI route is metered and protected per signed-in user.
    require_id_token: bool = False
    # Owners who may use /api/admin/*. An email only counts when Firebase reports it as verified.
    admin_emails: Annotated[list[str], NoDecode] = []
    admin_uids: Annotated[list[str], NoDecode] = []

    # Plans and limits (enforced on the server, not in the app)
    free_chats_per_day: int = 10
    premium_chats_per_day: int = 300
    report_free_for_premium: bool = True        # premium plans include the detailed PDF report

    # Wallet and consultations with human astrologers
    wallet_min_topup_paise: int = 10000         # Rs 100
    wallet_max_topup_paise: int = 500000        # Rs 5,000
    platform_commission_percent: int = 30       # share of each consultation kept by the platform
    consult_min_minutes: int = 5                # balance a user needs to start a session
    consult_request_ttl_seconds: int = 120      # a request nobody accepts expires
    consult_idle_timeout_seconds: int = 600     # a session with no messages for this long is closed
    block_contact_sharing: bool = True          # reject phone numbers, emails and links in chats
    razorpay_webhook_secret: str = ""           # enables POST /api/billing/webhook

    # Observability
    log_level: str = "INFO"

    @field_validator("allowed_origins", "admin_emails", "admin_uids", "groq_fallback_models", mode="before")
    @classmethod
    def parse_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, list):
            return v
        # Handle plain comma-separated: http://a.com,http://b.com
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        # Handle JSON array string: ["http://a.com","http://b.com"]
        import json
        return json.loads(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()