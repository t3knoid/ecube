from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import validates
from sqlalchemy.sql import func
from app.database import Base
from app.utils.sanitize import normalize_project_id


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    user = Column(String)
    action = Column(String, nullable=False)
    project_id = Column(String, nullable=True)
    drive_id = Column(
        Integer, ForeignKey("usb_drives.id", ondelete="SET NULL"), nullable=True
    )
    job_id = Column(
        Integer, ForeignKey("export_jobs.id", ondelete="SET NULL"), nullable=True
    )
    details = Column(JSON().with_variant(JSONB(), "postgresql"))
    client_ip = Column(String(45), nullable=True)

    @validates("project_id")
    def _normalize_project_id(self, _key, value):
        normalized = normalize_project_id(value)
        if normalized == "":
            return None
        return normalized
