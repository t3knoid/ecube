import os
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app


INTEGRATION_DATABASE_URL = os.getenv(
    "INTEGRATION_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration"),
)

engine = create_engine(INTEGRATION_DATABASE_URL, pool_pre_ping=True)
IntegrationSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _clear_database(session) -> None:
    for table in reversed(Base.metadata.sorted_tables):
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
