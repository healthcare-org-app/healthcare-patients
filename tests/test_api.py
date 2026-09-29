class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _FakeDemographicsClient:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def post(self, path, json=None):
        self.calls.append((path, json))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def test_create_with_address_gets_geocoded(client, svc):
    svc.clients["demographics-service"] = _FakeDemographicsClient(
        _FakeResponse(200, {"valid": True, "matched_address": "1 Main St, Springfield, IL, 62701",
                             "latitude": 39.8, "longitude": -89.6})
    )
    r = client.post("/api/patients/", json={
        "first_name": "Addr", "last_name": "Test", "dob": "1990-01-01",
        "address": "1 Main St", "city": "Springfield", "state": "IL", "zip": "62701",
    })
    assert r.status_code == 201, r.data
    body = r.get_json()
    assert body["address_validated"] is True
    assert body["latitude"] == 39.8


def test_create_with_unmatched_address_marks_invalid(client, svc):
    svc.clients["demographics-service"] = _FakeDemographicsClient(
        _FakeResponse(200, {"valid": False, "matched_address": None, "latitude": None, "longitude": None})
    )
    r = client.post("/api/patients/", json={
        "first_name": "NoMatch", "last_name": "Test", "dob": "1990-01-01",
        "address": "not a real place",
    })
    assert r.status_code == 201
    assert r.get_json()["address_validated"] is False


def test_create_without_address_skips_geocoding(client, svc):
    demo = _FakeDemographicsClient(_FakeResponse(200, {"valid": True}))
    svc.clients["demographics-service"] = demo
    r = client.post("/api/patients/", json={"first_name": "A", "last_name": "B", "dob": "1990-01-01"})
    assert r.status_code == 201
    assert demo.calls == []


def test_create_demographics_service_down_is_best_effort(client, svc):
    from healthcare_common.http import ServiceUnavailable
    svc.clients["demographics-service"] = _FakeDemographicsClient(ServiceUnavailable("down"))
    r = client.post("/api/patients/", json={
        "first_name": "Resilient", "last_name": "Test", "dob": "1990-01-01",
        "address": "1 Main St",
    })
    assert r.status_code == 201
    assert "address_validated" not in r.get_json()


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
