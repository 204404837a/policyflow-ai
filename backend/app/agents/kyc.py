"""KYC agent — rule-based identity validation against the member DB.

Deterministic checks (member found, ID expiry, name mismatch, policy match) —
no LLM needed; matches the dataset's KYC signals exactly. The ELA tamper signal
is computed upstream on the ID image (services/image_forensics.py) and arrives
via `identity["tamper_suspected"]`; here it becomes a `TAMPER_SUSPECTED` flag
that blocks APPROVE (fail-closed, Phase 8 bonus).
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.core.constants import (
    KYC_CONFIDENCE_MIN,
    KYC_CONFIDENCE_STRONG,
    KYC_CONFIDENCE_WEAK,
)
from app.db.models import Member
from app.schemas.agents import KYCOutput


class SupportsMemberLookup(Protocol):
    async def lookup(
        self,
        member_id: str | None = None,
        policy_number: str | None = None,
        name: str | None = None,
    ) -> Member | None: ...


def _norm(value: object) -> str:
    if not value:
        return ""
    return " ".join(str(value).lower().replace(".", "").split())


class KYCAgent:
    def __init__(self, members: SupportsMemberLookup) -> None:
        self._members = members

    async def run(self, identity: dict, *, case_id: str | None = None) -> KYCOutput:
        member_id = identity.get("member_id")
        policy = identity.get("policy_number")
        name = identity.get("name") or identity.get("full_name")

        member = await self._members.lookup(member_id=member_id, policy_number=policy, name=name)
        if member is None:
            return KYCOutput(
                kyc_passed=False,
                member_found=False,
                id_valid=False,
                flags=["MEMBER_NOT_FOUND"],
                confidence=KYC_CONFIDENCE_STRONG,
            )

        flags: list[str] = []
        id_expired = bool(member.id_expiry_date and member.id_expiry_date < date.today())
        if id_expired:
            flags.append("EXPIRED_ID")
        if name and _norm(name) != _norm(member.name):
            flags.append("NAME_MISMATCH")
        if policy and member.policy_number and policy != member.policy_number:
            flags.append("POLICY_MISMATCH")
        # ELA tamper signal is computed upstream (graph) on the ID image bytes.
        tamper_suspected = bool(identity.get("tamper_suspected"))
        if tamper_suspected:
            flags.append("TAMPER_SUSPECTED")

        provided = sum(1 for v in (member_id, policy, name) if v)
        if provided >= 2:
            confidence = KYC_CONFIDENCE_STRONG
        elif provided == 1:
            confidence = KYC_CONFIDENCE_WEAK
        else:
            confidence = KYC_CONFIDENCE_MIN
        return KYCOutput(
            kyc_passed=not flags,
            member_found=True,
            member_id=member.member_id,
            id_valid=not id_expired and not tamper_suspected,
            id_expired=id_expired,
            tamper_suspected=tamper_suspected,
            flags=flags,
            confidence=confidence,
        )
