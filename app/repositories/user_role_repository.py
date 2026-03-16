"""Data-access layer for :class:`~app.models.users.UserRole`."""

from typing import List

from sqlalchemy.orm import Session

from app.models.users import UserRole


class UserRoleRepository:
    """CRUD operations for user-role assignments."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_roles(self, username: str) -> List[str]:
        """Return the list of role strings assigned to *username*."""
        rows = (
            self.db.query(UserRole.role)
            .filter(UserRole.username == username)
            .order_by(UserRole.role)
            .all()
        )
        return [r[0] for r in rows]

    def set_roles(self, username: str, roles: List[str]) -> List[str]:
        """Replace all roles for *username* with *roles*.

        Returns the new role list.
        """
        self.db.query(UserRole).filter(UserRole.username == username).delete(
            synchronize_session=False,
        )
        for role in roles:
            self.db.add(UserRole(username=username, role=role))
        self.db.commit()
        return roles

    def delete_roles(self, username: str) -> int:
        """Remove all role assignments for *username*.  Returns count deleted."""
        count = (
            self.db.query(UserRole)
            .filter(UserRole.username == username)
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return count

    def list_users(self) -> List[dict]:
        """Return all users with their role assignments.

        Returns a list of ``{"username": str, "roles": [str, ...]}`` dicts.
        """
        rows = (
            self.db.query(UserRole.username, UserRole.role)
            .order_by(UserRole.username, UserRole.role)
            .all()
        )
        users: dict[str, list[str]] = {}
        for username, role in rows:
            users.setdefault(username, []).append(role)
        return [{"username": u, "roles": r} for u, r in users.items()]

    def has_any_admin(self) -> bool:
        """Return True if at least one user has the 'admin' role."""
        return (
            self.db.query(UserRole)
            .filter(UserRole.role == "admin")
            .first()
        ) is not None
