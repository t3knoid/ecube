# 8. Programming Language & Framework Requirements — Design

## 8.1 System Layer (Python)

- FastAPI for REST endpoints and OpenAPI generation.
- SQLAlchemy ORM with Alembic migrations for schema management.
- Celery or RQ for background copy/verify/manifest jobs.
- Service boundaries: API handlers, domain services, infrastructure adapters.

## 8.2 UI Layer

- React/Vue or server-rendered templates as presentation tier only.
- Consume HTTPS API with role-based endpoint access.
- Poll or subscribe for job progress updates.

## 8.3 Database Layer

- PostgreSQL 14+ as authoritative state store.
- Connection access restricted to system-layer runtime identity.
- Transaction boundaries align with state transition operations.
