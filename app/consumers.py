"""Kafka consumers registered by patients-service.

We subscribe to `identity.user.created` and, when the new user has role
`patient`, ensure a matching patients row exists (linked by `identity_sub`).
Idempotent: repeat deliveries are a no-op.
"""
from __future__ import annotations

import logging

from psycopg.types.json import Json

from healthcare_common.audit import emit_audit

log = logging.getLogger("patients.consumers")


def register(svc) -> None:
    db = svc.db
    bus = svc.bus

    @bus.on("identity.user.created")
    def _on_identity_user_created(envelope: dict) -> None:
        user = envelope.get("data") or {}
        roles = user.get("roles") or []
        if "patient" not in roles:
            return

        sub = user.get("sub")
        if not sub:
            log.warning("identity.user.created missing sub; envelope=%s", envelope)
            return

        # Idempotency: bail if we already linked this identity.
        existing = db.query_one(
            "SELECT id FROM patients WHERE identity_sub = %s", (sub,)
        )
        if existing:
            log.info("identity %s already linked to patient %s", sub, existing["id"])
            return

        payload = {
            "first_name": user.get("first_name") or user.get("given_name") or "",
            "last_name":  user.get("last_name")  or user.get("family_name") or "",
            "email":      user.get("email"),
            "dob":        user.get("dob"),
            "source":     "identity-service",
        }
        row = db.query_one(
            "INSERT INTO patients (identity_sub, data) VALUES (%s, %s) RETURNING *",
            (sub, Json(payload)),
        )
        log.info("linked identity %s -> patient %s", sub, row["id"])

        bus.publish("patient.created", key=str(row["id"]),
                    value={"id": row["id"], "identity_sub": sub, **payload})
        emit_audit(bus, action="patient.auto_link", actor="system:identity-consumer",
                   target=f"patient:{row['id']}", details={"identity_sub": sub})
