"""USB hotplug event monitoring infrastructure.

The Linux implementation subscribes to ``udevadm monitor`` for block and USB
events and forwards qualifying add/remove/change notifications to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import subprocess
import threading
from collections.abc import Callable
from typing import Any, Protocol

from app.infrastructure.subprocess_runner import open_subprocess, resolve_binary

logger = logging.getLogger(__name__)

_UDEV_EVENT_RE = re.compile(
    r"^(?:UDEV|KERNEL)\s+\[[^\]]+\]\s+(add|remove|change)\s+(.+?)\s+\(([^)]+)\)$"
)


@dataclass(frozen=True)
class UsbEvent:
    """Qualifying USB or block-device hotplug event."""

    action: str
    device_path: str
    subsystem: str


UsbEventHandler = Callable[[UsbEvent], None]


class UsbEventMonitor(Protocol):
    """Stream qualifying hardware events until stopped."""

    def run(self, handler: UsbEventHandler) -> None:
        """Start the monitor and invoke *handler* for qualifying events."""

    def stop(self) -> None:
        """Request that a running monitor exit promptly."""


class LinuxUdevUsbEventMonitor:
    """Monitor USB and block hotplug events with ``udevadm monitor``."""

    def __init__(
        self,
        *,
        udevadm_path: str | None = None,
        process_factory: Callable[..., subprocess.Popen[Any]] | None = None,
    ) -> None:
        self._udevadm_path = udevadm_path or resolve_binary(("udevadm",))
        if not self._udevadm_path:
            raise RuntimeError("udevadm is not available")
        self._process_factory = process_factory or open_subprocess
        self._process: subprocess.Popen[Any] | None = None
        self._lock = threading.Lock()
        self._stop_requested = threading.Event()

    def run(self, handler: UsbEventHandler) -> None:
        command = [
            self._udevadm_path,
            "monitor",
            "--udev",
            "--subsystem-match=usb",
            "--subsystem-match=block",
        ]
        try:
            process = self._process_factory(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise RuntimeError("udevadm monitor could not be started") from exc

        with self._lock:
            self._process = process

        if process.stdout is None:
            self.stop()
            raise RuntimeError("udevadm monitor did not expose stdout")

        try:
            for raw_line in process.stdout:
                if self._stop_requested.is_set():
                    break
                event = self._parse_event(raw_line)
                if event is None:
                    continue
                handler(event)

            if not self._stop_requested.is_set():
                return_code = process.poll()
                if return_code is None:
                    return_code = process.wait()
                if return_code not in (0, None):
                    raise RuntimeError("udevadm monitor exited unexpectedly")
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop_requested.set()
        with self._lock:
            process = self._process
            self._process = None

        if process is None:
            return

        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except Exception:
                logger.debug("udevadm monitor termination required escalation", exc_info=True)
                try:
                    process.kill()
                    process.wait(timeout=1)
                except Exception:
                    logger.debug("udevadm monitor kill path failed", exc_info=True)

    @staticmethod
    def _parse_event(raw_line: str) -> UsbEvent | None:
        line = raw_line.strip()
        if not line:
            return None

        match = _UDEV_EVENT_RE.match(line)
        if match is None:
            return None

        action, device_path, subsystem = match.groups()
        if subsystem not in {"usb", "block"}:
            return None

        return UsbEvent(action=action, device_path=device_path, subsystem=subsystem)
