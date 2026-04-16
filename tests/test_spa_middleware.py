"""Tests for the SPA fallback and strip_api_prefix middleware (app/spa.py)."""

import pathlib

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.spa import add_strip_api_prefix_middleware, mount_spa_frontend


# ---------------------------------------------------------------------------
# E – SPA fallback: unknown routes return ErrorResponse, not raw JSON
# ---------------------------------------------------------------------------

class TestUnknownRouteErrorResponse:
    """Unknown paths must return structured ErrorResponse (code, message, trace_id)."""

    def test_unknown_route_returns_error_response_schema(self, client):
        """GET to a totally unknown path returns NOT_FOUND with ErrorResponse keys."""
        resp = client.get("/this-route-does-not-exist")
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == "NOT_FOUND"
        assert "message" in body
        assert "trace_id" in body

    def test_unknown_route_no_bare_detail_key(self, client):
        """ErrorResponse uses 'message', not Starlette's default 'detail' key."""
        resp = client.get("/this-route-does-not-exist")
        body = resp.json()
        assert "detail" not in body


# ---------------------------------------------------------------------------
# F – strip_api_prefix middleware: path + raw_path rewriting
# ---------------------------------------------------------------------------

def _make_test_app():
    """Build a minimal app with strip_api_prefix to test path rewriting."""
    test_app = FastAPI()

    add_strip_api_prefix_middleware(test_app)

    @test_app.get("/echo")
    async def echo(request: Request):
        rp = request.scope.get("raw_path")
        return {
            "path": request.scope["path"],
            "raw_path": rp.decode() if rp is not None else None,
        }

    @test_app.get("/items/{item_id}")
    async def get_item(request: Request, item_id: str):
        rp = request.scope.get("raw_path")
        return {
            "item_id": item_id,
            "raw_path": rp.decode() if rp is not None else None,
        }

    @test_app.get("/")
    async def root():
        return {"root": True}

    return test_app


class TestStripApiPrefixMiddleware:
    """Verify the strip_api_prefix middleware rewrites paths correctly."""

    @pytest.fixture(autouse=True)
    def _setup_client(self):
        self.app = _make_test_app()
        self.client = TestClient(self.app)

    def test_api_prefix_stripped_from_path(self):
        resp = self.client.get("/api/echo")
        assert resp.status_code == 200
        assert resp.json()["path"] == "/echo"

    def test_api_prefix_stripped_from_raw_path(self):
        resp = self.client.get("/api/echo")
        assert resp.status_code == 200
        assert resp.json()["raw_path"] == "/echo"

    def test_bare_api_rewrites_to_root(self):
        resp = self.client.get("/api")
        assert resp.status_code == 200
        assert resp.json()["root"] is True

    def test_non_api_path_unchanged(self):
        resp = self.client.get("/echo")
        assert resp.status_code == 200
        assert resp.json()["path"] == "/echo"

    def test_percent_encoding_preserved_in_raw_path(self):
        """Percent-encoded chars must survive the /api/ prefix strip."""
        resp = self.client.get("/api/items/hello%20world")
        assert resp.status_code == 200
        body = resp.json()
        assert body["item_id"] == "hello world"
        assert body["raw_path"] is not None
        assert "%20" in body["raw_path"]

    def test_raw_path_popped_when_prefix_mismatch(self):
        """When raw_path doesn't carry /api/ but path does, raw_path is dropped."""

        # Wrap the app with a thin ASGI layer that forces raw_path to a
        # value *without* the /api/ prefix while path still has it.  This
        # triggers the middleware's ``else`` branch (scope.pop("raw_path")).
        inner = self.app

        async def tamper_raw_path(scope, receive, send):
            if scope["type"] == "http" and scope.get("path") == "/api/echo":
                scope["raw_path"] = b"/echo"  # mismatch: no /api/ prefix
            await inner(scope, receive, send)

        client = TestClient(tamper_raw_path)
        resp = client.get("/api/echo")
        assert resp.status_code == 200
        body = resp.json()
        assert body["path"] == "/echo"
        assert body["raw_path"] is None


# ---------------------------------------------------------------------------
# G – SPA frontend serving (SERVE_FRONTEND_PATH mode)
# ---------------------------------------------------------------------------

def _make_spa_app(frontend_dir: pathlib.Path):
    """Build a minimal app with the production SPA fallback from app.spa."""
    spa_app = FastAPI()

    # A dummy API route to confirm API paths still take priority.
    @spa_app.get("/health")
    def health():
        return {"status": "ok"}

    mount_spa_frontend(spa_app, frontend_dir)

    return spa_app


def _make_spa_app_with_strip(frontend_dir: pathlib.Path):
    """Build an app that combines strip_api_prefix + SPA fallback.

    This mirrors the full production behaviour when ``SERVE_FRONTEND_PATH``
    is set: API requests arrive as ``/api/…``, the middleware strips the
    prefix, real routes handle them, and anything left over hits the SPA
    catch-all which must still 404 for API misses.
    """
    app = _make_spa_app(frontend_dir)

    add_strip_api_prefix_middleware(app)

    return app


