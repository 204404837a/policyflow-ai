"""FastAPI dependency providers (overridden with fakes in tests)."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthError, decode_access_token
from app.core.config import settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.db.models import User
from app.db.session import get_session
from app.ingestion.storage import ObjectStorage
from app.llm.client import LLMClient
from app.services.case_repository import CaseRepository, SqlCaseRepository
from app.services.dispatcher import CeleryDispatcher, Dispatcher
from app.services.eval_registry import EvalRunRegistry
from app.services.member_service import MemberService
from app.services.policy_ingestor import DefaultPolicyIngestor, PolicyIngestor
from app.services.rag_service import RagService
from app.services.report_service import ReportService
from app.services.user_service import UserService

_bearer = HTTPBearer(auto_error=False)


def get_storage() -> ObjectStorage:
    return ObjectStorage()


def get_dispatcher() -> Dispatcher:
    return CeleryDispatcher()


_eval_registry = EvalRunRegistry()  # process-wide (holds one pooled Redis client)


def get_eval_registry() -> EvalRunRegistry:
    return _eval_registry


async def get_repo(session: AsyncSession = Depends(get_session)) -> CaseRepository:
    return SqlCaseRepository(session)


def get_report_service() -> ReportService:
    return ReportService()


def get_policy_ingestor() -> PolicyIngestor:
    from qdrant_client import QdrantClient  # lazy

    qdrant: Any = QdrantClient(url=settings.qdrant_url)
    return DefaultPolicyIngestor(RagService(LLMClient(), qdrant))


def get_rag_service() -> RagService:
    from qdrant_client import QdrantClient  # lazy

    qdrant: Any = QdrantClient(url=settings.qdrant_url)
    return RagService(LLMClient(), qdrant)


# ---- Auth (Phase 9 — RBAC) ------------------------------------------------
async def get_user_service(session: AsyncSession = Depends(get_session)) -> UserService:
    return UserService(session)


async def get_member_service(session: AsyncSession = Depends(get_session)) -> MemberService:
    return MemberService(session)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    users: UserService = Depends(get_user_service),
) -> User:
    if creds is None:
        raise UnauthorizedError("missing bearer token")
    try:
        claims = decode_access_token(creds.credentials)
    except AuthError as exc:
        raise UnauthorizedError("invalid or expired token") from exc
    username = claims.get("sub")
    user = await users.get_by_username(username) if username else None
    if user is None:
        raise UnauthorizedError("user not found")
    return user


def require_role(
    *roles: str,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    """Dependency factory: allow only the given roles (403 otherwise)."""
    allowed = set(roles)

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise ForbiddenError(f"role '{user.role}' not permitted")
        return user

    return _dep
