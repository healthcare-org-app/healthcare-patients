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
| GET       | `/api/patients/search?q=<term>`     | fuzzy search across name/medical_record_number/email/phone |
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
- `demographics-service` — address validation and name filtering on create/update (best-effort)
- `appointments-service`, `ehr-service`, `eligibility-service` — read by `/api/patients/<id>/summary` (best-effort)

## Local dev

```bash
# Deps (the shared lib is pinned to a commit in requirements.txt)
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

## Contract and quality gate

The API contract is `openapi.yaml` (single source of truth) and the Postman collection is `postman/collections/Patients API/`.
CI runs the platform API quality gate (`.github/workflows/quality-gate.yml`, config `quality-gate.yml`). Locally:

```bash
npx github:healthcare-org-app/healthcare-api-quality-gate#v1 run   # report in gate-results/report.md
```

See `CLAUDE.md` for the change loop.

## Tests

```bash
pip install pytest pytest-mock responses
pytest
```
