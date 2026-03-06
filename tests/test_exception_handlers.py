"""Tests for centralized exception handlers (401 / 403 / 409 / 500)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.exceptions import AuthenticationError, AuthorizationError, ConflictError, ECUBEException
from app.main import app


# ---------------------------------------------------------------------------
# Helpers – transient routes registered only during the test session
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def exception_routes(client):  # noqa: F811 – shadow outer client intentionally
    """Register temporary routes that raise each exception type, then clean up."""
    from fastapi import APIRouter

    router = APIRouter(prefix="/test-exceptions")

    @router.get("/401-custom")
    def raise_401_custom():
        raise AuthenticationError("Token has expired", code="TOKEN_EXPIRED")

    @router.get("/401-http")
    def raise_401_http():
        raise HTTPException(status_code=401, detail="Missing bearer token")

    @router.get("/403-custom")
    def raise_403_custom():
        raise AuthorizationError("Insufficient role", code="INSUFFICIENT_ROLE")

    @router.get("/403-http")
    def raise_403_http():
        raise HTTPException(status_code=403, detail="Forbidden")

    @router.get("/409-custom")
    def raise_409_custom():
        raise ConflictError("Drive already assigned", code="DRIVE_CONFLICT")

    @router.get("/409-http")
    def raise_409_http():
        raise HTTPException(status_code=409, detail="Already in use")

    @router.get("/500-ecube")
    def raise_500_ecube():
        raise ECUBEException("Something went wrong internally")

    @router.get("/500-unhandled")
    def raise_500_unhandled():
        raise RuntimeError("Completely unexpected failure")

    app.include_router(router)
    yield
    # Remove the router after the test so routes don't leak between tests
    app.router.routes = [r for r in app.router.routes if not getattr(r, "path", "").startswith("/test-exceptions")]


# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------

def _assert_error_schema(data: dict, expected_code: str | None = None) -> None:
    """Assert that *data* conforms to the ErrorResponse schema."""
    assert "code" in data, f"Missing 'code' field: {data}"
    assert "message" in data, f"Missing 'message' field: {data}"
    assert "trace_id" in data, f"Missing 'trace_id' field: {data}"
    assert isinstance(data["message"], str) and data["message"], "Empty message"
    if expected_code is not None:
        assert data["code"] == expected_code, f"Expected code {expected_code!r}, got {data['code']!r}"


# ---------------------------------------------------------------------------
# 401 tests
# ---------------------------------------------------------------------------

def test_401_custom_exception_schema(client, exception_routes):
    response = client.get("/test-exceptions/401-custom")
    assert response.status_code == 401
    data = response.json()
    _assert_error_schema(data, expected_code="TOKEN_EXPIRED")
    assert "Token has expired" in data["message"]


def test_401_http_exception_schema(client, exception_routes):
    response = client.get("/test-exceptions/401-http")
    assert response.status_code == 401
    data = response.json()
    _assert_error_schema(data, expected_code="UNAUTHORIZED")
    assert "Missing bearer token" in data["message"]


# ---------------------------------------------------------------------------
# 403 tests
# ---------------------------------------------------------------------------

def test_403_custom_exception_schema(client, exception_routes):
    response = client.get("/test-exceptions/403-custom")
    assert response.status_code == 403
    data = response.json()
    _assert_error_schema(data, expected_code="INSUFFICIENT_ROLE")
    assert "Insufficient role" in data["message"]


def test_403_http_exception_schema(client, exception_routes):
    response = client.get("/test-exceptions/403-http")
    assert response.status_code == 403
    data = response.json()
    _assert_error_schema(data, expected_code="FORBIDDEN")


# ---------------------------------------------------------------------------
# 409 tests
# ---------------------------------------------------------------------------

def test_409_custom_exception_schema(client, exception_routes):
    response = client.get("/test-exceptions/409-custom")
    assert response.status_code == 409
    data = response.json()
    _assert_error_schema(data, expected_code="DRIVE_CONFLICT")
    assert "Drive already assigned" in data["message"]


def test_409_http_exception_schema(client, exception_routes):
    response = client.get("/test-exceptions/409-http")
    assert response.status_code == 409
    data = response.json()
    _assert_error_schema(data, expected_code="CONFLICT")


# ---------------------------------------------------------------------------
# 500 tests
# ---------------------------------------------------------------------------

def test_500_ecube_exception_schema(client, exception_routes):
    response = client.get("/test-exceptions/500-ecube")
    assert response.status_code == 500
    data = response.json()
    _assert_error_schema(data, expected_code="INTERNAL_ERROR")


def test_500_unhandled_exception_sanitized(exception_routes):
    """Unhandled exceptions must not leak internals and must return 500.

    ``raise_server_exceptions=False`` is required so the TestClient returns the
    500 response instead of re-raising the exception into the test process.
    """
    from fastapi.testclient import TestClient as _TestClient

    with _TestClient(app, raise_server_exceptions=False) as safe_client:
        response = safe_client.get("/test-exceptions/500-unhandled")
    assert response.status_code == 500
    data = response.json()
    _assert_error_schema(data, expected_code="INTERNAL_ERROR")
    # Raw Python exception message must NOT be exposed to the caller
    assert "Completely unexpected failure" not in data["message"]
    assert "RuntimeError" not in data["message"]


# ---------------------------------------------------------------------------
# Existing endpoint compatibility – errors still return consistent schema
# ---------------------------------------------------------------------------

def test_existing_404_schema(client):
    """Existing 404 responses are normalized to the standard error schema."""
    response = client.get("/jobs/999999")
    assert response.status_code == 404
    data = response.json()
    _assert_error_schema(data, expected_code="NOT_FOUND")


def test_existing_isolation_violation_schema(manager_client, db):
    """Project isolation violations return 403 with the standard error schema."""
    from app.models.hardware import UsbDrive, DriveState

    drive = UsbDrive(
        device_identifier="USB-EH01",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-A",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-B"})
    assert response.status_code == 403
    data = response.json()
    _assert_error_schema(data, expected_code="FORBIDDEN")


def test_existing_409_job_start_schema(client, db):
    """Job already-running 409 uses the standard error schema."""
    from app.models.jobs import ExportJob, JobStatus

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-001",
        source_path="/data",
        status=JobStatus.RUNNING,
    )
    db.add(job)
    db.commit()

    response = client.post(f"/jobs/{job.id}/start", json={})
    assert response.status_code == 409
    data = response.json()
    _assert_error_schema(data, expected_code="CONFLICT")
