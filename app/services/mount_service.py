import logging
import subprocess
import shutil
import os
import posixpath
import re
import pwd
import grp
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.network import MountStatus, MountType, NetworkMount
from app.repositories.audit_repository import AuditRepository
from app.repositories.mount_repository import MountRepository
from app.schemas.network import MountCreate
from app.config import settings
from app.exceptions import ConflictError, EncodingError
from app.services.mount_check_utils import check_mounted_with_configured_timeout

from app.utils.sanitize import is_encoding_error, normalize_project_id, sanitize_error_message

# Re-export so existing ``mount_service.MountProvider`` access keeps working.
from app.infrastructure.mount_protocol import MountProvider  # noqa: F401 – re-export


def _default_provider() -> "MountProvider":
    """Lazy import to avoid circular dependency at module level."""
    from app.infrastructure import get_mount_provider
    return get_mount_provider()

logger = logging.getLogger(__name__)


class LinuxMountProvider:
    """Linux implementation using ``mount(8)``, ``umount(8)``, and ``mountpoint(1)``."""

    def os_mount(self, mount_type: MountType, remote_path: str, local_mount_point: str,
                 *, credentials_file: Optional[str] = None, username: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        if mount_type == MountType.NFS:
            cmd = [settings.mount_binary_path, "-t", "nfs", remote_path, local_mount_point]
        else:
            cmd = [settings.mount_binary_path, "-t", "cifs", remote_path, local_mount_point]
            if credentials_file:
                cmd += ["-o", f"credentials={credentials_file}"]
            elif username:
                cmd += ["-o", f"username={username}"]

        cmd = _with_host_mount_namespace(cmd)
        mount_label = _redacted_mount_label(local_mount_point)
        logger.info("Executing mount command: type=%s mount_label=%s", mount_type.value, mount_label)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.subprocess_timeout_seconds)
        if result.returncode == 0:
            mounted = self.check_mounted(local_mount_point)
            if mounted is True:
                return True, None
            error = "mount command reported success but mountpoint is not active"
            logger.warning("Mount command verification failed for mount_label=%s", mount_label)
            return False, error

        error = (result.stderr or result.stdout or "").strip() or "mount failed"
        logger.warning(
            "Mount command failed: type=%s mount_label=%s returncode=%s reason=%s",
            mount_type.value,
            mount_label,
            result.returncode,
            sanitize_error_message(error, "Mount command failed"),
        )

        # Some environments have /etc/fstab entries for the target path with options
        # that conflict with on-demand API mounts.
        if "failed to apply fstab options" in error.lower():
            retry_error = error

            # On some hosts, mount(8) continues to apply local policies for NFS
            # paths. Try mount.nfs directly to bypass mount(8) option handling.
            if mount_type == MountType.NFS:
                nfs_bin = _resolve_mount_nfs_binary()
                if nfs_bin:
                    direct_cmd = [nfs_bin, remote_path, local_mount_point]
                    direct_cmd = _with_host_mount_namespace(direct_cmd)
                    logger.info("Retrying direct NFS helper for mount_label=%s", mount_label)
                    direct_result = subprocess.run(
                        direct_cmd,
                        capture_output=True,
                        text=True,
                        timeout=settings.subprocess_timeout_seconds,
                    )
                    if direct_result.returncode == 0:
                        logger.info("Direct NFS helper mount succeeded for mount_label=%s", mount_label)
                        return True, None
                    direct_error = (direct_result.stderr or direct_result.stdout or "").strip() or "mount failed"
                    logger.warning(
                        "Direct NFS helper mount failed: mount_label=%s returncode=%s reason=%s",
                        mount_label,
                        direct_result.returncode,
                        sanitize_error_message(direct_error, "Direct NFS helper mount failed"),
                    )
                    retry_error = direct_error

            # If command flow reports failure but mountpoint is active, treat as success.
            mounted = self.check_mounted(local_mount_point)
            if mounted is True:
                logger.warning(
                    "Mount commands reported failure but the target is active; treating as mounted for mount_label=%s",
                    mount_label,
                )
                return True, None

            return False, retry_error

        return False, error

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
                return False, error
            logger.info("Unmount command succeeded for mount_label=%s", mount_label)
            return True, None
        except Exception as exc:
            logger.warning(
                "Unmount command raised exception for mount_label=%s reason=%s",
                _redacted_mount_label(local_mount_point),
                sanitize_error_message(exc, "Unmount command failed"),
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
    try:
        current_ns = os.readlink("/proc/self/ns/mnt")
    except Exception:
        # If we cannot read our own namespace, keep existing behavior.
        return True

    try:
        host_ns = os.readlink("/proc/1/ns/mnt")
    except Exception:
        # If host namespace cannot be read (for example hidepid restrictions),
        # force host-namespace command path via nsenter.
        logger.warning("Unable to read host mount namespace; assuming namespace differs")
        return False

    return current_ns == host_ns


def _with_host_mount_namespace(cmd: list[str]) -> list[str]:
    if _in_host_mount_namespace():
        return _with_sudo(cmd)

    ns_flag_cmd = _with_mount_namespace_flag(cmd)
    if ns_flag_cmd is not None:
        return _with_sudo(ns_flag_cmd)

    nsenter = shutil.which("nsenter")
    if not nsenter:
        logger.warning("Mount namespace differs from host but nsenter is unavailable; using current namespace")
        return _with_sudo(cmd)

    if os.geteuid() != 0:
        if not settings.use_sudo:
            logger.warning("Mount namespace differs from host but sudo is disabled; using current namespace")
            return cmd
        return ["sudo", "-n", nsenter, "-t", "1", "-m", *cmd]

    return [nsenter, "-t", "1", "-m", *cmd]


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
) -> None:
    candidate_type, candidate_host, candidate_path = _normalize_remote_reference(mount_type, remote_path)

    for existing in existing_mounts:
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
            success, error = False, create_dir_error
        else:
            owner_error = _validate_mount_directory_owner(mount.local_mount_point)
            if owner_error:
                success, error = False, owner_error
            else:
                success, error = provider.os_mount(
                    mount_data.type,
                    mount_data.remote_path,
                    mount.local_mount_point,
                    credentials_file=mount_data.credentials_file,
                    username=mount_data.username,
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


def list_mounts(db: Session):
    return MountRepository(db).list_all()


def validate_all_mounts(db: Session, actor: Optional[str] = None,
                        client_ip: Optional[str] = None) -> list[NetworkMount]:
    mount_repo = MountRepository(db)
    mounts = mount_repo.list_all()
    return [validate_mount(mount.id, db, actor=actor, client_ip=client_ip) for mount in mounts]


def validate_mount(mount_id: int, db: Session, actor: Optional[str] = None,
                   provider: Optional["MountProvider"] = None,
                   client_ip: Optional[str] = None) -> NetworkMount:
    mount_repo = MountRepository(db)
    audit_repo = AuditRepository(db)

    mount = mount_repo.get(mount_id)
    if not mount:
        raise HTTPException(status_code=404, detail="Mount not found")

    provider = provider or _default_provider()
    result = check_mounted_with_configured_timeout(provider, mount.local_mount_point)
    if result is True:
        mount.status = MountStatus.MOUNTED
    elif result is False:
        mount.status = MountStatus.UNMOUNTED
    else:
        mount.status = MountStatus.ERROR

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
