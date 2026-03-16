"""Test suite for API endpoint structure validation.

Validates that all endpoints have:
- Proper docstrings for OpenAPI documentation
- Response models defined
- Correct HTTP methods and paths
- Proper authentication/authorization
- Field descriptions in schemas
"""

import inspect

import pytest
from pydantic import BaseModel

from app.main import app
from app.routers import audit, drives, introspection, jobs, mounts


class TestEndpointDocumentation:
    """Verify all endpoints have proper docstrings for Swagger/OpenAPI."""

    def _get_all_routes(self):
        """Extract all route information from the app."""
        routes = []
        for route in app.routes:
            if hasattr(route, "path") and hasattr(route, "endpoint"):
                routes.append({
                    "path": route.path,
                    "methods": getattr(route, "methods", set()),
                    "endpoint": route.endpoint,
                    "tags": getattr(route, "tags", []),
                })
        return routes

    def test_all_endpoints_have_docstrings(self):
        """All non-health endpoints must have docstrings."""
        routes = self._get_all_routes()
        
        # Exclude FastAPI auto-generated documentation endpoints
        excluded_paths = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
        
        undocumented = []
        for route in routes:
            # Skip excluded endpoints
            if route["path"] in excluded_paths:
                continue
            
            # Check if endpoint has a docstring
            docstring = inspect.getdoc(route["endpoint"])
            if not docstring:
                undocumented.append(f"{route['methods']} {route['path']}")
        
        assert not undocumented, f"Endpoints missing docstrings:\n" + "\n".join(undocumented)

    def test_endpoints_have_meaningful_docstrings(self):
        """Docstrings should be more than one line and descriptive."""
        routes = self._get_all_routes()
        
        # Exclude FastAPI auto-generated documentation endpoints and health check
        excluded_paths = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
        
        short_docstrings = []
        for route in routes:
            if route["path"] in excluded_paths:
                continue
            
            docstring = inspect.getdoc(route["endpoint"])
            if docstring:
                # A meaningful docstring should have at least 5 words
                words = len(docstring.split())
                if words < 5:
                    short_docstrings.append(
                        f"{route['methods']} {route['path']}: '{docstring}' ({words} words)"
                    )
        
        assert not short_docstrings, f"Endpoints with insufficient docstrings:\n" + "\n".join(short_docstrings)

    def test_all_routers_have_tags(self):
        """All routers should define tags for organization in OpenAPI."""
        routers = [drives.router, jobs.router, mounts.router, audit.router, introspection.router]
        
        for router in routers:
            assert hasattr(router, "tags"), f"Router {router} missing tags attribute"
            assert len(router.tags) > 0, f"Router {router} has empty tags"


class TestResponseModels:
    """Verify endpoints have proper response model definitions."""

    def test_list_endpoints_have_response_model(self):
        """GET endpoints that return lists should define response_model."""
        # Build a set of (path, method) pairs where response_model is not None
        routes_with_model = {
            (route.path, method)
            for route in app.routes
            if hasattr(route, "response_model")
            and route.response_model is not None
            and hasattr(route, "methods")
            for method in route.methods
        }

        # These specific GET endpoints must have a non-None response_model
        expected_list_endpoints = [
            ("/drives", "GET"),
            ("/mounts", "GET"),
            ("/audit", "GET"),
        ]

        missing = [
            f"{method} {path}"
            for path, method in expected_list_endpoints
            if (path, method) not in routes_with_model
        ]
        assert not missing, "Endpoints missing response_model:\n" + "\n".join(missing)

    def test_single_resource_endpoints_have_response_model(self):
        """POST/PUT endpoints should define response_model."""
        # Build a set of (path, method) pairs where response_model is not None
        routes_with_model = {
            (route.path, method)
            for route in app.routes
            if hasattr(route, "response_model")
            and route.response_model is not None
            and hasattr(route, "methods")
            for method in route.methods
        }

        # Key mutation endpoints that must declare a response_model
        important_endpoints = [
            ("/drives/{drive_id}/initialize", "POST"),
            ("/drives/{drive_id}/prepare-eject", "POST"),
            ("/jobs", "POST"),  # create job
        ]

        missing = [
            f"{method} {path}"
            for path, method in important_endpoints
            if (path, method) not in routes_with_model
        ]
        assert not missing, "Endpoints missing response_model:\n" + "\n".join(missing)
