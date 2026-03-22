"""Test thread_count validation on endpoints."""
from app.models.hardware import DriveState, UsbDrive


def test_thread_count_validation_on_create_job(admin_client, db):
    """Verify POST /jobs validates thread_count constraints."""
    db.add(UsbDrive(
        device_identifier="USB-THREAD-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
    ))
    db.commit()

    # Test thread_count=0 (too low)
    response = admin_client.post(
        '/jobs',
        json={
            'project_id': 'PROJ-001',
            'evidence_number': 'EV-001',
            'source_path': '/data',
            'thread_count': 0
        }
    )
    assert response.status_code == 422, f"Expected 422 for thread_count=0, got {response.status_code}"
    
    # Test thread_count=16 (too high)
    response = admin_client.post(
        '/jobs',
        json={
            'project_id': 'PROJ-001',
            'evidence_number': 'EV-001',
            'source_path': '/data',
            'thread_count': 16
        }
    )
    assert response.status_code == 422, f"Expected 422 for thread_count=16, got {response.status_code}"
    
    # Test thread_count=4 (valid)
    response = admin_client.post(
        '/jobs',
        json={
            'project_id': 'PROJ-001',
            'evidence_number': 'EV-001',
            'source_path': '/data',
            'thread_count': 4
        }
    )
    assert response.status_code == 200
    assert response.json()['thread_count'] == 4


def test_thread_count_validation_on_start_job(admin_client, db):
    """Verify POST /jobs/{id}/start validates thread_count constraints."""
    from app.models.jobs import ExportJob
    
    # Create a job first
    job = ExportJob(
        project_id='PROJ-001',
        evidence_number='EV-TEST',
        source_path='/tmp'
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Test thread_count=0 (too low)
    response = admin_client.post(
        f'/jobs/{job.id}/start',
        json={'thread_count': 0}
    )
    assert response.status_code == 422, f"Expected 422 for thread_count=0, got {response.status_code}"
    
    # Test thread_count=100 (too high)
    response = admin_client.post(
        f'/jobs/{job.id}/start',
        json={'thread_count': 100}
    )
    assert response.status_code == 422, f"Expected 422 for thread_count=100, got {response.status_code}"
    
    # Test thread_count=6 (valid)
    from unittest.mock import patch
    with patch("app.services.copy_engine.run_copy_job"):
        response = admin_client.post(
            f'/jobs/{job.id}/start',
            json={'thread_count': 6}
        )
    assert response.status_code == 200
