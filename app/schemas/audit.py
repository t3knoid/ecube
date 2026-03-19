from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AuditLogSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the audit log entry")
    timestamp: datetime = Field(..., description="ISO 8601 timestamp when the action occurred")
    user: Optional[str] = Field(default=None, description="Username of the actor who performed the action")
    action: str = Field(..., description="Action code (e.g., FILE_HASHES_RETRIEVED, FILE_COMPARE, DRIVE_INITIALIZED)")
    job_id: Optional[int] = Field(default=None, description="ID of the related export job (if applicable)")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Structured metadata about the action (JSON object)")
    client_ip: Optional[str] = Field(default=None, description="IP address of the requesting client (null for background tasks or when redacted; 'unknown' when the client address could not be resolved)")

    model_config = {"from_attributes": True}
