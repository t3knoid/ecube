from typing import Any, Optional


def operation_extra(operation_id: Optional[str], **extra: Any) -> dict[str, Any]:
    if operation_id:
        return {"operation_id": operation_id, **extra}
    return extra


def details_with_operation_id(details: dict[str, Any], operation_id: Optional[str]) -> dict[str, Any]:
    if operation_id:
        return {**details, "operation_id": operation_id}
    return details