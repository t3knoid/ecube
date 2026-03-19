from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    user = Column(String)
    action = Column(String, nullable=False)
    job_id = Column(
        Integer, ForeignKey("export_jobs.id", ondelete="SET NULL"), nullable=True
    )
    details = Column(JSON().with_variant(JSONB(), "postgresql"))
    client_ip = Column(String(45), nullable=True)
