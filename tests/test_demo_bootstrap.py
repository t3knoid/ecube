from pathlib import Path

import pytest

from app import demo_bootstrap


def test_activate_install_root_uses_module_parent(monkeypatch, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    fake_file = app_dir / "demo_bootstrap.py"
    fake_file.write_text("# test module path\n", encoding="utf-8")

    monkeypatch.setattr(demo_bootstrap, "__file__", str(fake_file))
    monkeypatch.chdir("/")

    root = demo_bootstrap.activate_install_root()

    assert Path.cwd() == tmp_path.resolve()
    assert root == tmp_path.resolve()


def test_build_parser_rejects_removed_legacy_usb_seed_flags():
    """Removed USB seeding flags must stay rejected by the simplified CLI."""
    parser = demo_bootstrap.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([
            "seed",
            "--shared-password", "demo",
            "--seed-connected-usb",
            "--usb-project-id", "DEMO-CASE-001",
        ])


def test_main_reports_missing_schema_before_seed(monkeypatch, capsys):
    class _FakeSession:
        def close(self):
            return None

    monkeypatch.setattr(demo_bootstrap, "activate_install_root", lambda: Path("/tmp"))

    import app.database as database

    monkeypatch.setattr(database, "is_database_configured", lambda: True)
    monkeypatch.setattr(database, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(demo_bootstrap, "_missing_required_tables", lambda _db: ["export_jobs"])

    rc = demo_bootstrap.main(["seed", "--shared-password", "demo"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "Database schema is not initialized" in captured.err
    assert "export_jobs" in captured.err
