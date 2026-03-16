"""User-role assignment model.

The ``user_roles`` table stores explicit username→role mappings managed
through the admin API.  It does **not** store credentials — authentication
is handled by PAM (or OIDC).  This table is the authoritative source for
role resolution when entries exist; OS group mappings serve as a fallback.
"""

from sqlalchemy import Column, Enum, Integer, String, UniqueConstraint

from app.database import Base


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, index=True)
    role = Column(
        Enum("admin", "manager", "processor", "auditor", name="ecube_role", native_enum=False),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("username", "role", name="uq_user_role"),
    )
