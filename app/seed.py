"""Idempotent seed data.

Run once at container start (or manually) to populate demo patients.
"""
from __future__ import annotations

import logging

from psycopg.types.json import Json

from healthcare_common.db import db_pool
from .schema import create_tables

log = logging.getLogger("patients.seed")

SEED = [
    {"mrn": "MRN-001", "data": {"first_name": "Ava",    "last_name": "Reyes",  "dob": "1988-03-14", "email": "ava.reyes@example.com",   "phone": "+1-555-0110", "blood_type": "O+"}},
    {"mrn": "MRN-002", "data": {"first_name": "Julian", "last_name": "Okafor", "dob": "1975-11-02", "email": "julian.okafor@example.com","phone": "+1-555-0111", "blood_type": "A-"}},
    {"mrn": "MRN-003", "data": {"first_name": "Priya",  "last_name": "Shah",   "dob": "1992-06-21", "email": "priya.shah@example.com",   "phone": "+1-555-0112", "blood_type": "B+"}},
]


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = db_pool()
    create_tables(db)

    if db.query_one("SELECT count(*) AS n FROM patients")["n"] > 0:
        log.info("patients already seeded; skipping")
        return

    for rec in SEED:
        db.execute(
            "INSERT INTO patients (mrn, data) VALUES (%s, %s)",
            (rec["mrn"], Json(rec["data"])),
        )
    log.info("seeded %d patients", len(SEED))


if __name__ == "__main__":
    run()
