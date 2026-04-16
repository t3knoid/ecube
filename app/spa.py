"""Reusable SPA serving and API prefix-stripping helpers.

Extracted so both ``app/main`` and the test suite exercise the same code
paths.  All functions accept a :class:`~fastapi.FastAPI` instance and
mutate it in place (adding middleware, mounts, or routes).
"""

from __future__ import annotations

import logging
import pathlib

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

logger = logging.getLogger(__name__)


def add_strip_api_prefix_middleware(app: FastAPI) -> None:
    """Register middleware that rewrites ``/api/…`` requests to ``/…``.

    When the SPA is served directly by FastAPI (no reverse-proxy), the
    frontend sends all API requests to ``/api/...``.  This middleware
    strips the ``/api`` prefix so they match the actual router paths.

    The original path is stored in ``request.scope["_original_path"]``
    so downstream handlers (e.g. the SPA fallback) can distinguish a
    stripped API request from a genuine frontend route.
    """

    @app.middleware("http")
    async def strip_api_prefix(request: Request, call_next):
        path = request.scope["path"]
        raw_path = request.scope.get("raw_path")

        if path.startswith("/api/"):
            request.scope["_original_path"] = path
            request.scope["path"] = path[4:]  # "/api/foo" → "/foo"
            if raw_path is not None:
                if raw_path.startswith(b"/api/"):
                    request.scope["raw_path"] = raw_path[4:]
                else:
                    # raw_path doesn't carry the expected prefix — drop it
                    # rather than re-encoding the decoded path, which would
                    # lose the original percent-encoding.
                    request.scope.pop("raw_path", None)
        elif path == "/api":
            request.scope["_original_path"] = path
            request.scope["path"] = "/"
            request.scope["raw_path"] = b"/"
        return await call_next(request)


def mount_spa_frontend(app: FastAPI, frontend_dir: pathlib.Path) -> None:
    """Mount SPA static-file serving and the catch-all fallback route.

    *frontend_dir* must be a directory containing at least ``index.html``.
    Vite hashed assets under ``assets/`` are served via
    :class:`~starlette.staticfiles.StaticFiles`; all other paths fall back
    to ``index.html`` for client-side routing.

    When ``assets/`` is missing, ``/assets/…`` requests return 404 instead
    of silently serving ``index.html``, so broken deployments fail loudly.

    Security:

    * API paths (``/api/…``, ``/api-…``) and paths that were originally
      ``/api/…`` before prefix-stripping are rejected with 404.
    * Path-traversal (``..``) is blocked in two layers: segment inspection
      before ``resolve()`` and an ``is_relative_to()`` check afterward.
    """
    _index_html = frontend_dir / "index.html"

    # Serve Vite hashed assets with StaticFiles for proper content-type
    # headers and safe directory traversal handling.
    _assets_dir = frontend_dir / "assets"
    if _assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_assets_dir)),
            name="frontend-assets",
        )
    else:
        logger.warning(
            "Frontend assets/ directory not found at %s — "
            "/assets requests will return 404",
            _assets_dir,
        )

        @app.get("/assets/{asset_path:path}", include_in_schema=False)
        async def _missing_assets(asset_path: str):
            raise HTTPException(status_code=404, detail="Not Found")

    # Resolve the frontend root once at startup for containment checks.
    _frontend_root_resolved = frontend_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(request: Request, full_path: str):
        # Reject API requests that fell through to the SPA.  Two cases:
        # 1. Direct /api/… or /api-… requests (no prefix stripping).
        # 2. Stripped requests: path was /api/nonexistent, middleware
        #    rewrote it to /nonexistent, no route matched, and it
        #    arrived here.  _original_path records the pre-strip path.
        original_path = request.scope.get("_original_path", "")
        if full_path.startswith(("api/", "api-")) or original_path.startswith("/api"):
            raise HTTPException(status_code=404, detail="Not Found")
        # Guard against path traversal (e.g. ../../etc/passwd).
        # First reject any path containing ".." segments so we never
        # call resolve() on a path that could escape the frontend root
        # via symlink resolution or directory climbing.
        if ".." in pathlib.PurePosixPath(full_path).parts:
            logger.debug("SPA fallback: rejected traversal in /%s", full_path)
            return FileResponse(str(_index_html))
        file_path = (frontend_dir / full_path).resolve()
        # Second layer: even after resolve(), confirm the result is
        # still inside the frontend root.  is_relative_to() is a proper
        # path-hierarchy check that avoids prefix-string false positives
        # (e.g. /opt/ecube/www_malicious).
        if full_path and file_path.is_relative_to(_frontend_root_resolved) and file_path.is_file():
            logger.debug("SPA fallback: serving file %s for /%s", file_path, full_path)
            return FileResponse(str(file_path))
        # Otherwise, serve index.html for SPA client-side routing.
        logger.debug(
            "SPA fallback: serving index.html for /%s (file_path=%s, exists=%s)",
            full_path,
            file_path,
            file_path.is_file() if file_path.is_relative_to(_frontend_root_resolved) else "BLOCKED",
        )
        return FileResponse(str(_index_html))
