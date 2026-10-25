"""Independent test fixtures.

Every test starts from a private copy of a deterministic template database.
The project's data/mvp.db and data/source files are never modified.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT = Path(__file__).resolve().parents[2]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.batch import run_batch  # noqa: E402
from app.config import DEMO_DATE  # noqa: E402

ROLES = ("gm", "sd", "bu", "sm")


def _backup_db(source: Path, target: Path) -> None:
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


@dataclass
class Env:
    client: TestClient
    db_path: Path
    source_dir: Path

    def login(self, role: str) -> "Env":
        response = self.client.post("/api/auth/login", json={"user_id": f"u_{role}"})
        assert response.status_code == 200, response.text
        return self

    def logout(self) -> None:
        self.client.post("/api/auth/logout")

    def get(self, path: str, **kwargs):
        return self.client.get(path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.client.post(path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.client.patch(path, **kwargs)

    @contextmanager
    def db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def rows(self, sql: str, params=()):
        with self.db() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()):
        with self.db() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def execute(self, sql: str, params=()) -> None:
        with self.db() as conn:
            conn.execute(sql, params)
            conn.commit()

    def run_batch(self, as_of: str = DEMO_DATE.isoformat()) -> dict:
        return run_batch(
            DEMO_DATE.fromisoformat(as_of),
            trigger_type="manual",
            triggered_by="independent_test",
            db_path=self.db_path,
            source_dir=self.source_dir,
        )


@pytest.fixture(scope="session")
def source_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A private copy of the 10 source CSVs."""
    root = tmp_path_factory.mktemp("independent")
    target = root / "source"
    shutil.copytree(PROJECT / "data" / "source", target)
    return target


@pytest.fixture(scope="session")
def template_db(tmp_path_factory: pytest.TempPathFactory, source_dir: Path) -> Path:
    """One deterministic batch run used as the starting point for every test."""
    root = tmp_path_factory.mktemp("independent_template")
    db_path = root / "template.db"
    result = run_batch(
        DEMO_DATE,
        trigger_type="test_template",
        triggered_by="independent_test",
        db_path=db_path,
        source_dir=source_dir,
    )
    assert result["status"] == "success", result.get("error")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return db_path


@pytest.fixture()
def env(tmp_path: Path, template_db: Path, source_dir: Path) -> Env:
    db_path = tmp_path / "test.db"
    _backup_db(template_db, db_path)
    from app.main import app

    app.state.db_path = db_path
    client = TestClient(app)
    try:
        yield Env(client=client, db_path=db_path, source_dir=source_dir)
    finally:
        client.close()


@pytest.fixture()
def gm(env: Env) -> Env:
    return env.login("gm")


@pytest.fixture()
def bu(env: Env) -> Env:
    return env.login("bu")


@pytest.fixture()
def sm(env: Env) -> Env:
    return env.login("sm")
