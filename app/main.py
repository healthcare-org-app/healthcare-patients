"""patients-service entrypoint.

Assembles the Flask app, database schema, event consumers, and starts the
Kafka background thread — then serves HTTP forever.
"""
from __future__ import annotations

from pathlib import Path

from healthcare_common.bootstrap import create_service

from .schema import create_tables
from .routes import build_blueprint
from .consumers import register as register_consumers
from .seed import run as seed_if_empty


def build():
    svc = create_service("patients-service", service_dir=Path(__file__).resolve().parent.parent)
    create_tables(svc.db)
    seed_if_empty()
    svc.app.register_blueprint(build_blueprint(svc))
    register_consumers(svc)
    return svc


svc = build()
app = svc.app  # for `flask run` / gunicorn / test clients


if __name__ == "__main__":
    svc.run()
