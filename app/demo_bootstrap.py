from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError


def activate_install_root() -> Path:
    """Switch to the ECUBE install root so .env resolution is stable."""
    install_root = Path(__file__).resolve().parents[1]
    os.chdir(install_root)
    return install_root


_REQUIRED_SCHEMA_TABLES = {
    "audit_logs",
    "export_files",
    "export_jobs",
    "network_mounts",
    "usb_drives",
    "usb_hubs",
    "usb_ports",
    "user_roles",
}


def _missing_required_tables(db) -> list[str]:
    """Return required ECUBE tables that are not yet present in the configured DB."""
    inspector = inspect(db.get_bind())
    present_tables = set(inspector.get_table_names())
    return sorted(_REQUIRED_SCHEMA_TABLES - present_tables)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed or reset a demo ECUBE deployment on a normal install.",
    )
    parser.add_argument(
        "--actor",
        default="demo-bootstrap",
        help="Audit actor name recorded for the bootstrap action.",
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help="Dedicated demo-only directory used for staged sample files.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed", help="Seed demo users, roles, and sample content.")
    seed_parser.add_argument(
        "--shared-password",
        default=None,
        help="Optional shared password for demo OS accounts. Required if the demo users do not already exist on the host.",
    )
    seed_parser.add_argument(
        "--skip-os-users",
        action="store_true",
        help="Only seed the database and sample files without creating or updating OS accounts.",
    )

    subparsers.add_parser("reset", help="Remove demo-seeded roles, jobs, and staged files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    activate_install_root()

    from app.database import SessionLocal, is_database_configured
    from app.infrastructure import get_os_user_provider
    from app.services.demo_seed_service import reset_demo_environment, seed_demo_environment

    parser = build_parser()
    args = parser.parse_args(argv)

    if not is_database_configured():
        print("DATABASE_URL is not configured. Complete setup first.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        missing_tables = _missing_required_tables(db)
        if missing_tables:
            print(
                "Database schema is not initialized for demo bootstrap. "
                "Run the setup wizard or 'alembic upgrade head' first. "
                f"Missing tables: {', '.join(missing_tables)}",
                file=sys.stderr,
            )
            return 2

        if args.command == "seed":
            provider = None if args.skip_os_users else get_os_user_provider()
            result = seed_demo_environment(
                db,
                data_root=args.data_root,
                provider=provider,
                shared_password=args.shared_password,
                actor=args.actor,
            )
            print(
                "Demo bootstrap complete: "
                f"users={result.users_seeded}, roles={result.roles_seeded}, jobs={result.jobs_seeded}, files={result.files_staged}, usb_drives={result.usb_drives_seeded}, usb_mounted={result.usb_drives_mounted}, network_mounts={result.network_mounts_seeded}, network_mounted={result.network_mounts_mounted}, root={result.data_root}"
            )
            return 0

        if args.command == "reset":
            result = reset_demo_environment(
                db,
                data_root=args.data_root,
                actor=args.actor,
            )
            print(
                "Demo reset complete: "
                f"roles_removed={result.roles_removed}, jobs_removed={result.jobs_removed}, files_removed={result.files_removed}, root={result.data_root}"
            )
            return 0

        parser.print_help()
        return 2
    except SQLAlchemyError as exc:
        print(
            "Demo bootstrap could not access the ECUBE schema. "
            "Run the setup wizard or 'alembic upgrade head' first.",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
