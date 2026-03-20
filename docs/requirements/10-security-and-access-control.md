# 10. Security and Role-Based Access Control

## Identity Sources

### Default

- ECUBE uses local OS users and groups for identity and role mapping.
- Each authenticated request is associated with a local user account.

### Optional extension (LDAP)

- ECUBE can be configured to use LDAP as the identity provider.
- LDAP groups are mapped to ECUBE roles.
- Local and LDAP modes share the same role model.

## Roles

ECUBE defines four roles:

### Administrator

- Full access to all ECUBE operations and APIs.

### Manager

- Initialize drives and assign them to projects.
- Make drives available for processors.
- View jobs, drives, mounts, and logs.

### Processor

- Create jobs (within allowed projects).
- Start and monitor copy operations.
- View job and drive status.

### Auditor

- Read audit logs.
- View job and file metadata.
- Compute file hashes (for example, MD5 and SHA-256).
- Perform file comparisons.
- No write operations to jobs, drives, or mounts.

## Role Mapping

### Local mode (default)

- ECUBE reads local groups (for example, `/etc/group`) and maps them to roles.

Example configuration:

```yaml
security:
  mode: "local"
  local_group_role_mapping:
    "ecube-admins": "admin"
    "ecube-managers": "manager"
    "ecube-processors": "processor"
    "ecube-auditors": "auditor"
```

### LDAP mode (optional)

- ECUBE authenticates users via LDAP and maps LDAP groups to roles.

Example configuration:

```yaml
security:
  mode: "ldap"
  ldap:
    url: "ldaps://ldap.example.com"
    base_dn: "dc=example,dc=com"
    user_dn_template: "uid={username},ou=people,dc=example,dc=com"
    group_role_mapping:
      "CN=ECUBE-Admins,OU=Groups,DC=example,DC=com": "admin"
      "CN=ECUBE-Managers,OU=Groups,DC=example,DC=com": "manager"
      "CN=ECUBE-Processors,OU=Groups,DC=example,DC=com": "processor"
      "CN=ECUBE-Auditors,OU=Groups,DC=example,DC=com": "auditor"
```

## Authorization Matrix (High Level)

| Operation / API area                        | Admin | Manager | Processor | Auditor |
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

## Service-Layer Integration

### User context

Every request is resolved to a `UserContext`:

```python
@dataclass
class UserContext:
    username: str
    roles: list[str]  # ["admin", "manager", ...]
```

- In local mode, roles are derived from local groups.
- In LDAP mode, roles are derived from LDAP groups.

### Role enforcement

A simple decorator-style pattern at the service/API layer:

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

Example usage:

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
