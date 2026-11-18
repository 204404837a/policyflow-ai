"""Auth endpoints — login + current user (Phase 9).

Accounts are created by an admin (`/api/admin/users`, Phase 9d) or the bootstrap
seed; there is no open self-registration (roles are admin-assigned).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_user_service
from app.core.auth import create_access_token
from app.core.errors import UnauthorizedError
from app.db.models import User
from app.schemas.api import LoginRequest, TokenResponse, UserOut
from app.services.user_service import UserService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        username=u.username,
        role=u.role,
        email=u.email,
        first_name=u.first_name,
        last_name=u.last_name,
        status=u.status,
        created_at=u.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, users: UserService = Depends(get_user_service)
) -> TokenResponse:
    user = await users.authenticate(body.username, body.password)
    if user is None:
        raise UnauthorizedError("invalid username or password")
    token = create_access_token(username=user.username, role=user.role)
    return TokenResponse(access_token=token, username=user.username, role=user.role)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)
