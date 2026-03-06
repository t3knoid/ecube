from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class AuditLogSchema(BaseModel):
    id: int
    timestamp: datetime
    user: Optional[str] = None
    action: str
    job_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}
