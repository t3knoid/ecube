from pathlib import Path

from scripts import generate_dbml_schema


def test_dbml_check_succeeds_when_output_is_current(tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "schema.dbml"
    output_path.write_text("EXPECTED\n", encoding="utf-8")
    monkeypatch.setattr(generate_dbml_schema, "generate_dbml", lambda: "EXPECTED\n")

    exit_code = generate_dbml_schema.main(["--check", "--output", str(output_path)])

    assert exit_code == 0
    assert f"DBML is up to date: {output_path}" in capsys.readouterr().out


def test_dbml_check_fails_when_output_is_stale(tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "schema.dbml"
    output_path.write_text("OLD\n", encoding="utf-8")
    monkeypatch.setattr(generate_dbml_schema, "generate_dbml", lambda: "NEW\n")

    exit_code = generate_dbml_schema.main(["--check", "--output", str(output_path)])

    assert exit_code == 1
    captured = capsys.readouterr().out
    assert f"ERROR: {output_path} is out of date." in captured
    assert "python3 scripts/generate_dbml_schema.py" in captured


def test_dbml_generate_writes_output(tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "schema.dbml"
    monkeypatch.setattr(generate_dbml_schema, "generate_dbml", lambda: "GENERATED\n")

    exit_code = generate_dbml_schema.main(["--output", str(output_path)])

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8") == "GENERATED\n"
    assert f"Wrote DBML to {output_path}" in capsys.readouterr().out