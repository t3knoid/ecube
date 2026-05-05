import logging
import subprocess
import shutil
import os
import posixpath
import re
import tempfile
import pwd
import grp
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.network import MountStatus, MountType, NetworkMount
from app.infrastructure.mount_namespace import shares_host_mount_namespace
from app.repositories.audit_repository import AuditRepository
from app.repositories.mount_repository import MountRepository
from app.schemas.network import MountCreate, MountShareDiscoveryItem, MountShareDiscoveryRequest, MountShareDiscoveryResponse, MountUpdate, NetworkMountSchema
from app.config import settings
from app.exceptions import ConflictError, EncodingError
from app.services.mount_credentials_service import decrypt_mount_secret, encrypt_mount_secret
from app.services.mount_check_utils import check_mounted_with_configured_timeout

from app.utils.sanitize import is_encoding_error, normalize_project_id, sanitize_error_message

# Re-export so existing ``mount_service.MountProvider`` access keeps working.
from app.infrastructure.mount_protocol import MountProvider  # noqa: F401 – re-export


def _default_provider() -> "MountProvider":
    """Lazy import to avoid circular dependency at module level."""
    from app.infrastructure import get_mount_provider
    return get_mount_provider()

logger = logging.getLogger(__name__)

_SUPPORTED_NFS_CLIENT_VERSIONS = ("4.2", "4.1", "4.0", "3")

_CREDENTIAL_FIELD_NAMES = ("username", "password", "credentials_file")
_ENCRYPTED_CREDENTIAL_ATTRS = {
    "username": "encrypted_username",
    "password": "encrypted_password",
    "credentials_file": "encrypted_credentials_file",
}
_MOUNT_PATH_VIEWER_ROLES = frozenset({"admin", "manager"})
_REDACTED_MOUNT_PATH_VALUE = "[REDACTED]"


def _log_mount_debug_failure(
    message: str,
    *,
    local_mount_point: str,
    mount_type: MountType | None = None,
    remote_path: str | None = None,
    returncode: int | None = None,
    raw_error: object = None,
) -> None:
    raw_text = "" if raw_error is None else str(raw_error).strip()
    if not raw_text:
        raw_text = "(empty)"

    context_parts = [f"local_mount_point={local_mount_point}"]
    if mount_type is not None:
        context_parts.insert(0, f"type={mount_type.value}")
    if remote_path is not None:
        context_parts.append(f"remote_path={remote_path}")
    if returncode is not None:
        context_parts.append(f"returncode={returncode}")

    if returncode is None:
        logger.debug("%s: %s raw_error=%s", message, " ".join(context_parts), raw_text)
        return

    logger.debug("%s: %s raw_error=%s", message, " ".join(context_parts), raw_text)


def _mount_command_path(cmd: list[str]) -> str:
    if not cmd:
        return "unknown"
    if "nsenter" in cmd:
        return "nsenter"
    if "-N" in cmd:
        return "mount-namespace-flag"
    if cmd[:2] == ["sudo", "-n"]:
        return "sudo"
    return "direct"


