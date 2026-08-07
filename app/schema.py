"""Table creation and lightweight migration for patients-service."""
from __future__ import annotations

from healthcare_common.db import DBPool


def create_tables(db: DBPool) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id           BIGSERIAL PRIMARY KEY,
            mrn          TEXT UNIQUE,
            identity_sub TEXT UNIQUE,     -- links to identity-service user (nullable)
            data         JSONB NOT NULL,
            status       TEXT NOT NULL DEFAULT 'active',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS patients_status_idx ON patients (status)")
    db.execute("CREATE INDEX IF NOT EXISTS patients_data_gin ON patients USING gin (data jsonb_path_ops)")
