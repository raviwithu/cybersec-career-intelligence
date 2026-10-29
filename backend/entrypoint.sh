#!/bin/sh
set -eu

if [ "${SKIP_MIGRATIONS:-false}" = "true" ]; then
  exec "$@"
fi

python - "$@" <<'PY'
import os
import subprocess
import sys

from sqlalchemy import inspect, text

from app.database import engine


def migrate() -> None:
    with engine.connect() as connection:
        locked = connection.dialect.name == "postgresql"
        if locked:
            connection.execute(text("SELECT pg_advisory_lock(418927153)"))
        try:
            inspector = inspect(connection)
            if not inspector.has_table("alembic_version"):
                if inspector.has_table("model_selection") and inspector.has_table("model_evaluations") and inspector.has_table("research_submissions"):
                    columns = {column["name"] for column in inspector.get_columns("research_submissions")}
                    state = "complete" if {"model_name", "evaluation_version"} <= columns else "phase5"
                else:
                    state = "fresh"
            else:
                state = "versioned"
            if state == "fresh" or state == "versioned":
                commands = [["alembic", "upgrade", "head"]]
            elif state == "phase5":
                commands = [["alembic", "stamp", "phase5research"], ["alembic", "upgrade", "head"]]
            elif state == "complete":
                commands = [["alembic", "stamp", "phase5models"], ["alembic", "upgrade", "head"]]
            else:
                raise RuntimeError(f"Unknown database schema state: {state}")
            for command in commands:
                subprocess.run(command, check=True)
        finally:
            if locked:
                connection.execute(text("SELECT pg_advisory_unlock(418927153)"))


migrate()
os.execvp(sys.argv[1], sys.argv[1:])
PY
