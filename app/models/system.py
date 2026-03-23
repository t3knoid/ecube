"""System state models.

``system_initialization``
    Single-row table that records when and by whom the system was first
    initialized.  A check constraint (``id = 1``) ensures only one row
    can ever exist, providing a cross-process guard against concurrent
    initialization attempts — even when running multiple uvicorn workers.

``reconciliation_lock``
    Single-row table used as a cross-process guard for startup
    reconciliation.  Only one worker may hold the lock at a time; other
    workers skip reconciliation when the lock is already held.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String

from app.database import Base


class SystemInitialization(Base):
    __tablename__ = "system_initialization"

    id = Column(Integer, primary_key=True, autoincrement=False, default=1)
    initialized_by = Column(String, nullable=False)
    initialized_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_single_initialization_row"),
    )


class ReconciliationLock(Base):
    """Cross-process guard for startup reconciliation.

    Exactly one row (``id = 1``) can exist.  A worker acquires the lock
    by inserting the row and releases it by deleting it.  If the row
    already exists, the lock is held by another worker — or is stale
    (checked via ``locked_at``).
    """

    __tablename__ = "reconciliation_lock"

    id = Column(Integer, primary_key=True, autoincrement=False, default=1)
    locked_by = Column(String, nullable=False)
    locked_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_single_reconciliation_lock"),
    )
