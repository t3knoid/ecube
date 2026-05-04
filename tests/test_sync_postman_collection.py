from scripts import check_postman_collection, sync_postman_collection


def test_sync_collection_payload_replaces_generated_folder_and_preserves_manual_items():
    payload = {
        "variable": [{"key": "base_url", "value": "http://localhost:8000", "type": "string"}],
        "item": [
            {
                "name": "Health",
                "request": {
                    "method": "GET",
                    "url": {"raw": "{{base_url}}/health/live"},
                },
            },
            {
                "name": check_postman_collection.GENERATED_SYNC_FOLDER_NAME,
                "item": [],
            },
        ],
    }
    openapi_operations = [
        check_postman_collection.OpenAPIOperation(
            method="GET",
            path="/health/live",
            pattern=check_postman_collection._path_to_regex("/health/live"),
            operation_id="health_live",
            summary="Health live",
        ),
        check_postman_collection.OpenAPIOperation(
            method="PUT",
            path="/jobs/{job_id}",
            pattern=check_postman_collection._path_to_regex("/jobs/{job_id}"),
            operation_id="update_job",
            summary="Update job",
        ),
    ]

    synced_payload = sync_postman_collection.sync_collection_payload(payload, openapi_operations)

    assert synced_payload["item"][0]["name"] == "Health"
    assert synced_payload["item"][-1]["name"] == check_postman_collection.GENERATED_SYNC_FOLDER_NAME
    generated_requests = synced_payload["item"][-1]["item"]
    assert [request["name"] for request in generated_requests] == [
        "GET /health/live",
        "PUT /jobs/{job_id}",
    ]


def test_sync_collection_payload_adds_missing_path_variables():
    payload = {
        "variable": [{"key": "base_url", "value": "http://localhost:8000", "type": "string"}],
        "item": [],
    }
    openapi_operations = [
        check_postman_collection.OpenAPIOperation(
            method="GET",
            path="/jobs/{job_id}/files/{file_id}",
            pattern=check_postman_collection._path_to_regex("/jobs/{job_id}/files/{file_id}"),
        )
    ]

    synced_payload = sync_postman_collection.sync_collection_payload(payload, openapi_operations)

    variables = {entry["key"]: entry["value"] for entry in synced_payload["variable"]}
    assert variables["job_id"] == "1"
    assert variables["file_id"] == "1"


def test_sync_collection_payload_prunes_stale_manual_requests():
    payload = {
        "variable": [{"key": "base_url", "value": "http://localhost:8000", "type": "string"}],
        "item": [
            {
                "name": "Introspection",
                "item": [
                    {
                        "name": "System Health",
                        "request": {
                            "method": "GET",
                            "url": {"raw": "{{base_url}}/introspection/system-health"},
                        },
                    },
                    {
                        "name": "Job Debug",
                        "request": {
                            "method": "GET",
                            "url": {"raw": "{{base_url}}/introspection/jobs/{{job_id}}/debug"},
                        },
                    },
                ],
            }
        ],
    }
    openapi_operations = [
        check_postman_collection.OpenAPIOperation(
            method="GET",
            path="/introspection/system-health",
            pattern=check_postman_collection._path_to_regex("/introspection/system-health"),
        )
    ]

    synced_payload = sync_postman_collection.sync_collection_payload(payload, openapi_operations)

    introspection_items = synced_payload["item"][0]["item"]
    assert [entry["name"] for entry in introspection_items] == ["System Health"]