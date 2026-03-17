import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
import app.database as _app_database

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Reassign BEFORE importing app.main so that modules imported transitively
# (e.g. copy_engine, which does ``from app.database import SessionLocal`` at
# module level) bind to the test session factory instead of the production one.
_app_database.SessionLocal = TestingSessionLocal

from app.main import app  # noqa: E402  — must come after SessionLocal override


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run tests marked as integration.",
    )
    parser.addoption(
        "--run-hardware",
        action="store_true",
        default=False,
        help="Run tests marked as hardware (operator-driven HIL tests).",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as requiring integration environment")
    config.addinivalue_line("markers", "hardware: mark test as requiring physical hardware")


def pytest_collection_modifyitems(config, items):
    run_integration = config.getoption("--run-integration")
    run_hardware = config.getoption("--run-hardware")

    skip_integration = pytest.mark.skip(reason="Need --run-integration option to run")
    skip_hardware = pytest.mark.skip(reason="Need --run-hardware option to run")
    for item in items:
        if "integration" in item.keywords and not run_integration:
            item.add_marker(skip_integration)
        if "hardware" in item.keywords and not run_hardware:
            item.add_marker(skip_hardware)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db, auth_headers):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c.headers.update(auth_headers)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def unauthenticated_client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def admin_client(db):
    """Authenticated client with the *admin* role."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    payload = {
        "sub": "admin-user-id",
        "username": "admin-user",
        "groups": ["admins"],
        "roles": ["admin"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def manager_client(db):
    """Authenticated client with the *manager* role."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    payload = {
        "sub": "manager-user-id",
        "username": "manager-user",
        "groups": ["managers"],
        "roles": ["manager"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def auditor_client(db):
    """Authenticated client with the *auditor* role."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    payload = {
        "sub": "auditor-user-id",
        "username": "auditor-user",
        "groups": ["auditors"],
        "roles": ["auditor"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def auth_headers():
    payload = {
        "sub": "test-user-id",
        "username": "test-user",
        "groups": ["evidence-team"],
        "roles": ["processor"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return {"Authorization": f"Bearer {token}"}
