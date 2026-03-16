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
        # Check if SECRET_KEY is the default and warn
        content = env_path.read_text()
        if "change-me-in-production" in content:
            secret = secrets.token_hex(32)
            new_content = content.replace(
                "change-me-in-production-please-rotate-32b", secret,
            )
            env_path.write_text(new_content)
            print("  Rotated SECRET_KEY to a random value")
        return

    secret = secrets.token_hex(32)
    role_map = (
        '{"ecube-admins": ["admin"], "ecube-managers": ["manager"], '
        '"ecube-processors": ["processor"], "ecube-auditors": ["auditor"]}'
    )

    env_path.write_text(
        f"DATABASE_URL=postgresql://ecube:ecube@localhost/ecube\n"
        f"SECRET_KEY={secret}\n"
        f"ROLE_RESOLVER=local\n"
        f"LOCAL_GROUP_ROLE_MAP={role_map}\n"
    )
    # Restrict permissions — contains SECRET_KEY
    os.chmod(env_path, 0o600)
    print(f"  Generated {env_path} with random SECRET_KEY")


def _seed_database(username: str, install_dir: str) -> None:
    """Insert admin role mapping into user_roles table."""
    # Load .env from install_dir so we use the same DATABASE_URL / SECRET_KEY
    # that _generate_env() wrote, regardless of the caller's working directory.
    env_path = Path(install_dir) / ".env"
    if env_path.exists():
        os.environ.setdefault("ENV_FILE", str(env_path))
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)

    # Import after env is loaded to pick up the correct DATABASE_URL.
    from app.database import SessionLocal
    from app.models.users import UserRole
    from app.repositories.user_role_repository import UserRoleRepository
    from sqlalchemy import exc as sa_exc

    db = SessionLocal()
    try:
        repo = UserRoleRepository(db)
        if repo.has_any_admin():
            print("  Admin role already seeded in database — skipping")
            return
        existing = repo.get_roles(username)
        if "admin" not in existing:
            db.add(UserRole(username=username, role="admin"))
            db.commit()
            print(f"  Seeded database: '{username}' → admin")
        else:
            print(f"  User '{username}' already has admin role — skipping")
    except (sa_exc.ProgrammingError, sa_exc.OperationalError) as exc:
        print("  Error while seeding admin role in database.")
        print(f"  Details: {exc}")
        print("  The database schema may not be initialized. Run 'alembic upgrade head' and re-run this setup step.")
    finally:
        db.close()


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
    _seed_database(admin_username, install_dir)
    print()

    print("=" * 60)
    print("Setup complete!")
    print()
    print("Next steps:")
    print(f"  1. Review configuration: {install_dir}/.env")
    print("  2. Run migrations:       alembic upgrade head")
    print("  3. Start the service:    systemctl start ecube")
    print("=" * 60)


if __name__ == "__main__":
    main()
