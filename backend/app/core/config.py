"""Application settings — the single source of truth for all config.

Everything is read from the environment (see `.env.example`). No secret,
endpoint, model id, or threshold is hardcoded elsewhere in the codebase
(enforced by `.claude/rules/code-quality.md` §1).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Secrets that must be explicitly set outside local dev (fail-closed).
_REQUIRED_SECRETS = (
    "groq_api_key",
    "huggingface_api_key",
    "litellm_master_key",
    "minio_secret_key",
)
_DEV_DB_MARKERS = ("policyflow:policyflow", "claimshield:claimshield")
_DEV_JWT_SECRET = "dev-insecure-change-me"  # must be overridden outside local


class Settings(BaseSettings):
    """Env-backed settings. Field names map case-insensitively to env vars."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # ---- App ----
    app_env: str = "local"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]

    # ---- LLM gateway (LiteLLM → Groq / Hugging Face) ----
    groq_api_key: str = ""
    huggingface_api_key: str = ""
    litellm_master_key: str = ""
    litellm_base_url: str = "http://litellm:4000"

    # ---- Auth (RBAC) ----
    jwt_secret: str = "dev-insecure-change-me"  # required outside local
    jwt_algorithm: str = "HS256"
    jwt_expiry_min: int = 1440  # 24h
    admin_username: str = "admin"  # bootstrap admin (created by seed)
    admin_password: str = "admin"  # dev default; override via env outside local

    # ---- Tracing ----
    langsmith_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "policyflow-ai"

    # ---- Postgres ----
    database_url: str = "postgresql+asyncpg://policyflow:policyflow@postgres:5432/policyflow"

    # ---- Qdrant ----
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "policy_documents"

    # ---- MinIO ----
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = ""  # no default secret — must be set via env
    minio_bucket: str = "policyflow"
    minio_secure: bool = False

    # ---- Redis ----
    redis_url: str = "redis://redis:6379/0"

    # ---- Decision thresholds (referenced via core.constants) ----
    fraud_escalate_threshold: float = 0.3
    min_agent_confidence: float = 0.6
    max_retries: int = 3
    retrieval_top_k: int = 8

    # ---- LLM gateway tuning ----
    http_timeout_s: float = 90.0
    llm_max_attempts: int = 3
    llm_retry_initial_s: float = 0.5
    llm_retry_max_s: float = 8.0
    # Minimum seconds between LLM call starts (process-wide). 0 = disabled
    # (interactive/api). Set >0 on the worker to serialize + pace calls under a
    # free-tier tokens/min limit during batch eval (e.g. 12s ≈ 5 calls/min).
    llm_min_interval_s: float = 0.0
    breaker_fail_max: int = 5
    breaker_reset_s: float = 30.0

    # ---- Vector store ----
    embedding_dim: int = 1024

    # ---- Eval ----
    # Where a live eval run persists its predictions capture. Empty → repo
    # dataset/ (host/offline CLI). In containers dataset/ is read-only, so set a
    # writable shared path (see docker-compose EVAL_CAPTURE_PATH).
    eval_capture_path: str = ""
    # Delay between case-bundles during a live eval run, to stay under the LLM
    # gateway's rate limit (free tiers 429 on bursts). Tune up if runs still 429.
    eval_case_delay_s: float = 2.0

    # ---- Upload limits ----
    max_file_mb: int = 10

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @model_validator(mode="after")
    def _enforce_secrets_outside_local(self) -> Settings:
        """Fail-closed: outside local dev, required secrets must be set and the
        dev-default DB credentials must not be used."""
        if self.app_env.lower() == "local":
            return self
        missing = [name for name in _REQUIRED_SECRETS if not getattr(self, name)]
        if missing:
            raise ValueError(f"Missing required secrets for app_env={self.app_env!r}: {missing}")
        if any(marker in self.database_url for marker in _DEV_DB_MARKERS):
            raise ValueError("Refusing dev-default DATABASE_URL credentials outside local")
        if self.jwt_secret == _DEV_JWT_SECRET:
            raise ValueError("Set a real JWT_SECRET outside local")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (constructed once per process)."""
    return Settings()


settings = get_settings()
