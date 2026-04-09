# 10. Security and Role-Based Access Control — Design

| Field | Value |
|---|---|
| Title | Security and Role-Based Access Control |
| Purpose | Describes how ECUBE authentication, role resolution, authorization enforcement, and denial auditing are designed. |
| Updated on | 04/08/26 |
| Audience | Engineers, implementers, security reviewers, maintainers, and technical reviewers. |

## Design Goals

- Centralize authentication and authorization in the ECUBE System Layer.
- Support a common role model across local and LDAP identity modes.
- Enforce least privilege at endpoint and service boundaries.
- Maintain a security and access control design posture where authentication, role resolution, authorization enforcement, and denial auditing remain fail-closed by default.

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
| Manage USB port enablement                  |  ✔    |    ✔    |     ✖     |    ✖    |
| Manage hub/port labels                      |  ✔    |    ✔    |     ✖     |    ✖    |
| List USB hubs                               |  ✔    |    ✔    |     ✖     |    ✖    |
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
- All error responses use the standardized `ErrorResponse` JSON schema (see [06-rest-api-design.md](06-rest-api-design.md#standardized-error-response-format)); `400`, `401`, `403`, `404`, `409`, `422`, `500`, `503`, and `504` responses are declared in the OpenAPI specification for every authenticated endpoint (and conditional-auth endpoints when applicable) via reusable response dicts in `app/schemas/errors.py`.
- Keep introspection and audit endpoints read-only and role-gated.
- First-run setup is available through controlled initialization entrypoints and refuses to re-seed if an admin already exists. The API path uses a `system_initialization` single-row table with a uniqueness constraint as a cross-process guard, ensuring only one worker can complete initialization even in multi-worker deployments.
- Startup reconciliation uses a `reconciliation_lock` single-row table with the same guard pattern, ensuring only one worker runs mount/job/drive reconciliation even in multi-worker deployments.  Stale locks (> 5 minutes) are automatically reclaimed.
- Database provisioning endpoints (`POST /setup/database/test-connection`, `POST /setup/database/provision`) use a **dual-auth model with fail-closed semantics**:
  1. **DB reachable, no admin exists** → unauthenticated access allowed (positively confirmed initial setup).
  2. **DB reachable, admin exists** → valid JWT with the `admin` role required.
  3. **DB unreachable** → a valid admin JWT must be presented; if no valid JWT is provided the endpoint returns **503 Service Unavailable** rather than granting unauthenticated access. This prevents an attacker from exploiting a transient database outage to bypass authentication. Because the JWT is self-contained, an authenticated admin can still operate without DB connectivity.

  Initialization state is determined by `UserRoleRepository.has_any_admin()`. The remaining database endpoints (`GET /setup/database/status`, `PUT /setup/database/settings`) always require the `admin` role.
- **SSRF protection for webhook callbacks:** When a job specifies a `callback_url`, the callback service resolves the hostname and rejects any address that maps to a private or loopback range (RFC 1918, `127.0.0.0/8`, `::1`) before making the outbound HTTP request. This prevents server-side request forgery via crafted callback URLs. The check can be relaxed with `CALLBACK_ALLOW_PRIVATE_IPS=true` for isolated lab environments. See [04-functional-design.md § 4.8](04-functional-design.md) for retry and audit details.

## PAM Password Complexity and Policy Design

This section describes how ECUBE enforces password complexity, history, and expiration for locally managed OS accounts using the host PAM framework.

### Overview

ECUBE calls `chpasswd` (via `sudo`) to set and reset passwords for local OS accounts. On Ubuntu and Debian, `chpasswd` is compiled with PAM support and runs the `/etc/pam.d/common-password` stack before writing to `/etc/shadow`. This means configuring `pam_pwquality` and `pam_pwhistory` at the host level automatically enforces policy for all ECUBE password operations without requiring application-level reimplementation of the policy rules themselves.

```
   ECUBE API                  sudo chpasswd              Linux PAM
       │                            │                       │
       │  stdin: username:password  │                       │
       │──────────────────────────▶│                       │
       │                            │  pam_pwquality check  │
       │                            │──────────────────────▶│
       │                            │  pam_pwhistory check  │
       │                            │──────────────────────▶│
       │                            │  pam_unix write       │
       │                            │──────────────────────▶│
       │  exit 0 (success)          │                       │
       │  or exit 1 + stderr msg    │                       │
       │◀──────────────────────────│                       │
```

### OS Prerequisites

**Scope:** These prerequisites apply **only to the backend host** where the ECUBE application (FastAPI service, database, and user management) is deployed. The frontend (React/Vue UI) and other satellites that consume only the ECUBE REST API do not require these OS-level configurations. In containerized deployments where user management is delegated to the backend, these steps are performed only once at the backend container image build time or on the backend host.

The following host-level configuration must be applied by the ECUBE installer and Ansible roles before the application can rely on PAM policy enforcement. These steps apply to Ubuntu 20.04+ and Debian 11+. Debian 10 may still default to `pam_cracklib`; the installer must replace it with `pam_pwquality.so` in that case.

#### Install `libpam-pwquality`

```bash
apt-get install -y libpam-pwquality
```

On Ubuntu 20.04+ this package is typically pre-installed. On Debian 11+ it may need to be added explicitly.

#### Configure `/etc/security/pwquality.conf`

The installer writes (or merges into) `/etc/security/pwquality.conf` with the following baseline. Administrators can later modify these values through the ECUBE Configuration API.

```ini
# /etc/security/pwquality.conf — ECUBE baseline
# Minimum password length (NIST SP 800-63B recommends 12-14 characters).
# dcredit/ucredit/lcredit/ocredit all default to 0 in current releases, meaning
# the credit system is disabled by default — minlen = 14 therefore means exactly
# 14 characters minimum with no character-class bonuses.
minlen = 14

# Minimum number of character classes required (default 0 = disabled).
# The four classes are: digits, uppercase letters, lowercase letters, other.
# N of 4 classes must be present; no specific class is mandated.
minclass = 3

# Reject passwords with more than N same consecutive characters (0 = disabled).
maxrepeat = 3

# Reject passwords containing a monotonic character sequence longer than N
# (e.g. '12345' or 'fedcb'). Default is 0 (disabled).
maxsequence = 4

# Reject passwords containing the username in some form.
# Not checked for usernames shorter than 3 characters. Default is 1 (enabled).
usercheck = 1

# Dictionary check via cracklib. Default is 1 (enabled).
dictcheck = 1

# Minimum character changes (inserts/removals/replacements) required between
# old and new password. Value 0 disables all similarity checks except exact
# reuse. Default is 1.
difok = 5

# Number of retry attempts before returning an error. Default is 1.
retry = 3

# Enforce rules even when the caller is root. Default is off (root can bypass).
# This is critical because ECUBE calls chpasswd via sudo (as root).
enforce_for_root = 1
```

#### Configure `/etc/pam.d/common-password`

The PAM password stack must include `pam_pwquality` (replacing any existing `pam_cracklib` line) and `pam_pwhistory`. The installer should use `pam-auth-update` where possible, or write the file directly when a controlled deployment baseline is required.

```
# Enforce password quality requirements.
# All options (retry, minlen, etc.) are managed in /etc/security/pwquality.conf.
# Per best practice, keep the PAM line minimal — module arguments override conf
# file values, so configuring in both places is redundant.
password  requisite   pam_pwquality.so local_users_only

# Remember the last 12 passwords and prevent reuse.
# use_authtok: use the password token already obtained by pam_pwquality above;
#              do not prompt the user again.
# enforce_for_root: apply history check even when the caller is root
#                   (i.e. when ECUBE calls chpasswd via sudo).
password  required    pam_pwhistory.so remember=12 use_authtok enforce_for_root

# Write the new password to the shadow file.
# use_authtok: use the token from the preceding module; do not prompt again.
# Note: try_first_pass is redundant when use_authtok is present and is omitted.
password  [success=1 default=ignore]  pam_unix.so obscure use_authtok yescrypt
```

The `local_users_only` flag on `pam_pwquality.so` ensures LDAP/SSSD accounts are exempt from complexity enforcement at this layer (they inherit their upstream IdP's policy).

> **Note — `pam_pwquality` module type:** Per the man page, `pam_pwquality` provides **only the `password` module type**. It is not involved in login authentication (`auth`) or account management (`account`). Its own return values are `PAM_SUCCESS`, `PAM_AUTHTOK_ERR` (password fails strength check), `PAM_AUTHTOK_RECOVERY_ERR` (old password not supplied), and `PAM_SERVICE_ERR` (internal error). The expiration-related codes described in the login flow below originate from `pam_unix.so`.

#### Configure Password Expiration

Password expiration defaults are set in `/etc/login.defs` (affects all new accounts) and applied per-account with `chage`. The installer sets the following `login.defs` values:

```ini
PASS_MAX_DAYS   90      # Expire passwords after 90 days
PASS_MIN_DAYS   1       # Prevent same-day password cycling
PASS_WARN_AGE   14      # Warn 14 days before expiry
PASS_MIN_LEN    14      # Backup minimum length (independent of PAM)
```

When the ECUBE API creates a new OS user, it must also run `chage` to apply the expiration policy to newly created accounts, since `login.defs` only affects accounts created after the file is written:

```bash
sudo chage -M 90 -m 1 -W 14 <username>
```

### Application-Layer Design

#### `_run_sudo` and PAM Error Propagation

When `chpasswd` exits non-zero because PAM rejected a password, the stderr text contains PAM's human-readable reason (e.g., `"chpasswd: PAM: BAD PASSWORD: The password fails the dictionary check"`). The `_run_sudo` helper currently raises `OSUserError` with that text. The `_raise_os_error` mapper in `app/routers/admin.py` must be extended to detect PAM rejection patterns and map them to `422 Unprocessable Entity` rather than `500 Internal Server Error`.

Detection pattern (case-insensitive match on stderr):
```python
if "pam:" in lowered or "bad password" in lowered or "password fails" in lowered:
    raise HTTPException(status_code=422, detail=msg)
```

The full PAM error text is safe to forward to the client for password-policy violations because it describes a user-input error, not an internal system state.

#### Password Expiration Detection

ECUBE must check password expiration at login time. The `POST /auth/token` endpoint should inspect the result from `pam.authenticate()` and, if PAM signals account expiry or password expiry conditions, return a structured error (HTTP 401) that the UI can distinguish from a generic credentials failure.

Additionally, a new internal utility must check whether a user's password is nearing expiry using `chage --list` output (or by reading `/etc/shadow` directly with appropriate permissions). This is called at login to surface the warning-period notice.

The table below lists the PAM codes relevant to the login flow. These codes originate from different modules in the PAM stack (`python-pam` calls both `pam_authenticate()` and `pam_acct_mgmt()`):

- `PAM_AUTH_ERR` — from `pam_unix.so` **auth** module on wrong password.
- `PAM_ACCT_EXPIRED`, `PAM_NEW_AUTHTOK_REQD`, `PAM_AUTHTOK_EXPIRED` — from `pam_unix.so` **account management** (`pam_acct_mgmt()`). `pam_pwquality` is not involved here; it only provides the `password` module type and is not called at login time.

After a failed `python-pam` call, `pam_obj.code` contains the integer PAM return code and `pam_obj.reason` contains the corresponding strerror string. The service layer must check `pam_obj.code` against the known constants (from the `pam` module) to classify the failure correctly.

| PAM code | Source | Meaning | HTTP response |
|---|---|---|---|
| `PAM_SUCCESS` | — | Auth and account check passed | 200 OK + token |
| `PAM_AUTH_ERR` | `pam_unix` (auth) | Wrong password | 401 Unauthorized |
| `PAM_ACCT_EXPIRED` | `pam_unix` (account) | Account expired | 401 with `reason: account_expired` |
| `PAM_NEW_AUTHTOK_REQD` | `pam_unix` (account) | Password expired, change required | 401 with `reason: password_expired` |
| `PAM_AUTHTOK_EXPIRED` | `pam_unix` (account) | Password expired (auth-time variant) | 401 with `reason: password_expired` |

#### Forced Password-Change Workflow

When the UI receives a `401` response with `reason: password_expired`, it must present a password-change dialog that accepts the current password, new password, and confirmation before retrying login.

The API must expose a dedicated self-service endpoint:

```
POST /auth/change-password
```

**Request body:** `{ "username", "current_password", "new_password" }`

**Behavior:**
1. Re-authenticate the user with `pam.authenticate(username, current_password)` to verify possession of the current credential, even if the account is flagged as expired.
2. Call `chpasswd` with the new password. PAM enforces complexity and history checks at this point.
3. On success: issue a fresh token and return it in the response (the user is now logged in).
4. On failure: return `422` with the PAM rejection reason.

This endpoint must be accessible without a valid JWT so that an expired-password user can complete the change flow without first obtaining a token.

**Audit events emitted:**
- `PASSWORD_CHANGED` on success (actor = username, target = username)
- `PASSWORD_CHANGE_FAILED` on PAM rejection (actor = username, reason = PAM message category)

#### Admin-Managed `pwquality.conf`

A new admin-only API sub-resource exposes read and write access to the `pam_pwquality` configuration:

```
GET  /admin/password-policy          → returns current pwquality.conf key-value pairs
PUT  /admin/password-policy          → writes updated values to pwquality.conf (admin only)
```

**Implementation notes:**
- The endpoint reads and writes `/etc/security/pwquality.conf`.
- The ECUBE service account must have write permission via a new narrowly scoped `sudoers` rule:
  ```
  ecube ALL=(root) NOPASSWD: /usr/bin/tee /etc/security/pwquality.conf
  ```
  Or, equivalently, a dedicated helper script that validates the input before writing.
- Writes must use an atomic rename pattern: write to a `.tmp` file first, then rename to replace the live file.
- The API must enforce an allowlist of writable keys (`minlen`, `minclass`, `maxrepeat`, `maxsequence`, `maxclassrepeat`, `dictcheck`, `usercheck`, `difok`, `retry`) and reject attempts to set other keys with `422`. The `enforce_for_root` key is not exposed as writable — it is always written as `1` on every PUT to prevent accidental security bypass through a partial update.
- `enforce_for_root` must not be settable to `0` through the API to prevent policy bypass. Attempts to set it to `0` or `false` must be rejected with `422`.
- Each write emits a `PASSWORD_POLICY_UPDATED` audit event with the actor, the previous values, and the new values.

**Schema:**

```python
class PasswordPolicySettings(BaseModel):
    minlen: int       # 12 ≤ minlen ≤ 128
    minclass: int     # 0 ≤ minclass ≤ 4; N of 4 classes required (no specific class mandated)
    maxrepeat: int    # 0 = disabled; rejects passwords with N+ same consecutive characters
    maxsequence: int  # 0 = disabled; rejects monotonic sequences longer than N (e.g. '12345')
    maxclassrepeat: int  # 0 = disabled; rejects N+ consecutive characters of the same class
    dictcheck: int    # 0 or 1; default is 1 (cracklib dictionary check enabled)
    usercheck: int    # 0 or 1; default is 1; not applied to usernames shorter than 3 chars
    difok: int        # 0 disables all similarity checks except exact reuse; default is 1
    retry: int        # 1 ≤ retry ≤ 10; default is 1
    # enforce_for_root is always written as 1 by the API and is not a settable field
```

#### Sudoers Changes

The `deploy/ecube-sudoers` file must be extended with the `chage` and `pwquality.conf` write permissions:

```
ecube ALL=(root) NOPASSWD: /usr/sbin/useradd, /usr/sbin/usermod, /usr/sbin/userdel, /usr/sbin/groupadd, /usr/sbin/groupdel, /usr/sbin/chpasswd, /usr/bin/chage, /usr/bin/tee /etc/security/pwquality.conf
```

### Installer and Ansible Responsibilities

**Scope:** The following steps are performed on the **backend host** where the ECUBE application and OS user management service are deployed. These do not apply to frontend-only installations or satellite deployments.

The ECUBE installer (`install.sh`) and the Ansible role for the ecube-host (backend only) must:

1. Install `libpam-pwquality` if not present.
2. Write the baseline `/etc/security/pwquality.conf` (preserving any existing admin customizations if upgrading).
3. Patch `/etc/pam.d/common-password` to include `pam_pwquality.so` (with `local_users_only`) and `pam_pwhistory.so remember=12`.
4. Set `/etc/login.defs` values `PASS_MAX_DAYS`, `PASS_MIN_DAYS`, `PASS_WARN_AGE`, and `PASS_MIN_LEN`.
5. Install the updated `ecube-sudoers` file (allows the `ecube` service account to execute `chpasswd`, `chage`, and `tee` commands for user management).

These steps must be idempotent so that repeated installer runs do not reset administrator customizations made after initial deployment. In containerized deployments, these configurations are typically baked into the backend container image during the build phase.

### Scope Boundary

**Deployment context:**
- These PAM configurations apply only to **local user account management** deployments (where ECUBE directly manages OS users on the backend host via `chpasswd`).
- In containerized or split-deployment scenarios, PAM configuration is still needed on the backend container/host where ECUBE binary runs, but not on frontend-only hosts.
- Frontend deployments that only consume the ECUBE REST API do not require any PAM configuration.

**Account scope:**
- Policy enforcement through `pam_pwquality` and `pam_pwhistory` applies only to local OS accounts managed via `chpasswd`.
- LDAP and OIDC accounts inherit their upstream IdP's policy. ECUBE does not call `chpasswd` for those accounts.
- The `/admin/password-policy` API is visible and writable only to `admin` role users and is available only on the backend.
- Reading `pwquality.conf` does not require elevated host permissions; the ECUBE service can read the file directly without `sudo`.

## References
