import re
from unittest.mock import MagicMock

from app.database import SessionLocal
from app.main import app as fastapi_app
from app.models.jobs import ExportJob, JobStatus
from app.models.users import UserRole
from app.routers.auth import _get_pam
from app.services import metrics_service


def _metrics_text(client) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    return response.text


def test_metrics_endpoint_requires_authenticated_read_only_role(unauthenticated_client, client, auditor_client):
    unauthenticated_response = unauthenticated_client.get("/metrics")
    assert unauthenticated_response.status_code == 401

    processor_response = client.get("/metrics")
    assert processor_response.status_code == 403

    auditor_response = auditor_client.get("/metrics")
    assert auditor_response.status_code == 200


def test_metrics_endpoint_exposes_prometheus_text_and_route_labels(unauthenticated_client, auditor_client):
    metrics_service.reset_for_tests()

    live_response = unauthenticated_client.get("/health/live")
    assert live_response.status_code == 200

    metrics_text = _metrics_text(auditor_client)

    assert "# HELP ecube_http_requests_total" in metrics_text
    assert "# HELP ecube_jobs_running" in metrics_text
    assert "# HELP process_resident_memory_bytes" in metrics_text
    assert re.search(
        r'ecube_http_requests_total\{[^}]*method="GET"[^}]*route="/health/live"[^}]*status_class="2xx"[^}]*\} 1\.0',
        metrics_text,
    )


def test_metrics_endpoint_tracks_auth_attempt_results(unauthenticated_client, auditor_client, db):
    metrics_service.reset_for_tests()
    db.add(UserRole(username="metrics-user", role="processor"))
    db.commit()

    mock_pam = MagicMock()
    mock_pam.authenticate.side_effect = [False, True]
    mock_pam.get_user_groups.return_value = ["evidence-team"]
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam

    try:
        invalid_response = unauthenticated_client.post(
            "/auth/token",
            json={"username": "metrics-user", "password": "wrong"},
        )
        assert invalid_response.status_code == 401

        success_response = unauthenticated_client.post(
            "/auth/token",
            json={"username": "metrics-user", "password": "secret"},
        )
        assert success_response.status_code == 200

        metrics_text = _metrics_text(auditor_client)
        assert 'ecube_auth_attempts_total{result="invalid_credentials"} 1.0' in metrics_text
        assert 'ecube_auth_attempts_total{result="success"} 1.0' in metrics_text
    finally:
        fastapi_app.dependency_overrides.pop(_get_pam, None)


def test_metrics_endpoint_tracks_role_denials(client, auditor_client):
    metrics_service.reset_for_tests()

    response = client.get("/users")
    assert response.status_code == 403

    metrics_text = _metrics_text(auditor_client)
    assert 'ecube_role_denials_total{route="/users"} 1.0' in metrics_text


def test_sample_active_job_throughput_updates_prometheus_gauge(db):
    metrics_service.reset_for_tests()

    job = ExportJob(
        project_id="PROJ-METRICS",
        evidence_number="EV-METRICS",
        source_path="/tmp/source",
        thread_count=1,
        status=JobStatus.RUNNING,
        copied_bytes=100,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    first_outcome = metrics_service.sample_active_job_throughput(
        db_factory=SessionLocal,
        sampled_at_monotonic=10.0,
    )
    assert first_outcome == "ok"

    job.copied_bytes = 200
    db.commit()

    second_outcome = metrics_service.sample_active_job_throughput(
        db_factory=SessionLocal,
        sampled_at_monotonic=20.0,
    )
    assert second_outcome == "ok"

    metrics_payload = metrics_service.render_metrics(db).decode("utf-8")
    assert 'ecube_job_copy_throughput_bytes_per_second{thread_count_bucket="1"} 10.0' in metrics_payload