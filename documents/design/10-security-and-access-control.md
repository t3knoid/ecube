# 10. Security and Role-Based Access Control — Design

## Design Goals

- Centralize authentication and authorization in the ECUBE System Layer.
- Support a common role model across local and LDAP identity modes.
- Enforce least privilege at endpoint and service boundaries.

## Identity Source Design

### Local mode (default)

- Resolve identity from local OS authentication context.
- Map local groups to ECUBE roles via configuration.

### LDAP mode (optional)

- Authenticate users against LDAP.
- Resolve group membership and map to ECUBE roles.
- Keep the same downstream role evaluation path used in local mode.

## Role Model

- `admin`: unrestricted operations.
- `manager`: drive lifecycle and operational oversight.
- `processor`: job execution and monitoring.
- `auditor`: read-only audit/integrity functions.

## Authorization Matrix (Design Baseline)

| Operation / API area                         | Admin | Manager | Processor | Auditor |
|---------------------------------------------|:-----:|:-------:|:---------:|:-------:|
| Manage users / security config (future)     |  ✔    |    ✖    |     ✖     |    ✖    |
| Add/remove mounts                           |  ✔    |    ✔    |     ✖     |    ✖    |
| List mounts                                 |  ✔    |    ✔    |     ✔     |    ✔    |
| Initialize drives / assign to projects      |  ✔    |    ✔    |     ✖     |    ✖    |
| Prepare drives for eject                    |  ✔    |    ✔    |     ✖     |    ✖    |
| List drives / drive states                  |  ✔    |    ✔    |     ✔     |    ✔    |
| Create jobs                                 |  ✔    |    ✔    |     ✔     |    ✖    |
| Start copy jobs                             |  ✔    |    ✔    |     ✔     |    ✖    |
| View job status                             |  ✔    |    ✔    |     ✔     |    ✔    |
| Regenerate manifest / verify job            |  ✔    |    ✔    |     ✔     |    ✖    |
| Read audit logs                             |  ✔    |    ✔    |     ✖     |    ✔    |
| Introspection (read-only system info)       |  ✔    |    ✔    |     ✔     |    ✔    |
| File hash / file compare (audit functions)  |  ✔    |    ✖    |     ✖     |    ✔    |

## Service-Layer Integration Pattern

### User context

```python
@dataclass
class UserContext:
    username: str
    roles: list[str]
```

### Role guard

```python
def require_roles(*allowed_roles: str):
    def decorator(handler):
        def wrapper(user: UserContext, *args, **kwargs):
            if not any(r in user.roles for r in allowed_roles):
                raise ForbiddenError("Insufficient role")
            return handler(user, *args, **kwargs)
        return wrapper
    return decorator
```

### Endpoint examples

```python
@router.post("/drives/{drive_id}/initialize")
@require_roles("admin", "manager")
def initialize_drive(drive_id: int, user: UserContext):
    ...

@router.post("/jobs/{job_id}/start")
@require_roles("admin", "manager", "processor")
def start_job(job_id: int, user: UserContext):
    ...

@router.get("/audit")
@require_roles("admin", "manager", "auditor")
def get_audit_logs(user: UserContext):
    ...
```

## Recommended Controls

- Log role-evaluation denials in `audit_logs` with action and endpoint.
- Add explicit `403` response schema for authorization failures.
- Keep introspection and audit endpoints read-only and role-gated.
