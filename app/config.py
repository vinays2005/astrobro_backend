"""Application configuration from environment variables."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    allowed_origins: list[str] = ["http://localhost:3000"]

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

    # Observability
    log_level: str = "INFO"

    @field_validator("allowed_origins", mode="before")
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