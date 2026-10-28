import os
from pathlib import Path

import pytest
from sqlalchemy import event

TEST_DATABASE = Path(__file__).parent / "test.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE}"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"
os.environ["ADMIN_API_KEY"] = "test-admin-key"

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()



@pytest.fixture(scope="session", autouse=True)
def clean_test_database():
    Base.metadata.drop_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    TEST_DATABASE.unlink(missing_ok=True)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
