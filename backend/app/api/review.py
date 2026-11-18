"""Human review — override an escalated case (finalize + audit + lock)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_repo, require_role
from app.db.models import User
from app.schemas.api import OverrideRequest, OverrideResponse
from app.schemas.enums import Role
from app.services.case_repository import CaseRepository

router = APIRouter(prefix="/api", tags=["review"])


@router.post("/cases/{case_id}/override", response_model=OverrideResponse)
async def override_case(
    case_id: str,
    body: OverrideRequest,
    repo: CaseRepository = Depends(get_repo),
    user: User = Depends(require_role(Role.REVIEWER.value)),
) -> OverrideResponse:
    # Reviewer identity comes from the token, not the request body.
    return await repo.apply_override(
        case_id, body.decision, user.username, body.reason
    )  # 400 if not awaiting review / bad decision, 404 if missing
