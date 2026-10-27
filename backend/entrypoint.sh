#!/bin/sh
set -eu

schema_state=$(python - <<'PY'
from app.config import get_settings
from app.database import engine
from sqlalchemy import inspect

inspector = inspect(engine)
if not inspector.has_table("alembic_version"):
    if inspector.has_table("model_selection") and inspector.has_table("model_evaluations") and inspector.has_table("research_submissions"):
        columns = {column["name"] for column in inspector.get_columns("research_submissions")}
        print("complete" if {"model_name", "evaluation_version"} <= columns else "phase5")
    else:
        print("fresh")
else:
    print("versioned")
PY
)

case "$schema_state" in
  fresh)
    alembic upgrade head
    ;;
  phase5)
    alembic stamp phase5research
    alembic upgrade head
    ;;
  complete)
    alembic stamp phase5models
    alembic upgrade head
    ;;
  versioned)
    alembic upgrade head
    ;;
  *)
    echo "Unknown database schema state: $schema_state" >&2
    exit 1
    ;;
esac

exec "$@"
