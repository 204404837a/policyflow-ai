"""Fraud scoring — statistical/rule signals over the case + claim history.

The six signals mirror the dataset's `fraud_reason`s. Any signal pushes the
score to ≥ the escalate threshold (→ ESCALATE), matching the derived label map.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    FRAUD_CONFIDENCE,
    FRAUD_ESCALATE_THRESHOLD,
    FRAUD_HIGH_RISK_THRESHOLD,
    FRAUD_WEIGHTS,
    MATERNITY_CPT_PREFIX,
    MATERNITY_ICD_PREFIXES,
    READMISSION_WINDOW_DAYS,
    STRUCTURING_MAX,
    STRUCTURING_MIN,
)
from app.db.models import ClaimHistory
from app.schemas.agents import FraudOutput
from app.schemas.enums import RiskLevel


@dataclass
class FraudSignals:
    duplicate_claim: bool = False
    readmission_30d: bool = False
    date_conflict: bool = False
    proc_diag_mismatch: bool = False
    structuring: bool = False
    name_mismatch: bool = False
    history_count: int = 0


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def structuring(amount: float | None) -> bool:
    return amount is not None and STRUCTURING_MIN <= amount <= STRUCTURING_MAX


def proc_diag_mismatch(cpt_codes: list[str], icd_codes: list[str]) -> bool:
    """Maternity procedure billed against a non-maternity diagnosis."""
    has_maternity_cpt = any(c.startswith(MATERNITY_CPT_PREFIX) for c in cpt_codes)
    if not has_maternity_cpt:
        return False
    has_maternity_icd = any(c.upper().startswith(MATERNITY_ICD_PREFIXES) for c in icd_codes)
    return not has_maternity_icd


def date_conflict(service_date: object, discharge_date: object) -> bool:
    svc, dis = _parse_date(service_date), _parse_date(discharge_date)
    return svc is not None and dis is not None and svc > dis


def readmission(service_date: object, history: list[ClaimHistory]) -> bool:
    svc = _parse_date(service_date)
    if svc is None:
        return False
    window = timedelta(days=READMISSION_WINDOW_DAYS)
    return any(0 <= (svc - h.claim_date).days <= window.days for h in history)


def score_case(sig: FraudSignals) -> FraudOutput:
    """Pure scorer: weighted sum of active signals → FraudOutput."""
    score = 0.0
    anomalies: list[str] = []
    for name, weight in FRAUD_WEIGHTS.items():
        if getattr(sig, name):
            score += weight
            anomalies.append(name)
    score = min(1.0, round(score, 3))

    if score >= FRAUD_HIGH_RISK_THRESHOLD:
        risk = RiskLevel.HIGH
    elif score >= FRAUD_ESCALATE_THRESHOLD:
        risk = RiskLevel.MEDIUM
    else:
        risk = RiskLevel.LOW

    return FraudOutput(
        fraud_score=score,
        anomalies=anomalies,
        risk_level=risk,
        claim_history_count=sig.history_count,
        confidence=FRAUD_CONFIDENCE,
    )


class FraudService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def history(self, member_id: str) -> list[ClaimHistory]:
        stmt = select(ClaimHistory).where(ClaimHistory.member_id == member_id)
        return list(await self._session.scalars(stmt))
