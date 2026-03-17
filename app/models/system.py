"""System state model.

The ``system_initialization`` table is a single-row table that records
when and by whom the system was first initialized.  A check constraint
(``id = 1``) ensures only one row can ever exist, providing a cross-process
guard against concurrent initialization attempts — even when running
multiple uvicorn workers.
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
