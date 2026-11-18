"""Member lookup repository — the source of truth KYC validates against.

Also owns admin-side KYC member CRUD (Phase 9d): the PT_ records can now be
added/updated through the admin API, not only the `members.json` seed.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.db.models import Member


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class MemberService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lookup(
        self,
        member_id: str | None = None,
        policy_number: str | None = None,
        name: str | None = None,
    ) -> Member | None:
        """Resolve a member by the strongest available key (id → policy → name).

        A claim form's visible "member ID" is often the policy number, so each
        identifier is tried as both the primary key and a policy number before
        falling back to an exact name match.
        """
        identifiers = [v for v in (member_id, policy_number) if v]
        # 1. Primary-key (internal member_id) match.
        for ident in identifiers:
            m = await self._session.get(Member, ident)
            if m is not None:
                return m
        # 2. Policy-number match (covers the MED-GLD-… value from claim forms).
        stmt = select(Member)
        for ident in identifiers:
            row = await self._session.scalar(stmt.where(Member.policy_number == ident))
            if row is not None:
                return row
        # 3. Name fallback.
        if name:
            return await self._session.scalar(stmt.where(Member.name == name))
        return None

    # ---- Admin CRUD (Phase 9d) --------------------------------------------
    async def list_members(self, page: int = 1, limit: int = 50) -> tuple[list[Member], int]:
        total = int(await self._session.scalar(select(func.count()).select_from(Member)) or 0)
        rows = await self._session.scalars(
            select(Member).order_by(Member.member_id).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    def _apply(self, member: Member, data: dict) -> None:
        member.name = data["name"]
        member.id_display_name = data.get("id_display_name") or data["name"]
        member.policy_number = data["policy_number"]
        member.policy_type = data["policy_type"]
        member.date_of_birth = _parse_date(data.get("date_of_birth"))
        member.id_expiry_date = _parse_date(data.get("id_expiry_date"))
        for attr in (
            "gender",
            "group_number",
            "address",
            "city",
            "state",
            "id_type",
            "provider_npi",
        ):
            setattr(member, attr, data.get(attr))

    async def create(self, data: dict) -> Member:
        existing = await self._session.get(Member, data["member_id"])
        if existing is not None:
            raise ConflictError(f"member '{data['member_id']}' already exists")
        member = Member(member_id=data["member_id"])
        self._apply(member, data)
        self._session.add(member)
        await self._session.commit()
        await self._session.refresh(member)
        return member

    async def upsert_many(self, rows: list[dict]) -> tuple[int, int, list[str]]:
        """Bulk create-or-update by member_id. Returns (created, updated, errors)."""
        created = updated = 0
        errors: list[str] = []
        required = ("member_id", "name", "policy_number", "policy_type")
        for i, data in enumerate(rows):
            if not isinstance(data, dict):
                errors.append(f"row {i}: not an object")
                continue
            missing = [k for k in required if not data.get(k)]
            if missing:
                errors.append(f"row {i}: missing {', '.join(missing)}")
                continue
            mid = data["member_id"]
            member = await self._session.get(Member, mid)
            if member is None:
                member = Member(member_id=mid)
                self._session.add(member)
                created += 1
            else:
                updated += 1
            self._apply(member, data)
        await self._session.commit()
        return created, updated, errors
