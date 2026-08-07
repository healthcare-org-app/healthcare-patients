"""Pytest fixtures that stand up a fake `Service` with in-memory DB + fake bus,
so route tests don't need Postgres or Kafka running."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from flask import Flask

from healthcare_common.tracing import request_id_middleware


# ── Fakes ────────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._rows: list[dict] = []
        self.description: Any = None
        self.rowcount = 0

    def execute(self, sql, params=()):
        self._rows, self.description, self.rowcount = self.store.exec(sql, params)

    def fetchall(self):
        return list(self._rows)

    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeConn:
    def __init__(self, store): self.store = store
    def cursor(self): return FakeCursor(self.store)
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeDB:
    """Minimal in-memory replacement for DBPool used in tests.

    Supports the subset of SQL that patients-service issues: patients table
    with id (autoincrement), mrn, identity_sub, data (JSONB), status, created/updated_at.
    """

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self._next_id = 1000

    # DBPool-compatible surface
    def query(self, sql, params=()): return self.exec(sql, params)[0]
    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None
    def execute(self, sql, params=()): return self.exec(sql, params)[2]

    def exec(self, sql, params):
        s = " ".join(sql.split()).lower()
        if s.startswith("select count(*)"):
            return [{"n": len(self.rows)}], "count", len(self.rows)
        if "insert into patients (mrn, identity_sub, data)" in s:
            mrn, identity_sub, data = params
            rid = self._next_id; self._next_id += 1
            now = datetime.now(timezone.utc)
            row = {"id": rid, "mrn": mrn, "identity_sub": identity_sub,
                   "data": data.obj if hasattr(data, "obj") else data,
                   "status": "active", "created_at": now, "updated_at": now}
            self.rows[rid] = row
            return [row], "row", 1
        if "insert into patients (identity_sub, data)" in s:
            identity_sub, data = params
            rid = self._next_id; self._next_id += 1
            now = datetime.now(timezone.utc)
            row = {"id": rid, "mrn": None, "identity_sub": identity_sub,
                   "data": data.obj if hasattr(data, "obj") else data,
                   "status": "active", "created_at": now, "updated_at": now}
            self.rows[rid] = row
            return [row], "row", 1
        if "insert into patients (mrn, data)" in s:
            mrn, data = params
            rid = self._next_id; self._next_id += 1
            now = datetime.now(timezone.utc)
            self.rows[rid] = {"id": rid, "mrn": mrn, "identity_sub": None,
                              "data": data.obj if hasattr(data, "obj") else data,
                              "status": "active", "created_at": now, "updated_at": now}
            return [], None, 1
        if s.startswith("select * from patients where id"):
            pid = params[0]
            return ([self.rows[pid]] if pid in self.rows else []), "row", 1
        if s.startswith("select id from patients where identity_sub"):
            for r in self.rows.values():
                if r["identity_sub"] == params[0]:
                    return [{"id": r["id"]}], "row", 1
            return [], "row", 0
        if s.startswith("select * from patients") and "order by id" in s:
            limit, offset = params[-2], params[-1]
            items = sorted(self.rows.values(), key=lambda r: r["id"])[offset:offset+limit]
            return items, "row", len(items)
        if s.startswith("update patients set data") and "returning *" in s:
            data, status, mrn, pid = params
            r = self.rows.get(pid)
            if not r: return [], "row", 0
            r["data"] = data.obj if hasattr(data, "obj") else data
            r["status"] = status; r["mrn"] = mrn
            r["updated_at"] = datetime.now(timezone.utc)
            return [r], "row", 1
        if s.startswith("update patients set status='inactive'") and "returning *" in s:
            pid = params[0]
            r = self.rows.get(pid)
            if not r: return [], "row", 0
            r["status"] = "inactive"; r["updated_at"] = datetime.now(timezone.utc)
            return [r], "row", 1
        if "select * from patients" in s and "ilike" in s:
            q = params[0].strip("%").lower()
            hits = []
            for r in self.rows.values():
                d = r["data"] or {}
                haystack = " ".join(str(x or "") for x in [r["mrn"], d.get("first_name"), d.get("last_name"), d.get("email"), d.get("phone")]).lower()
                if q in haystack: hits.append(r)
            return hits, "row", len(hits)
        if s.startswith("create table") or s.startswith("create index"):
            return [], None, 0
        raise NotImplementedError(f"FakeDB: unhandled SQL: {sql}")


@dataclass
class FakeBus:
    published: list[tuple[str, str, dict]] = field(default_factory=list)
    handlers: dict = field(default_factory=dict)

    def publish(self, topic, *, key, value):
        self.published.append((topic, key, value))
    def on(self, topic):
        def _dec(fn): self.handlers[topic] = fn; return fn
        return _dec
    def start(self): pass
    def stop(self, *a): pass


@dataclass
class FakeService:
    app: Flask
    bus: FakeBus
    db: FakeDB
    clients: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    name: str = "patients-service"


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    app = Flask("patients-test")
    request_id_middleware(app)
    return FakeService(app=app, bus=FakeBus(), db=FakeDB())


@pytest.fixture
def client(svc):
    from app.routes import build_blueprint
    from app.consumers import register as register_consumers
    svc.app.register_blueprint(build_blueprint(svc))
    register_consumers(svc)
    with svc.app.test_client() as c:
        yield c
