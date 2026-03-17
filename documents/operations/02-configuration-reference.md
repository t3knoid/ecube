# ECUBE Configuration Reference

**Version:** 1.0
**Last Updated:** March 2026
**Audience:** Systems Administrators, Operators, IT Staff
**Source of truth:** `app/config.py` — every setting listed here maps 1-to-1 to a field in the `Settings` class.

---

## Overview

ECUBE reads configuration from **environment variables** or a `.env` file placed in the application root (`/opt/ecube/.env`). Every setting has a built-in default; the `.env` file is **optional** — create one only when you need to override defaults.

> **Path resolution:** Pydantic-settings resolves `.env` relative to the **process working directory**, not the application package. The reference systemd unit ([00-operational-guide.md §4](00-operational-guide.md)) sets `WorkingDirectory=/opt/ecube`, so `.env` resolves to `/opt/ecube/.env`. If you run the application from a different directory (e.g. during development), place the `.env` file in that directory or export the variables directly.

See `.env.example` in the release package for a copy-paste starting point.

---

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://ecube:ecube@localhost/ecube` | PostgreSQL connection URI. |

---

## Security & Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `change-me-in-production-please-rotate-32b` | Signing key for JWT tokens **and** cookie-based sessions (`SESSION_BACKEND=cookie`). Rotating this value invalidates all outstanding JWTs and active cookie sessions. Generate with `openssl rand -hex 32`. |
| `ALGORITHM` | `HS256` | JWT signing algorithm. |
| `TOKEN_EXPIRE_MINUTES` | `60` | Minutes before a locally-issued JWT expires. |
| `ROLE_RESOLVER` | `local` | Role resolver provider: `local`, `ldap`, or `oidc`. |

---

## Local Group-to-Role Mapping

Used when `ROLE_RESOLVER=local`.

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_GROUP_ROLE_MAP` | `{}` | JSON object mapping local OS group names to lists of ECUBE role strings. Example: `{"evidence-admins": ["admin"], "evidence-team": ["processor"]}` |

---

## LDAP Configuration

Used when `ROLE_RESOLVER=ldap`.

| Variable | Default | Description |
|----------|---------|-------------|
| `LDAP_SERVER` | *(empty)* | LDAP server URI, e.g. `ldap://ldap.example.com` or `ldaps://ldap.example.com:636`. |
| `LDAP_BIND_DN` | *(empty)* | Distinguished name for LDAP bind. |
| `LDAP_BIND_PASSWORD` | *(empty)* | Password for the LDAP bind DN. |
| `LDAP_BASE_DN` | *(empty)* | Base DN for LDAP search queries. |
| `LDAP_GROUP_ROLE_MAP` | `{}` | JSON object mapping LDAP group DNs to ECUBE role lists. Example: `{"CN=EvidenceAdmins,DC=corp,DC=example,DC=com": ["admin"]}` |

---

## OIDC Configuration

Used when `ROLE_RESOLVER=oidc`.

| Variable | Default | Description |
|----------|---------|-------------|
| `OIDC_DISCOVERY_URL` | *(empty)* | Full OIDC discovery URL (`.well-known/openid-configuration` endpoint). |
| `OIDC_CLIENT_ID` | *(empty)* | OIDC client ID registered with the identity provider. |
| `OIDC_CLIENT_SECRET` | *(empty)* | OIDC client secret. |
| `OIDC_AUDIENCE` | *(empty)* | Expected `aud` claim value. Leave empty to skip audience validation. |
| `OIDC_GROUP_CLAIM_NAME` | `groups` | JWT claim name containing group memberships. |
| `OIDC_GROUP_ROLE_MAP` | `{}` | JSON object mapping OIDC group values to ECUBE role lists. |
| `OIDC_ALLOWED_ALGORITHMS` | `["RS256","RS384","RS512","ES256","ES384","ES512"]` | Allowed JWT signing algorithms (JSON list). |
| `OIDC_DISCOVERY_TIMEOUT_SECONDS` | `10` | Timeout in seconds for fetching the OIDC discovery document. |

---

## HTTPS / TLS

| Variable | Default | Description |
|----------|---------|-------------|
| `TLS_CERTFILE` | `/opt/ecube/certs/cert.pem` | Path to the TLS certificate file. |
| `TLS_KEYFILE` | `/opt/ecube/certs/key.pem` | Path to the TLS private key file. |

---

