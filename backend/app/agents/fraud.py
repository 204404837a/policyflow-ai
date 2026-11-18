"""Fraud agent — assembles signals from the case context + history → FraudOutput."""

from __future__ import annotations

from typing import Protocol

from app.db.models import ClaimHistory
from app.schemas.agents import FraudOutput
from app.services.fraud_service import (
    FraudSignals,
    date_conflict,
    proc_diag_mismatch,
    readmission,
    score_case,
    structuring,
)


class SupportsHistory(Protocol):
    async def history(self, member_id: str) -> list[ClaimHistory]: ...


class FraudAgent:
    def __init__(self, service: SupportsHistory) -> None:
        self._service = service

    async def run(self, ctx: dict, *, case_id: str | None = None) -> FraudOutput:
        """`ctx` carries the aggregated case signals:
        member_id, claim_doc_count, claim_amount, cpt_codes, icd_codes,
        service_date, discharge_date, kyc_flags.
        """
        member_id = ctx.get("member_id")
        history = await self._service.history(member_id) if member_id else []

        sig = FraudSignals(
            duplicate_claim=int(ctx.get("claim_doc_count", 1)) > 1,
            readmission_30d=readmission(ctx.get("service_date"), history),
            date_conflict=date_conflict(ctx.get("service_date"), ctx.get("discharge_date")),
            proc_diag_mismatch=proc_diag_mismatch(
                ctx.get("cpt_codes", []), ctx.get("icd_codes", [])
            ),
            structuring=structuring(ctx.get("claim_amount")),
            name_mismatch="NAME_MISMATCH" in ctx.get("kyc_flags", []),
            history_count=len(history),
        )
        return score_case(sig)
