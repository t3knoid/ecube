from __future__ import annotations

import asyncio
import threading

import pytest

import app.infrastructure as infra_module
import app.main as main_module
from app.infrastructure.usb_event_monitor import LinuxUdevUsbEventMonitor, UsbEvent


class _BlockingUsbEventMonitor:
    def __init__(self):
        self._stop_event = threading.Event()

    def run(self, handler):
        handler(UsbEvent(action="add", device_path="/devices/pci0000:00/usb1/1-1", subsystem="block"))
        self._stop_event.wait()

    def stop(self):
        self._stop_event.set()


class _FailingUsbEventMonitor:
    def run(self, handler):
        raise RuntimeError("udevadm monitor failed to start")

    def stop(self):
        return None


def test_linux_udev_usb_event_monitor_parses_qualifying_events():
    event = LinuxUdevUsbEventMonitor._parse_event("UDEV  [123.456789] add      /devices/pci0000:00/usb1/1-1 (block)")

    assert event == UsbEvent(
        action="add",
        device_path="/devices/pci0000:00/usb1/1-1",
        subsystem="block",
    )
    assert LinuxUdevUsbEventMonitor._parse_event("ignored line") is None


@pytest.mark.asyncio
async def test_usb_discovery_event_loop_refreshes_on_udev_event(monkeypatch):
    observed_sources: list[str] = []
    observed_event = threading.Event()
    monitor = _BlockingUsbEventMonitor()

    monkeypatch.setattr(main_module.settings, "usb_discovery_interval", 0)

    def _record_sync(*, discovery_source: str) -> None:
        observed_sources.append(discovery_source)
        if discovery_source == "udev_event":
            observed_event.set()

    async def _unexpected_poll_loop():
        raise AssertionError("poll loop should not run while monitor is healthy")

    monkeypatch.setattr(infra_module, "get_usb_event_monitor", lambda: monitor)
    monkeypatch.setattr(main_module, "_usb_discovery_poll_loop", _unexpected_poll_loop)
    monkeypatch.setattr(main_module, "_run_usb_discovery_sync_once", _record_sync)

    task = asyncio.create_task(main_module._usb_discovery_event_loop())

    await asyncio.wait_for(asyncio.to_thread(observed_event.wait, 1.0), timeout=2.0)

    assert observed_sources == ["udev_startup", "udev_event"]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_usb_discovery_event_loop_does_not_fallback_to_polling_when_monitor_fails(monkeypatch):
    observed_sources: list[str] = []
    observed: list[str] = []

    monkeypatch.setattr(main_module.settings, "usb_discovery_interval", 0)

    monkeypatch.setattr(infra_module, "get_usb_event_monitor", lambda: _FailingUsbEventMonitor())
    monkeypatch.setattr(
        main_module,
        "_run_usb_discovery_sync_once",
        lambda *, discovery_source: observed_sources.append(discovery_source),
    )

    async def _fake_sleep(_seconds):
        observed.append("slept")
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await main_module._usb_discovery_event_loop()

    assert observed_sources == ["udev_startup"]
    assert observed == ["slept"]


@pytest.mark.asyncio
async def test_usb_discovery_event_loop_runs_baseline_sync_before_monitor_blocks(monkeypatch):
    observed_sources: list[str] = []
    monitor_started = threading.Event()
    release_monitor = threading.Event()

    monkeypatch.setattr(main_module.settings, "usb_discovery_interval", 0)

    class _WaitingMonitor:
        def run(self, handler):
            monitor_started.set()
            release_monitor.wait()

        def stop(self):
            release_monitor.set()

    monkeypatch.setattr(infra_module, "get_usb_event_monitor", lambda: _WaitingMonitor())
    monkeypatch.setattr(
        main_module,
        "_run_usb_discovery_sync_once",
        lambda *, discovery_source: observed_sources.append(discovery_source),
    )

    task = asyncio.create_task(main_module._usb_discovery_event_loop())

    await asyncio.wait_for(asyncio.to_thread(monitor_started.wait, 1.0), timeout=2.0)

    assert observed_sources == ["udev_startup"]
    assert monitor_started.is_set()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_usb_discovery_runtime_loop_selects_polling_mode(monkeypatch):
    observed: list[str] = []

    monkeypatch.setattr(main_module.settings, "usb_discovery_interval", 5)

    async def _fake_poll_loop():
        observed.append("polling")
        raise asyncio.CancelledError

    async def _unexpected_event_loop():
        raise AssertionError("event loop should not run when polling mode is selected")

    monkeypatch.setattr(main_module, "_usb_discovery_poll_loop", _fake_poll_loop)
    monkeypatch.setattr(main_module, "_usb_discovery_event_loop", _unexpected_event_loop)

    with pytest.raises(asyncio.CancelledError):
        await main_module._usb_discovery_runtime_loop()

    assert observed == ["polling"]


@pytest.mark.asyncio
async def test_usb_discovery_runtime_loop_selects_event_mode(monkeypatch):
    observed: list[str] = []

    monkeypatch.setattr(main_module.settings, "usb_discovery_interval", 0)

    async def _fake_event_loop():
        observed.append("udev")
        raise asyncio.CancelledError

    async def _unexpected_poll_loop():
        raise AssertionError("polling loop should not run when event mode is selected")

    monkeypatch.setattr(main_module, "_usb_discovery_event_loop", _fake_event_loop)
    monkeypatch.setattr(main_module, "_usb_discovery_poll_loop", _unexpected_poll_loop)

    with pytest.raises(asyncio.CancelledError):
        await main_module._usb_discovery_runtime_loop()

    assert observed == ["udev"]


@pytest.mark.asyncio
async def test_usb_discovery_runtime_loop_switches_from_event_mode_to_polling(monkeypatch):
    observed: list[str] = []

    monkeypatch.setattr(main_module.settings, "usb_discovery_interval", 0)

    async def _fake_event_loop():
        observed.append("udev")
        main_module.settings.usb_discovery_interval = 5

    async def _fake_poll_loop():
        observed.append("polling")
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module, "_usb_discovery_event_loop", _fake_event_loop)
    monkeypatch.setattr(main_module, "_usb_discovery_poll_loop", _fake_poll_loop)

    with pytest.raises(asyncio.CancelledError):
        await main_module._usb_discovery_runtime_loop()

    assert observed == ["udev", "polling"]


@pytest.mark.asyncio
async def test_usb_discovery_runtime_loop_switches_from_polling_to_event_mode(monkeypatch):
    observed: list[str] = []

    monkeypatch.setattr(main_module.settings, "usb_discovery_interval", 5)

    async def _fake_poll_loop():
        observed.append("polling")
        main_module.settings.usb_discovery_interval = 0

    async def _fake_event_loop():
        observed.append("udev")
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module, "_usb_discovery_poll_loop", _fake_poll_loop)
    monkeypatch.setattr(main_module, "_usb_discovery_event_loop", _fake_event_loop)

    with pytest.raises(asyncio.CancelledError):
        await main_module._usb_discovery_runtime_loop()

    assert observed == ["polling", "udev"]