## Session & Cookie

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_BACKEND` | `cookie` | Session storage backend: `cookie` (signed browser cookies) or `redis` (server-side, requires `redis` package). |
| `SESSION_COOKIE_NAME` | `ecube_session` | Name of the session cookie sent to browsers. |
| `SESSION_COOKIE_EXPIRATION_SECONDS` | `3600` | Cookie lifetime in seconds. Use `86400` for 24 hours. |
| `SESSION_COOKIE_DOMAIN` | *(empty)* | Domain scope for the cookie. Leave empty for the browser's default rules. |
| `SESSION_COOKIE_SECURE` | `true` | Send cookie only over HTTPS. Set `false` for local dev without TLS. |
| `SESSION_COOKIE_SAMESITE` | `lax` | SameSite cookie attribute: `strict`, `lax`, or `none`. |

> **Note:** The `HttpOnly` flag is always enabled on session cookies and cannot be disabled. Both Starlette's `SessionMiddleware` and ECUBE's `RedisSessionMiddleware` enforce this unconditionally.

---

## Redis

Required only when `SESSION_BACKEND=redis`. If Redis is unavailable, ECUBE automatically falls back to cookie-based sessions and logs a warning.

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | *(empty)* | Redis connection URL, e.g. `redis://localhost:6379/0`. |
| `REDIS_CONNECTION_TIMEOUT` | `5` | Timeout in seconds for establishing a Redis connection. |
| `REDIS_SOCKET_KEEPALIVE` | `true` | Enable TCP keepalive on the Redis socket. |

---

## Operational Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIT_LOG_RETENTION_DAYS` | `365` | Days to retain audit log records. `0` = keep forever. |
| `COPY_JOB_TIMEOUT` | `3600` | Seconds before a copy job is marked FAILED with timeout. `0` = no timeout. |
| `USB_DISCOVERY_INTERVAL` | `30` | Seconds between automatic USB discovery sweeps. `0` = disabled. |

---

## Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Root log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_FORMAT` | `text` | Output format: `text` (human-readable) or `json` (structured). |
| `LOG_FILE` | *(empty)* | Optional path to a log file. Leave empty for stdout only. |
| `LOG_FILE_MAX_BYTES` | `10485760` | Maximum log file size in bytes before rotation (default 10 MB). |
| `LOG_FILE_BACKUP_COUNT` | `5` | Number of rotated backup log files to keep. |

---

## Copy Engine Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `COPY_CHUNK_SIZE_BYTES` | `1048576` | Chunk size in bytes for file copy and checksum computation (1 MB). |
| `COPY_DEFAULT_THREAD_COUNT` | `4` | Default worker thread pool size when not set on a job. |
| `COPY_DEFAULT_MAX_RETRIES` | `3` | Default maximum per-file retries when not set on a job. |
| `COPY_DEFAULT_RETRY_DELAY_SECONDS` | `1.0` | Default retry delay in seconds when not set on a job. |

---

## Subprocess & System Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `SUBPROCESS_TIMEOUT_SECONDS` | `30` | Timeout in seconds for subprocess calls (mount, umount, sync). |
| `MOUNT_BINARY_PATH` | `/bin/mount` | Path to the `mount` binary. |
| `SYNC_BINARY_PATH` | `/bin/sync` | Path to the `sync` binary. |
| `UMOUNT_BINARY_PATH` | `/bin/umount` | Path to the `umount` binary. |
| `USERADD_BINARY_PATH` | `/usr/sbin/useradd` | Path to `useradd` (must match sudoers whitelist). |
| `USERMOD_BINARY_PATH` | `/usr/sbin/usermod` | Path to `usermod` (must match sudoers whitelist). |
| `USERDEL_BINARY_PATH` | `/usr/sbin/userdel` | Path to `userdel` (must match sudoers whitelist). |
| `GROUPADD_BINARY_PATH` | `/usr/sbin/groupadd` | Path to `groupadd` (must match sudoers whitelist). |
| `GROUPDEL_BINARY_PATH` | `/usr/sbin/groupdel` | Path to `groupdel` (must match sudoers whitelist). |
| `CHPASSWD_BINARY_PATH` | `/usr/sbin/chpasswd` | Path to `chpasswd` (must match sudoers whitelist). |
| `PROCFS_MOUNTS_PATH` | `/proc/mounts` | Path to `/proc/mounts` for reading active mounts. |
| `SYSFS_USB_DEVICES_PATH` | `/sys/bus/usb/devices` | Sysfs USB devices directory. |
| `SYSFS_BLOCK_PATH` | `/sys/block` | Sysfs block devices directory. |

---

## Audit Log Pagination

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIT_LOG_DEFAULT_LIMIT` | `100` | Default page size for audit log queries. |
| `AUDIT_LOG_MAX_LIMIT` | `1000` | Maximum allowed page size for audit log queries. |

---

## Database Connection Pool

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POOL_SIZE` | `5` | Number of persistent connections in the pool. |
| `DB_POOL_MAX_OVERFLOW` | `10` | Maximum overflow connections above pool size. |
| `DB_POOL_RECYCLE_SECONDS` | `-1` | Seconds after which a connection is recycled. `-1` = disabled. |

---

## OpenAPI Metadata

| Variable | Default | Description |
|----------|---------|-------------|
| `API_CONTACT_NAME` | `ECUBE Support` | Contact name shown in the OpenAPI spec. |
| `API_CONTACT_EMAIL` | `support@ecube.local` | Contact email shown in the OpenAPI spec. |
