"""User persistence + authentication (Phase 9 — RBAC).

Owns app-user CRUD and credential checks. Passwords are only ever stored as
bcrypt hashes (see core/auth). Distinct from MemberService (KYC patients).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password, verify_password
from app.core.errors import BadRequestError, ConflictError
from app.db.models import User
from app.schemas.enums import Role, UserStatus


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> User | None:
        return await self._session.scalar(select(User).where(User.username == username))

    async def create(
        self,
        *,
        username: str,
        password: str,
        role: str,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        if role not in {r.value for r in Role}:
            raise BadRequestError(f"invalid role: {role}")
        if await self.get_by_username(username) is not None:
            raise ConflictError(f"username '{username}' already exists")
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            email=email,
            first_name=first_name,
            last_name=last_name,
            status=UserStatus.ACTIVE.value,
        )
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def authenticate(self, username: str, password: str) -> User | None:
        user = await self.get_by_username(username)
        if user is None or user.status != UserStatus.ACTIVE.value:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    async def list_users(self) -> list[User]:
        return list(await self._session.scalars(select(User).order_by(User.created_at)))
