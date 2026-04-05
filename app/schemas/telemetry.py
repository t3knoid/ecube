"""Pydantic schemas for frontend telemetry ingestion."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.utils.sanitize import SafeStr, StrictSafeStr


class UiNavigationTelemetryEvent(BaseModel):
    """Frontend UI navigation telemetry payload."""

    event_type: Literal[
        "UI_NAVIGATION_CLICK",
        "UI_NAVIGATION_REDIRECT",
        "UI_NAVIGATION_COMPLETED",
    ] = Field(..., description="Telemetry event type")
    action: Optional[SafeStr] = Field(default=None, description="UI action kind (button, link, etc.)")
    label: Optional[SafeStr] = Field(default=None, description="Displayed control label")
    source: Optional[StrictSafeStr] = Field(default=None, description="Current page/path where interaction occurred")
    destination: Optional[StrictSafeStr] = Field(default=None, description="Intended destination page/path")
    route_name: Optional[SafeStr] = Field(default=None, description="Named route when available")
    reason: Optional[SafeStr] = Field(default=None, description="Redirect reason when applicable")
