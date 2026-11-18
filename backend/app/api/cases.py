"""Case list + detail + report endpoints (RBAC-scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_current_user, get_repo, get_report_service
from app.core.errors import ForbiddenError
from app.db.models import User
from app.schemas.api import CaseDetail, CaseList
from app.schemas.enums import Role
from app.services.case_repository import CaseRepository
from app.services.report_service import ReportService

router = APIRouter(prefix="/api", tags=["cases"])


def _is_employer(user: User) -> bool:
    return user.role == Role.EMPLOYER.value


def _assert_can_view(detail: CaseDetail, user: User) -> None:
    """Employers may only see their own cases; reviewer/admin see all."""
    if _is_employer(user) and detail.submitted_by != str(user.id):
        raise ForbiddenError("not your case")


@router.get("/cases", response_model=CaseList)
async def list_cases(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    repo: CaseRepository = Depends(get_repo),
) -> CaseList:
    # Employers are scoped to their own submissions; reviewer/admin see all.
    submitted_by = str(user.id) if _is_employer(user) else None
    return await repo.list_cases(status, page, limit, submitted_by=submitted_by, q=q)


@router.get("/cases/{case_id}", response_model=CaseDetail)
async def get_case(
    case_id: str,
    user: User = Depends(get_current_user),
    repo: CaseRepository = Depends(get_repo),
) -> CaseDetail:
    detail = await repo.get_detail(case_id)  # 404 if missing
    _assert_can_view(detail, user)
    return detail


@router.get(
    "/cases/{case_id}/report",
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_case_report(
    case_id: str,
    user: User = Depends(get_current_user),
    repo: CaseRepository = Depends(get_repo),
    reports: ReportService = Depends(get_report_service),
) -> Response:
    """Download the case's audit PDF (owner employer, or reviewer/admin)."""
    detail = await repo.get_detail(case_id)  # 404 if missing
    _assert_can_view(detail, user)
    pdf = reports.render(detail)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="case-{case_id}.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )
