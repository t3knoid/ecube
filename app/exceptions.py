"""Custom domain exceptions for ECUBE.

Raising these exceptions from anywhere in the application (routers, services,
background tasks) will be caught by the global exception handlers registered
in ``app.main`` and converted into a uniform JSON error response.
"""

from http import HTTPStatus


class ECUBEException(Exception):
    """Base class for all application-level exceptions."""

    status_code: int = 500
    default_code: str = "INTERNAL_ERROR"
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, code: str | None = None) -> None:
        self.message = message or self.default_message
        self.detail = self.message
        self.code = code or self.default_code
        super().__init__(self.message)


class BadRequestError(ECUBEException):
    """Raised when a request is syntactically valid but missing required intent (HTTP 400)."""

    status_code = 400
    default_code = "BAD_REQUEST"
    default_message = "The request is invalid."


class AuthenticationError(ECUBEException):
    """Raised when a request lacks valid authentication credentials (HTTP 401)."""

    status_code = 401
    default_code = "UNAUTHORIZED"
    default_message = "Authentication credentials are missing or invalid."

    def __init__(
        self,
        message: str | None = None,
        code: str | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        super().__init__(message=message, code=code)
        self.reason = reason


class AuthorizationError(ECUBEException):
    """Raised when an authenticated user lacks the required role/permission (HTTP 403)."""

    status_code = 403
    default_code = "FORBIDDEN"
    default_message = "You do not have permission to perform this action."


class NotFoundError(ECUBEException):
    """Raised when a requested resource or action does not exist (HTTP 404)."""

    status_code = 404
    default_code = "NOT_FOUND"
    default_message = "The requested resource was not found."


class ConflictError(ECUBEException):
    """Raised when a request conflicts with the current state of a resource (HTTP 409)."""

    status_code = 409
    default_code = "CONFLICT"
    default_message = "The request conflicts with the current state of the resource."


class ValidationError(ECUBEException):
    """Raised when validated request data still fails domain validation (HTTP 422)."""

    status_code = 422
    default_code = "VALIDATION_ERROR"
    default_message = "The request could not be processed."


class DatabaseStatusUnknownError(ECUBEException):
    """Raised when provisioning state cannot be determined (HTTP 503).

    This typically means the database is unreachable due to a transient
    outage or misconfigured ``DATABASE_URL``.  The caller should fail
    closed rather than assuming the database is unprovisioned.
    """

    status_code = 503
    default_code = "SERVICE_UNAVAILABLE"
    default_message = (
        "Cannot determine database provisioning state. "
        "The database may be temporarily unreachable."
    )


class EngineReinitializationError(ECUBEException):
    """Raised when a database engine swap is already in progress (HTTP 503)."""

    status_code = 503
    default_code = "SERVICE_UNAVAILABLE"
    default_message = (
        "Database engine reinitialization is already in progress. "
        "Please retry after the current operation completes."
    )


class InternalServiceError(ECUBEException):
    """Raised when an internal service operation fails unexpectedly (HTTP 500)."""

    status_code = 500
    default_code = "INTERNAL_ERROR"
    default_message = "An unexpected error occurred."


class ServiceUnavailableError(ECUBEException):
    """Raised when a dependency or host capability is unavailable (HTTP 503)."""

    status_code = 503
    default_code = "SERVICE_UNAVAILABLE"
    default_message = "The service is temporarily unavailable."


class EncodingError(ECUBEException):
    """Raised when input contains invalid characters that cannot be stored (HTTP 422)."""

    status_code = 422
    default_code = "ENCODING_ERROR"
    default_message = "Request contains invalid characters."


class OSUserPasswordRequiredError(ECUBEException):
    """Raised when creating a new OS user without a password (HTTP 422)."""

    status_code = 422
    default_code = "OS_USER_PASSWORD_REQUIRED"
    default_message = "Password is required when creating a new OS user."


class StatusCodeError(ECUBEException):
    """Fallback ECUBE exception when a precise domain subclass does not exist."""

    def __init__(self, status_code: int, message: str | None = None, code: str | None = None) -> None:
        self.status_code = status_code
        default_code = code
        if default_code is None:
            try:
                default_code = HTTPStatus(status_code).name
            except ValueError:
                default_code = f"HTTP_{status_code}"
        super().__init__(message=message, code=default_code)


def service_exception(*, status_code: int, detail: str | None = None) -> ECUBEException:
    """Map service-layer status/detail pairs to ECUBE domain exceptions.

    Services may still need to express transport-adjacent outcomes such as 404
    or 409, but they should do so via application exceptions rather than
    FastAPI's transport-layer ``HTTPException``.
    """

    exception_map = {
        400: BadRequestError,
        401: AuthenticationError,
        403: AuthorizationError,
        404: NotFoundError,
        409: ConflictError,
        422: ValidationError,
        500: InternalServiceError,
        503: ServiceUnavailableError,
    }
    exc_cls = exception_map.get(status_code)
    if exc_cls is not None:
        return exc_cls(detail)
    return StatusCodeError(status_code=status_code, message=detail)
