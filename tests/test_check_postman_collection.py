from pathlib import Path
import sys
import types

from scripts import check_postman_collection


def _build_generated_folder(*requests: dict[str, object]) -> dict[str, object]:
    return {
        "name": check_postman_collection.GENERATED_SYNC_FOLDER_NAME,
        "item": list(requests),
    }


def test_normalize_postman_url_removes_base_url_and_query_string():
    normalized = check_postman_collection.normalize_postman_url(
        "{{base_url}}/jobs/55/files?limit=10#fragment"
    )

    assert normalized == "/jobs/55/files"


def test_find_collection_drift_accepts_matching_path_parameters():
    collection_requests = [
        check_postman_collection.CollectionRequest(
            name="Jobs / Get Job",
            method="GET",
            path="/jobs/55",
        )
    ]
    openapi_operations = [
        check_postman_collection.OpenAPIOperation(
            method="GET",
            path="/jobs/{job_id}",
            pattern=check_postman_collection._path_to_regex("/jobs/{job_id}"),
        )
    ]

    assert check_postman_collection.find_collection_drift(collection_requests, openapi_operations) == []


def test_find_collection_drift_reports_method_mismatch():
    collection_requests = [
        check_postman_collection.CollectionRequest(
            name="Jobs / Update Job",
            method="PATCH",
            path="/jobs/55",
        )
    ]
    openapi_operations = [
        check_postman_collection.OpenAPIOperation(
            method="PUT",
            path="/jobs/{job_id}",
            pattern=check_postman_collection._path_to_regex("/jobs/{job_id}"),
        )
    ]

    errors = check_postman_collection.find_collection_drift(collection_requests, openapi_operations)

    assert errors == [
        "Jobs / Update Job: PATCH /jobs/55 does not match the OpenAPI method set (PUT)"
    ]


def test_find_generated_sync_drift_reports_missing_generated_folder():
    payload = {"item": []}

    errors = check_postman_collection.find_generated_sync_drift(
        payload,
        [
            check_postman_collection.OpenAPIOperation(
                method="GET",
                path="/health/live",
                pattern=check_postman_collection._path_to_regex("/health/live"),
            )
        ],
    )

    assert errors == [
        "Missing generated sync folder 'OpenAPI Route Sync (Generated)'. Run python3 scripts/sync_postman_collection.py."
    ]


def test_find_generated_sync_drift_reports_missing_operation():
    payload = {
        "item": [
            _build_generated_folder(
                {
                    "name": "GET /health/live",
                    "request": {"method": "GET", "url": {"raw": "{{base_url}}/health/live"}},
                }
            )
        ]
    }

    errors = check_postman_collection.find_generated_sync_drift(
        payload,
        [
            check_postman_collection.OpenAPIOperation(
                method="GET",
                path="/health/live",
                pattern=check_postman_collection._path_to_regex("/health/live"),
            ),
            check_postman_collection.OpenAPIOperation(
                method="GET",
                path="/health/ready",
                pattern=check_postman_collection._path_to_regex("/health/ready"),
            ),
        ],
    )

    assert errors == [
        "Generated sync folder is missing 1 OpenAPI operation(s): GET /health/ready"
    ]


def test_main_reports_stale_collection(tmp_path, monkeypatch, capsys):
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(
        """
        {
          "item": [
            {
              "name": "Jobs",
              "item": [
                {
                  "name": "Delete Job",
                  "request": {
                    "method": "DELETE",
                    "url": {"raw": "{{base_url}}/jobs/55"}
                  }
                }
              ]
                        },
                        {
                            "name": "OpenAPI Route Sync (Generated)",
                            "item": [
                                {
                                    "name": "GET /jobs/{job_id}",
                                    "request": {
                                        "method": "GET",
                                        "url": {"raw": "{{base_url}}/jobs/{{job_id}}"}
                                    }
                                }
                            ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_postman_collection,
        "load_openapi_operations",
        lambda: [
            check_postman_collection.OpenAPIOperation(
                method="GET",
                path="/jobs/{job_id}",
                pattern=check_postman_collection._path_to_regex("/jobs/{job_id}"),
            )
        ],
    )

    exit_code = check_postman_collection.main(["--collection", str(collection_path)])

    assert exit_code == 1
    captured = capsys.readouterr().out
    assert f"ERROR: {collection_path} is out of sync with the ECUBE OpenAPI schema." in captured
    assert "Delete Job: DELETE /jobs/55 does not match the OpenAPI method set (GET)" in captured


def test_main_reports_success_when_collection_matches(tmp_path, monkeypatch, capsys):
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(
        """
        {
          "item": [
            {
              "name": "Health",
              "request": {
                "method": "GET",
                "url": {"raw": "{{base_url}}/health/live"}
              }
                        },
                        {
                            "name": "OpenAPI Route Sync (Generated)",
                            "item": [
                                {
                                    "name": "GET /health/live",
                                    "request": {
                                        "method": "GET",
                                        "url": {"raw": "{{base_url}}/health/live"}
                                    }
                                }
                            ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_postman_collection,
        "load_openapi_operations",
        lambda: [
            check_postman_collection.OpenAPIOperation(
                method="GET",
                path="/health/live",
                pattern=check_postman_collection._path_to_regex("/health/live"),
            )
        ],
    )

    exit_code = check_postman_collection.main(["--collection", str(collection_path)])

    assert exit_code == 0
    assert f"Postman collection routes are in sync: {collection_path}" in capsys.readouterr().out


def test_load_openapi_operations_uses_lightweight_openapi_module(monkeypatch):
    fake_module = types.ModuleType("app.openapi")
    fake_module.load_openapi_schema = lambda: {
        "paths": {
            "/health/live": {
                "get": {
                    "operationId": "health_live",
                    "summary": "Health live",
                }
            }
        }
    }

    monkeypatch.setitem(sys.modules, "app.openapi", fake_module)
    monkeypatch.delitem(sys.modules, "app.main", raising=False)

    operations = check_postman_collection.load_openapi_operations()

    assert operations == [
        check_postman_collection.OpenAPIOperation(
            method="GET",
            path="/health/live",
            pattern=check_postman_collection._path_to_regex("/health/live"),
            operation_id="health_live",
            summary="Health live",
        )
    ]