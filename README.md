# patients-service

System of record for **patient demographics, identifiers, and contact info**
in the healthcare-org platform. Every clinical, billing, and communications
flow starts by resolving a patient here.

- **Port:** 8100
- **Language:** Python 3.11 + Flask
- **Storage:** Postgres (`patients` database), JSONB per-row model
- **Event bus:** Kafka

## HTTP API

| Method    | Path                                | Purpose                                  |
|-----------|-------------------------------------|------------------------------------------|
| GET       | `/api/patients/`                    | list (`?limit`, `?offset`, `?field=val`) |
| POST      | `/api/patients/`                    | create                                   |
| GET       | `/api/patients/<id>`                | read                                     |
| PUT/PATCH | `/api/patients/<id>`                | update                                   |
| DELETE    | `/api/patients/<id>`                | soft-delete (`status=inactive`)          |
| GET       | `/api/patients/search?q=<term>`     | fuzzy search across name/mrn/email/phone |
| GET       | `/api/patients/<id>/summary`        | aggregate linked records (via peers)     |
| GET       | `/health`, `/ready`                 | ops                                      |

All endpoints require `Authorization: Bearer <jwt>` unless `AUTH_DISABLED=1`.
Scopes are checked per-endpoint (`patients.read`, `patients.write`).

## Events

**Publishes**

- `patient.created` on POST
- `patient.updated` on PUT/PATCH/DELETE
- `audit.event` on every mutating action

**Subscribes**

- `identity.user.created` — links an identity-service user to a patient record
  when the user has role `patient` (idempotent).

## Peer HTTP dependencies

Instantiated lazily via `svc.clients[...]`:

- `identity-service` — verify identities on link
- `auth-service` — token verification (via `require_auth` decorator; not a direct client)
- `audit-log-service` — audit read (`/api/patients/<id>/audit-trail`)
- `notifications-service` — welcome message on create

## Local dev

```bash
# One-time: install the shared lib editable
pip install -e ../../libs/py-healthcare-common

# Deps
pip install -r requirements.txt

# Bring up infra
(cd ../../infra && docker compose up -d postgres kafka kafka-init)

# Env
cp .env.example .env

# Migrate + seed
python -m app.seed

# Run
python -m app.main
```

Then:

```bash
curl -H "Authorization: Bearer any" http://localhost:8100/api/patients/
```

## Tests

```bash
pip install pytest pytest-mock responses
pytest
```
