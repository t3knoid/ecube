"""Custom domain exceptions for ECUBE.

Raising these exceptions from anywhere in the application (routers, services,
background tasks) will be caught by the global exception handlers registered
in ``app.main`` and converted into a uniform JSON error response.
"""


class ECUBEException(Exception):
    """Base class for all application-level exceptions."""

    status_code: int = 500
    default_code: str = "INTERNAL_ERROR"
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, code: str | None = None) -> None:
        self.message = message or self.default_message
        self.code = code or self.default_code
        super().__init__(self.message)


class AuthenticationError(ECUBEException):
    """Raised when a request lacks valid authentication credentials (HTTP 401)."""

    status_code = 401
    default_code = "UNAUTHORIZED"
    default_message = "Authentication credentials are missing or invalid."


class AuthorizationError(ECUBEException):
    """Raised when an authenticated user lacks the required role/permission (HTTP 403)."""

    status_code = 403
    default_code = "FORBIDDEN"
    default_message = "You do not have permission to perform this action."


class ConflictError(ECUBEException):
    """Raised when a request conflicts with the current state of a resource (HTTP 409)."""

    status_code = 409
    default_code = "CONFLICT"
    default_message = "The request conflicts with the current state of the resource."
