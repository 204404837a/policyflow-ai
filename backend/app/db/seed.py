"""Seed the member DB + synthetic claim history from the dataset.

`members` are loaded **verbatim** from `dataset/members.json` (IDs must match the
generated documents, else KYC fails — docs/DATABASE_SCHEMA.md §5). `claim_history`
is a light benign baseline per member; the dataset's fraud signals are encoded
intra-bundle in the documents and detected at runtime (see phase1-plan.md).

Run: `uv run python -m app.db.seed`
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.constants import (
    ID_EXPIRED_OFFSET_DAYS,
    ID_EXPIRING_SOON_DAYS,
    ID_VALID_DAYS,
)
from app.core.logging import configure_logging, get_logger
from app.db.models import ClaimHistory, Member
from app.db.session import SessionFactory
from app.schemas.enums import Role

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATASET_DIR = Path(os.environ.get("DATASET_DIR", _REPO_ROOT / "dataset"))

_ICD_POOL = ["E11.9", "I10", "J45.909", "M54.5", "K21.9", "N39.0"]
_CPT_POOL = ["99213", "99214", "80053", "93000", "71046", "70450"]
_HISTORY_MIN_CLAIMS, _HISTORY_MAX_CLAIMS = 1, 2
_HISTORY_AMOUNT_MIN, _HISTORY_AMOUNT_MAX = 150.0, 4200.0


class MemberSeed(BaseModel):
    """Typed view of one `members.json` record (validated on load)."""

    model_config = ConfigDict(extra="ignore")

    member_id: str
    name: str
    id_display_name: str | None = None
    dob: str | None = None
    gender: str | None = None
    policy_number: str
    policy_type: str = "GOLD"
    group_number: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    id_type: str | None = None
    provider_npi: str | None = None
    cluster_id: str | None = None
    is_fraud: bool = False
    fraud_reason: str | None = None
    edge_flags: list[str] = Field(default_factory=list)


def _derive_id_expiry(edge_flags: list[str]) -> date:
    """Derive ID expiry from the edge flags baked into the dataset."""
    today = date.today()
    if "expired_id" in edge_flags:
        return today - timedelta(days=ID_EXPIRED_OFFSET_DAYS)
    if "expiring_soon_id" in edge_flags:
        return today + timedelta(days=ID_EXPIRING_SOON_DAYS)
    return today + timedelta(days=ID_VALID_DAYS)


def _parse_dob(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%m/%d/%Y").date()
    except (ValueError, TypeError):
        return None


def _synth_history(member_id: str, npi: str | None) -> list[ClaimHistory]:
    """Deterministic benign prior claims (frequency baseline for Fraud)."""
    rng = random.Random(member_id)
    rows: list[ClaimHistory] = []
    for _ in range(rng.randint(_HISTORY_MIN_CLAIMS, _HISTORY_MAX_CLAIMS)):
        d = date(2024, rng.randint(1, 12), rng.randint(1, 28))
        rows.append(
            ClaimHistory(
                member_id=member_id,
                claim_date=d,
                claim_amount=round(rng.uniform(_HISTORY_AMOUNT_MIN, _HISTORY_AMOUNT_MAX), 2),
                icd_code=rng.choice(_ICD_POOL),
                cpt_code=rng.choice(_CPT_POOL),
                provider_npi=npi,
                status="APPROVED",
            )
        )
    return rows


def _member_from_record(rec: MemberSeed) -> Member:
    return Member(
        member_id=rec.member_id,
        name=rec.name,
        id_display_name=rec.id_display_name or rec.name,
        date_of_birth=_parse_dob(rec.dob),
        gender=rec.gender,
        policy_number=rec.policy_number,
        policy_type=rec.policy_type,
        group_number=rec.group_number,
        address=rec.address,
        city=rec.city,
        state=rec.state,
        id_type=rec.id_type,
        id_expiry_date=_derive_id_expiry(rec.edge_flags),
        provider_npi=rec.provider_npi,
        cluster_id=rec.cluster_id,
    )


def load_members_json() -> list[MemberSeed]:
    path = _DATASET_DIR / "members.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run Phase 0 dataset generators first.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [MemberSeed.model_validate(rec) for rec in raw]


async def seed() -> tuple[int, int]:
    """Seed members + claim_history. No-op if members already exist.

    Skipping when populated keeps this FK-safe (cases reference members) and
    preserves members an admin added via the UI (Phase 9d) rather than wiping
    them on every run.
    """
    records = load_members_json()
    async with SessionFactory() as session:
        existing = int(await session.scalar(select(func.count()).select_from(Member)) or 0)
        if existing:
            n_claims = int(
                await session.scalar(select(func.count()).select_from(ClaimHistory)) or 0
            )
            logger.info("members_present_skip_reseed", extra={"members": existing})
            return existing, n_claims
        # First run (empty): clear (no-op) then insert.
        await session.execute(delete(ClaimHistory))
        await session.execute(delete(Member))
        members = [_member_from_record(r) for r in records]
        session.add_all(members)
        claims: list[ClaimHistory] = []
        for r in records:
            claims.extend(_synth_history(r.member_id, r.provider_npi))
        session.add_all(claims)
        await session.commit()
    logger.info("seeded", extra={"members": len(members), "claims": len(claims)})
    return len(members), len(claims)


async def ensure_admin() -> bool:
    """Idempotently create the bootstrap admin from settings (Phase 9)."""
    from app.services.user_service import UserService

    async with SessionFactory() as session:
        svc = UserService(session)
        if await svc.get_by_username(settings.admin_username) is not None:
            return False
        await svc.create(
            username=settings.admin_username,
            password=settings.admin_password,
            role=Role.ADMIN.value,
        )
        return True


async def _bootstrap() -> tuple[bool, int, int]:
    created = await ensure_admin()  # independent of member reseed
    n_members, n_claims = await seed()
    return created, n_members, n_claims


def main() -> None:
    configure_logging()
    created, n_members, n_claims = asyncio.run(_bootstrap())
    admin_note = "created" if created else "already exists"
    print(
        f"Seeded {n_members} members and {n_claims} claim-history rows. "
        f"Bootstrap admin '{settings.admin_username}' {admin_note}."
    )


if __name__ == "__main__":
    main()