class LinuxMountProvider:
    """Linux implementation using ``mount(8)``, ``umount(8)``, and ``mountpoint(1)``."""

    def discover_shares(
        self,
        mount_type: MountType,
        remote_path: str,
        *,
        credentials_file: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> list[str]:
        if mount_type == MountType.NFS:
            server = _extract_share_discovery_target(mount_type, remote_path)
            showmount_bin = _resolve_showmount_binary()
            if not showmount_bin:
                raise FileNotFoundError("showmount not available")

            result = subprocess.run(
                [showmount_bin, "-e", server],
                capture_output=True,
                text=True,
                timeout=settings.subprocess_timeout_seconds,
            )
            if result.returncode != 0:
                error = (result.stderr or result.stdout or "").strip() or "showmount failed"
                raise RuntimeError(error)

            discovered: list[str] = []
            for line in (result.stdout or "").splitlines():
                stripped = line.strip()
                if not stripped or stripped.lower().startswith("exports list on"):
                    continue
                export_path = stripped.split()[0]
                if export_path.startswith("/"):
                    discovered.append(f"{server}:{export_path}")
            return discovered

        server = _extract_share_discovery_target(mount_type, remote_path)
        smbclient_bin = _resolve_smbclient_binary()
        if not smbclient_bin:
            raise FileNotFoundError("smbclient not available")

        cmd = [smbclient_bin, "-g", "-L", server]
        if credentials_file:
            cmd.extend(["-A", credentials_file])
        elif username is not None or password is not None:
            cmd.extend(["-U", f"{username or ''}%{password or ''}"])
        else:
            cmd.append("-N")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.subprocess_timeout_seconds,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "").strip() or "smbclient failed"
            raise RuntimeError(error)

        discovered: list[str] = []
        for line in (result.stdout or "").splitlines():
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 2 or parts[0] != "Disk":
                continue
            share_name = parts[1]
            if not share_name or share_name.upper() in {"IPC$", "PRINT$"}:
                continue
            discovered.append(f"//{server}/{share_name}")
        return discovered

    def os_mount(self, mount_type: MountType, remote_path: str, local_mount_point: str,
                 *, credentials_file: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None,
                 nfs_client_version: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        resolved_nfs_client_version: Optional[str] = None
        temporary_credentials_file: Optional[str] = None
        if mount_type == MountType.NFS:
            resolved_nfs_client_version = _resolve_nfs_client_version(nfs_client_version)
            cmd = [settings.mount_binary_path, "-t", "nfs", "-o", f"vers={resolved_nfs_client_version}", remote_path, local_mount_point]
        else:
            cmd = [settings.mount_binary_path, "-t", "cifs", remote_path, local_mount_point]
            if credentials_file:
                cmd += ["-o", f"credentials={credentials_file}"]
            elif username is not None or password is not None:
                mount_label = _redacted_mount_label(local_mount_point)
                try:
                    temporary_credentials_file = _prepare_temporary_smb_credentials_file(
                        username=username,
                        password=password,
                    )
                except Exception as exc:
                    logger.warning(
                        "Temporary SMB credentials preparation failed for mount_label=%s reason=%s",
                        mount_label,
                        sanitize_error_message(exc, "Temporary SMB credentials preparation failed"),
                    )
                    logger.debug(
                        "Temporary SMB credentials preparation details: mount_label=%s local_mount_point=%s remote_path=%s raw_error=%s",
                        mount_label,
                        local_mount_point,
                        remote_path,
                        str(exc),
                    )
                    return False, str(exc)
                cmd += ["-o", f"credentials={temporary_credentials_file}"]
            else:
                cmd += ["-o", "guest"]

        cmd = _with_host_mount_namespace(cmd)
        mount_label = _redacted_mount_label(local_mount_point)
        command_path = _mount_command_path(cmd)
        if mount_type == MountType.NFS:
            logger.info(
                "Executing NFS mount command: mount_label=%s nfs_client_version=%s command_path=%s",
                mount_label,
                resolved_nfs_client_version,
                command_path,
            )
            logger.debug(
                "NFS mount command context: mount_label=%s remote_path=%s local_mount_point=%s nfs_client_version=%s command_path=%s",
                mount_label,
                remote_path,
                local_mount_point,
                resolved_nfs_client_version,
                command_path,
            )
        logger.info("Executing mount command: type=%s mount_label=%s", mount_type.value, mount_label)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.subprocess_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            logger.warning(
                "Mount command timed out: type=%s mount_label=%s reason=%s",
                mount_type.value,
                mount_label,
                sanitize_error_message(exc, "Mount command timed out"),
            )
            _log_mount_debug_failure(
                "Mount command timeout details",
                mount_type=mount_type,
                remote_path=remote_path,
                local_mount_point=local_mount_point,
                raw_error=exc,
            )
            return False, str(exc)
        try:
            if result.returncode == 0:
                mounted = self.check_mounted(local_mount_point)
                if mounted is True:
                    logger.info(
                        "Mount command succeeded: type=%s mount_label=%s command_path=%s",
                        mount_type.value,
                        mount_label,
                        command_path,
                    )
                    return True, None
                error = "mount command reported success but mountpoint is not active"
                logger.warning("Mount command verification failed for mount_label=%s", mount_label)
                logger.debug(
                    "Mount command verification details: type=%s mount_label=%s remote_path=%s local_mount_point=%s command_path=%s mounted=%s",
                    mount_type.value,
                    mount_label,
                    remote_path,
                    local_mount_point,
                    command_path,
                    mounted,
                )
                return False, error

            error = (result.stderr or result.stdout or "").strip() or "mount failed"
            logger.warning(
                "Mount command failed: type=%s mount_label=%s returncode=%s reason=%s",
                mount_type.value,
                mount_label,
                result.returncode,
                sanitize_error_message(error, "Mount command failed"),
            )
            _log_mount_debug_failure(
                "Mount command raw error",
                mount_type=mount_type,
                remote_path=remote_path,
                local_mount_point=local_mount_point,
                returncode=result.returncode,
                raw_error=error,
            )

            if "failed to apply fstab options" in error.lower():
                retry_error = error

                if mount_type == MountType.NFS:
                    nfs_bin = _resolve_mount_nfs_binary()
                    if nfs_bin:
                        direct_cmd = [nfs_bin, remote_path, local_mount_point]
                        direct_cmd = _with_host_mount_namespace(direct_cmd)
                        direct_command_path = _mount_command_path(direct_cmd)
                        logger.info(
                            "Retrying direct NFS helper for mount_label=%s command_path=%s",
                            mount_label,
                            direct_command_path,
                        )
                        logger.debug(
                            "Direct NFS helper context: mount_label=%s helper=%s remote_path=%s local_mount_point=%s command_path=%s",
                            mount_label,
                            nfs_bin,
                            remote_path,
                            local_mount_point,
                            direct_command_path,
                        )
                        try:
                            direct_result = subprocess.run(
                                direct_cmd,
                                capture_output=True,
                                text=True,
                                timeout=settings.subprocess_timeout_seconds,
                            )
                        except subprocess.TimeoutExpired as exc:
                            logger.warning(
                                "Direct NFS helper mount timed out: mount_label=%s reason=%s",
                                mount_label,
                                sanitize_error_message(exc, "Direct NFS helper mount timed out"),
                            )
                            _log_mount_debug_failure(
                                "Direct NFS helper timeout details",
                                mount_type=mount_type,
                                remote_path=remote_path,
                                local_mount_point=local_mount_point,
                                raw_error=exc,
                            )
                            return False, str(exc)
                        if direct_result.returncode == 0:
                            logger.info(
                                "Direct NFS helper mount succeeded for mount_label=%s command_path=%s",
                                mount_label,
                                direct_command_path,
                            )
                            return True, None
                        direct_error = (direct_result.stderr or direct_result.stdout or "").strip() or "mount failed"
                        logger.warning(
                            "Direct NFS helper mount failed: mount_label=%s returncode=%s reason=%s",
                            mount_label,
                            direct_result.returncode,
                            sanitize_error_message(direct_error, "Direct NFS helper mount failed"),
                        )
                        _log_mount_debug_failure(
                            "Direct NFS helper raw error",
                            mount_type=mount_type,
                            remote_path=remote_path,
                            local_mount_point=local_mount_point,
                            returncode=direct_result.returncode,
                            raw_error=direct_error,
                        )
                        retry_error = direct_error

                mounted = self.check_mounted(local_mount_point)
                if mounted is True:
                    logger.warning(
                        "Mount commands reported failure but the target is active; treating as mounted for mount_label=%s",
                        mount_label,
                    )
                    return True, None

                return False, retry_error

            return False, error
        finally:
            if temporary_credentials_file:
                _cleanup_temporary_smb_credentials_file(temporary_credentials_file)

    def os_unmount(self, local_mount_point: str) -> Tuple[bool, Optional[str]]:
        try:
            cmd = _with_host_mount_namespace([settings.umount_binary_path, local_mount_point])
            mount_label = _redacted_mount_label(local_mount_point)
            logger.info("Executing unmount command for mount_label=%s", mount_label)
            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                timeout=settings.subprocess_timeout_seconds,
            )
            if result.returncode != 0:
                error = (result.stderr or result.stdout or "").strip() or "umount failed"
                logger.warning(
                    "Unmount command failed: mount_label=%s returncode=%s reason=%s",
                    mount_label,
                    result.returncode,
                    sanitize_error_message(error, "Unmount command failed"),
                )
                _log_mount_debug_failure(
                    "Unmount command raw error",
                    local_mount_point=local_mount_point,
                    returncode=result.returncode,
                    raw_error=error,
                )
                return False, error
            logger.info("Unmount command succeeded for mount_label=%s", mount_label)
            return True, None
        except Exception as exc:
            logger.warning(
                "Unmount command raised exception for mount_label=%s reason=%s",
                _redacted_mount_label(local_mount_point),
                sanitize_error_message(exc, "Unmount command failed"),
            )
            _log_mount_debug_failure(
                "Unmount command exception details",
                local_mount_point=local_mount_point,
                raw_error=exc,
            )
            return False, str(exc)

    def check_mounted(self, local_mount_point: str, *, timeout_seconds: Optional[float] = None) -> Optional[bool]:
        try:
            default_timeout = settings.subprocess_timeout_seconds
            timeout = default_timeout if timeout_seconds is None or timeout_seconds <= 0 else timeout_seconds
            if not _in_host_mount_namespace():
                local_path = os.path.normpath(local_mount_point)
                cmd = _with_sudo([settings.mount_binary_path, "-N", "/proc/1/ns/mnt"])
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                if result.returncode != 0:
                    error = (result.stderr or result.stdout or "").strip() or "mount list check failed"
                    logger.warning("Host namespace mount list check failed: reason=%s", sanitize_error_message(error, "Mount list check failed"))
                    return self._check_mounted_with_mountpoint(local_mount_point, timeout)

                stdout = result.stdout if isinstance(result.stdout, str) else ""
                if stdout:
                    return f" on {local_path} " in stdout

                # Some mocked/test environments don't provide mount output.
                return self._check_mounted_with_mountpoint(local_mount_point, timeout)

            return self._check_mounted_with_mountpoint(local_mount_point, timeout)
        except Exception:
            return None

    def _check_mounted_with_mountpoint(self, local_mount_point: str, timeout: float) -> Optional[bool]:
        cmd = _with_sudo([settings.mountpoint_binary_path, "-q", local_mount_point])
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return result.returncode == 0


