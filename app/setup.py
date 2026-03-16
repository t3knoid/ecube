"""ECUBE first-run setup script.

Creates OS groups and an initial admin user, generates default configuration,
and seeds the database with the admin role mapping.

Must be run as root/sudo::

    sudo python -m app.setup
"""

from __future__ import annotations

import getpass
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path


ECUBE_GROUPS = {
    "ecube-admins": "admin",
    "ecube-managers": "manager",
    "ecube-processors": "processor",
    "ecube-auditors": "auditor",
}

DEFAULT_INSTALL_DIR = "/opt/ecube"


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _chown_as_dir_owner(file_path: Path) -> None:
    """Set *file_path* ownership to match its parent directory's owner.

    The setup script runs as root, but the service runs as a non-root
    account (typically ``ecube``).  Aligning the ``.env`` file owner with
    the install directory owner ensures the service can read it.
    """
    parent_stat = file_path.parent.stat()
    shutil.chown(file_path, user=parent_stat.st_uid, group=parent_stat.st_gid)


def _group_exists(name: str) -> bool:
    result = _run(["getent", "group", name], check=False)
    return result.returncode == 0


def _user_exists(name: str) -> bool:
    result = _run(["getent", "passwd", name], check=False)
    return result.returncode == 0


def _create_groups() -> None:
    """Create ECUBE role groups if they don't exist."""
    for group in ECUBE_GROUPS:
        if _group_exists(group):
            print(f"  Group '{group}' already exists — skipping")
        else:
            _run(["groupadd", group])
            print(f"  Created group '{group}'")


def _create_admin_user() -> str:
    """Prompt for admin credentials, create the OS user, return username."""
    username = input("Enter admin username [ecube-admin]: ").strip() or "ecube-admin"

    if _user_exists(username):
        print(f"  OS user '{username}' already exists — adding to ecube-admins")
    else:
        password = getpass.getpass("Enter admin password: ")
        if not password:
            print("Error: password cannot be empty", file=sys.stderr)
            sys.exit(1)
        confirm = getpass.getpass("Confirm admin password: ")
        if password != confirm:
            print("Error: passwords do not match", file=sys.stderr)
            sys.exit(1)

        _run(["useradd", "-m", username])
        subprocess.run(
            ["chpasswd"],
            input=f"{username}:{password}",
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"  Created OS user '{username}'")

    # Add to ecube-admins
    _run(["usermod", "-aG", "ecube-admins", username])
    print(f"  Added '{username}' to group 'ecube-admins'")
    return username


def _generate_env(install_dir: str) -> None:
    """Write default .env file if it doesn't exist."""
    env_path = Path(install_dir) / ".env"
    if env_path.exists():
        print(f"  {env_path} already exists — not overwriting")
        # Check if SECRET_KEY is the default placeholder and rotate if so
        content = env_path.read_text()
        placeholder = "change-me-in-production-please-rotate-32b"
        rotated = False
        if placeholder in content:
            secret = secrets.token_hex(32)
            new_content = content.replace(placeholder, secret)
            if new_content != content:
                env_path.write_text(new_content)
                rotated = True
        if rotated:
            print("  Rotated SECRET_KEY to a random value")
        # Always enforce restrictive permissions on existing .env
        os.chmod(env_path, 0o600)
        _chown_as_dir_owner(env_path)
        return

    secret = secrets.token_hex(32)
    role_map = (
        '{"ecube-admins": ["admin"], "ecube-managers": ["manager"], '
        '"ecube-processors": ["processor"], "ecube-auditors": ["auditor"]}'
    )

    # Determine DATABASE_URL without using a fixed default password.
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("  No DATABASE_URL found in environment.")
        print("  Please enter the PostgreSQL connection URL to store in .env.")
        print("  Example: postgresql://ecube:YOUR_PASSWORD@localhost/ecube")
        user_input = input("  DATABASE_URL (leave empty to build it interactively): ").strip()
        if user_input:
            db_url = user_input
        else:
            default_user = "ecube"
            default_host = "localhost"
            default_db = "ecube"
            username = input(f"  DB username [{default_user}]: ").strip() or default_user
            host = input(f"  DB host [{default_host}]: ").strip() or default_host
            dbname = input(f"  DB name [{default_db}]: ").strip() or default_db
            password = getpass.getpass("  DB password (will not echo): ")
            db_url = f"postgresql://{username}:{password}@{host}/{dbname}"

    env_path.write_text(
        f"DATABASE_URL={db_url}\n"
        f"SECRET_KEY={secret}\n"
        f"ROLE_RESOLVER=local\n"
        f"LOCAL_GROUP_ROLE_MAP={role_map}\n"
    )
    # Restrict permissions — contains SECRET_KEY
    os.chmod(env_path, 0o600)
    _chown_as_dir_owner(env_path)
    print(f"  Generated {env_path} with random SECRET_KEY")


