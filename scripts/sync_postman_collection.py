#!/usr/bin/env python3
"""Synchronize the generated OpenAPI route section in the ECUBE Postman collection."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_postman_collection import (  # noqa: E402
    CollectionRequest,
    DEFAULT_COLLECTION_PATH,
    GENERATED_SYNC_FOLDER_DESCRIPTION,
    GENERATED_SYNC_FOLDER_NAME,
    OpenAPIOperation,
    get_collection_items,
    normalize_postman_url,
    load_collection_payload,
    load_openapi_operations,
    request_matches_openapi,
)


PATH_PARAMETER_PATTERN = re.compile(r"\{([^{}]+)\}")


def default_variable_value(name: str) -> str:
    if name.endswith("_id"):
        return "1"
    if name.endswith("_name"):
        return f"sample-{name[:-5]}"
    if name == "filename":
        return "ecube.log"
    return f"sample-{name}"


def iter_operation_path_parameters(path: str) -> list[str]:
    return PATH_PARAMETER_PATTERN.findall(path)


def build_postman_url(path: str) -> dict[str, Any]:
    parts: list[str] = []
    raw_parts: list[str] = ["{{base_url}}"]
    for segment in [piece for piece in path.strip("/").split("/") if piece]:
        match = PATH_PARAMETER_PATTERN.fullmatch(segment)
        if match:
            token = f"{{{{{match.group(1)}}}}}"
            parts.append(token)
            raw_parts.append(token)
            continue
        parts.append(segment)
        raw_parts.append(segment)

    return {
        "raw": "/".join(raw_parts),
        "host": ["{{base_url}}"],
        "path": parts,
    }


def build_generated_request(operation: OpenAPIOperation) -> dict[str, Any]:
    description_parts = [
        "Auto-generated from the ECUBE OpenAPI schema.",
    ]
    if operation.summary:
        description_parts.append(f"Summary: {operation.summary}")
    if operation.operation_id:
        description_parts.append(f"operationId: {operation.operation_id}")

    return {
        "name": f"{operation.method} {operation.path}",
        "request": {
            "method": operation.method,
            "header": [],
            "url": build_postman_url(operation.path),
            "description": "\n\n".join(description_parts),
        },
        "response": [],
    }


def build_generated_folder(openapi_operations: Sequence[OpenAPIOperation]) -> dict[str, Any]:
    generated_items = [
        build_generated_request(operation)
        for operation in sorted(openapi_operations, key=lambda operation: (operation.path, operation.method))
    ]
    return {
        "name": GENERATED_SYNC_FOLDER_NAME,
        "description": GENERATED_SYNC_FOLDER_DESCRIPTION,
        "item": generated_items,
    }


def ensure_collection_variables(
    collection_payload: dict[str, Any],
    openapi_operations: Sequence[OpenAPIOperation],
) -> None:
    variables = collection_payload.get("variable")
    if not isinstance(variables, list):
        variables = []
        collection_payload["variable"] = variables

    existing_keys = {
        str(variable.get("key"))
        for variable in variables
        if isinstance(variable, dict) and variable.get("key")
    }
    for name in sorted({param for operation in openapi_operations for param in iter_operation_path_parameters(operation.path)}):
        if name in existing_keys:
            continue
        variables.append(
            {
                "key": name,
                "value": default_variable_value(name),
                "type": "string",
            }
        )


def _prune_stale_items(
    items: Sequence[dict[str, Any]],
    openapi_operations: Sequence[OpenAPIOperation],
) -> list[dict[str, Any]]:
    pruned_items: list[dict[str, Any]] = []
    for item in items:
        if item.get("name") == GENERATED_SYNC_FOLDER_NAME:
            continue

        updated_item = dict(item)
        nested = item.get("item")
        if isinstance(nested, list):
            updated_item["item"] = _prune_stale_items(nested, openapi_operations)

        request = item.get("request")
        if isinstance(request, dict):
            method = str(request.get("method") or "").upper()
            if not method:
                continue
            collection_request = CollectionRequest(
                name=str(item.get("name") or "<unnamed>"),
                method=method,
                path=normalize_postman_url(request.get("url")),
            )
            if not request_matches_openapi(collection_request, openapi_operations):
                continue

        has_nested_items = isinstance(updated_item.get("item"), list) and bool(updated_item["item"])
        has_request = isinstance(updated_item.get("request"), dict)
        if has_nested_items or has_request:
            pruned_items.append(updated_item)
    return pruned_items


def sync_collection_payload(
    collection_payload: dict[str, Any],
    openapi_operations: Sequence[OpenAPIOperation],
) -> dict[str, Any]:
    synced_payload = dict(collection_payload)
    items = _prune_stale_items(get_collection_items(collection_payload), openapi_operations)
    items.append(build_generated_folder(openapi_operations))
    synced_payload["item"] = items
    ensure_collection_variables(synced_payload, openapi_operations)
    return synced_payload


def write_collection_payload(collection_path: Path, collection_payload: dict[str, Any]) -> None:
    collection_path.write_text(
        json.dumps(collection_payload, indent="\t", ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize the generated OpenAPI route section inside the ECUBE Postman collection."
    )
    parser.add_argument(
        "--collection",
        default=str(DEFAULT_COLLECTION_PATH),
        help="Path to the Postman collection JSON file",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    collection_path = Path(args.collection)

    try:
        collection_payload = load_collection_payload(collection_path)
        openapi_operations = load_openapi_operations()
        synced_payload = sync_collection_payload(collection_payload, openapi_operations)
        write_collection_payload(collection_path, synced_payload)
    except Exception as exc:  # pragma: no cover - thin CLI wrapper
        print(f"ERROR: Unable to synchronize Postman collection: {exc}")
        return 1

    print(f"Synchronized Postman collection with ECUBE OpenAPI schema: {collection_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())