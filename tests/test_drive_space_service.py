from types import SimpleNamespace

from app.exceptions import ConflictError
from app.models.hardware import DriveState, UsbDrive
from app.repositories.drive_repository import DriveRepository
from app.services import drive_space_service


class _ImmediateExecutor:
    def submit(self, func, *args, **kwargs):
        func(*args, **kwargs)
        return SimpleNamespace(result=lambda timeout=None: None)


class _Probe:
    def __init__(self, available_bytes):
        self.available_bytes = available_bytes
        self.paths = []

    def probe_available_bytes(self, mount_path: str):
        self.paths.append(mount_path)
        return self.available_bytes


def test_request_available_space_refresh_updates_persisted_value(db, monkeypatch):
    drive = UsbDrive(
        device_identifier="USB-SPACE-001",
        current_state=DriveState.IN_USE,
        mount_path="/mnt/ecube/space-001",
        available_bytes=None,
    )
    db.add(drive)
    db.commit()

    probe = _Probe(available_bytes=8192)

    monkeypatch.setattr(drive_space_service, "_get_executor", lambda: _ImmediateExecutor())

    drive_space_service.request_available_space_refresh(drive.id, probe=probe)

    db.refresh(drive)
    assert probe.paths == ["/mnt/ecube/space-001"]
    assert drive.available_bytes == 8192


def test_request_available_space_refresh_skips_unmounted_drive(db, monkeypatch):
    drive = UsbDrive(
        device_identifier="USB-SPACE-002",
        current_state=DriveState.AVAILABLE,
        mount_path=None,
        available_bytes=1024,
    )
    db.add(drive)
    db.commit()

    probe = _Probe(available_bytes=2048)

    monkeypatch.setattr(drive_space_service, "_get_executor", lambda: _ImmediateExecutor())

    drive_space_service.request_available_space_refresh_for_drive(drive, probe=probe)

    db.refresh(drive)
    assert probe.paths == []
    assert drive.available_bytes == 1024


def test_request_available_space_refresh_runs_inline_for_sqlite(db, monkeypatch):
    drive = UsbDrive(
        device_identifier="SPACE-SQLITE-1",
        current_state=DriveState.IN_USE,
        mount_path="/mnt/sqlite-drive",
        available_bytes=None,
    )
    db.add(drive)
    db.commit()

    probe = _Probe(available_bytes=4096)

    def _unexpected_executor():
        raise AssertionError("executor should not be used for sqlite refresh")

    monkeypatch.setattr(drive_space_service, "_get_executor", _unexpected_executor)

    drive_space_service.request_available_space_refresh(drive.id, probe=probe)

    db.refresh(drive)
    assert probe.paths == ["/mnt/sqlite-drive"]
    assert drive.available_bytes == 4096


def test_request_available_space_refresh_skips_lock_conflict_without_exception_trace(db, monkeypatch, caplog):
    drive = UsbDrive(
        device_identifier="SPACE-CONFLICT-1",
        current_state=DriveState.IN_USE,
        mount_path="/mnt/conflict-drive",
        available_bytes=1024,
    )
    db.add(drive)
    db.commit()

    def _raise_conflict(self, drive_id: int):
        raise ConflictError("Drive is currently locked by another operation.")

    monkeypatch.setattr(DriveRepository, "get_for_update", _raise_conflict)

    with caplog.at_level("DEBUG"):
        drive_space_service._refresh_available_space_sync(drive.id, probe=_Probe(available_bytes=2048))

    assert any(
        record.getMessage() == "Drive available-space refresh skipped"
        and getattr(record, "failure_class", None) == "available_space_refresh_conflict"
        for record in caplog.records
    )
    assert any(
        record.getMessage() == "Drive available-space refresh conflict diagnostics"
        and getattr(record, "raw_error", None) == "Drive is currently locked by another operation."
        for record in caplog.records
    )
    assert not any(
        record.getMessage() == "Drive available-space refresh task raised an unexpected exception"
        for record in caplog.records
    )