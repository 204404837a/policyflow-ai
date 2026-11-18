"""Admin API tests (Phase 9d) — users, KYC members, eval metrics.

Uses fake services injected via dependency_overrides, plus an ADMIN
`get_current_user`, so no live DB/eval infra is touched.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.api.admin import _dataset_path
from app.api.deps import (
    get_current_user,
    get_member_service,
    get_user_service,
)
from app.db.models import Member, User
from app.main import create_app
from fastapi.testclient import TestClient


def _user(role: str = "ADMIN") -> User:
    return User(
        id=uuid.uuid4(),
        username="admin",
        password_hash="x",
        role=role,
        status="ACTIVE",
        created_at=datetime(2026, 1, 1),
    )


def _member(mid: str = "PT_000013") -> Member:
    return Member(
        member_id=mid,
        name="Jane Doe",
        id_display_name="Jane Doe",
        policy_number="MED-GLD-1",
        policy_type="GOLD",
        date_of_birth=date(1990, 1, 1),
        city="Austin",
        state="TX",
    )


class FakeUsers:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.created.append(kwargs)
        return User(
            id=uuid.uuid4(),
            username=kwargs["username"],
            password_hash="x",
            role=kwargs["role"],
            status="ACTIVE",
            created_at=datetime(2026, 1, 1),
        )

    async def list_users(self):  # noqa: ANN201
        return [_user()]


class FakeMembers:
    def __init__(self) -> None:
        self.bulk_rows: list[dict] | None = None

    async def create(self, data):  # noqa: ANN001, ANN201
        return _member(data["member_id"])

    async def list_members(self, page=1, limit=50):  # noqa: ANN001, ANN201
        return [_member()], 1

    async def upsert_many(self, rows):  # noqa: ANN001, ANN201
        self.bulk_rows = rows
        return len(rows), 0, []


def _client(role: str = "ADMIN") -> tuple[TestClient, FakeUsers, FakeMembers]:
    app = create_app()
    users, members = FakeUsers(), FakeMembers()
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    app.dependency_overrides[get_user_service] = lambda: users
    app.dependency_overrides[get_member_service] = lambda: members
    return TestClient(app), users, members


# ---- RBAC gate --------------------------------------------------------------
def test_non_admin_forbidden() -> None:
    client, _, _ = _client(role="EMPLOYER")
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/members").status_code == 403
    assert client.get("/api/eval/metrics").status_code == 403


# ---- users ------------------------------------------------------------------
def test_create_and_list_users() -> None:
    client, users, _ = _client()
    r = client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "secret6", "role": "REVIEWER"},
    )
    assert r.status_code == 201 and r.json()["role"] == "REVIEWER"
    assert users.created[0]["username"] == "bob"
    assert client.get("/api/admin/users").json()["total"] == 1


# ---- reset ingested claims --------------------------------------------------
def test_clear_all_cases(monkeypatch) -> None:  # noqa: ANN001
    import app.db.clear_cases as cc

    async def fake_clear(*, purge_files: bool = True, clear_checkpoints: bool = True):  # noqa: ANN202
        return cc.ClearResult(
            cases=3, documents=5, files_removed=5, files_failed=0, checkpoints_cleared=True
        )

    monkeypatch.setattr(cc, "clear_cases", fake_clear)
    client, _, _ = _client()
    r = client.request("DELETE", "/api/admin/cases")
    assert r.status_code == 200
    body = r.json()
    assert body["cases"] == 3 and body["documents"] == 5 and body["files_removed"] == 5


def test_clear_cases_forbidden_for_non_admin() -> None:
    client, _, _ = _client(role="REVIEWER")
    assert client.request("DELETE", "/api/admin/cases").status_code == 403


# ---- members ----------------------------------------------------------------
def test_create_member_returns_full_id() -> None:
    client, _, _ = _client()
    r = client.post(
        "/api/admin/members",
        json={
            "member_id": "PT_000099",
            "name": "Jane Doe",
            "policy_number": "MED-GLD-1",
            "policy_type": "GOLD",
        },
    )
    assert r.status_code == 201
    assert r.json()["member_id"] == "PT_000099"  # detail view is unmasked


def test_list_members_masks_id() -> None:
    client, _, _ = _client()
    body = client.get("/api/admin/members").json()
    assert body["total"] == 1
    assert body["members"][0]["member_id"] == "PT_***13"  # masked in list


def test_bulk_members_forwards_rows() -> None:
    client, _, members = _client()
    r = client.post(
        "/api/admin/members/bulk",
        json=[
            {
                "member_id": "PT_1",
                "name": "A",
                "policy_number": "P1",
                "policy_type": "GOLD",
            }
        ],
    )
    assert r.status_code == 200 and r.json()["created"] == 1
    assert members.bulk_rows and members.bulk_rows[0]["member_id"] == "PT_1"


# ---- eval metrics -----------------------------------------------------------
def test_eval_metrics_missing_capture_404(monkeypatch) -> None:  # noqa: ANN001
    client, _, _ = _client()
    # Point the dataset lookup at a non-existent capture.
    import app.api.admin as admin_mod

    monkeypatch.setattr(admin_mod, "_dataset_path", lambda name: _dataset_path("__nope__.json"))
    assert client.get("/api/eval/metrics").status_code == 404
