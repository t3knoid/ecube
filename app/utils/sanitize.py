"""Unicode string sanitization for database-safe input handling.

Strips null bytes and unpaired surrogates that pass Pydantic validation
but cause PostgreSQL to reject the value at insert time (issue #124).
"""

import re
from typing import Annotated

from pydantic import BeforeValidator

# Matches lone surrogates (U+D800–U+DFFF) which are invalid in UTF-8.
_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")

# Substrings in DB exception messages that indicate encoding/character issues.
_ENCODING_ERROR_MARKERS = (
    "invalid byte sequence",
    "character with byte sequence",
    "unterminated string",
    "unsupported unicode",
    "invalid unicode",
    "null character",
    "\\x00",
    "0x00",
)


def sanitize_string(value: object) -> object:
    """Strip null bytes and unpaired surrogates from a string value.

    Non-string values are returned unchanged so this can be used safely
    as a Pydantic ``BeforeValidator`` on ``Optional`` fields.
    """
    if not isinstance(value, str):
        return value
    value = value.replace("\x00", "")
    value = _SURROGATE_RE.sub("", value)
    return value


def is_encoding_error(exc: BaseException) -> bool:
    """Return True if *exc* looks like a database character-encoding failure."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _ENCODING_ERROR_MARKERS)


# Drop-in replacement for ``str`` in Pydantic schemas.
SafeStr = Annotated[str, BeforeValidator(sanitize_string)]
