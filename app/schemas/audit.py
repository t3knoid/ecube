from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer, model_validator

from app.utils.sanitize import ProjectIdStr, SafeStr


class AuditLogSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the audit log entry")
    timestamp: datetime = Field(..., description="ISO 8601 timestamp when the action occurred")
    user: Optional[str] = Field(default=None, description="Username of the actor who performed the action")
    action: str = Field(..., description="Action code (e.g., FILE_HASHES_RETRIEVED, FILE_COMPARE, DRIVE_INITIALIZED)")
    project_id: Optional[str] = Field(default=None, description="Project identifier associated with the event (if applicable)")
    drive_id: Optional[int] = Field(default=None, description="Drive identifier associated with the event (if applicable)")
    job_id: Optional[int] = Field(default=None, description="ID of the related export job (if applicable)")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Structured metadata about the action (JSON object)")
    client_ip: Optional[str] = Field(default=None, description="IP address of the requesting client (null for background tasks or when redacted; 'unknown' when the client address could not be resolved)")

    model_config = {"from_attributes": True}


class ChainOfCustodyEventSchema(BaseModel):
    event_id: int = Field(..., description="Audit event ID")
    event_type: str = Field(..., description="Audit action code")
    timestamp: datetime = Field(..., description="Event timestamp (ISO 8601)")
    actor: Optional[str] = Field(default=None, description="Actor who performed the event")
    action: str = Field(..., description="Human-readable event label")
    details: Dict[str, Any] = Field(default_factory=dict, description="Structured event metadata")


class ManifestSummarySchema(BaseModel):
    job_id: int = Field(..., description="Related export job ID")
    total_files: int = Field(..., description="Number of files copied during this drive assignment for the job")
    total_bytes: int = Field(..., description="Total bytes copied during this drive assignment for the job")
    manifest_count: int = Field(..., description="Number of generated manifests for the job")
    latest_manifest_path: Optional[str] = Field(default=None, description="Path of most recent manifest")
    latest_manifest_format: Optional[str] = Field(default=None, description="Format of most recent manifest")
    latest_manifest_created_at: Optional[datetime] = Field(default=None, description="Creation time of most recent manifest")


class ChainOfCustodyDriveReportSchema(BaseModel):
    drive_id: int = Field(..., description="Target drive ID")
    drive_sn: str = Field(..., description="Drive serial/device identifier")
    drive_manufacturer: Optional[str] = Field(default=None, description="Drive manufacturer when available")
    drive_model: Optional[str] = Field(default=None, description="Drive model/product name when available")
    project_id: Optional[str] = Field(default=None, description="Bound project ID for the drive")
    custody_complete: bool = Field(..., description="Whether handoff confirmation exists")
    delivery_time: Optional[datetime] = Field(default=None, description="Physical handoff timestamp if confirmed")
    chain_of_custody_events: List[ChainOfCustodyEventSchema] = Field(default_factory=list, description="Chronological custody-related audit events")
    manifest_summary: List[ManifestSummarySchema] = Field(default_factory=list, description="Per-job manifest and size summary")

    @field_serializer("delivery_time")
    def _serialize_delivery_time(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        return dt.isoformat().replace("+00:00", "Z")


class ChainOfCustodyReportSchema(BaseModel):
    selector_mode: str = Field(..., description="Resolved selector mode: DRIVE_ID, DRIVE_SN, or PROJECT")
    project_id: Optional[str] = Field(default=None, description="Project selector when provided")
    reports: List[ChainOfCustodyDriveReportSchema] = Field(default_factory=list, description="Drive-scoped chain-of-custody reports")


class ChainOfCustodyHandoffRequest(BaseModel):
    drive_id: int = Field(..., ge=1, description="Drive identifier")
    project_id: Optional[ProjectIdStr] = Field(default=None, min_length=1, description="Expected project identifier")
    possessor: SafeStr = Field(..., min_length=1, description="Person or entity taking possession")
    delivery_time: datetime = Field(..., description="Physical handoff time in RFC 3339 UTC")
    received_by: Optional[SafeStr] = Field(default=None, min_length=1, description="Receiver identity when different from possessor")
    receipt_ref: Optional[SafeStr] = Field(default=None, min_length=1, description="External receipt/signature reference")
    notes: Optional[SafeStr] = Field(default=None, description="Optional custody notes")

    @model_validator(mode="after")
    def _validate_delivery_time_utc(self):
        if self.delivery_time.tzinfo is None or self.delivery_time.utcoffset() is None:
            raise ValueError("delivery_time must include timezone information")
        if self.delivery_time.utcoffset() != timezone.utc.utcoffset(self.delivery_time):
            raise ValueError("delivery_time must be a UTC timestamp")
        return self


class ChainOfCustodyHandoffResponse(BaseModel):
    event_id: int = Field(..., description="Audit event ID")
    event_type: str = Field(..., description="Event type code")
    drive_id: int = Field(..., description="Drive identifier")
    project_id: Optional[str] = Field(default=None, description="Project identifier")
    creator: Optional[str] = Field(default=None, description="Authenticated user who recorded the event")
    possessor: str = Field(..., description="Person/entity taking possession")
    delivery_time: datetime = Field(..., description="Physical handoff time in UTC")
    received_by: Optional[str] = Field(default=None, description="Receiving party")
    receipt_ref: Optional[str] = Field(default=None, description="Receipt reference")
    notes: Optional[str] = Field(default=None, description="Optional notes")
    recorded_at: datetime = Field(..., description="When this event was recorded")

    @field_serializer("delivery_time", "recorded_at")
    def _serialize_utc_datetime(self, dt: datetime) -> str:
        return dt.isoformat().replace("+00:00", "Z")
