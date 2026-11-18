"""Admin-only endpoints (Phase 9d) — app users, KYC members, eval metrics.

All routes require the ADMIN role. App users (login accounts) and KYC members
(PT_ patient records) are distinct stores; both are managed here. The eval
route is a live view over the last captured predictions (offline
`python -m eval.run_eval` remains the source of truth).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    get_dispatcher,
    get_eval_registry,
    get_member_service,
    get_user_service,
    require_role,
)
from app.core.errors import ConflictError, NotFoundError
from app.core.security import mask_value
from app.db.models import Member, User
from app.schemas.api import (
    BulkMembersResult,
    ClearCasesResult,
    EvalJobStatus,
    EvalMetrics,
    EvalRunAccepted,
    EvalRunRequest,
    EvalRunStatus,
    MemberCreate,
    MemberList,
    MemberOut,
    UserCreate,
    UserList,
    UserOut,
)
from app.schemas.enums import EvalScope, Role
from app.services.dispatcher import Dispatcher
from app.services.eval_registry import EvalRunRegistry, is_active_state
from app.services.member_service import MemberService
from app.services.user_service import UserService

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_role(Role.ADMIN.value))]
)


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


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _member_out(m: Member, *, mask: bool) -> MemberOut:
    return MemberOut(
        member_id=mask_value("member_id", m.member_id) if mask else m.member_id,
        name=m.name,
        policy_number=m.policy_number,
        policy_type=m.policy_type,
        date_of_birth=_iso(m.date_of_birth),
        id_expiry_date=_iso(m.id_expiry_date),
        city=m.city,
        state=m.state,
    )


# ---- App users -------------------------------------------------------------
@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, users: UserService = Depends(get_user_service)) -> UserOut:
    user = await users.create(
        username=body.username,
        password=body.password,
        role=body.role,
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
    )
    return _user_out(user)


@router.get("/users", response_model=UserList)
async def list_users(users: UserService = Depends(get_user_service)) -> UserList:
    rows = await users.list_users()
    return UserList(users=[_user_out(u) for u in rows], total=len(rows))


# ---- KYC members -----------------------------------------------------------
@router.post("/members", response_model=MemberOut, status_code=201)
async def create_member(
    body: MemberCreate, members: MemberService = Depends(get_member_service)
) -> MemberOut:
    member = await members.create(body.model_dump())
    return _member_out(member, mask=False)


@router.get("/members", response_model=MemberList)
async def list_members(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    members: MemberService = Depends(get_member_service),
) -> MemberList:
    rows, total = await members.list_members(page, limit)
    return MemberList(members=[_member_out(m, mask=True) for m in rows], total=total)


@router.post("/members/bulk", response_model=BulkMembersResult)
async def bulk_members(
    body: list[MemberCreate], members: MemberService = Depends(get_member_service)
) -> BulkMembersResult:
    created, updated, errors = await members.upsert_many([m.model_dump() for m in body])
    return BulkMembersResult(created=created, updated=updated, errors=errors)


# ---- Reset ingested claims -------------------------------------------------
@router.delete("/cases", response_model=ClearCasesResult)
async def clear_all_cases(keep_files: bool = Query(default=False)) -> ClearCasesResult:
    """Reset ingested claims to a fresh state (cases + docs + files + checkpoints).

    Preserves members, users, and policy vectors. Same effect as
    `python -m app.db.clear_cases`. Destructive — ADMIN only (router gate).
    """
    from app.db.clear_cases import clear_cases  # lazy: keeps db-reset off the hot path

    result = await clear_cases(purge_files=not keep_files)
    return ClearCasesResult(**vars(result))


# ---- Live eval metrics -----------------------------------------------------
def _dataset_path(name: str) -> Path:
    # dataset/ sits at repo root, two levels up from backend/app/api/.
    return Path(__file__).resolve().parents[3] / "dataset" / name


eval_router = APIRouter(
    prefix="/api/eval", tags=["eval"], dependencies=[Depends(require_role(Role.ADMIN.value))]
)


@eval_router.get("/metrics", response_model=EvalMetrics)
async def eval_metrics() -> EvalMetrics:
    """Score the last captured predictions against the dataset labels."""
    from eval.predictions import PredictionSet  # lazy: keeps eval off the hot path
    from eval.run_eval import (
        capture_path,
        group_cases,
        report_to_dict,
        restrict_to_captured,
        score,
    )

    predictions_path = capture_path()
    metadata_path = _dataset_path("metadata.json")
    if not predictions_path.exists():
        raise NotFoundError("no eval capture yet — run one from the dashboard")
    predictions = PredictionSet.load(predictions_path)
    all_records = json.loads(metadata_path.read_text())
    # Grade only the cases that were actually captured (a sampled run must not be
    # penalized for the cases it never executed).
    records = restrict_to_captured(predictions, all_records)
    report = score(predictions, records)
    report.notes.append(
        f"scored over {len(predictions.cases)}/{len(group_cases(all_records))} captured case(s)"
    )
    return EvalMetrics(**report_to_dict(report, source=predictions_path.name))


@eval_router.get("/status", response_model=EvalRunStatus)
async def eval_status(
    registry: EvalRunRegistry = Depends(get_eval_registry),
) -> EvalRunStatus:
    """Whether a live run is currently in flight (so a refreshed page can resume
    polling instead of losing track of it)."""
    from app.worker.celery_app import celery_app  # lazy

    active = await registry.get_active()
    if not active:
        return EvalRunStatus(running=False)
    state = str(celery_app.AsyncResult(active["task_id"]).state)
    if not is_active_state(state):
        # The recorded run has resolved; drop it so the button frees up.
        await registry.clear()
        return EvalRunStatus(running=False)
    return EvalRunStatus(
        running=True, task_id=active["task_id"], scope=EvalScope(active["scope"]), state=state
    )


@eval_router.post("/run", response_model=EvalRunAccepted, status_code=202)
async def eval_run(
    body: EvalRunRequest,
    dispatcher: Dispatcher = Depends(get_dispatcher),
    registry: EvalRunRegistry = Depends(get_eval_registry),
) -> EvalRunAccepted:
    """Launch a live eval run in the worker. Rejects a second concurrent run
    (409) so clicks don't stack duplicate passes over the rate-limited dataset."""
    from app.worker.celery_app import celery_app  # lazy

    active = await registry.get_active()
    if active and is_active_state(str(celery_app.AsyncResult(active["task_id"]).state)):
        raise ConflictError(
            f"a {active['scope']} eval run is already in progress — wait for it to finish"
        )

    task_id = dispatcher.dispatch_eval(body.limit, body.scope.value)
    await registry.set_active(task_id, body.scope.value)
    return EvalRunAccepted(task_id=task_id, scope=body.scope)


@eval_router.get("/jobs/{task_id}", response_model=EvalJobStatus)
async def eval_job_status(
    task_id: str, registry: EvalRunRegistry = Depends(get_eval_registry)
) -> EvalJobStatus:
    from app.worker.celery_app import celery_app  # lazy

    res = celery_app.AsyncResult(task_id)
    state = str(res.state)
    if not is_active_state(state):
        # Terminal — release the active-run slot regardless of pass/fail.
        active = await registry.get_active()
        if active and active["task_id"] == task_id:
            await registry.clear()
    if state == "SUCCESS":
        return EvalJobStatus(task_id=task_id, state=state, metrics=EvalMetrics(**res.result))
    if state == "FAILURE":
        return EvalJobStatus(task_id=task_id, state=state, error=str(res.result))
    return EvalJobStatus(task_id=task_id, state=state)
