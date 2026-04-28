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
    os.getenv("DATABASE_URL", "postgresql://ecube_test:ecube_test@localhost:5432/ecube_integration"),
)

engine = create_engine(INTEGRATION_DATABASE_URL, pool_pre_ping=True)
IntegrationSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _get_integration_alembic_revision(bind, existing_tables: set[str]) -> str | None:
    if "alembic_version" not in existing_tables:
        return None

    with bind.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _describe_integration_schema_drift(bind) -> str | None:
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    missing_tables: list[str] = []
    missing_columns: list[tuple[str, list[str]]] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            missing_tables.append(table.name)
            continue

        actual_columns = {column["name"] for column in inspector.get_columns(table.name)}
        expected_columns = {column.name for column in table.columns}
        table_missing_columns = sorted(expected_columns - actual_columns)
        if table_missing_columns:
            missing_columns.append((table.name, table_missing_columns))

    if not missing_tables and not missing_columns:
        return None

    revision = _get_integration_alembic_revision(bind, existing_tables)
    lines = [
        "Integration DB schema is stale. Rebuild the integration DB (drop/create + alembic upgrade head).",
        f"Database URL: {INTEGRATION_DATABASE_URL}",
    ]
    if revision:
        lines.append(f"Current alembic_version: {revision}")
    if revision == "0001":
        lines.append(
            "ECUBE v0.2.0 uses a mutable release-scoped baseline, so a database already stamped at 0001 can still be outdated."
        )
    if missing_tables:
        lines.append("Missing tables: " + ", ".join(sorted(missing_tables)))
    if missing_columns:
        rendered = []
        for table_name, columns in missing_columns:
            rendered.extend(f"{table_name}.{column_name}" for column_name in columns)
        lines.append("Missing columns: " + ", ".join(rendered))

    return "\n".join(lines)


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
    schema_drift_message = _describe_integration_schema_drift(engine)
    if schema_drift_message:
        pytest.exit(schema_drift_message, returncode=4)

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
