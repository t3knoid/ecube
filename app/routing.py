"""Shared custom route classes for ECUBE routers."""

import logging

from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request

from app.config import settings

logger = logging.getLogger(__name__)


class LocalOnlyRoute(APIRoute):
    """Custom route class that short-circuits with 404 *before* dependency
    resolution when the role resolver is not ``"local"``.

    This guarantees that non-local deployments never leak 401/403 responses
    for endpoints that should appear non-existent.  The raised
    ``HTTPException`` is caught by the global handler in ``app.main`` so
    callers receive the standard ``ErrorResponse`` payload.
    """

    def get_route_handler(self):  # type: ignore[override]
        original = super().get_route_handler()

        async def _guarded(request: Request):
            if getattr(settings, "role_resolver", "local") != "local":
                logger.warning(
                    "Local-only endpoint called while role_resolver=%s; path=%s",
                    getattr(settings, "role_resolver", None),
                    request.url.path,
                )
                raise HTTPException(status_code=404, detail="Not found")
            return await original(request)

        return _guarded
