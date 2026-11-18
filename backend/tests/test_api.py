from __future__ import annotations

import uuid
from datetime import datetime

from app.api.deps import (
    get_current_user,
    get_dispatcher,
    get_eval_registry,
    get_policy_ingestor,
    get_repo,
    get_storage,
)
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.db.models import User
from app.main import create_app
from app.schemas.api import (
    AppendResponse,
    CaseCreatedResponse,
    CaseDetail,
    CaseList,
    CaseListItem,
    DocumentSummary,
    OverrideResponse,
)
from fastapi.testclient import TestClient

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_NOW = datetime(2026, 1, 1, 12, 0, 0)
EMPLOYER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ID = "22222222-2222-2222-2222-222222222222"


class FakeRepo:
    def __init__(self) -> None:
        self.cases: dict[str, dict] = {}

    async def create_case(self, case_id, cluster_id, docs, submitted_by=None):  # noqa: ANN001, ANN201
        self.cases[case_id] = {
            "status": "RECEIVED",
            "override": None,
            "decision": None,
            "submitted_by": submitted_by,
        }
        return CaseCreatedResponse(
            case_id=case_id,
            status="RECEIVED",
            documents=[
                DocumentSummary(
                    doc_id=d.doc_id,
                    original_filename=d.original_filename,
                    storage_key=d.storage_key,
                    mime_type=d.mime_type,
                )
                for d in docs
            ],
        )

    async def append_documents(self, case_id, docs):  # noqa: ANN001, ANN201
        c = self.cases.get(case_id)
        if c is None:
            raise NotFoundError("nope")
        if c["override"]:
            raise ConflictError("locked")
        return AppendResponse(case_id=case_id, status="PROCESSING", added=[])

    async def list_cases(self, status, page, limit, submitted_by=None, q=None):  # noqa: ANN001, ANN201
        items = [
            CaseListItem(
                case_id=k,
                status=v["status"],
                member_id="PT_***13",
                submitted_by=v.get("submitted_by"),
                created_at=_NOW,
                updated_at=_NOW,
            )
            for k, v in self.cases.items()
            if (submitted_by is None or v.get("submitted_by") == submitted_by)
            and (status is None or v["status"] == status)
        ]
        return CaseList(cases=items, total=len(items), page=page, limit=limit)

    async def get_detail(self, case_id):  # noqa: ANN001, ANN201
        c = self.cases.get(case_id)
        if c is None:
            raise NotFoundError("nope")
        return CaseDetail(
            case_id=case_id,
            status=c["status"],
            decision=c.get("decision"),
            submitted_by=c.get("submitted_by"),
            created_at=_NOW,
            updated_at=_NOW,
        )

    async def apply_override(self, case_id, decision, reviewer, reason):  # noqa: ANN001, ANN201
        if decision not in ("APPROVE", "REJECT"):
            raise BadRequestError("bad decision")
        c = self.cases.get(case_id)
        if c is None:
            raise NotFoundError("nope")
        if c["status"] not in ("ESCALATED", "AWAITING_HUMAN"):
            raise BadRequestError("not awaiting review")
        c["override"] = decision
        c["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
        return OverrideResponse(
            case_id=case_id,
            original_decision=c.get("decision"),
            override_decision=decision,
            override_by=reviewer,
            override_at=_NOW,
        )


class FakeStorage:
    async def put(self, key, data, content_type):  # noqa: ANN001, ANN201
        return key

    async def get(self, key):  # noqa: ANN001, ANN201
        return b"filedata"


class FakeDispatcher:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.policy_calls: list[tuple[str, str, str]] = []
        self.eval_calls: list[tuple[int | None, str]] = []

    def dispatch(self, case_id: str) -> None:
        self.calls.append(case_id)

    def dispatch_policy(self, storage_key: str, plan: str, filename: str) -> str:
        self.policy_calls.append((storage_key, plan, filename))
        return "task-123"

    def dispatch_eval(self, limit: int | None, scope: str) -> str:
        self.eval_calls.append((limit, scope))
        return "eval-task-1"


class FakeIngestor:
    async def ingest(self, data, plan, filename):  # noqa: ANN001, ANN201
        return 5


class FakeEvalRegistry:
    """In-memory stand-in for the Redis-backed active-run registry."""

    def __init__(self) -> None:
        self.active: dict[str, str] | None = None

    async def set_active(self, task_id: str, scope: str) -> None:
        self.active = {"task_id": task_id, "scope": scope}

    async def get_active(self) -> dict[str, str] | None:
        return self.active

    async def clear(self) -> None:
        self.active = None


def _user(role: str, uid: str) -> User:
    return User(
        id=uuid.UUID(uid),
        username=role.lower(),
        password_hash="x",
        role=role,
        status="ACTIVE",
        created_at=_NOW,
    )


def _client(
    repo: FakeRepo,
    dispatcher: FakeDispatcher | None = None,
    role: str = "EMPLOYER",
    uid: str = EMPLOYER_ID,
    authed: bool = True,
    registry: FakeEvalRegistry | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher or FakeDispatcher()
    app.dependency_overrides[get_policy_ingestor] = lambda: FakeIngestor()
    app.dependency_overrides[get_eval_registry] = lambda: registry or FakeEvalRegistry()
    if authed:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)
    return TestClient(app)


# ---- submit (employer) ------------------------------------------------------
def test_create_case_dispatches() -> None:
    repo, disp = FakeRepo(), FakeDispatcher()
    client = _client(repo, disp, role="EMPLOYER")
    r = client.post(
        "/api/cases",
        files=[("files", ("a.png", PNG, "image/png")), ("files", ("b.png", PNG, "image/png"))],
    )
    assert r.status_code == 202
    assert len(r.json()["documents"]) == 2
    assert len(disp.calls) == 1


def test_create_case_forbidden_for_reviewer() -> None:
    r = _client(FakeRepo(), role="REVIEWER").post(
        "/api/cases", files=[("files", ("a.png", PNG, "image/png"))]
    )
    assert r.status_code == 403


def test_unauthenticated_401() -> None:
    assert _client(FakeRepo(), authed=False).get("/api/cases").status_code == 401


def test_upload_rejects_bad_type() -> None:
    client = _client(FakeRepo(), role="EMPLOYER")
    r = client.post("/api/cases", files=[("files", ("a.txt", b"hello plain text", "text/plain"))])
    assert r.status_code == 400


# ---- list / detail scoping --------------------------------------------------
def test_employer_sees_only_own_cases() -> None:
    repo = FakeRepo()
    repo.cases["mine"] = {
        "status": "APPROVED",
        "override": None,
        "decision": "APPROVE",
        "submitted_by": EMPLOYER_ID,
    }
    repo.cases["theirs"] = {
        "status": "APPROVED",
        "override": None,
        "decision": "APPROVE",
        "submitted_by": OTHER_ID,
    }
    client = _client(repo, role="EMPLOYER", uid=EMPLOYER_ID)
    body = client.get("/api/cases").json()
    assert body["total"] == 1 and body["cases"][0]["case_id"] == "mine"


def test_reviewer_sees_all_cases() -> None:
    repo = FakeRepo()
    repo.cases["mine"] = {
        "status": "APPROVED",
        "override": None,
        "decision": "APPROVE",
        "submitted_by": EMPLOYER_ID,
    }
    repo.cases["theirs"] = {
        "status": "ESCALATED",
        "override": None,
        "decision": "ESCALATE",
        "submitted_by": OTHER_ID,
    }
    assert _client(repo, role="REVIEWER").get("/api/cases").json()["total"] == 2


def test_employer_cannot_view_others_detail() -> None:
    repo = FakeRepo()
    repo.cases["theirs"] = {
        "status": "APPROVED",
        "override": None,
        "decision": "APPROVE",
        "submitted_by": OTHER_ID,
    }
    client = _client(repo, role="EMPLOYER", uid=EMPLOYER_ID)
    assert client.get("/api/cases/theirs").status_code == 403


def test_reviewer_detail_and_404() -> None:
    repo = FakeRepo()
    repo.cases["c1"] = {
        "status": "APPROVED",
        "override": None,
        "decision": "APPROVE",
        "submitted_by": OTHER_ID,
    }
    client = _client(repo, role="REVIEWER")
    assert client.get("/api/cases/c1").json()["status"] == "APPROVED"
    assert client.get("/api/cases/missing").status_code == 404


# ---- override (reviewer) + locked append (employer) -------------------------
def test_override_then_locked_append() -> None:
    repo = FakeRepo()
    repo.cases["esc"] = {
        "status": "ESCALATED",
        "override": None,
        "decision": "ESCALATE",
        "submitted_by": EMPLOYER_ID,
    }
    r = _client(repo, role="REVIEWER").post(
        "/api/cases/esc/override", json={"decision": "APPROVE", "reason": "reviewed"}
    )
    assert r.status_code == 200 and r.json()["override_decision"] == "APPROVE"
    a = _client(repo, role="EMPLOYER", uid=EMPLOYER_ID).post(
        "/api/cases/esc/documents", files=[("files", ("a.png", PNG, "image/png"))]
    )
    assert a.status_code == 409


def test_override_forbidden_for_employer() -> None:
    repo = FakeRepo()
    repo.cases["esc"] = {
        "status": "ESCALATED",
        "override": None,
        "decision": "ESCALATE",
        "submitted_by": EMPLOYER_ID,
    }
    r = _client(repo, role="EMPLOYER").post(
        "/api/cases/esc/override", json={"decision": "APPROVE", "reason": "x"}
    )
    assert r.status_code == 403


def test_override_rejected_when_not_awaiting() -> None:
    repo = FakeRepo()
    repo.cases["appr"] = {
        "status": "APPROVED",
        "override": None,
        "decision": "APPROVE",
        "submitted_by": EMPLOYER_ID,
    }
    r = _client(repo, role="REVIEWER").post(
        "/api/cases/appr/override", json={"decision": "APPROVE", "reason": "x"}
    )
    assert r.status_code == 400


# ---- files (ungated: UUID keys) + policies (admin) --------------------------
def test_file_serving_headers() -> None:
    r = _client(FakeRepo(), authed=False).get("/api/files/raw/c/d.png")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"] == "inline"
    assert r.headers["content-type"] == "image/png"


def test_policy_ingest_enqueues_job() -> None:
    disp = FakeDispatcher()
    ok = _client(FakeRepo(), dispatcher=disp, role="ADMIN").post(
        "/api/policies/ingest",
        data={"plan": "GOLD"},
        files=[("file", ("g.pdf", b"%PDF-1.4", "application/pdf"))],
    )
    assert ok.status_code == 202
    body = ok.json()
    assert body["task_id"] == "task-123" and body["status"] == "PROCESSING"
    assert disp.policy_calls and disp.policy_calls[0][1] == "GOLD"  # (key, plan, filename)


def test_policy_ingest_admin_only() -> None:
    bad = _client(FakeRepo(), role="ADMIN").post(
        "/api/policies/ingest",
        data={"plan": "BRONZE"},
        files=[("file", ("g.pdf", b"%PDF-1.4", "application/pdf"))],
    )
    assert bad.status_code == 400
    forbidden = _client(FakeRepo(), role="EMPLOYER").post(
        "/api/policies/ingest",
        data={"plan": "GOLD"},
        files=[("file", ("g.pdf", b"%PDF-1.4", "application/pdf"))],
    )
    assert forbidden.status_code == 403


def test_list_policies_admin() -> None:
    from app.api.deps import get_rag_service

    class FakeRag:
        async def list_policies(self):  # noqa: ANN202
            return [
                {"plan": "GOLD", "chunk_count": 59, "section_count": 8, "sections": ["Coverage"]}
            ]

    client = _client(FakeRepo(), role="ADMIN")
    client.app.dependency_overrides[get_rag_service] = lambda: FakeRag()
    r = client.get("/api/policies")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["policies"][0]["chunk_count"] == 59


def test_list_policies_forbidden_for_employer() -> None:
    assert _client(FakeRepo(), role="EMPLOYER").get("/api/policies").status_code == 403


def test_eval_run_enqueues() -> None:
    disp = FakeDispatcher()
    reg = FakeEvalRegistry()
    r = _client(FakeRepo(), dispatcher=disp, role="ADMIN", registry=reg).post(
        "/api/eval/run", json={"limit": 5}
    )
    assert r.status_code == 202 and r.json()["task_id"] == "eval-task-1"
    assert r.json()["scope"] == "pipeline"  # default group
    assert disp.eval_calls == [(5, "pipeline")]
    assert reg.active == {"task_id": "eval-task-1", "scope": "pipeline"}


def test_eval_run_retrieval_scope() -> None:
    disp = FakeDispatcher()
    r = _client(FakeRepo(), dispatcher=disp, role="ADMIN").post(
        "/api/eval/run", json={"scope": "retrieval"}
    )
    assert r.status_code == 202 and r.json()["scope"] == "retrieval"
    assert disp.eval_calls == [(None, "retrieval")]


def test_eval_run_rejects_concurrent(monkeypatch) -> None:  # noqa: ANN001
    from app.worker import celery_app as cworker

    monkeypatch.setattr(
        cworker.celery_app, "AsyncResult", lambda _t: type("R", (), {"state": "STARTED"})()
    )
    reg = FakeEvalRegistry()
    reg.active = {"task_id": "eval-task-1", "scope": "pipeline"}
    r = _client(FakeRepo(), role="ADMIN", registry=reg).post("/api/eval/run", json={})
    assert r.status_code == 409  # a run is already in flight


def test_eval_status_running(monkeypatch) -> None:  # noqa: ANN001
    from app.worker import celery_app as cworker

    monkeypatch.setattr(
        cworker.celery_app, "AsyncResult", lambda _t: type("R", (), {"state": "STARTED"})()
    )
    reg = FakeEvalRegistry()
    reg.active = {"task_id": "eval-task-1", "scope": "retrieval"}
    r = _client(FakeRepo(), role="ADMIN", registry=reg).get("/api/eval/status")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is True and body["scope"] == "retrieval"


def test_eval_status_clears_resolved_run(monkeypatch) -> None:  # noqa: ANN001
    from app.worker import celery_app as cworker

    monkeypatch.setattr(
        cworker.celery_app, "AsyncResult", lambda _t: type("R", (), {"state": "SUCCESS"})()
    )
    reg = FakeEvalRegistry()
    reg.active = {"task_id": "eval-task-1", "scope": "pipeline"}
    r = _client(FakeRepo(), role="ADMIN", registry=reg).get("/api/eval/status")
    assert r.json()["running"] is False
    assert reg.active is None  # resolved run releases the slot


def test_eval_run_forbidden_for_reviewer() -> None:
    r = _client(FakeRepo(), role="REVIEWER").post("/api/eval/run", json={})
    assert r.status_code == 403


def test_eval_job_status(monkeypatch) -> None:  # noqa: ANN001
    from app.worker import celery_app as cworker

    class FakeRes:
        state = "SUCCESS"
        result = {
            "classification_accuracy": 0.8,
            "extraction_accuracy": 0.7,
            "retrieval_relevance_at_k": 0.6,
            "retrieval_mrr": 0.5,
            "decision_accuracy": 0.65,
            "kyc": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "fraud": None,
            "weighted_grade": 0.72,
            "decision_gate_passed": True,
            "overall_gate_passed": True,
            "passed": True,
            "notes": [],
            "source": "live-run",
        }

    monkeypatch.setattr(cworker.celery_app, "AsyncResult", lambda _t: FakeRes())
    r = _client(FakeRepo(), role="ADMIN").get("/api/eval/jobs/eval-task-1")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "SUCCESS" and body["metrics"]["decision_accuracy"] == 0.65


def test_policy_job_status(monkeypatch) -> None:  # noqa: ANN001
    from app.worker import celery_app as cworker

    class FakeRes:
        state = "SUCCESS"
        result = 7

    monkeypatch.setattr(cworker.celery_app, "AsyncResult", lambda _tid: FakeRes())
    r = _client(FakeRepo(), role="ADMIN").get("/api/policies/jobs/task-123")
    assert r.status_code == 200
    assert r.json()["state"] == "SUCCESS" and r.json()["chunks_created"] == 7


def test_ws_snapshot() -> None:
    repo = FakeRepo()
    repo.cases["done"] = {
        "status": "APPROVED",
        "override": None,
        "decision": "APPROVE",
        "submitted_by": EMPLOYER_ID,
    }
    client = _client(repo, authed=False)
    with client.websocket_connect("/ws/cases/done") as ws:
        msg = ws.receive_json()
        assert msg["status"] == "APPROVED"
        assert msg["decision"] == "APPROVE"