class TestSpaFrontendServing:
    """Integration tests for the SPA static-file + fallback mode.

    Each test gets a temporary directory tree that mimics a Vite ``dist/``
    build output::

        dist/
          index.html
          favicon.ico
          assets/
            app-abc123.js
            style-def456.css
    """

    @staticmethod
    def _build_dist(tmp_path: pathlib.Path) -> pathlib.Path:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text(
            "<!doctype html><html><body>SPA</body></html>"
        )
        (dist / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
        assets = dist / "assets"
        assets.mkdir()
        (assets / "app-abc123.js").write_text("console.log('app');")
        (assets / "style-def456.css").write_text("body{margin:0}")
        return dist

    # -- index.html fallback for SPA client-side routes --------------------

    def test_root_returns_index_html(self, tmp_path):
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/")
        assert resp.status_code == 200
        assert "SPA" in resp.text

    def test_unknown_client_route_returns_index_html(self, tmp_path):
        """SPA client routes (e.g. /projects/123) should serve index.html."""
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/projects/123/files")
        assert resp.status_code == 200
        assert "SPA" in resp.text

    # -- Static file serving -----------------------------------------------

    def test_favicon_served_directly(self, tmp_path):
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/favicon.ico")
        assert resp.status_code == 200
        assert resp.content == b"\x00\x00\x01\x00"

    def test_assets_js_served(self, tmp_path):
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/assets/app-abc123.js")
        assert resp.status_code == 200
        assert "console.log" in resp.text

    def test_assets_css_served(self, tmp_path):
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/assets/style-def456.css")
        assert resp.status_code == 200
        assert "margin" in resp.text

    def test_missing_asset_returns_404(self, tmp_path):
        """A request for a non-existent file under /assets/ should 404."""
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/assets/does-not-exist.js")
        assert resp.status_code == 404

    # -- API paths must not fall through to the SPA ------------------------

    def test_api_prefix_rejected(self, tmp_path):
        """Paths starting with api/ must 404, not silently return index.html."""
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/api/v1/drives")
        assert resp.status_code == 404

    def test_api_dash_prefix_rejected(self, tmp_path):
        """Paths starting with api-* must 404."""
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/api-docs")
        assert resp.status_code == 404

    def test_real_api_route_takes_priority(self, tmp_path):
        """Explicit API routes must still be reachable, not shadowed by the SPA."""
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    # -- Stripped /api/ paths must 404, not serve index.html ---------------

    def test_stripped_api_nonexistent_returns_404(self, tmp_path):
        """GET /api/nonexistent → strip → /nonexistent → no route → SPA → 404.

        Without the _original_path guard this would serve index.html.
        """
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app_with_strip(dist))
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404
        assert "SPA" not in resp.text

    def test_stripped_api_deep_path_returns_404(self, tmp_path):
        """GET /api/v1/some/deep/path must 404 after prefix stripping."""
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app_with_strip(dist))
        resp = client.get("/api/v1/some/deep/path")
        assert resp.status_code == 404

    def test_stripped_api_real_route_still_works(self, tmp_path):
        """GET /api/health → strip → /health → matched route → 200."""
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app_with_strip(dist))
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_non_api_spa_route_still_serves_index(self, tmp_path):
        """Non-API paths must still get index.html even with strip middleware."""
        dist = self._build_dist(tmp_path)
        client = TestClient(_make_spa_app_with_strip(dist))
        resp = client.get("/projects/123/files")
        assert resp.status_code == 200
        assert "SPA" in resp.text

    # -- Path traversal rejection ------------------------------------------

    def test_traversal_dot_dot_returns_index_html(self, tmp_path):
        """../ traversal must NOT escape the dist root.

        httpx normalises ``/../secret.txt`` to ``/secret.txt`` before it
        reaches the ASGI app, so we inject the un-normalised path directly
        into the ASGI scope to exercise the ``is_relative_to()`` guard.
        """
        dist = self._build_dist(tmp_path)
        # Place a sentinel *outside* dist/ that a naive join would reach.
        (tmp_path / "secret.txt").write_text("LEAKED")
        inner = _make_spa_app(dist)

        async def inject_traversal(scope, receive, send):
            if scope["type"] == "http":
                scope["path"] = "/../secret.txt"
                scope["raw_path"] = b"/../secret.txt"
            await inner(scope, receive, send)

        client = TestClient(inject_traversal)
        resp = client.get("/../secret.txt")
        assert resp.status_code == 200
        assert "LEAKED" not in resp.text
        assert "SPA" in resp.text

    def test_encoded_traversal_returns_index_html(self, tmp_path):
        """Percent-encoded traversal (..%2F) must not escape the dist root."""
        dist = self._build_dist(tmp_path)
        (tmp_path / "secret.txt").write_text("LEAKED")
        client = TestClient(_make_spa_app(dist))
        resp = client.get("/..%2Fsecret.txt")
        assert resp.status_code == 200
        assert "LEAKED" not in resp.text

    def test_deep_traversal_returns_index_html(self, tmp_path):
        """Multiple ../ levels must still be contained.

        httpx normalises the deep traversal before it reaches the ASGI app,
        so we inject the raw path directly into the scope.  The path does
        NOT start with ``/assets/`` to avoid hitting the ``StaticFiles``
        mount (which would 404 on its own before reaching the catch-all).
        """
        dist = self._build_dist(tmp_path)
        traversal = "/img/../../../../../../../etc/passwd"
        inner = _make_spa_app(dist)

        async def inject_traversal(scope, receive, send):
            if scope["type"] == "http":
                scope["path"] = traversal
                scope["raw_path"] = traversal.encode()
            await inner(scope, receive, send)

        client = TestClient(inject_traversal)
        resp = client.get(traversal)
        assert resp.status_code == 200
        # Should get index.html, not /etc/passwd content
        assert "SPA" in resp.text
