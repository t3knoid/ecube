# 10. Security and Role-Based Access Control — Design

## Design Goals

- Centralize authentication and authorization in the ECUBE System Layer.
- Support a common role model across local and LDAP identity modes.
- Enforce least privilege at endpoint and service boundaries.

## Identity Source Design

### Local mode (default)

- Authenticate users via PAM (Pluggable Authentication Modules) on the host OS.
- The `POST /auth/token` endpoint accepts `username` and `password`, validates
  credentials through PAM, and resolves ECUBE roles using the hybrid model below.
- Token expiration is configurable via `TOKEN_EXPIRE_MINUTES` (default: 60).
- No user/password database is required — PAM delegates to whatever authentication
  backend the host is configured for (`/etc/shadow`, SSSD, Kerberos, etc.).

### Hybrid authorization model (PAM auth + DB roles)

Authentication and authorization are separated:

- **Authentication** stays with PAM — the OS validates credentials.
- **Authorization** is managed through the `user_roles` database table, with
  OS group mappings as a fallback.

**Role resolution priority:**

1. Check the `user_roles` table for explicit role assignments → use if found.
2. Fall back to OS group memberships + `LOCAL_GROUP_ROLE_MAP` config → use if found.
3. No roles → empty list → `require_roles()` rejects with 403.

This design allows the system to work immediately after first-run setup (OS
groups provide roles) while the admin GUI can override and refine assignments
via the database as needed.

**`user_roles` table:**

| Column     | Type                                          | Constraints                          |
|------------|-----------------------------------------------|--------------------------------------|
| `id`       | Integer (PK)                                  | Auto-increment                       |
| `username` | String (indexed)                              | Not null                             |
| `role`     | Enum: admin, manager, processor, auditor      | Not null, `native_enum=False`        |
|            |                                               | Unique on (`username`, `role`)       |

This table stores no credentials — it is a lightweight role assignment store
managed through the `/users/*/roles` admin API endpoints.

#### Local mode authentication flow

```text
 Client                  ECUBE System Layer               Linux PAM
   │                          │                               │
   │  POST /auth/token        │                               │
   │  {username, password}    │                               │
   │────────────────────────▶│                               │
   │                          │  pam.authenticate(user, pass) │
   │                          │──────────────────────────────▶│
   │                          │  success / failure            │
   │                          │◀──────────────────────────────│
   │                          │                               │
   │                          │  SELECT role FROM user_roles   │
   │                          │    WHERE username = ?          │
   │                          │  if DB roles → use them        │
   │                          │  else:                         │
   │                          │    os.getgrouplist() → groups  │
   │                          │    LOCAL_GROUP_ROLE_MAP → roles│
   │                          │  sign JWT(sub, groups, roles)  │
   │                          │                               │
   │  {access_token, bearer}  │                               │
   │◀────────────────────────│                               │
```

### LDAP mode (optional)

- Authenticate users via PAM with an LDAP backend (e.g., SSSD or pam_ldap).
- The same `POST /auth/token` endpoint handles login — PAM transparently
  delegates to the LDAP directory when the host is configured for it.
- LDAP group memberships appear as OS groups (via `nsswitch.conf` / SSSD)
  and are mapped to ECUBE roles via `LDAP_GROUP_ROLE_MAP`.
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
| Manage user roles (`/users/*/roles`)       |  ✔    |    ✖    |     ✖     |    ✖    |
| Manage OS users/groups (local only)        |  ✔    |    ✖    |     ✖     |    ✖    |
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

@router.post("/drives/{drive_id}/format")
@require_roles("admin", "manager")
def format_drive(drive_id: int, user: UserContext):
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

## ECUBE Namespace Isolation

OS user and group management endpoints are scoped to the `ecube-` namespace to prevent accidental damage to host system accounts:

- **Group namespace:** `POST /admin/os-groups` and `DELETE /admin/os-groups/{name}` reject any group name that does not start with the `ecube-` prefix (`422 Unprocessable Entity`). `GET /admin/os-groups` lists only groups matching the prefix. The four default groups (`ecube-admins`, `ecube-managers`, `ecube-processors`, `ecube-auditors`) are bootstrapped during first-run setup.

- **ECUBE-managed user guard:** Mutative user operations (`DELETE /admin/os-users/{username}`, `PUT .../password`, `PUT .../groups`, `POST .../groups`) verify that the target user belongs to at least one `ecube-*` OS group before proceeding. Users who are not members of any `ecube-*` group — such as `postgres`, `www-data`, or manually-created system accounts — are rejected with `422 Unprocessable Entity`. A hardcoded reserved-username list (`root`, `nobody`, `daemon`, etc.) provides an additional layer of protection. This check is bypassed only for internal compensation and first-run recovery paths where the user may not yet have been added to an `ecube-*` group.

- **User listing:** `GET /admin/os-users` returns only users who belong to at least one `ecube-*` group.

## Recommended Controls

- Log role-evaluation denials in `audit_logs` with action and endpoint.
- Log all role assignment/removal events (`ROLE_ASSIGNED`, `ROLE_REMOVED`) with actor identity.
- Add explicit `403` response schema for authorization failures.
- Keep introspection and audit endpoints read-only and role-gated.
- First-run setup is available via the unauthenticated `POST /setup/initialize` API endpoint or the CLI `python -m app.setup` script.  Both refuse to re-seed if an admin already exists.  The API endpoint uses a `system_initialization` single-row table with a uniqueness constraint as a cross-process guard, ensuring only one worker can complete initialization even in multi-worker deployments.
- Database provisioning endpoints (`POST /setup/database/test-connection`, `POST /setup/database/provision`) use a **dual-auth model with fail-closed semantics**:
  1. **DB reachable, no admin exists** → unauthenticated access allowed (positively confirmed initial setup).
  2. **DB reachable, admin exists** → valid JWT with the `admin` role required.
  3. **DB unreachable** → a valid admin JWT must be presented; if no valid JWT is provided the endpoint returns **503 Service Unavailable** rather than granting unauthenticated access. This prevents an attacker from exploiting a transient database outage to bypass authentication. Because the JWT is self-contained, an authenticated admin can still operate without DB connectivity.

  Initialization state is determined by `UserRoleRepository.has_any_admin()`. The remaining database endpoints (`GET /setup/database/status`, `PUT /setup/database/settings`) always require the `admin` role.
