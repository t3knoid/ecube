from sqlalchemy import Column, Integer, String, Enum, DateTime
from sqlalchemy.sql import func
from app.database import Base
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
    id = Column(Integer, primary_key=True)
    type = Column(Enum(MountType, native_enum=False), nullable=False)
    remote_path = Column(String, nullable=False)
    local_mount_point = Column(String, nullable=False, unique=True)
    status = Column(Enum(MountStatus, native_enum=False), default=MountStatus.UNMOUNTED)
    last_checked_at = Column(DateTime(timezone=True), server_default=func.now())
