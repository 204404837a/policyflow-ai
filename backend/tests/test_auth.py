"""Auth core + endpoint tests (Phase 9b) — no live DB (fake UserService)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from app.api.deps import get_user_service, require_role
from app.core.auth import (
    AuthError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.models import User
from app.main import create_app
from fastapi import Depends
from fastapi.testclient import TestClient


# ---- core/auth --------------------------------------------------------------
def test_password_hash_roundtrip() -> None:
    h = hash_password("s3cret-pass")
    assert h != "s3cret-pass"
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip_carries_sub_and_role() -> None:
    token = create_access_token(username="alice", role="ADMIN")
    claims = decode_access_token(token)
    assert claims["sub"] == "alice"
    assert claims["role"] == "ADMIN"


def test_decode_bad_token_raises() -> None:
    with pytest.raises(AuthError):
        decode_access_token("not.a.jwt")


# ---- fakes ------------------------------------------------------------------
def _user(role: str = "ADMIN", username: str = "alice") -> User:
    return User(
        id=uuid.uuid4(),
        username=username,
        password_hash="x",
        role=role,
        status="ACTIVE",
        created_at=datetime(2026, 1, 1),
    )


class FakeUsers:
    def __init__(self, user: User | None) -> None:
        self._u = user

    async def authenticate(self, username, password):  # noqa: ANN001, ANN201
        if self._u and username == self._u.username and password == "rightpass":
            return self._u
        return None

    async def get_by_username(self, username):  # noqa: ANN001, ANN201
        return self._u if self._u and username == self._u.username else None


def _client(user: User | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_user_service] = lambda: FakeUsers(user)
    return TestClient(app)


# ---- login / me -------------------------------------------------------------
def test_login_success_then_me() -> None:
    client = _client(_user())
    r = client.post("/api/auth/login", json={"username": "alice", "password": "rightpass"})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "ADMIN" and body["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == "alice"


def test_login_bad_password_401() -> None:
    assert (
        _client(_user())
        .post("/api/auth/login", json={"username": "alice", "password": "nope"})
        .status_code
        == 401
    )


def test_me_without_token_401() -> None:
    assert _client(_user()).get("/api/auth/me").status_code == 401


# ---- require_role matrix ----------------------------------------------------
def test_require_role_allows_and_forbids() -> None:
    app = create_app()
    app.dependency_overrides[get_user_service] = lambda: FakeUsers(_user("ADMIN"))

    @app.get("/_admin")
    async def _admin(u: User = Depends(require_role("ADMIN"))) -> dict:  # noqa: ANN202, B008
        return {"u": u.username}

    @app.get("/_reviewer")
    async def _reviewer(u: User = Depends(require_role("REVIEWER"))) -> dict:  # noqa: ANN202, B008
        return {"u": u.username}

    client = TestClient(app)
    hdr = {"Authorization": f"Bearer {create_access_token(username='alice', role='ADMIN')}"}
    assert client.get("/_admin", headers=hdr).status_code == 200  # role matches
    assert client.get("/_reviewer", headers=hdr).status_code == 403  # role mismatch
    assert client.get("/_admin").status_code == 401  # no token
