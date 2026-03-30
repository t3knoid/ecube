import os
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import app.database as _app_database
from app.config import settings
from app.database import Base, get_db
from app.main import app


INTEGRATION_DATABASE_URL = os.getenv(
    "INTEGRATION_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration"),
)

engine = create_engine(INTEGRATION_DATABASE_URL, pool_pre_ping=True)
IntegrationSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True, scope="session")
def _restore_session_local_for_integration():
    """Point app.database.SessionLocal at PostgreSQL for integration tests.

    tests/conftest.py (the root conftest) replaces SessionLocal with a
    SQLite in-memory factory so that unit-test fixtures work in isolation.
    That global patch persists into the integration-test run, causing the
    app lifespan (which calls SessionLocal() directly) to connect to SQLite
    and log spurious OperationalErrors on startup.

    This session-scoped autouse fixture swaps it back to the PostgreSQL
    IntegrationSessionLocal for the duration of the integration test session.
    """
    original = _app_database.SessionLocal
    _app_database.SessionLocal = IntegrationSessionLocal
    yield
    _app_database.SessionLocal = original


def _clear_database(session) -> None:
    """Delete all rows from every application table that currently exists.

    Only operates on tables present in the database to avoid
    ``ProgrammingError`` on a fresh schema where some tables may not
    exist yet (e.g., if this is called before migrations have run).
    """
    inspector = inspect(session.get_bind())
    existing = set(inspector.get_table_names())
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in existing:
            session.execute(table.delete())
    session.commit()


@pytest.fixture(scope="function")
def integration_db():
    session = IntegrationSessionLocal()
    _clear_database(session)
    try:
        yield session
    finally:
        _clear_database(session)
        session.close()


@pytest.fixture(scope="function")
def integration_auth_headers():
    payload = {
        "sub": "integration-user-id",
        "username": "integration-user",
        "groups": ["evidence-team"],
        "roles": ["admin"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def integration_client(integration_db, integration_auth_headers):
    def override_get_db():
        try:
            yield integration_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        client.headers.update(integration_auth_headers)
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def integration_unauthenticated_client(integration_db):
    def override_get_db():
        try:
            yield integration_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
