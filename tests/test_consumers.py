from app.consumers import register as register_consumers


def test_identity_user_created_links_patient(svc):
    register_consumers(svc)
    handler = svc.bus.handlers["identity.user.created"]

    handler({
        "id": "e-1", "event_type": "identity.user.created",
        "occurred_at": "2026-08-07T00:00:00Z", "producer": "identity-service",
        "request_id": "abc",
        "data": {
            "sub": "user-abc", "roles": ["patient"],
            "first_name": "New", "last_name": "Person",
            "email": "new@example.com", "dob": "1985-05-05",
        },
    })

    # Now a patients row should exist linked to that sub.
    row = svc.db.query_one("SELECT id FROM patients WHERE identity_sub = %s", ("user-abc",))
    assert row is not None

    # And patient.created was fanned out downstream.
    topics = [t for t, _, _ in svc.bus.published]
    assert "patient.created" in topics


def test_identity_user_created_ignored_for_non_patients(svc):
    register_consumers(svc)
    handler = svc.bus.handlers["identity.user.created"]

    handler({
        "id": "e-2", "event_type": "identity.user.created",
        "occurred_at": "2026-08-07T00:00:00Z", "producer": "identity-service",
        "request_id": "abc",
        "data": {"sub": "doctor-xyz", "roles": ["provider"]},
    })

    row = svc.db.query_one("SELECT id FROM patients WHERE identity_sub = %s", ("doctor-xyz",))
    assert row is None


def test_identity_user_created_is_idempotent(svc):
    register_consumers(svc)
    handler = svc.bus.handlers["identity.user.created"]
    envelope = {
        "data": {"sub": "user-dup", "roles": ["patient"], "first_name": "D", "last_name": "P"},
    }
    handler(envelope)
    handler(envelope)   # second delivery, must not create a duplicate

    matches = svc.db.query("SELECT id FROM patients WHERE identity_sub = %s", ("user-dup",))
    assert len(matches) == 1
