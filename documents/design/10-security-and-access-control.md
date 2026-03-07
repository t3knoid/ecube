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

### OIDC mode (optional)

- Accept OIDC ID tokens (JWTs) issued by a third-party identity provider such
  as Auth0, Okta, Azure AD, or Google Cloud Identity.
- Validate the token signature using the provider's JWKS (fetched from the
  discovery URL; cached for the process lifetime).
- Extract the configured group claim (default: `"groups"`) and map to ECUBE
  roles via `oidc_group_role_map`.
- Enabled by setting `role_resolver = "oidc"` in configuration.

#### OIDC token validation flow

```text
 Client                 ECUBE System Layer              OIDC Provider
   │                          │                               │
   │  Bearer: <id_token>      │                               │
   │────────────────────────▶│                               │
   │                          │  [on first request]           │
   │                          │  GET /.well-known/openid-     │
   │                          │  configuration                │
   │                          │──────────────────────────────▶│
   │                          │  { "jwks_uri": "..." }        │
   │                          │◀──────────────────────────────│
   │                          │  GET /jwks.json (cached)      │
   │                          │──────────────────────────────▶│
   │                          │  { "keys": [...] }            │
   │                          │◀──────────────────────────────│
   │                          │                               │
   │                          │  verify signature, exp, aud   │
   │                          │  extract groups claim         │
   │                          │  resolve groups → roles       │
   │  200 OK (or 401/403)     │                               │
   │◀────────────────────────│                               │
```

#### Group claim mapping

The `oidc_group_claim_name` setting (default `"groups"`) specifies which JWT
claim contains the user's group memberships.  The `oidc_group_role_map`
dictionary maps each group value to one or more ECUBE roles.

Example:

```json
{
  "oidc_group_claim_name": "groups",
  "oidc_group_role_map": {
    "evidence-admins": ["admin"],
    "evidence-team":   ["processor", "auditor"]
  }
}
```

Unmapped groups are silently ignored (**deny-by-default**).  A user whose
groups are entirely unmapped receives an empty role list, which causes
`require_roles` to return HTTP 403.

## Role Model

- `admin`: unrestricted operations.
- `manager`: drive lifecycle and operational oversight.
- `processor`: job execution and monitoring.
- `auditor`: read-only audit/integrity functions.

## Authorization Matrix (Design Baseline)

| Operation / API area                       | Admin | Manager | Processor | Auditor |
|--------------------------------------------|:-----:|:-------:|:---------:|:-------:|
| Manage users / security config (future)    |  ✔    |    ✖    |     ✖     |    ✖    |
| Add/remove mounts                          |  ✔    |    ✔    |     ✖     |    ✖    |
| List mounts                                |  ✔    |    ✔    |     ✔     |    ✔    |
| Initialize drives / assign to projects     |  ✔    |    ✔    |     ✖     |    ✖    |
| Prepare drives for eject                   |  ✔    |    ✔    |     ✖     |    ✖    |
| List drives / drive states                 |  ✔    |    ✔    |     ✔     |    ✔    |
| Create jobs                                |  ✔    |    ✔    |     ✔     |    ✖    |
| Start copy jobs                            |  ✔    |    ✔    |     ✔     |    ✖    |
| View job status                            |  ✔    |    ✔    |     ✔     |    ✔    |
| Regenerate manifest / verify job           |  ✔    |    ✔    |     ✔     |    ✖    |
| Read audit logs                            |  ✔    |    ✔    |     ✖     |    ✔    |
| Introspection (read-only system info)      |  ✔    |    ✔    |     ✔     |    ✔    |
| File hash / file compare (audit functions) |  ✔    |    ✖    |     ✖     |    ✔    |

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
