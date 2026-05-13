from pathlib import Path

import pytest

from app.services.copy_path_diagnostic import (
    _build_diagnostic_notes,
    _build_small_file_stress_sample_plan,
    run_copy_path_diagnostic,
)
from scripts.copy_path_diagnostic import _build_parser


def test_build_diagnostic_notes_flags_small_file_fsync_bottleneck():
    notes = _build_diagnostic_notes(
        share_read_mbps=65.0,
        drive_write_mbps=57.5,
        benchmark_effective_copy_mbps=30.0,
        end_to_end_copy_mbps=2.1,
        sample_file_count=12,
        sample_median_file_size_bytes=128 * 1024,
        sample_small_file_count=10,
        copy_file_fsync_enabled=True,
    )

    assert any("small-file heavy" in note for note in notes)
    assert any("copy_file_fsync_enabled is on" in note for note in notes)
    assert any("far below the isolated source and target measurements" in note for note in notes)


def test_run_copy_path_diagnostic_reports_metrics_and_cleans_up(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    (source_dir / "alpha.bin").write_bytes(b"a" * 1024)
    nested = source_dir / "nested"
    nested.mkdir()
    (nested / "bravo.bin").write_bytes(b"b" * 2048)

    result = run_copy_path_diagnostic(
        str(source_dir),
        str(target_dir),
        benchmark_bytes=2048,
    )

    assert result.source_path == str(source_dir)
    assert result.target_path == str(target_dir)
    assert result.sample_mode == "balanced"
    assert result.source_file_count == 2
    assert result.source_total_bytes == 3072
    assert result.benchmark_requested_bytes == 2048
    assert result.benchmark_measured_bytes > 0
    assert result.sample_file_count >= 1
    assert result.sample_copied_bytes >= result.benchmark_requested_bytes
    assert result.sample_copy_elapsed_seconds >= 0.0
    assert result.sample_copy_files_per_second is not None
    assert result.share_read_mbps is not None
    assert result.drive_write_mbps is not None
    assert result.end_to_end_copy_mbps is not None
    assert not list(target_dir.glob(".copy-path-diagnostic-*"))


def test_build_small_file_stress_sample_plan_prefers_smallest_files(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    tiny = source_dir / "tiny.bin"
    tiny.write_bytes(b"a" * 16)
    small = source_dir / "small.bin"
    small.write_bytes(b"b" * 64)
    medium = source_dir / "medium.bin"
    medium.write_bytes(b"c" * 256)
    large = source_dir / "large.bin"
    large.write_bytes(b"d" * 1024)

    sample_plan = _build_small_file_stress_sample_plan(
        [large, medium, small, tiny],
        max_sample_file_count=3,
    )

    assert [file_path.name for file_path, _size in sample_plan] == ["tiny.bin", "small.bin", "medium.bin"]


def test_run_copy_path_diagnostic_small_file_stress_mode_uses_requested_file_count(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    for index, size_bytes in enumerate((32, 48, 64, 80, 96), start=1):
        (source_dir / f"file{index}.bin").write_bytes(b"x" * size_bytes)

    result = run_copy_path_diagnostic(
        str(source_dir),
        str(target_dir),
        sample_mode="small-file-stress",
        small_file_stress_sample_file_count=3,
    )

    assert result.sample_mode == "small-file-stress"
    assert result.sample_file_count == 3
    assert result.sample_small_file_count == 3
    assert result.sample_copied_bytes == 32 + 48 + 64
    assert result.sample_copy_files_per_second is not None


def test_copy_path_diagnostic_parser_rejects_nonpositive_numeric_flags():
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["/mnt/share", "/mnt/ecube/1", "--benchmark-bytes", "0"])

    with pytest.raises(SystemExit):
        parser.parse_args(["/mnt/share", "/mnt/ecube/1", "--sample-file-count", "-1"])


def test_copy_path_diagnostic_parser_preserves_explicit_sample_file_count():
    parser = _build_parser()

    args = parser.parse_args(["/mnt/share", "/mnt/ecube/1", "--sample-file-count", "1"])

    assert args.sample_file_count == 1