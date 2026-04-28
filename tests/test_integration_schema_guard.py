from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_integration_conftest_module():
    module_path = Path(__file__).resolve().parent / "integration" / "conftest.py"
    spec = importlib.util.spec_from_file_location("tests_integration_conftest", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_describe_integration_schema_drift_reports_rebuild_message(monkeypatch):
    integration_conftest = _load_integration_conftest_module()

    class FakeInspector:
        def get_table_names(self):
            return ["alembic_version", "export_jobs"]

        def get_columns(self, table_name):
            if table_name == "export_jobs":
                return [{"name": name} for name in [
                    "id",
                    "project_id",
                    "evidence_number",
                    "source_path",
                    "target_mount_path",
                    "status",
                    "total_bytes",
                    "copied_bytes",
                    "file_count",
                    "thread_count",
                    "max_file_retries",
                    "retry_delay_seconds",
                    "active_duration_seconds",
                    "started_at",
                    "completed_at",
                    "created_by",
                    "started_by",
                    "client_ip",
                    "callback_url",
                    "failure_reason",
                    "created_at",
                ]]
            return []

    monkeypatch.setattr(integration_conftest, "inspect", lambda bind: FakeInspector())
    monkeypatch.setattr(integration_conftest, "_get_integration_alembic_revision", lambda bind, tables: "0001")

    message = integration_conftest._describe_integration_schema_drift(object())

    assert message is not None
    assert "Rebuild the integration DB" in message
    assert "Current alembic_version: 0001" in message
    assert "export_jobs.startup_analysis_status" in message


def test_describe_integration_schema_drift_returns_none_when_schema_matches(monkeypatch):
    integration_conftest = _load_integration_conftest_module()
    metadata_columns = {
        table.name: [{"name": column.name} for column in table.columns]
        for table in integration_conftest.Base.metadata.sorted_tables
    }

    class FakeInspector:
        def get_table_names(self):
            return ["alembic_version", *metadata_columns.keys()]

        def get_columns(self, table_name):
            return metadata_columns[table_name]

    monkeypatch.setattr(integration_conftest, "inspect", lambda bind: FakeInspector())
    monkeypatch.setattr(integration_conftest, "_get_integration_alembic_revision", lambda bind, tables: "0001")

    message = integration_conftest._describe_integration_schema_drift(object())

    assert message is None