def _load_env_file(env_path: Path) -> None:
    """Read a simple KEY=VALUE .env file into ``os.environ``."""
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ[key.strip()] = value


def _seed_database(username: str, install_dir: str) -> bool:
    """Insert admin role mapping into user_roles table.

    Returns True if seeding succeeded (or was already in place), False if a
    database error occurred (e.g., missing migrations).
    """
    # Load .env from install_dir so we use the same DATABASE_URL / SECRET_KEY
    # that _generate_env() wrote, regardless of the caller's working directory.
    env_path = Path(install_dir) / ".env"
    if env_path.exists():
        _load_env_file(env_path)

    # Import after env is loaded to pick up the correct DATABASE_URL.
    from app.database import SessionLocal
    from app.models.users import UserRole
    from app.repositories.user_role_repository import UserRoleRepository
    from sqlalchemy import exc as sa_exc

    db = SessionLocal()
    success = True
    try:
        repo = UserRoleRepository(db)
        if repo.has_any_admin():
            print("  Admin role already seeded in database — skipping")
            return True
        existing = repo.get_roles(username)
        if "admin" not in existing:
            db.add(UserRole(username=username, role="admin"))
            db.commit()
            print(f"  Seeded database: '{username}' → admin")
        else:
            print(f"  User '{username}' already has admin role — skipping")
    except (sa_exc.ProgrammingError, sa_exc.OperationalError) as exc:
        success = False
        print("  Error while seeding admin role in database.")
        print(f"  Details: {exc}")
        print("  The database schema may not be initialized. Run 'alembic upgrade head' and re-run this setup step.")
    finally:
        db.close()

    return success


def main() -> None:
    if os.geteuid() != 0:
        print("Error: this script must be run as root (sudo python -m app.setup)", file=sys.stderr)
        sys.exit(1)

    install_dir = os.environ.get("ECUBE_INSTALL_DIR", DEFAULT_INSTALL_DIR)

    print("=" * 60)
    print("ECUBE First-Run Setup")
    print("=" * 60)
    print()

    print("Step 1: Creating ECUBE groups...")
    _create_groups()
    print()

    print("Step 2: Creating admin user...")
    admin_username = _create_admin_user()
    print()

    print("Step 3: Generating configuration...")
    _generate_env(install_dir)
    print()

    print("Step 4: Seeding database...")
    seed_ok = _seed_database(admin_username, install_dir)
    print()

    if not seed_ok:
        print("=" * 60)
        print("Setup aborted: database seeding failed.")
        print()
        print("Please ensure the database schema is initialized:")
        print("  1. Run migrations:       alembic upgrade head")
        print("  2. Re-run this setup script: sudo python -m app.setup")
        print("=" * 60)
        sys.exit(1)

    print("=" * 60)
    print("Setup complete!")
    print()
    print("Next steps:")
    print(f"  1. Review configuration: {install_dir}/.env")
    print("  2. Start the service:    systemctl start ecube")
    print("=" * 60)


if __name__ == "__main__":
    main()
