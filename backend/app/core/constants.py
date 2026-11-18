"""Decision thresholds & fixed constants — single reference point.

Values originate from env via `settings`; this module is the one place the
rest of the code imports them from (enforced by code-quality rule §1).
"""

from __future__ import annotations

from app.core.config import settings

# Orchestrator decision rule (see docs/HLD.md §3, GUARDRAILS.md G1)
FRAUD_ESCALATE_THRESHOLD: float = settings.fraud_escalate_threshold  # >= → ESCALATE
MIN_AGENT_CONFIDENCE: float = settings.min_agent_confidence  # < → ESCALATE

# Bounded autonomy (code-quality §7)
MAX_RETRIES: int = settings.max_retries

# Retrieval (docs/HLD.md §5)
RETRIEVAL_TOP_K: int = settings.retrieval_top_k
RETRIEVAL_RERANK_KEEP: int = 3  # top-N clauses returned after rerank
EMBEDDING_DIM: int = settings.embedding_dim
QDRANT_POINT_ID_MODULO: int = 10**15

# LLM gateway tuning (from settings)
HTTP_TIMEOUT_S: float = settings.http_timeout_s
LLM_MAX_ATTEMPTS: int = settings.llm_max_attempts
LLM_RETRY_INITIAL_S: float = settings.llm_retry_initial_s
LLM_RETRY_MAX_S: float = settings.llm_retry_max_s
BREAKER_FAIL_MAX: int = settings.breaker_fail_max
BREAKER_RESET_S: float = settings.breaker_reset_s
ERROR_TEXT_SNIPPET: int = 200  # chars of upstream error body to surface

# Confidence heuristics (single source; tuned per stage)
INGEST_CONFIDENCE_DOCLING: float = 0.9
INGEST_CONFIDENCE_VISION: float = 0.85
INGEST_CONFIDENCE_OCR: float = 0.4
KYC_CONFIDENCE_STRONG: float = 0.9  # ≥2 identity keys matched
KYC_CONFIDENCE_WEAK: float = 0.7  # 1 identity key
KYC_CONFIDENCE_MIN: float = 0.5  # no identity keys
CLAIMS_CONFIDENCE_BASE: float = 0.5  # floor; scales up with fields passing
POLICY_NO_CLAUSE_CONFIDENCE: float = 0.5

# Image forensics — ELA tamper detection (Phase 8 bonus, docs/EXTENSIONS.md)
ELA_JPEG_QUALITY: int = 90  # recompression quality for the error-level pass
ELA_TAMPER_PERCENTILE: float = 0.995  # robust high-percentile of recompression error
ELA_TAMPER_THRESHOLD: float = 0.18  # p99.5 error (0–1) above this ⇒ tamper suspected

# ID-expiry derivation offsets (seed) — days
ID_EXPIRED_OFFSET_DAYS: int = 90
ID_EXPIRING_SOON_DAYS: int = 20
ID_VALID_DAYS: int = 1095  # ~3 years

# Fraud scoring (docs/GOLDEN_SET.md)
FRAUD_HIGH_RISK_THRESHOLD: float = 0.6  # >= → HIGH (MEDIUM at FRAUD_ESCALATE_THRESHOLD)
FRAUD_CONFIDENCE: float = 0.8  # rule-based scorer confidence
READMISSION_WINDOW_DAYS: int = 30
STRUCTURING_MIN: float = 9000.0  # amounts just under the $10k reporting line
STRUCTURING_MAX: float = 9999.99
MATERNITY_CPT_PREFIX: str = "59"  # obstetric procedure codes
MATERNITY_ICD_PREFIXES: tuple[str, ...] = ("O", "Z34", "Z3A")
FRAUD_WEIGHTS: dict[str, float] = {
    "duplicate_claim": 0.5,
    "readmission_30d": 0.4,
    "date_conflict": 0.4,
    "proc_diag_mismatch": 0.4,
    "structuring": 0.35,
    "name_mismatch": 0.4,
}

# LangGraph
GRAPH_RECURSION_LIMIT: int = 25

# WebSocket status stream
WS_POLL_INTERVAL_S: float = 1.0
WS_MAX_SNAPSHOTS: int = 120

# Upload validation (docs/DATA_HANDLING.md)
MAX_FILE_BYTES: int = settings.max_file_bytes

# Object storage
PRESIGN_EXPIRES_S: int = 3600  # presigned URL lifetime
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/tiff", "application/pdf"}
)

# LiteLLM logical aliases — app code references these, never a provider/model id
VISION_ALIAS = "vision"
REASONING_ALIAS = "reasoning"
EMBEDDINGS_ALIAS = "embeddings"

# Sensitive field names (redaction / masking) — see core.security, core.logging
SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "ssn",
        "date_of_birth",
        "dob",
        "member_id",
        "patient_id",
        "policy_number",
        "name",
        "address",
        "provider_npi",
        "claim_amount",
        "icd_code",
        "cpt_code",
        "raw_text",
    }
)
