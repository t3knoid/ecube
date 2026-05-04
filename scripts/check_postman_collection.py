#!/usr/bin/env python3
"""Validate that the Postman collection references current ECUBE API routes."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COLLECTION_PATH = PROJECT_ROOT / "postman" / "ecube-postman-collection.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
GENERATED_SYNC_FOLDER_NAME = "OpenAPI Route Sync (Generated)"
GENERATED_SYNC_FOLDER_DESCRIPTION = (
    "Auto-generated from the ECUBE OpenAPI schema by scripts/sync_postman_collection.py. "
    "Do not edit manually."
)
POSTMAN_VARIABLE_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")


@dataclass(frozen=True)
class CollectionRequest:
    name: str
    method: str
    path: str


@dataclass(frozen=True)
class OpenAPIOperation:
    method: str
    path: str
    pattern: re.Pattern[str]
    operation_id: str = ""
    summary: str = ""


def _path_to_regex(path: str) -> re.Pattern[str]:
    parts = [segment for segment in path.strip("/").split("/") if segment]
    pattern_parts: list[str] = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            pattern_parts.append(r"[^/]+")
        else:
            pattern_parts.append(re.escape(part))
    if not pattern_parts:
        return re.compile(r"^/$")
    return re.compile(r"^/" + "/".join(pattern_parts) + r"$")


def _normalize_path(raw_path: str) -> str:
    path = raw_path.strip()
    if not path:
        return "/"
    if path.startswith("{{"):
        closing = path.find("}}")
        if closing != -1:
            path = path[closing + 2 :]
    elif path.startswith("http://") or path.startswith("https://"):
        path = urlsplit(path).path
    else:
        path = urlsplit(path).path or path

    path = path.split("?", 1)[0].split("#", 1)[0].strip()
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def normalize_postman_url(url: Any) -> str:
    if isinstance(url, str):
        return _normalize_path(url)
    if not isinstance(url, dict):
        raise ValueError("request URL must be a string or object")

    path_parts = url.get("path")
    if isinstance(path_parts, list) and path_parts:
        joined = "/".join(str(part).strip("/") for part in path_parts if str(part).strip("/"))
        if joined:
            return _normalize_path("/" + joined)

    raw = url.get("raw")
    if isinstance(raw, str) and raw.strip():
        return _normalize_path(raw)

    raise ValueError("request URL is missing both path and raw values")


def canonicalize_parameter_path(path: str) -> str:
    return POSTMAN_VARIABLE_PATTERN.sub(lambda match: "{" + match.group(1) + "}", path)


def load_collection_payload(collection_path: Path) -> dict[str, Any]:
    payload = json.loads(collection_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Collection JSON root must be an object")
    return payload


def get_collection_items(collection_payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = collection_payload.get("item")
    if not isinstance(items, list):
        raise ValueError("Collection JSON is missing the top-level item array")
    return items


def iter_collection_requests(items: Iterable[dict[str, Any]], trail: tuple[str, ...] = ()) -> Iterable[CollectionRequest]:
    for item in items:
        name = str(item.get("name") or "<unnamed>")
        current_trail = (*trail, name)

        nested = item.get("item")
        if isinstance(nested, list):
            yield from iter_collection_requests(nested, current_trail)

        request = item.get("request")
        if not isinstance(request, dict):
            continue

        method = str(request.get("method") or "").upper()
        if not method:
            raise ValueError(f"Collection request {' / '.join(current_trail)} is missing an HTTP method")

        path = normalize_postman_url(request.get("url"))
        yield CollectionRequest(name=" / ".join(current_trail), method=method, path=path)


def load_collection_requests(collection_path: Path) -> list[CollectionRequest]:
    payload = load_collection_payload(collection_path)
    return list(iter_collection_requests(get_collection_items(payload)))


def extract_openapi_operations(openapi_schema: dict[str, Any]) -> list[OpenAPIOperation]:
    paths = openapi_schema.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI schema is missing the paths object")

    operations: list[OpenAPIOperation] = []
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operations.append(
                OpenAPIOperation(
                    method=method.upper(),
                    path=path,
                    pattern=_path_to_regex(path),
                    operation_id=str(operation.get("operationId") or ""),
                    summary=str(operation.get("summary") or ""),
                )
            )
    return operations


def load_openapi_operations() -> list[OpenAPIOperation]:
    from app.openapi import load_openapi_schema

    return extract_openapi_operations(load_openapi_schema())


def find_generated_sync_folder(collection_payload: dict[str, Any]) -> dict[str, Any] | None:
    for item in get_collection_items(collection_payload):
        if item.get("name") != GENERATED_SYNC_FOLDER_NAME:
            continue
        if isinstance(item.get("item"), list):
            return item
    return None


def find_collection_drift(
    collection_requests: Sequence[CollectionRequest],
    openapi_operations: Sequence[OpenAPIOperation],
) -> list[str]:
    errors: list[str] = []
    for request in collection_requests:
        matches = [
            operation
            for operation in openapi_operations
            if operation.method == request.method and operation.pattern.match(request.path)
        ]
        if matches:
            continue

        method_matches = [
            operation
            for operation in openapi_operations
            if operation.pattern.match(request.path)
        ]
        if method_matches:
            supported_methods = ", ".join(sorted({operation.method for operation in method_matches}))
            errors.append(
                f"{request.name}: {request.method} {request.path} does not match the OpenAPI method set ({supported_methods})"
            )
            continue

        errors.append(f"{request.name}: {request.method} {request.path} is not present in the OpenAPI schema")
    return errors


def request_matches_openapi(
    request: CollectionRequest,
    openapi_operations: Sequence[OpenAPIOperation],
) -> bool:
    return any(
        operation.method == request.method and operation.pattern.match(request.path)
        for operation in openapi_operations
    )


def find_generated_sync_drift(
    collection_payload: dict[str, Any],
    openapi_operations: Sequence[OpenAPIOperation],
) -> list[str]:
    generated_folder = find_generated_sync_folder(collection_payload)
    if generated_folder is None:
        return [
            f"Missing generated sync folder '{GENERATED_SYNC_FOLDER_NAME}'. "
            "Run python3 scripts/sync_postman_collection.py."
        ]

    generated_requests = list(
        iter_collection_requests(
            generated_folder.get("item", []),
            trail=(GENERATED_SYNC_FOLDER_NAME,),
        )
    )
    generated_keys = {
        (request.method, canonicalize_parameter_path(request.path))
        for request in generated_requests
    }
    openapi_keys = {
        (operation.method, canonicalize_parameter_path(_normalize_path(operation.path)))
        for operation in openapi_operations
    }

    errors: list[str] = []
    missing = sorted(openapi_keys - generated_keys)
    extra = sorted(generated_keys - openapi_keys)

    if missing:
        missing_text = ", ".join(f"{method} {path}" for method, path in missing)
        errors.append(
            f"Generated sync folder is missing {len(missing)} OpenAPI operation(s): {missing_text}"
        )
    if extra:
        extra_text = ", ".join(f"{method} {path}" for method, path in extra)
        errors.append(
            f"Generated sync folder contains {len(extra)} request(s) that are not in OpenAPI: {extra_text}"
        )
    return errors


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that the ECUBE Postman collection paths and methods still match the OpenAPI schema."
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
        collection_requests = list(iter_collection_requests(get_collection_items(collection_payload)))
        openapi_operations = load_openapi_operations()
        errors = find_collection_drift(collection_requests, openapi_operations)
        errors.extend(find_generated_sync_drift(collection_payload, openapi_operations))
    except Exception as exc:  # pragma: no cover - thin CLI wrapper
        print(f"ERROR: Unable to validate Postman collection sync: {exc}")
        return 1

    if errors:
        print(f"ERROR: {collection_path} is out of sync with the ECUBE OpenAPI schema.")
        for error in errors:
            print(f" - {error}")
        print("\nRun python3 scripts/sync_postman_collection.py, review the generated changes, and restage the collection.")
        return 1

    print(f"Postman collection routes are in sync: {collection_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())