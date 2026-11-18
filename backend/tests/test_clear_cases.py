"""Reset-to-fresh tests (clear_cases) — fakes, no live DB.

Verifies FK-safe delete order (children before parents), MinIO purge of captured
storage keys, and that the --keep-files / --keep-checkpoints paths skip work.
"""

from __future__ import annotations

import app.db.clear_cases as mod
import pytest
from app.db.clear_cases import clear_cases


class FakeSession:
    def __init__(self, storage_keys: list[str], case_count: int) -> None:
        self._keys = storage_keys
        self._case_count = case_count
        self.deleted_tables: list[str] = []
        self.checkpoint_deletes: list[str] = []
        self.committed = False

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def scalars(self, _stmt: object) -> list[str]:
        return list(self._keys)  # Document.storage_key select

    async def scalar(self, stmt: object) -> object:
        return None if "to_regclass" in str(stmt) else self._case_count

    async def execute(self, stmt: object) -> None:
        table = getattr(stmt, "table", None)
        if table is not None:  # a delete(Model)
            self.deleted_tables.append(table.name)
        else:  # raw text() — a checkpoint delete (won't run: to_regclass → None)
            self.checkpoint_deletes.append(str(stmt))

    async def commit(self) -> None:
        self.committed = True


class FakeStorage:
    def __init__(self) -> None:
        self.removed: list[str] = []

    async def remove(self, key: str) -> None:
        self.removed.append(key)


@pytest.fixture
def patched(monkeypatch):  # noqa: ANN001, ANN201
    session = FakeSession(["cases/a/1.png", "cases/a/2.pdf"], case_count=1)
    storage = FakeStorage()
    monkeypatch.setattr(mod, "SessionFactory", lambda: session)
    monkeypatch.setattr(mod, "ObjectStorage", lambda: storage)
    return session, storage


async def test_deletes_children_before_parents(patched) -> None:  # noqa: ANN001
    session, _ = patched
    await clear_cases()
    assert session.deleted_tables == [
        "agent_outputs",
        "llm_calls",
        "audit_events",
        "documents",
        "cases",
    ]
    assert session.committed


async def test_purges_captured_files(patched) -> None:  # noqa: ANN001
    session, storage = patched
    result = await clear_cases()
    assert storage.removed == ["cases/a/1.png", "cases/a/2.pdf"]
    assert result.files_removed == 2 and result.files_failed == 0
    assert result.cases == 1 and result.documents == 2


async def test_keep_files_skips_storage(patched) -> None:  # noqa: ANN001
    _, storage = patched
    result = await clear_cases(purge_files=False)
    assert storage.removed == []
    assert result.files_removed == 0


async def test_absent_checkpoint_tables_are_skipped(patched) -> None:  # noqa: ANN001
    session, _ = patched
    result = await clear_cases()  # to_regclass → None → no DELETEs issued
    assert session.checkpoint_deletes == []
    assert result.checkpoints_cleared is False
