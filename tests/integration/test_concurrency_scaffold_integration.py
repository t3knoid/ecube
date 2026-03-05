from sqlalchemy.orm import sessionmaker

import pytest

from app.exceptions import ConflictError
from app.models.jobs import ExportJob
from app.repositories.job_repository import JobRepository


@pytest.mark.integration
def test_postgres_nowait_row_lock_conflict_scaffold(integration_db):
    """Starter real-concurrency scaffold for PostgreSQL row-lock behavior.

    Opens two independent sessions against the same PostgreSQL database.
    Session A acquires ``FOR UPDATE`` lock on a job row. Session B then
    attempts ``FOR UPDATE NOWAIT`` on the same row and should receive
    ``ConflictError`` via repository translation.
    """
    bind = integration_db.get_bind()
    if bind.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL backend for real NOWAIT lock behavior")

    job = ExportJob(project_id="PROJ-CONC", evidence_number="EV-CONC", source_path="/tmp")
    integration_db.add(job)
    integration_db.commit()

    SessionFactory = sessionmaker(bind=bind, autoflush=False, autocommit=False)
    session_a = SessionFactory()
    session_b = SessionFactory()

    try:
        repo_a = JobRepository(session_a)
        repo_b = JobRepository(session_b)

        locked_job = repo_a.get_for_update(job.id)
        assert locked_job is not None

        with pytest.raises(ConflictError):
            repo_b.get_for_update(job.id)
    finally:
        session_a.rollback()
        session_b.rollback()
        session_a.close()
        session_b.close()
