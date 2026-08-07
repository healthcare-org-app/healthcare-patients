def test_create_then_read(client, svc):
    r = client.post("/api/patients/", json={
        "first_name": "Test", "last_name": "User", "dob": "1990-01-01",
        "email": "t@example.com",
    })
    assert r.status_code == 201, r.data
    body = r.get_json()
    pid = body["id"]
    assert body["first_name"] == "Test"

    # patient.created event was published
    topics = [t for t, _, _ in svc.bus.published]
    assert "patient.created" in topics
    # audit event too
    assert "audit.event" in topics

    r2 = client.get(f"/api/patients/{pid}")
    assert r2.status_code == 200
    assert r2.get_json()["email"] == "t@example.com"


def test_create_missing_fields(client):
    r = client.post("/api/patients/", json={"first_name": "Only"})
    assert r.status_code == 400
    assert "missing fields" in r.get_json()["error"]


def test_update_publishes_updated_event(client, svc):
    r = client.post("/api/patients/", json={
        "first_name": "A", "last_name": "B", "dob": "1990-01-01",
    })
    pid = r.get_json()["id"]
    svc.bus.published.clear()

    r = client.patch(f"/api/patients/{pid}", json={"email": "new@example.com"})
    assert r.status_code == 200
    assert r.get_json()["email"] == "new@example.com"

    topics = [t for t, _, _ in svc.bus.published]
    assert "patient.updated" in topics


def test_soft_delete(client, svc):
    r = client.post("/api/patients/", json={"first_name": "A", "last_name": "B", "dob": "1990-01-01"})
    pid = r.get_json()["id"]
    r = client.delete(f"/api/patients/{pid}")
    assert r.status_code == 200

    r = client.get(f"/api/patients/{pid}")
    assert r.get_json()["status"] == "inactive"


def test_search(client):
    client.post("/api/patients/", json={"first_name": "Findme", "last_name": "X", "dob": "1990-01-01"})
    r = client.get("/api/patients/search?q=findme")
    assert r.status_code == 200
    body = r.get_json()
    assert body["count"] == 1
    assert body["items"][0]["first_name"] == "Findme"


def test_search_empty_q(client):
    r = client.get("/api/patients/search?q=")
    assert r.get_json() == {"count": 0, "items": []}
