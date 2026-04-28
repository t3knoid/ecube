from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func

from app.database import Base
from app.utils.sanitize import normalize_project_id


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    normalized_project_id = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    jobs = relationship("ExportJob", back_populates="project")

    @validates("normalized_project_id")
    def _normalize_project_id(self, _key, value):
        normalized = normalize_project_id(value)
        return normalized if isinstance(normalized, str) else value

    @property
    def project_id(self) -> str:
        return self.normalized_project_id