"""HTTP routes for patients-service.

CRUD + search + summary. Every mutating handler publishes a domain event
and an audit event; every read handler publishes an audit event only.
"""
from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, jsonify, request, g
from psycopg.types.json import Json

from healthcare_common.audit import emit_audit
from healthcare_common.auth import require_auth
from healthcare_common.http import ServiceUnavailable, json_or_raise


REQUIRED_FIELDS = ["first_name", "last_name", "dob"]


def build_blueprint(svc) -> Blueprint:
    """Return a blueprint bound to `svc` (see bootstrap.Service).

    We accept `svc` here (rather than importing a global) so tests can build
    the blueprint against a fake service without spinning up Kafka / Postgres.
    """
    bp = Blueprint("patients", __name__, url_prefix="/api/patients")

    db = svc.db
    bus = svc.bus
    clients = svc.clients

    def _actor() -> str:
        return getattr(g, "principal", {}).get("sub", "anonymous")

    def _row_to_json(row: dict) -> dict:
        return {
            "id": row["id"],
            "mrn": row["mrn"],
            "identity_sub": row["identity_sub"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            **(row["data"] or {}),
        }

    # ── list ─────────────────────────────────────────────────────

    @bp.get("/")
    @require_auth(scopes=["patients.read"])
    def list_patients():
        try:
            offset = int(request.args.get("offset", 0))
            limit = min(int(request.args.get("limit", 50)), 500)
        except ValueError:
            return jsonify({"error": "offset and limit must be integers"}), 400

        # Simple field-level filter: ?status=active or ?data.city=Boston
        wheres: list[str] = []
        params: list[Any] = []
        for key, value in request.args.items():
            if key in ("limit", "offset"):
                continue
            if key == "status":
                wheres.append("status = %s"); params.append(value)
            elif key.startswith("data."):
                jkey = key.split(".", 1)[1]
                wheres.append("data->>%s = %s"); params.extend([jkey, value])

        clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        rows = db.query(
            f"SELECT * FROM patients {clause} ORDER BY id LIMIT %s OFFSET %s",
            tuple(params + [limit, offset]),
        )
        total = db.query_one(f"SELECT count(*) AS n FROM patients {clause}", tuple(params))["n"]

        emit_audit(bus, action="patient.list", actor=_actor(), target=None,
                   details={"count": len(rows), "filters": dict(request.args)})
        return jsonify({
            "count": total,
            "items": [_row_to_json(r) for r in rows],
        })

    # ── create ───────────────────────────────────────────────────

    @bp.post("/")
    @require_auth(scopes=["patients.write"])
    def create_patient():
        payload = request.get_json(silent=True) or {}
        missing = [f for f in REQUIRED_FIELDS if f not in payload]
        if missing:
            return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400

        mrn = payload.pop("mrn", None)
        identity_sub = payload.pop("identity_sub", None)
        row = db.query_one(
            "INSERT INTO patients (mrn, identity_sub, data) VALUES (%s, %s, %s) RETURNING *",
            (mrn, identity_sub, Json(payload)),
        )
        record = _row_to_json(row)

        bus.publish("patient.created", key=str(row["id"]), value=record)
        emit_audit(bus, action="patient.create", actor=_actor(),
                   target=f"patient:{row['id']}")

        # Best-effort welcome notification. Don't fail the create if notifications
        # is down — the notification-service will replay via patient.created anyway.
        notif = clients.get("notifications-service")
        if notif:
            try:
                notif.post("/api/notifications/", json={
                    "patient_id": row["id"],
                    "channel": "email",
                    "subject": "Welcome to the hospital portal",
                    "message": f"Hello {record.get('first_name', '')}, your account is ready.",
                })
            except ServiceUnavailable:
                pass

        return jsonify(record), 201

    # ── read ─────────────────────────────────────────────────────

    @bp.get("/<int:patient_id>")
    @require_auth(scopes=["patients.read"])
    def get_patient(patient_id: int):
        row = db.query_one("SELECT * FROM patients WHERE id = %s", (patient_id,))
        if not row:
            return jsonify({"error": f"patient {patient_id} not found"}), 404
        emit_audit(bus, action="patient.read", actor=_actor(),
                   target=f"patient:{patient_id}")
        return jsonify(_row_to_json(row))

    # ── update ───────────────────────────────────────────────────

    @bp.put("/<int:patient_id>")
    @bp.patch("/<int:patient_id>")
    @require_auth(scopes=["patients.write"])
    def update_patient(patient_id: int):
        existing = db.query_one("SELECT * FROM patients WHERE id = %s", (patient_id,))
        if not existing:
            return jsonify({"error": f"patient {patient_id} not found"}), 404

        payload = request.get_json(silent=True) or {}
        payload.pop("id", None)
        new_status = payload.pop("status", existing["status"])
        new_mrn = payload.pop("mrn", existing["mrn"])
        merged = {**(existing["data"] or {}), **payload}

        row = db.query_one(
            """UPDATE patients SET data=%s, status=%s, mrn=%s, updated_at=now()
               WHERE id=%s RETURNING *""",
            (Json(merged), new_status, new_mrn, patient_id),
        )
        record = _row_to_json(row)
        bus.publish("patient.updated", key=str(patient_id), value=record)
        emit_audit(bus, action="patient.update", actor=_actor(),
                   target=f"patient:{patient_id}",
                   details={"fields": list(payload.keys())})
        return jsonify(record)

    # ── soft delete ──────────────────────────────────────────────

    @bp.delete("/<int:patient_id>")
    @require_auth(scopes=["patients.write"])
    def delete_patient(patient_id: int):
        row = db.query_one(
            """UPDATE patients SET status='inactive', updated_at=now()
               WHERE id=%s RETURNING *""",
            (patient_id,),
        )
        if not row:
            return jsonify({"error": f"patient {patient_id} not found"}), 404
        bus.publish("patient.updated", key=str(patient_id), value=_row_to_json(row))
        emit_audit(bus, action="patient.deactivate", actor=_actor(),
                   target=f"patient:{patient_id}")
        return jsonify({"deactivated": patient_id})

    # ── search ───────────────────────────────────────────────────

    @bp.get("/search")
    @require_auth(scopes=["patients.read"])
    def search():
        q = (request.args.get("q") or "").strip()
        if not q:
            return jsonify({"count": 0, "items": []})
        rows = db.query(
            """SELECT * FROM patients
               WHERE mrn ILIKE %s
                  OR data->>'first_name' ILIKE %s
                  OR data->>'last_name'  ILIKE %s
                  OR data->>'email'      ILIKE %s
                  OR data->>'phone'      ILIKE %s
               LIMIT 100""",
            tuple([f"%{q}%"] * 5),
        )
        emit_audit(bus, action="patient.search", actor=_actor(),
                   target=None, details={"q": q, "hits": len(rows)})
        return jsonify({"count": len(rows), "items": [_row_to_json(r) for r in rows]})

    # ── summary (fan-out to peers) ───────────────────────────────

    @bp.get("/<int:patient_id>/summary")
    @require_auth(scopes=["patients.read"])
    def summary(patient_id: int):
        row = db.query_one("SELECT * FROM patients WHERE id = %s", (patient_id,))
        if not row:
            return jsonify({"error": f"patient {patient_id} not found"}), 404

        result: dict[str, Any] = {"patient": _row_to_json(row)}

        # Fan out to peers in parallel would be nicer; sequential is fine for the
        # reference. Each peer is behind a circuit breaker so slow/down peers
        # degrade gracefully.
        peer_paths = {
            "appointments": ("appointments-service", f"/api/appointments/?patient_id={patient_id}"),
            "ehr":          ("ehr-service",          f"/api/ehr/?patient_id={patient_id}"),
            "insurance":    ("eligibility-service",  f"/api/eligibility/?patient_id={patient_id}"),
        }
        for label, (name, path) in peer_paths.items():
            client = clients.get(name)
            if not client:
                result[label] = {"error": "peer not configured"}; continue
            try:
                result[label] = json_or_raise(client.get(path))
            except ServiceUnavailable as e:
                result[label] = {"error": str(e)}

        emit_audit(bus, action="patient.summary", actor=_actor(),
                   target=f"patient:{patient_id}")
        return jsonify(result)

    return bp
