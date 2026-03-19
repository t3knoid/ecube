from sqlalchemy import Boolean, Column, Integer, String, BigInteger, Enum, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class DriveState(str, enum.Enum):
    EMPTY = "EMPTY"
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"


class UsbHub(Base):
    __tablename__ = "usb_hubs"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    system_identifier = Column(String, unique=True, nullable=False)
    location_hint = Column(String)
    vendor_id = Column(String, nullable=True)
    product_id = Column(String, nullable=True)
    ports = relationship("UsbPort", back_populates="hub")


class UsbPort(Base):
    __tablename__ = "usb_ports"
    id = Column(Integer, primary_key=True)
    hub_id = Column(Integer, ForeignKey("usb_hubs.id"), nullable=False)
    port_number = Column(Integer, nullable=False)
    system_path = Column(String, unique=True, nullable=False)
    friendly_label = Column(String)
    enabled = Column(Boolean, nullable=False, default=False, server_default="0")
    vendor_id = Column(String, nullable=True)
    product_id = Column(String, nullable=True)
    speed = Column(String, nullable=True)
    hub = relationship("UsbHub", back_populates="ports")
    drives = relationship("UsbDrive", back_populates="port")


class UsbDrive(Base):
    __tablename__ = "usb_drives"
    id = Column(Integer, primary_key=True)
    port_id = Column(Integer, ForeignKey("usb_ports.id"), nullable=True)
    device_identifier = Column(String, unique=True, nullable=False)
    filesystem_path = Column(String)
    capacity_bytes = Column(BigInteger)
    encryption_status = Column(String)
    filesystem_type = Column(String, nullable=True)
    current_state = Column(
        Enum(DriveState, native_enum=False), default=DriveState.AVAILABLE
    )
    current_project_id = Column(String)
    last_seen_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    port = relationship("UsbPort", back_populates="drives")
    assignments = relationship("DriveAssignment", back_populates="drive")
