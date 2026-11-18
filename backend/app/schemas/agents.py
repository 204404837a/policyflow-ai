"""Agent I/O contracts (Pydantic v2). See docs/LLD.md §3 and DATA_DICTIONARY.md."""

from __future__ import annotations

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.schemas.enums import Decision, DocumentType, RiskLevel

# ---- coercion helpers (LLM output is loosely typed) ----------------------


def as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [p.strip() for p in str(value).replace(";", ",").split(",") if p.strip()]


def as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def as_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


class ClassifierOutput(BaseModel):
    doc_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)
    routing_tags: list[str] = Field(default_factory=list)


class KYCOutput(BaseModel):
    kyc_passed: bool
    member_found: bool
    member_id: str | None = None
    id_valid: bool = True
    id_expired: bool = False
    tamper_suspected: bool = False
    flags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ClaimsExtractedFields(BaseModel):
    """Parses the claim form's (loosely-typed) extracted fields and serves as the
    Claims output contract. Alias-tolerant + self-coercing so the raw vision
    output maps in one `model_validate` (no hand-written `.get()` fan-out)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    patient_name: str | None = Field(
        default=None, validation_alias=AliasChoices("patient_name", "full_name")
    )
    member_id: str | None = None
    claim_amount: float | None = Field(
        default=None, validation_alias=AliasChoices("claim_amount", "amount")
    )
    icd_codes: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("icd_codes", "icd_code")
    )
    cpt_codes: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("cpt_codes", "cpt_code")
    )
    provider_npi: str | None = None
    service_date: str | None = Field(
        default=None, validation_alias=AliasChoices("service_date", "date")
    )
    provider_name: str | None = None

    @field_validator("claim_amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> float | None:
        return as_float(v)

    @field_validator("icd_codes", "cpt_codes", mode="before")
    @classmethod
    def _coerce_codes(cls, v: object) -> list[str]:
        return as_list(v)

    @field_validator(
        "patient_name",
        "member_id",
        "provider_npi",
        "service_date",
        "provider_name",
        mode="before",
    )
    @classmethod
    def _coerce_str(cls, v: object) -> str | None:
        # Vision can return multi-valued fields (e.g. a from/to service_date) as
        # a list; keep the first value for these single-string fields.
        if isinstance(v, list):
            v = v[0] if v else None
        return as_str(v)


class ClaimsOutput(BaseModel):
    extracted_fields: ClaimsExtractedFields
    schema_valid: bool
    validation_errors: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class PolicyOutput(BaseModel):
    covered: bool
    coverage_percentage: float | None = None
    policy_clause: str | None = None
    policy_section: str | None = None
    exclusions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class FraudOutput(BaseModel):
    fraud_score: float = Field(ge=0.0, le=1.0)
    anomalies: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    claim_history_count: int = 0
    confidence: float = Field(ge=0.0, le=1.0)


class OrchestratorOutput(BaseModel):
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    justification: str
    agent_summaries: dict[str, dict] = Field(default_factory=dict)
