import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


def _mount_credentials_fernet() -> Fernet:
    seed = settings.mount_credentials_encryption_key or settings.secret_key
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_mount_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value == "":
        return None
    return _mount_credentials_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_mount_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return _mount_credentials_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        logger.warning(
            "Stored mount credential decryption failed",
            extra={"context": {"failure_category": "mount_credentials_decryption", "reason": "invalid_token"}},
        )
        raise RuntimeError("Stored mount credential decryption failed") from exc