def _resolve_mount_nfs_binary() -> Optional[str]:
    for candidate in ("/sbin/mount.nfs", "/usr/sbin/mount.nfs", "mount.nfs"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _resolve_nfs_client_version(requested_version: Optional[str]) -> str:
    candidate = str(requested_version or settings.nfs_client_version or "4.1").strip()
    if candidate not in _SUPPORTED_NFS_CLIENT_VERSIONS:
        return "4.1"
    return candidate


def _stored_nfs_client_version(mount_type: MountType, requested_version: Optional[str]) -> Optional[str]:
    if mount_type != MountType.NFS:
        return None
    if requested_version is None or not str(requested_version).strip():
        return None
    return _resolve_nfs_client_version(requested_version)


def _resolve_showmount_binary() -> Optional[str]:
    for candidate in ("/usr/sbin/showmount", "/sbin/showmount", "showmount"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _resolve_smbclient_binary() -> Optional[str]:
    for candidate in ("/usr/bin/smbclient", "/bin/smbclient", "smbclient"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _cleanup_temporary_smb_credentials_file(credentials_path: str) -> None:
    try:
        if settings.use_sudo and os.geteuid() != 0:
            subprocess.run(
                _with_sudo(["rm", "-f", credentials_path]),
                check=True,
                capture_output=True,
                text=True,
                timeout=settings.subprocess_timeout_seconds,
            )
            return
        os.remove(credentials_path)
    except FileNotFoundError:
        return
    except subprocess.CalledProcessError as exc:
        error = (exc.stderr or exc.stdout or "").strip() or str(exc)
        logger.warning(
            "Temporary SMB credentials cleanup failed: reason=%s",
            sanitize_error_message(error, "Temporary SMB credentials cleanup failed"),
        )
        logger.debug(
            "Temporary SMB credentials cleanup details: credentials_file=%s raw_error=%s",
            credentials_path,
            error,
        )
    except Exception as exc:
        logger.warning(
            "Temporary SMB credentials cleanup failed: reason=%s",
            sanitize_error_message(exc, "Temporary SMB credentials cleanup failed"),
        )
        logger.debug(
            "Temporary SMB credentials cleanup details: credentials_file=%s raw_error=%s",
            credentials_path,
            str(exc),
        )


def _prepare_temporary_smb_credentials_file(
    *,
    username: Optional[str],
    password: Optional[str],
) -> str:
    fd, credentials_path = tempfile.mkstemp(prefix="ecube-smb-", suffix=".cred")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            if username is not None:
                handle.write(f"username={username}\n")
            if password is not None:
                handle.write(f"password={password}\n")

        if os.geteuid() == 0:
            os.chown(credentials_path, 0, 0)
        elif settings.use_sudo:
            subprocess.run(
                _with_sudo(["chown", "root:root", credentials_path]),
                check=True,
                capture_output=True,
                text=True,
                timeout=settings.subprocess_timeout_seconds,
            )

        return credentials_path
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        _cleanup_temporary_smb_credentials_file(credentials_path)
        raise


def _with_sudo(cmd: list[str]) -> list[str]:
    # Use non-interactive sudo when configured and not already running as root.
    if settings.use_sudo and os.geteuid() != 0:
        return ["sudo", "-n", *cmd]
    return cmd


def _with_mount_namespace_flag(cmd: list[str]) -> Optional[list[str]]:
    """Add util-linux namespace flag for mount/umount commands when applicable."""
    if not cmd:
        return None

    binary = os.path.basename(cmd[0])
    if binary in ("mount", "umount"):
        return [cmd[0], "-N", "/proc/1/ns/mnt", *cmd[1:]]
    return None


def _in_host_mount_namespace() -> bool:
    return shares_host_mount_namespace(
        on_self_read_error=True,
        on_host_read_error=False,
        on_host_read_error_callback=lambda _exc: logger.warning(
            "Unable to read host mount namespace; assuming namespace differs"
        ),
    )


def _with_host_mount_namespace(cmd: list[str]) -> list[str]:
    if _in_host_mount_namespace():
        return _with_sudo(cmd)

    ns_flag_cmd = _with_mount_namespace_flag(cmd)
    if ns_flag_cmd is not None:
        logger.warning("Mount namespace differs from host; using util-linux namespace flag")
        return _with_sudo(ns_flag_cmd)

    logger.warning("Mount namespace differs from host but no namespace helper is available; using current namespace")
    return _with_sudo(cmd)


def _mount_root_for_type(mount_type: MountType) -> str:
    return "/nfs" if mount_type == MountType.NFS else "/smb"


def _extract_remote_leaf(mount_type: MountType, remote_path: str) -> str:
    path_part = remote_path
    if mount_type == MountType.NFS:
        if ":" in remote_path:
            path_part = remote_path.rsplit(":", 1)[1]
    else:
        stripped = remote_path.lstrip("/")
        smb_parts = [part for part in stripped.split("/") if part]
        if len(smb_parts) >= 2:
            path_part = "/".join(smb_parts[1:])

    parts = [part for part in path_part.split("/") if part not in ("", ".", "..")]
    return parts[-1] if parts else "share"


def _slugify_mount_leaf(name: str) -> str:
    # Keep mount directory names predictable and filesystem-safe.
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return slug or "share"


def _generate_local_mount_point(
    mount_type: MountType,
    remote_path: str,
    existing_mount_points: set[str],
) -> str:
    root = _mount_root_for_type(mount_type)
    leaf = _slugify_mount_leaf(_extract_remote_leaf(mount_type, remote_path))
    candidate = f"{root}/{leaf}"
    suffix = 2
    while candidate in existing_mount_points:
        candidate = f"{root}/{leaf}-{suffix}"
        suffix += 1
    return candidate


def _managed_mount_root(local_mount_point: str) -> Optional[str]:
    normalized = os.path.normpath(local_mount_point)
    if normalized.startswith("/nfs/"):
        return "/nfs"
    if normalized.startswith("/smb/"):
        return "/smb"
    return None


def _service_owner_spec() -> str:
    uid = os.geteuid()
    gid = os.getegid()
    try:
        user = pwd.getpwuid(uid).pw_name
    except Exception:
        user = str(uid)
    try:
        group = grp.getgrgid(gid).gr_name
    except Exception:
        group = str(gid)
    return f"{user}:{group}"


def _run_sudo_cmd(cmd: list[str]) -> Tuple[bool, str]:
    result = subprocess.run(
        ["sudo", "-n", *cmd],
        capture_output=True,
        text=True,
        timeout=settings.subprocess_timeout_seconds,
    )
    if result.returncode == 0:
        return True, ""
    error = (result.stderr or result.stdout or "").strip() or "sudo command failed"
    return False, error


def _ensure_mount_directory(local_mount_point: str) -> Optional[str]:
    try:
        os.makedirs(local_mount_point, exist_ok=True)
        return None
    except PermissionError as exc:
        managed_root = _managed_mount_root(local_mount_point)

        # Bootstrap managed roots and mount leaf as root, then hand ownership
        # to the service account so future operations are non-root.
        if managed_root and settings.use_sudo and os.geteuid() != 0:
            owner_spec = _service_owner_spec()
            ok, error = _run_sudo_cmd(["mkdir", "-p", managed_root, local_mount_point])
            if not ok:
                return f"failed to create local mount point directory: {error}"
            ok, error = _run_sudo_cmd(["chown", owner_spec, managed_root, local_mount_point])
            if not ok:
                return f"failed to set local mount point ownership: {error}"
            return None

        if managed_root and not os.path.isdir(managed_root):
            return (
                f"failed to create local mount point directory: {exc}. "
                f"Missing managed mount root '{managed_root}'. "
                f"Create it and set ownership to the ECUBE service account."
            )

        if managed_root:
            return (
                f"failed to create local mount point directory: {exc}. "
                f"Ensure '{managed_root}' is writable by the ECUBE service account."
            )

        return f"failed to create local mount point directory: {exc}"
    except Exception as exc:
        return f"failed to create local mount point directory: {exc}"


def _validate_mount_directory_owner(local_mount_point: str) -> Optional[str]:
    try:
        st = os.stat(local_mount_point)
    except Exception as exc:
        return f"failed to stat local mount point directory: {exc}"

    # When the path is already a mount point (i.e. a filesystem is mounted on
    # top of it), os.stat() returns the *mounted* filesystem's root ownership
    # — not the underlying directory's.  Network mounts (SMB/NFS) typically
    # report root:root regardless of the local directory owner, so the
    # ownership check would always fail.  Skip it in that case.
    if os.path.ismount(local_mount_point):
        return None

    # Enforce ownership by the service account; if needed and allowed, repair
    # ownership for managed mount roots via sudo.
    if os.geteuid() != 0 and st.st_uid != os.geteuid():
        managed_root = _managed_mount_root(local_mount_point)
        if managed_root and settings.use_sudo:
            owner_spec = _service_owner_spec()
            ok, error = _run_sudo_cmd(["chown", owner_spec, managed_root, local_mount_point])
            if not ok:
                return f"local mount point directory ownership repair failed: {error}"
            try:
                st = os.stat(local_mount_point)
            except Exception as exc:
                return f"failed to stat local mount point directory: {exc}"
        if st.st_uid == 0:
            return "local mount point directory is owned by root; it must be owned by the ECUBE service account"
        if st.st_uid != os.geteuid():
            return "local mount point directory is not owned by the ECUBE service account"
    return None


def _is_generated_mount_point(local_mount_point: str) -> bool:
    return local_mount_point.startswith("/nfs/") or local_mount_point.startswith("/smb/")


def _cleanup_target_for_generated_mount_point(local_mount_point: str) -> Optional[str]:
    normalized = os.path.normpath(local_mount_point)
    if normalized.startswith("/nfs/"):
        root = "/nfs"
    elif normalized.startswith("/smb/"):
        root = "/smb"
    else:
        return None

    rel = os.path.relpath(normalized, root)
    # Only allow one generated leaf directly under /nfs or /smb.
    if rel in (".", "..") or rel.startswith("../") or "/" in rel:
        logger.warning(
            "Skipping generated mount cleanup for non-leaf managed path label=%s",
            _redacted_mount_label(local_mount_point),
        )
        return None
    return os.path.join(root, rel)


def _cleanup_generated_mount_directory(local_mount_point: str) -> None:
    # Only remove one generated leaf directory under managed roots.
    target = _cleanup_target_for_generated_mount_point(local_mount_point)
    if not target:
        return

    try:
        os.rmdir(target)
        return
    except FileNotFoundError:
        return
    except PermissionError as exc:
        logger.warning("Failed to remove generated mount directory %s: %s", target, exc)
        return
    except OSError as exc:
        logger.warning("Failed to remove generated mount directory %s: %s", target, exc)
        return


def _redacted_mount_label(local_mount_point: str) -> str:
    """Return a safe label for audits without persisting the full mount path."""
    label = os.path.basename(os.path.normpath(local_mount_point or ""))
    return label or "mount"


def _normalize_remote_subpath(path: str) -> str:
    raw = (path or "").strip().replace("\\", "/")
    normalized = posixpath.normpath(f"/{raw.lstrip('/')}")
    return normalized if normalized != "." else "/"


def _normalize_remote_reference(mount_type: MountType, remote_path: str) -> tuple[str, str, str]:
    raw = (remote_path or "").strip()

    if mount_type == MountType.NFS:
        if ":" in raw:
            host, path = raw.split(":", 1)
        else:
            host, path = raw, "/"
        return mount_type.value, host.strip().lower(), _normalize_remote_subpath(path)

    normalized = raw.replace("\\", "/")
    parts = [part for part in normalized.lstrip("/").split("/") if part]
    if not parts:
        return mount_type.value, "", "/"

    host = parts[0].strip().lower()
    share_path = "/" + "/".join(parts[1:]) if len(parts) > 1 else "/"
    return mount_type.value, host, _normalize_remote_subpath(share_path)


def _extract_share_discovery_target(mount_type: MountType, remote_path: str) -> str:
    protocol, host, _path = _normalize_remote_reference(mount_type, remote_path)
    if protocol and host:
        return host
    raise HTTPException(status_code=422, detail="Enter a server address before browsing shares")


def _discovered_share_display_name(mount_type: MountType, remote_path: str) -> str:
    if mount_type == MountType.NFS:
        export_path = remote_path.split(":", 1)[1] if ":" in remote_path else remote_path
        parts = [part for part in export_path.split("/") if part]
        return parts[-1] if parts else "/"

    parts = [part for part in remote_path.replace("\\", "/").lstrip("/").split("/") if part]
    return parts[-1] if parts else remote_path


def _share_discovery_unavailable_detail(mount_type: MountType) -> str:
    if mount_type == MountType.NFS:
        return "Share browsing requires the host showmount tool. Install showmount on the ECUBE host, then try again."
    return "Share browsing requires the host smbclient tool. Install smbclient on the ECUBE host, then try again."


def _normalize_discovered_share_paths(mount_type: MountType, remote_paths: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_path in remote_paths:
        if not isinstance(raw_path, str):
            continue
        candidate = raw_path.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _remote_paths_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    left_prefix = left.rstrip("/") + "/"
    right_prefix = right.rstrip("/") + "/"
    return left.startswith(right_prefix) or right.startswith(left_prefix)


def _validate_remote_path_conflicts(
    mount_type: MountType,
    remote_path: str,
    project_id: str,
    existing_mounts: list[NetworkMount],
    *,
    ignore_mount_id: int | None = None,
) -> None:
    candidate_type, candidate_host, candidate_path = _normalize_remote_reference(mount_type, remote_path)

    for existing in existing_mounts:
        if ignore_mount_id is not None and existing.id == ignore_mount_id:
            continue
        existing_mount_type = existing.type if isinstance(existing.type, MountType) else MountType(str(existing.type))
        existing_remote_path = str(existing.remote_path)
        existing_type, existing_host, existing_path = _normalize_remote_reference(existing_mount_type, existing_remote_path)
        if (candidate_type, candidate_host, candidate_path) == (existing_type, existing_host, existing_path):
            raise HTTPException(
                status_code=409,
                detail="A mount for this remote source is already configured.",
            )

        if candidate_type != existing_type or candidate_host != existing_host:
            continue

        if _remote_paths_overlap(candidate_path, existing_path):
            existing_project_id = normalize_project_id(existing.project_id) or "UNASSIGNED"
            if existing_project_id != project_id:
                raise HTTPException(
                    status_code=409,
                    detail="Remote source paths overlap with another project's configured mount.",
                )


def _credentials_supplied(mount_data: MountCreate | MountUpdate) -> bool:
    return bool(mount_data.username or mount_data.password or mount_data.credentials_file)


def _credential_fields_provided(mount_data: MountCreate | MountUpdate) -> bool:
    return any(field_name in mount_data.model_fields_set for field_name in _CREDENTIAL_FIELD_NAMES)


def _stored_credentials_present(mount: NetworkMount) -> bool:
    return bool(
        mount.encrypted_username
        or mount.encrypted_password
        or mount.encrypted_credentials_file
    )


def _apply_encrypted_mount_credentials(
    mount: NetworkMount,
    mount_data: MountCreate | MountUpdate,
    *,
    preserve_existing: bool,
) -> None:
    for field_name, encrypted_attr in _ENCRYPTED_CREDENTIAL_ATTRS.items():
        if preserve_existing and field_name not in mount_data.model_fields_set:
            continue
        setattr(mount, encrypted_attr, encrypt_mount_secret(getattr(mount_data, field_name)))


def _load_stored_mount_credentials(mount: NetworkMount) -> dict[str, str | None]:
    try:
        return {
            "username": decrypt_mount_secret(mount.encrypted_username),
            "password": decrypt_mount_secret(mount.encrypted_password),
            "credentials_file": decrypt_mount_secret(mount.encrypted_credentials_file),
        }
    except RuntimeError as exc:
        logger.info(
            "Stored mount credentials unavailable",
            extra={
                "context": {
                    "mount_id": mount.id,
                    "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                    "reason": "decryption_failed",
                    "failure_category": "mount_credentials",
                }
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Stored mount credentials could not be decrypted",
        ) from exc


def _resolve_mount_operation_credentials(
    mount: NetworkMount,
    mount_data: MountCreate | MountUpdate,
) -> dict[str, str | None]:
    credentials = (
        _load_stored_mount_credentials(mount)
        if _stored_credentials_present(mount)
        else {"username": None, "password": None, "credentials_file": None}
    )

    for field_name in _CREDENTIAL_FIELD_NAMES:
        if field_name in mount_data.model_fields_set:
            credentials[field_name] = getattr(mount_data, field_name)

    return credentials


def _changed_mount_fields(
    mount: NetworkMount,
    mount_data: MountUpdate,
    *,
    normalized_project_id: str,
) -> list[str]:
    changed_fields: list[str] = []

    current_type = mount.type if isinstance(mount.type, MountType) else MountType(str(mount.type))
    if current_type != mount_data.type:
        changed_fields.append("type")
    if str(mount.remote_path) != mount_data.remote_path:
        changed_fields.append("remote_path")
    if normalize_project_id(mount.project_id) != normalized_project_id:
        changed_fields.append("project_id")
    if _stored_nfs_client_version(mount_data.type, mount_data.nfs_client_version) != _stored_nfs_client_version(current_type, mount.nfs_client_version):
        changed_fields.append("nfs_client_version")
    if _credential_fields_provided(mount_data):
        changed_fields.append("credentials")

    return changed_fields


def _prepare_mount_for_update(
    mount: NetworkMount,
    *,
    provider: "MountProvider",
) -> None:
    local_mount_point = str(mount.local_mount_point)
    if mount.status != MountStatus.MOUNTED or not local_mount_point:
        return

    try:
        unmount_ok, unmount_error = provider.os_unmount(local_mount_point)
    except Exception as exc:
        unmount_ok, unmount_error = False, str(exc)

    if unmount_ok:
        mount.status = MountStatus.UNMOUNTED
        return

    error_text = unmount_error or "umount failed"
    lowered_error = error_text.lower()
    if any(phrase in lowered_error for phrase in ("not mounted", "no mount point")):
        logger.info(
            "Treating already-unmounted mount update as unmounted",
            extra={
                "context": {
                    "mount_id": mount.id,
                    "mount_label": _redacted_mount_label(local_mount_point),
                    "reason": sanitize_error_message(error_text, "Target was already unmounted"),
                    "failure_category": "mount_unmount",
                }
            },
        )
        mount.status = MountStatus.UNMOUNTED
        return

    logger.warning(
        "Mount update aborted because unmount failed",
        extra={
            "context": {
                "mount_id": mount.id,
                "mount_label": _redacted_mount_label(local_mount_point),
                "reason": sanitize_error_message(error_text, "Unmount failed"),
                "failure_category": "mount_unmount",
            }
        },
    )
    raise HTTPException(
        status_code=409,
        detail=(
            f"Failed to unmount {_redacted_mount_label(local_mount_point)}: "
            f"{sanitize_error_message(error_text, 'Unmount failed')}"
        ),
    )


def _restore_mount_after_candidate_validation(
    mount: NetworkMount,
    *,
    provider: "MountProvider",
    original_mount_type: MountType,
    original_remote_path: str,
    original_was_mounted: bool,
) -> Optional[str]:
    local_mount_point = str(mount.local_mount_point)
    current_result = check_mounted_with_configured_timeout(provider, local_mount_point)

    if current_result is True:
        try:
            unmount_ok, unmount_error = provider.os_unmount(local_mount_point)
        except Exception as exc:
            unmount_ok, unmount_error = False, str(exc)

        if not unmount_ok:
            error_text = unmount_error or "umount failed"
            lowered_error = error_text.lower()
            if not any(phrase in lowered_error for phrase in ("not mounted", "no mount point")):
                return error_text

    if not original_was_mounted:
        return None

    original_credentials = (
        _load_stored_mount_credentials(mount)
        if _stored_credentials_present(mount)
        else {"username": None, "password": None, "credentials_file": None}
    )
    restore_ok, restore_error = provider.os_mount(
        original_mount_type,
        original_remote_path,
        local_mount_point,
        credentials_file=original_credentials["credentials_file"],
        username=original_credentials["username"],
        password=original_credentials["password"],
    )
    if restore_ok:
        return None
    return restore_error or "Failed to restore original mount state"


def validate_mount_candidate(mount_data: MountCreate, db: Session, actor: Optional[str] = None,
                             provider: Optional["MountProvider"] = None,
                             client_ip: Optional[str] = None) -> NetworkMount:
    normalized_project_id = normalize_project_id(mount_data.project_id)
    if not isinstance(normalized_project_id, str) or not normalized_project_id:
        raise HTTPException(status_code=422, detail="project_id must not be empty")

    mount_repo = MountRepository(db)
    audit_repo = AuditRepository(db)
    provider = provider or _default_provider()

    mount_repo.acquire_create_lock()
    existing_mounts = mount_repo.list_all()
    _validate_remote_path_conflicts(
        mount_data.type,
        mount_data.remote_path,
        normalized_project_id,
        existing_mounts,
    )

    existing_mount_points = {str(m.local_mount_point) for m in existing_mounts}
    local_mount_point = _generate_local_mount_point(
        mount_data.type,
        mount_data.remote_path,
        existing_mount_points,
    )
    checked_at = datetime.now(timezone.utc)
    mount = NetworkMount(
        type=mount_data.type,
        remote_path=mount_data.remote_path,
        project_id=normalized_project_id,
        nfs_client_version=_stored_nfs_client_version(mount_data.type, mount_data.nfs_client_version),
        local_mount_point=local_mount_point,
        status=MountStatus.UNMOUNTED,
    )

    validation_error = None
    candidate_status = MountStatus.ERROR
    logger.info(
        "Mount candidate validation started: type=%s mount_label=%s actor=%s",
        mount_data.type.value,
        _redacted_mount_label(str(mount.local_mount_point)),
        actor or "system",
    )
    try:
        create_dir_error = _ensure_mount_directory(mount.local_mount_point)
        if create_dir_error:
            validation_error = create_dir_error
            _log_mount_debug_failure(
                "Mount candidate validation mountpoint preparation raw error",
                mount_type=mount_data.type,
                remote_path=mount_data.remote_path,
                local_mount_point=str(mount.local_mount_point),
                raw_error=create_dir_error,
            )
        else:
            owner_error = _validate_mount_directory_owner(mount.local_mount_point)
            if owner_error:
                validation_error = owner_error
                _log_mount_debug_failure(
                    "Mount candidate validation mountpoint ownership raw error",
                    mount_type=mount_data.type,
                    remote_path=mount_data.remote_path,
                    local_mount_point=str(mount.local_mount_point),
                    raw_error=owner_error,
                )
            else:
                resolved_credentials = _resolve_mount_operation_credentials(mount, mount_data)
                success, validation_error = provider.os_mount(
                    mount_data.type,
                    mount_data.remote_path,
                    mount.local_mount_point,
                    credentials_file=resolved_credentials["credentials_file"],
                    username=resolved_credentials["username"],
                    password=resolved_credentials["password"],
                    nfs_client_version=mount.nfs_client_version,
                )
                candidate_status = MountStatus.MOUNTED if success else MountStatus.ERROR
    finally:
        restore_error = _restore_mount_after_candidate_validation(
            mount,
            provider=provider,
            original_mount_type=mount_data.type,
            original_remote_path=mount_data.remote_path,
            original_was_mounted=False,
        )

    if restore_error:
        logger.info(
            "Mount candidate validation could not restore original state",
            extra={
                "context": {
                    "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                    "failure_category": "mount_validate_restore",
                    "project_id": normalized_project_id,
                }
            },
        )
        logger.debug(
            "Mount candidate validation restore raw error",
            extra={
                "context": {
                    "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                    "project_id": normalized_project_id,
                    "raw_error": restore_error,
                }
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Mount validation could not restore original mount state",
        )

    if candidate_status == MountStatus.MOUNTED:
        logger.info(
            "Mount candidate validation succeeded: type=%s mount_label=%s actor=%s",
            mount_data.type.value,
            _redacted_mount_label(str(mount.local_mount_point)),
            actor or "system",
        )
    else:
        logger.info(
            "Mount candidate validation failed: type=%s mount_label=%s actor=%s failure_category=%s reason=%s",
            mount_data.type.value,
            _redacted_mount_label(str(mount.local_mount_point)),
            actor or "system",
            "mount_validate_candidate",
            sanitize_error_message(validation_error, "Mount validation failed"),
        )
        logger.debug(
            "Mount candidate validation failure details",
            extra={
                "context": {
                    "type": mount_data.type.value,
                    "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                    "remote_path": mount_data.remote_path,
                    "local_mount_point": str(mount.local_mount_point),
                    "project_id": normalized_project_id,
                    "raw_error": validation_error,
                }
            },
        )

    try:
        audit_repo.add(
            action="MOUNT_VALIDATE_CANDIDATE",
            user=actor,
            project_id=normalized_project_id,
            details={
                "project_id": normalized_project_id,
                "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                "status": candidate_status.value,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception(
            "Failed to write audit log for MOUNT_VALIDATE_CANDIDATE",
            extra={"context": {"project_id": normalized_project_id}},
        )

    if candidate_status != MountStatus.MOUNTED:
        raise HTTPException(
            status_code=409,
            detail=sanitize_error_message(validation_error, "Mount validation failed"),
        )

    return NetworkMount(
        type=mount_data.type,
        remote_path=mount_data.remote_path,
        project_id=normalized_project_id,
        nfs_client_version=mount.nfs_client_version,
        local_mount_point=local_mount_point,
        status=candidate_status,
        last_checked_at=checked_at,
    )


def discover_mount_shares(
    discovery_data: MountShareDiscoveryRequest,
    db: Session,
    actor: Optional[str] = None,
    provider: Optional["MountProvider"] = None,
    client_ip: Optional[str] = None,
) -> MountShareDiscoveryResponse:
    audit_repo = AuditRepository(db)
    provider = provider or _default_provider()

    if settings.is_demo_mode_enabled():
        try:
            audit_repo.add(
                action="MOUNT_SHARE_DISCOVERY_FAILED",
                user=actor,
                details={
                    "type": discovery_data.type.value,
                    "reason": "demo_mode_disabled",
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for MOUNT_SHARE_DISCOVERY_FAILED")
        raise HTTPException(status_code=403, detail="Share browsing is unavailable in demo mode")

    discovery_target = _extract_share_discovery_target(discovery_data.type, discovery_data.remote_path)
    logger.info(
        "Mount share discovery started",
        extra={"context": {"type": discovery_data.type.value, "actor": actor or "system"}},
    )

    try:
        discovered_paths = provider.discover_shares(
            discovery_data.type,
            discovery_data.remote_path,
            credentials_file=discovery_data.credentials_file,
            username=discovery_data.username,
            password=discovery_data.password,
        )
    except FileNotFoundError as exc:
        logger.info(
            "Mount share discovery unavailable",
            extra={"context": {"type": discovery_data.type.value, "reason": "tool_unavailable"}},
        )
        logger.debug(
            "Mount share discovery unavailable details",
            extra={"context": {"type": discovery_data.type.value, "server": discovery_target, "raw_error": str(exc)}},
        )
        try:
            audit_repo.add(
                action="MOUNT_SHARE_DISCOVERY_FAILED",
                user=actor,
                details={
                    "type": discovery_data.type.value,
                    "reason": "tool_unavailable",
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for MOUNT_SHARE_DISCOVERY_FAILED")
        raise HTTPException(
            status_code=500,
            detail=_share_discovery_unavailable_detail(discovery_data.type),
        ) from exc
    except Exception as exc:
        logger.info(
            "Mount share discovery failed",
            extra={"context": {"type": discovery_data.type.value, "reason": "discovery_failed"}},
        )
        logger.debug(
            "Mount share discovery failure details",
            extra={"context": {"type": discovery_data.type.value, "server": discovery_target, "raw_error": str(exc)}},
        )
        try:
            audit_repo.add(
                action="MOUNT_SHARE_DISCOVERY_FAILED",
                user=actor,
                details={
                    "type": discovery_data.type.value,
                    "reason": "discovery_failed",
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for MOUNT_SHARE_DISCOVERY_FAILED")
        raise HTTPException(
            status_code=409,
            detail="Share discovery failed. Review the server address or credentials and try again.",
        ) from exc

    normalized_paths = _normalize_discovered_share_paths(discovery_data.type, list(discovered_paths or []))
    shares = [
        MountShareDiscoveryItem(
            remote_path=remote_path,
            display_name=_discovered_share_display_name(discovery_data.type, remote_path),
        )
        for remote_path in normalized_paths
    ]

    try:
        audit_repo.add(
            action="MOUNT_SHARE_DISCOVERY_ATTEMPTED",
            user=actor,
            details={
                "type": discovery_data.type.value,
                "share_count": len(shares),
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for MOUNT_SHARE_DISCOVERY_ATTEMPTED")

    return MountShareDiscoveryResponse(shares=shares)


def add_mount(mount_data: MountCreate, db: Session, actor: Optional[str] = None,
              provider: Optional["MountProvider"] = None,
              client_ip: Optional[str] = None) -> NetworkMount:
    normalized_project_id = normalize_project_id(mount_data.project_id)
    if not isinstance(normalized_project_id, str) or not normalized_project_id:
        raise HTTPException(status_code=422, detail="project_id must not be empty")

    mount_repo = MountRepository(db)
    audit_repo = AuditRepository(db)
    provider = provider or _default_provider()

    try:
        mount_repo.acquire_create_lock()
        existing_mounts = mount_repo.list_all()
        _validate_remote_path_conflicts(
            mount_data.type,
            mount_data.remote_path,
            normalized_project_id,
            existing_mounts,
        )
    except (HTTPException, ConflictError) as exc:
        rejection_message = str(exc.detail) if isinstance(exc, HTTPException) else exc.message
        try:
            audit_repo.add(
                action="MOUNT_ADD_REJECTED_CONFLICT",
                user=actor,
                project_id=normalized_project_id,
                details={
                    "project_id": normalized_project_id,
                    "status": "REJECTED",
                    "message": rejection_message,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for MOUNT_ADD_REJECTED_CONFLICT")
        raise

    existing_mount_points = {str(m.local_mount_point) for m in existing_mounts}
    local_mount_point = _generate_local_mount_point(
        mount_data.type,
        mount_data.remote_path,
        existing_mount_points,
    )

    mount = NetworkMount(
        type=mount_data.type,
        remote_path=mount_data.remote_path,
        project_id=normalized_project_id,
        nfs_client_version=_stored_nfs_client_version(mount_data.type, mount_data.nfs_client_version),
        local_mount_point=local_mount_point,
        status=MountStatus.UNMOUNTED,
    )
    try:
        mount_repo.add(mount)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A mount with this local_mount_point already exists",
        ) from exc
    except Exception as exc:
        if is_encoding_error(exc):
            raise EncodingError("Mount data contains invalid characters") from exc
        logger.error("DB commit failed while creating mount record")
        raise HTTPException(
            status_code=500,
            detail="Database error while creating mount record",
        )

    _apply_encrypted_mount_credentials(mount, mount_data, preserve_existing=False)

    _mount_error = None
    logger.info(
        "Mount attempt started: mount_id=%s type=%s mount_label=%s actor=%s",
        mount.id,
        mount_data.type.value,
        _redacted_mount_label(str(mount.local_mount_point)),
        actor or "system",
    )
    try:
        create_dir_error = _ensure_mount_directory(mount.local_mount_point)
        if create_dir_error:
            logger.warning(
                "Mountpoint preparation failed: mount_id=%s type=%s mount_label=%s actor=%s reason=%s",
                mount.id,
                mount_data.type.value,
                _redacted_mount_label(str(mount.local_mount_point)),
                actor or "system",
                sanitize_error_message(create_dir_error, "Mountpoint preparation failed"),
            )
            _log_mount_debug_failure(
                "Mountpoint preparation raw error",
                mount_type=mount_data.type,
                remote_path=mount_data.remote_path,
                local_mount_point=str(mount.local_mount_point),
                raw_error=create_dir_error,
            )
            success, error = False, create_dir_error
        else:
            owner_error = _validate_mount_directory_owner(mount.local_mount_point)
            if owner_error:
                _log_mount_debug_failure(
                    "Mountpoint ownership raw error",
                    mount_type=mount_data.type,
                    remote_path=mount_data.remote_path,
                    local_mount_point=str(mount.local_mount_point),
                    raw_error=owner_error,
                )
                success, error = False, owner_error
            else:
                resolved_credentials = _resolve_mount_operation_credentials(mount, mount_data)
                success, error = provider.os_mount(
                    mount_data.type,
                    mount_data.remote_path,
                    mount.local_mount_point,
                    credentials_file=resolved_credentials["credentials_file"],
                    username=resolved_credentials["username"],
                    password=resolved_credentials["password"],
                    nfs_client_version=mount.nfs_client_version,
                )
        if success:
            mount.status = MountStatus.MOUNTED
            logger.info(
                "Mount attempt succeeded: mount_id=%s type=%s mount_label=%s actor=%s",
                mount.id,
                mount_data.type.value,
                _redacted_mount_label(str(mount.local_mount_point)),
                actor or "system",
            )
        else:
            mount.status = MountStatus.ERROR
            _mount_error = error
            logger.info(
                "Mount attempt failed: mount_id=%s type=%s mount_label=%s actor=%s failure_category=%s reason=%s",
                mount.id,
                mount_data.type.value,
                _redacted_mount_label(str(mount.local_mount_point)),
                actor or "system",
                "mount_add",
                sanitize_error_message(_mount_error, "Mount command failed"),
            )
            logger.warning(
                "Mount attempt failed: mount_id=%s type=%s mount_label=%s actor=%s reason=%s",
                mount.id,
                mount_data.type.value,
                _redacted_mount_label(str(mount.local_mount_point)),
                actor or "system",
                sanitize_error_message(_mount_error, "Mount attempt failed"),
            )
        try:
            mount_repo.save(mount)
        except Exception:
            logger.exception(
                "DB commit failed while updating mount status after OS mount for mount %s",
                mount.id,
            )
            # At this point the OS mount may have succeeded but the database did not
            # reflect the new status. Surface this as a server error rather than
            # returning an inconsistent mount object to the caller.
            raise HTTPException(
                status_code=500,
                detail="Database error while updating mount status after OS mount; mount may be active at OS level.",
            )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            # Re-raise HTTPExceptions so that intended HTTP error responses are not swallowed
            raise
        mount.status = MountStatus.ERROR
        try:
            mount_repo.save(mount)
        except Exception:
            logger.exception(
                "DB commit failed while recording mount error for mount %s",
                mount.id,
            )
        _mount_error = str(exc)
        logger.exception(
            "Mount attempt raised exception: mount_id=%s type=%s mount_label=%s actor=%s",
            mount.id,
            mount_data.type.value,
            _redacted_mount_label(str(mount.local_mount_point)),
            actor or "system",
        )

    try:
        audit_repo.add(
            action="MOUNT_ADDED",
            user=actor,
            project_id=mount.project_id,
            details={
                "mount_id": mount.id,
                "project_id": mount.project_id,
                "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                "status": mount.status.value,
                "error_code": "MOUNT_FAILED" if _mount_error else None,
                "message": "Provider mount operation failed" if _mount_error else None,
                "details": sanitize_error_message(_mount_error, "Mount provider reported failure") if _mount_error else None,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for MOUNT_ADDED")
    return mount


def update_mount(mount_id: int, mount_data: MountUpdate, db: Session, actor: Optional[str] = None,
                 provider: Optional["MountProvider"] = None,
                 client_ip: Optional[str] = None) -> NetworkMount:
    normalized_project_id = normalize_project_id(mount_data.project_id)
    if not isinstance(normalized_project_id, str) or not normalized_project_id:
        raise HTTPException(status_code=422, detail="project_id must not be empty")

    mount_repo = MountRepository(db)
    audit_repo = AuditRepository(db)
    provider = provider or _default_provider()

    mount = mount_repo.get(mount_id)
    if not mount:
        raise HTTPException(status_code=404, detail="Mount not found")

    mount_label = _redacted_mount_label(str(mount.local_mount_point))
    changed_fields = _changed_mount_fields(
        mount,
        mount_data,
        normalized_project_id=normalized_project_id,
    )
    mount.nfs_client_version = _stored_nfs_client_version(mount_data.type, mount_data.nfs_client_version)

    try:
        mount_repo.acquire_create_lock()
        _validate_remote_path_conflicts(
            mount_data.type,
            mount_data.remote_path,
            normalized_project_id,
            mount_repo.list_all(),
            ignore_mount_id=mount_id,
        )
    except (HTTPException, ConflictError):
        raise

    mount.type = mount_data.type
    mount.remote_path = mount_data.remote_path
    mount.project_id = normalized_project_id
    mount.last_checked_at = datetime.now(timezone.utc)
    _apply_encrypted_mount_credentials(mount, mount_data, preserve_existing=True)

    _mount_error = None
    logger.info(
        "Mount update started",
        extra={
            "context": {
                "mount_id": mount.id,
                "type": mount_data.type.value,
                "mount_label": mount_label,
                "actor": actor or "system",
            }
        },
    )
    try:
        _prepare_mount_for_update(mount, provider=provider)

        create_dir_error = _ensure_mount_directory(mount.local_mount_point)
        if create_dir_error:
            logger.warning(
                "Mountpoint preparation failed during update",
                extra={
                    "context": {
                        "mount_id": mount.id,
                        "type": mount_data.type.value,
                        "mount_label": mount_label,
                        "actor": actor or "system",
                        "reason": sanitize_error_message(create_dir_error, "Mountpoint preparation failed"),
                        "failure_category": "mount_directory_prepare",
                    }
                },
            )
            _log_mount_debug_failure(
                "Mountpoint preparation raw error",
                mount_type=mount_data.type,
                remote_path=mount_data.remote_path,
                local_mount_point=str(mount.local_mount_point),
                raw_error=create_dir_error,
            )
            success, error = False, create_dir_error
        else:
            owner_error = _validate_mount_directory_owner(mount.local_mount_point)
            if owner_error:
                _log_mount_debug_failure(
                    "Mountpoint ownership raw error",
                    mount_type=mount_data.type,
                    remote_path=mount_data.remote_path,
                    local_mount_point=str(mount.local_mount_point),
                    raw_error=owner_error,
                )
                success, error = False, owner_error
            else:
                resolved_credentials = _resolve_mount_operation_credentials(mount, mount_data)
                success, error = provider.os_mount(
                    mount_data.type,
                    mount_data.remote_path,
                    mount.local_mount_point,
                    credentials_file=resolved_credentials["credentials_file"],
                    username=resolved_credentials["username"],
                    password=resolved_credentials["password"],
                    nfs_client_version=mount.nfs_client_version,
                )

        if success:
            mount.status = MountStatus.MOUNTED
            logger.info(
                "Mount update succeeded",
                extra={
                    "context": {
                        "mount_id": mount.id,
                        "type": mount_data.type.value,
                        "mount_label": mount_label,
                        "actor": actor or "system",
                    }
                },
            )
        else:
            mount.status = MountStatus.ERROR
            _mount_error = error
            logger.warning(
                "Mount update failed",
                extra={
                    "context": {
                        "mount_id": mount.id,
                        "type": mount_data.type.value,
                        "mount_label": mount_label,
                        "actor": actor or "system",
                        "reason": sanitize_error_message(_mount_error, "Mount update failed"),
                        "failure_category": "mount_update",
                    }
                },
            )

        try:
            mount_repo.save(mount)
        except Exception:
            logger.exception(
                "DB commit failed while updating mount record after mount update",
                extra={
                    "context": {
                        "mount_id": mount.id,
                        "mount_label": mount_label,
                        "failure_category": "mount_update_persist",
                    }
                },
            )
            raise HTTPException(
                status_code=500,
                detail="Database error while updating mount record after mount attempt; mount may be active at OS level.",
            )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        mount.status = MountStatus.ERROR
        try:
            mount_repo.save(mount)
        except Exception:
            logger.exception(
                "DB commit failed while recording mount update error",
                extra={
                    "context": {
                        "mount_id": mount.id,
                        "mount_label": mount_label,
                        "failure_category": "mount_update_error_record",
                    }
                },
            )
        _mount_error = str(exc)
        logger.exception(
            "Mount update raised exception",
            extra={
                "context": {
                    "mount_id": mount.id,
                    "type": mount_data.type.value,
                    "mount_label": mount_label,
                    "actor": actor or "system",
                    "failure_category": "mount_update_exception",
                }
            },
        )

    try:
        audit_repo.add(
            action="MOUNT_UPDATED",
            user=actor,
            project_id=mount.project_id,
            details={
                "mount_id": mount.id,
                "mount_label": mount_label,
                "status": mount.status.value,
                "changed_fields": changed_fields,
                "error_code": "MOUNT_FAILED" if _mount_error else None,
                "message": "Provider mount operation failed" if _mount_error else None,
                "details": sanitize_error_message(_mount_error, "Mount provider reported failure") if _mount_error else None,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for MOUNT_UPDATED")

    return mount


def remove_mount(mount_id: int, db: Session, actor: Optional[str] = None,
                 provider: Optional["MountProvider"] = None,
                 client_ip: Optional[str] = None) -> None:
    mount_repo = MountRepository(db)
    audit_repo = AuditRepository(db)

    mount = mount_repo.get(mount_id)
    if not mount:
        raise HTTPException(status_code=404, detail="Mount not found")

    provider = provider or _default_provider()
    local_mount_point = str(mount.local_mount_point)
    should_attempt_unmount = mount.status == MountStatus.MOUNTED and bool(local_mount_point)

    if not should_attempt_unmount:
        logger.info(
            "Skipping OS unmount for non-mounted record removal: mount_id=%s mount_label=%s status=%s",
            mount_id,
            _redacted_mount_label(local_mount_point),
            mount.status.value,
        )

    if should_attempt_unmount:
        try:
            unmount_ok, unmount_error = provider.os_unmount(local_mount_point)
        except Exception as exc:
            unmount_ok, unmount_error = False, str(exc)

        if not unmount_ok:
            error_text = unmount_error or "umount failed"
            lowered_error = error_text.lower()
            if any(phrase in lowered_error for phrase in ("not mounted", "no mount point")):
                logger.info(
                    "Treating already-unmounted mount removal as success: mount_id=%s mount_label=%s reason=%s",
                    mount_id,
                    _redacted_mount_label(local_mount_point),
                    sanitize_error_message(error_text, "Target was already unmounted"),
                )
            else:
                logger.warning(
                    "Mount removal aborted because unmount failed: mount_id=%s mount_label=%s reason=%s",
                    mount_id,
                    _redacted_mount_label(local_mount_point),
                    sanitize_error_message(error_text, "Unmount failed"),
                )
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Failed to unmount {_redacted_mount_label(local_mount_point)}: "
                        f"{sanitize_error_message(error_text, 'Unmount failed')}"
                    ),
                )

    _cleanup_generated_mount_directory(local_mount_point)

    try:
        audit_repo.add(
            action="MOUNT_REMOVED",
            user=actor,
            details={"mount_id": mount_id, "mount_label": _redacted_mount_label(str(mount.local_mount_point))},
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for MOUNT_REMOVED")
    try:
        mount_repo.delete(mount)
    except Exception:
        logger.exception("DB commit failed while deleting mount record %s", mount_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while removing mount record",
        )


def _can_view_mount_paths(user_roles: Optional[list[str]]) -> bool:
    return any(role in _MOUNT_PATH_VIEWER_ROLES for role in (user_roles or []))


def _redact_mount_paths(mount: NetworkMount) -> NetworkMountSchema:
    return NetworkMountSchema.model_validate(mount).model_copy(
        update={
            "remote_path": _REDACTED_MOUNT_PATH_VALUE,
            "local_mount_point": _REDACTED_MOUNT_PATH_VALUE,
        }
    )


def list_mounts(db: Session, user_roles: Optional[list[str]] = None):
    mounts = MountRepository(db).list_all()
    if _can_view_mount_paths(user_roles):
        return mounts
    return [_redact_mount_paths(mount) for mount in mounts]


def validate_all_mounts(db: Session, actor: Optional[str] = None,
                        client_ip: Optional[str] = None) -> list[NetworkMount]:
    mount_repo = MountRepository(db)
    mounts = mount_repo.list_all()
    return [validate_mount(mount.id, db, actor=actor, client_ip=client_ip) for mount in mounts]


def validate_mount(mount_id: int, db: Session, actor: Optional[str] = None,
                   provider: Optional["MountProvider"] = None,
                   client_ip: Optional[str] = None,
                   mount_data: Optional[MountUpdate] = None) -> NetworkMount:
    mount_repo = MountRepository(db)
    audit_repo = AuditRepository(db)

    mount = mount_repo.get(mount_id)
    if not mount:
        raise HTTPException(status_code=404, detail="Mount not found")

    provider = provider or _default_provider()

    if mount_data is not None:
        normalized_project_id = normalize_project_id(mount_data.project_id)
        if not isinstance(normalized_project_id, str) or not normalized_project_id:
            raise HTTPException(status_code=422, detail="project_id must not be empty")

        mount_repo.acquire_create_lock()
        _validate_remote_path_conflicts(
            mount_data.type,
            mount_data.remote_path,
            normalized_project_id,
            mount_repo.list_all(),
            ignore_mount_id=mount_id,
        )

        checked_at = datetime.now(timezone.utc)
        original_status = mount.status
        original_mount_type = mount.type if isinstance(mount.type, MountType) else MountType(str(mount.type))
        original_remote_path = str(mount.remote_path)
        original_mount_state = check_mounted_with_configured_timeout(provider, str(mount.local_mount_point))
        original_was_mounted = original_mount_state is True or original_status == MountStatus.MOUNTED

        candidate_status = MountStatus.ERROR
        validation_error = None
        try:
            if original_was_mounted:
                _prepare_mount_for_update(mount, provider=provider)

            create_dir_error = _ensure_mount_directory(mount.local_mount_point)
            if create_dir_error:
                validation_error = create_dir_error
            else:
                owner_error = _validate_mount_directory_owner(mount.local_mount_point)
                if owner_error:
                    validation_error = owner_error
                else:
                    resolved_credentials = _resolve_mount_operation_credentials(mount, mount_data)
                    success, validation_error = provider.os_mount(
                        mount_data.type,
                        mount_data.remote_path,
                        mount.local_mount_point,
                        credentials_file=resolved_credentials["credentials_file"],
                        username=resolved_credentials["username"],
                        password=resolved_credentials["password"],
                        nfs_client_version=mount.nfs_client_version,
                    )
                    candidate_status = MountStatus.MOUNTED if success else MountStatus.ERROR
        finally:
            mount.status = original_status
            restore_error = _restore_mount_after_candidate_validation(
                mount,
                provider=provider,
                original_mount_type=original_mount_type,
                original_remote_path=original_remote_path,
                original_was_mounted=original_was_mounted,
            )

        if restore_error:
            logger.info(
                "Mount candidate validation could not restore original state",
                extra={
                    "context": {
                        "mount_id": mount.id,
                        "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                        "failure_category": "mount_validate_restore",
                    }
                },
            )
            logger.debug(
                "Mount candidate validation restore raw error",
                extra={
                    "context": {
                        "mount_id": mount.id,
                        "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                        "raw_error": restore_error,
                    }
                },
            )
            raise HTTPException(
                status_code=500,
                detail="Mount validation could not restore original mount state",
            )

        mount.last_checked_at = checked_at
        try:
            mount_repo.save(mount)
        except Exception:
            logger.exception(
                "DB commit failed while saving mount validation timestamp",
                extra={"context": {"mount_id": mount_id}},
            )
            raise HTTPException(
                status_code=500,
                detail="Database error while saving mount validation",
            )

        try:
            audit_repo.add(
                action="MOUNT_VALIDATED",
                user=actor,
                details={
                    "mount_id": mount_id,
                    "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                    "status": candidate_status.value,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception(
                "Failed to write audit log for MOUNT_VALIDATED",
                extra={"context": {"mount_id": mount_id}},
            )

        if candidate_status != MountStatus.MOUNTED:
            raise HTTPException(
                status_code=409,
                detail=sanitize_error_message(validation_error, "Mount validation failed"),
            )

        return NetworkMount(
            id=mount.id,
            type=mount_data.type,
            remote_path=mount_data.remote_path,
            project_id=normalized_project_id,
            nfs_client_version=mount.nfs_client_version,
            local_mount_point=mount.local_mount_point,
            status=candidate_status,
            last_checked_at=checked_at,
        )

    result = check_mounted_with_configured_timeout(provider, mount.local_mount_point)
    if result is True:
        mount.status = MountStatus.MOUNTED
    else:
        create_dir_error = _ensure_mount_directory(mount.local_mount_point)
        if create_dir_error:
            logger.warning(
                "Mountpoint preparation failed during validation: mount_id=%s type=%s mount_label=%s reason=%s",
                mount.id,
                mount.type.value,
                _redacted_mount_label(str(mount.local_mount_point)),
                sanitize_error_message(create_dir_error, "Mountpoint preparation failed"),
            )
            mount.status = MountStatus.ERROR
        else:
            owner_error = _validate_mount_directory_owner(mount.local_mount_point)
            if owner_error:
                logger.warning(
                    "Mountpoint ownership failed during validation: mount_id=%s type=%s mount_label=%s reason=%s",
                    mount.id,
                    mount.type.value,
                    _redacted_mount_label(str(mount.local_mount_point)),
                    sanitize_error_message(owner_error, "Mountpoint ownership failed"),
                )
                mount.status = MountStatus.ERROR
            else:
                stored_credentials = (
                    _load_stored_mount_credentials(mount)
                    if _stored_credentials_present(mount)
                    else {"username": None, "password": None, "credentials_file": None}
                )
                success, _mount_error = provider.os_mount(
                    mount.type,
                    mount.remote_path,
                    mount.local_mount_point,
                    credentials_file=stored_credentials["credentials_file"],
                    username=stored_credentials["username"],
                    password=stored_credentials["password"],
                    nfs_client_version=mount.nfs_client_version,
                )
                mount.status = MountStatus.MOUNTED if success else MountStatus.ERROR

    mount.last_checked_at = datetime.now(timezone.utc)
    try:
        mount = mount_repo.save(mount)
    except Exception:
        logger.exception("DB commit failed while saving mount validation for mount %s", mount_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while saving mount validation",
        )

    try:
        audit_repo.add(
            action="MOUNT_VALIDATED",
            user=actor,
            details={
                "mount_id": mount_id,
                "mount_label": _redacted_mount_label(str(mount.local_mount_point)),
                "status": mount.status.value,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for MOUNT_VALIDATED")
    return mount
