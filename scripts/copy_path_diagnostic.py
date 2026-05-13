from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.copy_path_diagnostic import run_copy_path_diagnostic


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an ECUBE real-world copy-path diagnostic from a source path to a mounted target path.",
    )
    parser.add_argument("source_path", help="Mounted source path, for example an NFS mount directory")
    parser.add_argument("target_path", help="Mounted target path, for example a USB mount directory")
    parser.add_argument(
        "--sample-mode",
        choices=["balanced", "small-file-stress"],
        default="balanced",
        help="Choose a balanced byte-budget sample or a many-small-files stress sample.",
    )
    parser.add_argument(
        "--benchmark-bytes",
        type=int,
        default=None,
        help="Sample-budget cap in bytes. Defaults to ECUBE startup-analysis benchmark size.",
    )
    parser.add_argument(
        "--sample-file-count",
        type=int,
        default=None,
        help="When --sample-mode=small-file-stress, copy up to this many smallest files. Defaults to the service default.",
    )
    parser.add_argument(
        "--keep-sample",
        action="store_true",
        help="Keep the copied diagnostic sample directory on the target instead of removing it.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the result as JSON instead of a human-readable summary.",
    )
    return parser


def _print_human_summary(result: dict[str, object]) -> None:
    print("ECUBE Copy Path Diagnostic")
    print(f"source_path: {result['source_path']}")
    print(f"target_path: {result['target_path']}")
    print(f"sample_mode: {result['sample_mode']}")
    print(f"source_file_count: {result['source_file_count']}")
    print(f"source_total_bytes: {result['source_total_bytes']}")
    print(f"benchmark_requested_bytes: {result['benchmark_requested_bytes']}")
    print(f"benchmark_measured_bytes: {result['benchmark_measured_bytes']}")
    print(f"sample_file_count: {result['sample_file_count']}")
    print(f"sample_copied_bytes: {result['sample_copied_bytes']}")
    print(f"sample_median_file_size_bytes: {result['sample_median_file_size_bytes']}")
    print(f"sample_small_file_count: {result['sample_small_file_count']}")
    print(f"share_read_mbps: {result['share_read_mbps']}")
    print(f"drive_write_mbps: {result['drive_write_mbps']}")
    print(f"benchmark_effective_copy_mbps: {result['benchmark_effective_copy_mbps']}")
    print(f"end_to_end_copy_mbps: {result['end_to_end_copy_mbps']}")
    print(f"sample_copy_elapsed_seconds: {result['sample_copy_elapsed_seconds']}")
    print(f"sample_copy_files_per_second: {result['sample_copy_files_per_second']}")
    print(f"copy_chunk_size_bytes: {result['copy_chunk_size_bytes']}")
    print(f"copy_file_fsync_enabled: {result['copy_file_fsync_enabled']}")
    print("notes:")
    for note in cast(list[str], result["notes"]):
        print(f"- {note}")


def main() -> int:
    args = _build_parser().parse_args()
    result = run_copy_path_diagnostic(
        args.source_path,
        args.target_path,
        sample_mode=args.sample_mode,
        benchmark_bytes=args.benchmark_bytes,
        small_file_stress_sample_file_count=args.sample_file_count or 2000,
        keep_sample=args.keep_sample,
    ).as_dict()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())