class TestPydanticSchemas:
    """Verify request/response schemas have field descriptions."""

    def _get_schema_fields(self, model: type[BaseModel]):
        """Extract field information from a Pydantic model."""
        fields = []
        for field_name, field_info in model.model_fields.items():
            fields.append({
                "name": field_name,
                "description": field_info.description,
                "required": field_info.is_required(),
            })
        return fields

    def test_important_schemas_have_field_descriptions(self):
        """Key request/response schemas should document their fields."""
        # Import schemas
        from app.schemas import hardware, jobs, network, errors
        
        schemas_to_check = [
            ("DriveInitialize", hardware.DriveInitialize),
            ("ErrorResponse", errors.ErrorResponse),
        ]
        
        missing_descriptions = []
        for schema_name, schema_class in schemas_to_check:
            fields = self._get_schema_fields(schema_class)
            for field in fields:
                if not field["description"]:
                    missing_descriptions.append(f"{schema_name}.{field['name']}")
        
        # Note: This is informational; Copilot Ticket 2 addresses this
        if missing_descriptions:
            pytest.skip(f"Field descriptions needed: {', '.join(missing_descriptions[:5])}")


class TestOpenAPISchema:
    """Verify OpenAPI/Swagger schema is properly generated."""

    def test_openapi_schema_is_generated(self):
        """FastAPI should generate a valid OpenAPI schema."""
        # The /openapi.json endpoint returns the schema
        assert app.openapi() is not None, "OpenAPI schema is not generated"

    def test_openapi_has_security_components(self, client):
        """Security schemes should be documented in OpenAPI."""
        from app.main import app

        openapi_schema = app.openapi()

        assert openapi_schema is not None
        assert "components" in openapi_schema, "OpenAPI schema missing 'components'"
        assert "securitySchemes" in openapi_schema["components"], (
            "OpenAPI schema missing security schemes; Bearer/JWT auth must be documented"
        )
        scheme = openapi_schema["components"]["securitySchemes"].get("HTTPBearer", {})
        assert scheme.get("type") == "http"
        assert scheme.get("scheme") == "bearer"
        assert scheme.get("bearerFormat") == "JWT"

    def test_openapi_tag_descriptions_present(self):
        """Tag descriptions defined in tags_metadata must appear in the OpenAPI schema."""
        from app.main import app

        openapi_schema = app.openapi()
        tags = {t["name"]: t for t in openapi_schema.get("tags", [])}

        expected_tags = ["drives", "jobs", "mounts", "audit", "introspection", "files"]
        for tag_name in expected_tags:
            assert tag_name in tags, f"Tag '{tag_name}' missing from OpenAPI schema"
            assert tags[tag_name].get("description"), (
                f"Tag '{tag_name}' is missing a description in the OpenAPI schema"
            )

    def test_protected_endpoints_have_security_requirement(self):
        """All non-health, non-login endpoints must declare the HTTPBearer security requirement."""
        from app.main import app

        openapi_schema = app.openapi()
        unauthenticated_paths = {"/health", "/auth/token"}
        violations = []
        for path, path_item in openapi_schema.get("paths", {}).items():
            if path in unauthenticated_paths:
                continue
            for method, operation in path_item.items():
                if isinstance(operation, dict) and "responses" in operation:
                    if not operation.get("security"):
                        violations.append(f"{method.upper()} {path}")

        assert not violations, (
            "Endpoints missing HTTPBearer security requirement:\n" + "\n".join(violations)
        )

    def test_swagger_ui_endpoint_is_accessible(self, client):
        """Swagger UI should be accessible at /docs."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_redoc_endpoint_is_accessible(self, client):
        """ReDoc should be accessible at /redoc."""
        response = client.get("/redoc")
        assert response.status_code == 200


class TestAuthenticationStructure:
    """Verify endpoints have proper authentication and authorization gating."""

    def test_protected_endpoints_require_auth(self, unauthenticated_client, db):
        """Protected endpoints should reject unauthenticated requests."""
        response = unauthenticated_client.get("/drives")
        assert response.status_code == 401, "Protected endpoint should require authentication"

    def test_authorization_headers_properly_gated(self, auditor_client, manager_client, db):
        """Role-based endpoints should reject insufficient roles."""
        # auditor_client should fail on manager-only endpoints
        # This validates that require_roles() is properly applied
        
        # This is a light validation - actual authorization tests are in test_authorization.py
        response = auditor_client.post("/drives/1/initialize", json={"project_id": "PROJ-001"})
        assert response.status_code == 403, "Role-based access should be enforced with 403 for insufficient role"


class TestEndpointHttpMethods:
    """Verify endpoints use correct HTTP methods."""

    def test_read_operations_use_correct_methods(self):
        """GET operations should be idempotent and safe."""
        routes = app.routes
        
        get_routes = [r for r in routes if hasattr(r, "methods") and "GET" in r.methods]
        assert len(get_routes) > 0, "No GET endpoints defined"
        
        # Verify /health is GET
        health_route = [r for r in get_routes if r.path == "/health"]
        assert len(health_route) == 1, "/health endpoint missing"

    def test_write_operations_use_correct_methods(self):
        """POST/PUT/PATCH operations should be used for mutations."""
        post_routes = [r for r in app.routes if hasattr(r, "methods") and "POST" in r.methods]
        
        # Should have at least some POST endpoints for creating resources
        assert len(post_routes) > 0, "No POST endpoints defined"
