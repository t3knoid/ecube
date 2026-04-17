from sqlalchemy import Column, Integer, String, Enum, DateTime, Index
from sqlalchemy.orm import validates
from sqlalchemy.sql import func
from app.database import Base
from app.utils.sanitize import normalize_project_id
import enum


class MountType(str, enum.Enum):
    NFS = "NFS"
    SMB = "SMB"


class MountStatus(str, enum.Enum):
    MOUNTED = "MOUNTED"
    UNMOUNTED = "UNMOUNTED"
    ERROR = "ERROR"


class NetworkMount(Base):
    __tablename__ = "network_mounts"
    __table_args__ = (
        Index("ix_network_mounts_status_project", "status", "project_id"),
    )

    id = Column(Integer, primary_key=True)
    type = Column(Enum(MountType, native_enum=False), nullable=False)
    remote_path = Column(String, nullable=False)
    project_id = Column(String, nullable=False, default="UNASSIGNED", index=True)
    local_mount_point = Column(String, nullable=False, unique=True)
    status = Column(Enum(MountStatus, native_enum=False), default=MountStatus.UNMOUNTED, index=True)
    last_checked_at = Column(DateTime(timezone=True), server_default=func.now())

    @validates("project_id")
    def _normalize_project_id(self, _key, value):
        normalized = normalize_project_id(value)
        if not isinstance(normalized, str) or normalized == "":
            return "UNASSIGNED"
        return normalized
