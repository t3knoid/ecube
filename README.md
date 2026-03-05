# ecube
Evidence Copying &amp; USB Based Export

ECUBE is a secure evidence export platform designed to copy eDiscovery data onto encrypted USB drives from a Linux-based copy machine, with strict project isolation, full audit logging, hardware-aware drive management, and a trusted system-layer API that isolates the public UI from direct hardware and database access.

## Application Stack

- **System Layer API:** Python 3.11+, FastAPI
- **Data Layer:** PostgreSQL with SQLAlchemy + Alembic
- **Background Processing:** Celery or RQ workers for copy, verification, and manifest tasks
- **UI Layer:** React, Vue, or server-rendered templates (HTTPS-only)
- **Runtime Platform:** Linux-based copy machine with USB hub integration and NFS/SMB mount support
- **Planned/Optional Security:** LDAP identity provider mode and token-based API authentication (JWT or signed session token)

## Documentation

- [Requirements Documents](documents/requirements)
- [ECUBE Requirements Overview](documents/requirements/00-overview.md)
- [Security & Access Control (Requirements)](documents/requirements/10-security-and-access-control.md)
- [Design Documents](documents/design)
- [ECUBE Design Overview](documents/design/00-overview.md)
- [Security & Access Control (Design)](documents/design/10-security-and-access-control.md)
