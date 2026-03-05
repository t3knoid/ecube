from unittest.mock import patch

from app.models.hardware import UsbDrive, DriveState


def test_create_job(client, db):
    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/data/evidence",
            "thread_count": 4,
            "created_by": "investigator",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == "PROJ-001"
    assert data["status"] == "PENDING"


def test_get_job(client, db):
    create_response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/data/evidence",
        },
    )
    job_id = create_response.json()["id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["id"] == job_id


def test_get_job_not_found(client, db):
    response = client.get("/jobs/999")
    assert response.status_code == 404


def test_start_job(client, db):
    create_response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/tmp",
        },
    )
    job_id = create_response.json()["id"]

    with patch("app.services.copy_engine.run_copy_job") as mock_copy:
        mock_copy.return_value = None
        response = client.post(f"/jobs/{job_id}/start", json={"thread_count": 2})
    assert response.status_code == 200


def test_start_already_running_job(client, db):
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


def test_verify_job(client, db):
    create_response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/tmp",
        },
    )
    job_id = create_response.json()["id"]

    with patch("app.services.copy_engine.run_verify_job") as mock_verify:
        mock_verify.return_value = None
        response = client.post(f"/jobs/{job_id}/verify")
    assert response.status_code == 200
    assert response.json()["status"] == "VERIFYING"
