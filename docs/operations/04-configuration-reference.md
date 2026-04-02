# ECUBE Configuration Reference

**Version:** 1.0
**Last Updated:** March 2026
**Audience:** Systems Administrators, Operators, IT Staff
**Source of truth:** `app/config.py` — all ECUBE application settings in this document map 1-to-1 to fields in the `Settings` class. Deployment-only Docker Compose variables are explicitly marked in their own section.

---

## Overview

ECUBE reads configuration from **environment variables** or a `.env` file placed in the application root (`/opt/ecube/.env`). Every setting has a built-in default; the `.env` file is **optional** — create one only when you need to override defaults.

> **Path resolution:** Pydantic-settings resolves `.env` relative to the **process working directory**, not the application package. The reference systemd unit ([00-operational-guide.md §4](00-operational-guide.md)) sets `WorkingDirectory=/opt/ecube`, so `.env` resolves to `/opt/ecube/.env`. If you run the application from a different directory (e.g. during development), place the `.env` file in that directory or export the variables directly.

See `.env.example` in the release package for a copy-paste starting point.

---

## Database

| Variable       | Default                                    | Description                |
| -------------- | ------------------------------------------ | -------------------------- |
| `DATABASE_URL` | `postgresql://ecube:ecube@localhost/ecube` | PostgreSQL connection URI. |

---

## Target Platform

| Variable   | Default | Description |
| ---------- | ------- | ----------- |
| `PLATFORM` | `linux` | Target platform for infrastructure implementations. Currently only `linux` adapters are implemented. `windows` is reserved for future use and will raise a runtime error if selected. |

---

## First-Run Setup

These settings control the behaviour of the first-run setup wizard before the application database is provisioned.

| Variable               | Default    | Description                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SETUP_DOCKER_DB_HOST` | `postgres` | PostgreSQL hostname suggested to the setup wizard when the application detects it is running inside a Docker container. The setup wizard pre-fills the database host field with this value when `GET /setup/database/system-info` reports `in_docker: true`. Set this to the Docker Compose service name of your PostgreSQL container if it differs from the default `postgres`. |

---

## Security & Authentication

| Variable               | Default                                     | Description                                                                                                                                                                                                 |
| ---------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`           | `change-me-in-production-please-rotate-32b` | Signing key for JWT tokens **and** cookie-based sessions (`SESSION_BACKEND=cookie`). Rotating this value invalidates all outstanding JWTs and active cookie sessions. Generate with `openssl rand -hex 32`. |
| `ALGORITHM`            | `HS256`                                     | JWT signing algorithm.                                                                                                                                                                                      |
| `TOKEN_EXPIRE_MINUTES` | `60`                                        | Minutes before a locally-issued JWT expires.                                                                                                                                                                |
| `ROLE_RESOLVER`        | `local`                                     | Role resolver provider: `local`, `ldap`, or `oidc`.                                                                                                                                                         |

---

## Local Group-to-Role Mapping

Used when `ROLE_RESOLVER=local`.

| Variable               | Default | Description                                                                                                                                        |
| ---------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LOCAL_GROUP_ROLE_MAP` | `{}`    | JSON object mapping local OS group names to lists of ECUBE role strings. Example: `{"evidence-admins": ["admin"], "evidence-team": ["processor"]}` |

---

## LDAP Configuration

Used when `ROLE_RESOLVER=ldap`.

| Variable              | Default   | Description                                                                                                                   |
| --------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `LDAP_SERVER`         | *(empty)* | LDAP server URI, e.g. `ldap://ldap.example.com` or `ldaps://ldap.example.com:636`.                                            |
| `LDAP_BIND_DN`        | *(empty)* | Distinguished name for LDAP bind.                                                                                             |
| `LDAP_BIND_PASSWORD`  | *(empty)* | Password for the LDAP bind DN.                                                                                                |
| `LDAP_BASE_DN`        | *(empty)* | Base DN for LDAP search queries.                                                                                              |
| `LDAP_GROUP_ROLE_MAP` | `{}`      | JSON object mapping LDAP group DNs to ECUBE role lists. Example: `{"CN=EvidenceAdmins,DC=corp,DC=example,DC=com": ["admin"]}` |

---

## OIDC Configuration

Used when `ROLE_RESOLVER=oidc`.

| Variable                         | Default                                             | Description                                                            |
| -------------------------------- | --------------------------------------------------- | ---------------------------------------------------------------------- |
| `OIDC_DISCOVERY_URL`             | *(empty)*                                           | Full OIDC discovery URL (`.well-known/openid-configuration` endpoint). |
| `OIDC_CLIENT_ID`                 | *(empty)*                                           | OIDC client ID registered with the identity provider.                  |
| `OIDC_CLIENT_SECRET`             | *(empty)*                                           | OIDC client secret.                                                    |
| `OIDC_AUDIENCE`                  | *(empty)*                                           | Expected `aud` claim value. Leave empty to skip audience validation.   |
| `OIDC_GROUP_CLAIM_NAME`          | `groups`                                            | JWT claim name containing group memberships. Some providers use `roles` or another custom claim name; override to match your identity provider. |
| `OIDC_GROUP_ROLE_MAP`            | `{}`                                                | JSON object mapping OIDC group values to ECUBE role lists.             |
| `OIDC_ALLOWED_ALGORITHMS`        | `["RS256","RS384","RS512","ES256","ES384","ES512"]` | Allowed JWT signing algorithms (JSON list).                            |
| `OIDC_DISCOVERY_TIMEOUT_SECONDS` | `10`                                                | Timeout in seconds for fetching the OIDC discovery document.           |

---

## HTTPS / TLS

| Variable       | Default                     | Description                       |
| -------------- | --------------------------- | --------------------------------- |
| `TLS_CERTFILE` | `/opt/ecube/certs/cert.pem` | Path to the TLS certificate file. |
| `TLS_KEYFILE`  | `/opt/ecube/certs/key.pem`  | Path to the TLS private key file. |

---

## UI Container (Docker Compose)

These are deployment variables from Docker Compose (not `app/config.py` settings).

| Variable           | Default           | Description                                                                                                         |
| ------------------ | ----------------- | ------------------------------------------------------------------------------------------------------------------- |
| `UI_PORT`          | `8443`            | Host port mapped to the `ecube-ui` HTTPS listener (port 443 inside the container).                                  |
| `ECUBE_CERTS_DIR`  | `./deploy/certs`  | Host directory containing `cert.pem` and `key.pem` for nginx TLS termination. Use `/opt/ecube/certs` in production. |
| `ECUBE_THEMES_DIR` | `./deploy/themes` | Host directory for optional CSS theme overrides served by nginx. Use `/opt/ecube/themes` in production.             |

For off-the-shelf themes, custom theme creation, default-theme behavior, and logo configuration details, see [11-theme-and-branding-guide.md](11-theme-and-branding-guide.md).

---

## Session & Cookie

| Variable                            | Default         | Description                                                                                                                                                                                                                     |
| ----------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SESSION_BACKEND`                   | `cookie`        | Session storage backend: `cookie` (signed browser cookies) or `redis` (server-side, requires `redis` package).                                                                                                                  |
| `SESSION_COOKIE_NAME`               | `ecube_session` | Name of the session cookie sent to browsers.                                                                                                                                                                                    |
| `SESSION_COOKIE_EXPIRATION_SECONDS` | `3600`          | Cookie lifetime in seconds. Use `86400` for 24 hours.                                                                                                                                                                           |
| `SESSION_COOKIE_DOMAIN`             | *(empty)*       | Domain scope for the cookie. Leave empty for the browser's default rules.                                                                                                                                                       |
| `SESSION_COOKIE_SECURE`             | `true`          | Send cookie only over HTTPS. Set `false` for local dev without TLS. **Must be `true` when `SESSION_COOKIE_SAMESITE=none`** — browsers reject `SameSite=None` cookies without the `Secure` flag; ECUBE enforces this at startup. |
| `SESSION_COOKIE_SAMESITE`           | `lax`           | SameSite cookie attribute: `strict`, `lax`, or `none`.                                                                                                                                                                          |

> **Note:** The `HttpOnly` flag is always enabled on session cookies and cannot be disabled. Both Starlette's `SessionMiddleware` and ECUBE's `RedisSessionMiddleware` enforce this unconditionally.

---

## Redis

Required only when `SESSION_BACKEND=redis`. If Redis is unavailable, ECUBE automatically falls back to cookie-based sessions and logs a warning.

| Variable                   | Default   | Description                                             |
| -------------------------- | --------- | ------------------------------------------------------- |
| `REDIS_URL`                | *(empty)* | Redis connection URL, e.g. `redis://localhost:6379/0`.  |
| `REDIS_CONNECTION_TIMEOUT` | `5`       | Timeout in seconds for establishing a Redis connection. |
| `REDIS_SOCKET_KEEPALIVE`   | `true`    | Enable TCP keepalive on the Redis socket.               |

> **Redis session security:** The Redis backend protects against session fixation (stale or attacker-chosen session-id cookies are discarded when no matching Redis key exists), validates session-id cookie format before lookup, and only issues `Set-Cookie` headers when data has been successfully persisted to Redis. All Redis I/O is non-blocking (async).

---

## Operational Tuning

| Variable                   | Default | Description                                                                |
| -------------------------- | ------- | -------------------------------------------------------------------------- |
| `AUDIT_LOG_RETENTION_DAYS` | `365`   | Days to retain audit log records. `0` = keep forever.                      |
| `COPY_JOB_TIMEOUT`         | `3600`  | Seconds before a copy job is marked FAILED with timeout. `0` = no timeout. |
| `USB_DISCOVERY_INTERVAL`   | `30`    | Seconds between automatic USB discovery sweeps. `0` = disabled.            |

---

## CORS

| Variable               | Default | Description |
| ---------------------- | ------- | ----------- |
| `CORS_ALLOWED_ORIGINS` | `[]`    | JSON array of origins allowed for cross-origin requests. Leave empty in same-origin deployments. Example: `["http://localhost:5173"]`. |

---

## Webhook Callbacks

| Variable                     | Default | Description                                                                                                                               |
| ---------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `CALLBACK_TIMEOUT_SECONDS`   | `30`    | Timeout in seconds for each individual callback HTTP request.                                                                             |
| `CALLBACK_ALLOW_PRIVATE_IPS` | `false` | Allow callbacks to private/reserved IP addresses. Must remain `false` in production to prevent SSRF.                                      |
| `CALLBACK_MAX_WORKERS`       | `4`     | Maximum number of concurrent callback delivery threads.                                                                                   |
| `CALLBACK_MAX_PENDING`       | `100`   | Maximum outstanding deliveries (queued + in-flight). When exceeded, new deliveries are dropped and logged as `CALLBACK_DELIVERY_DROPPED`. |

---

## Logging

| Variable                | Default    | Description                                                     |
| ----------------------- | ---------- | --------------------------------------------------------------- |
| `LOG_LEVEL`             | `INFO`     | Root log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`.            |
| `LOG_FORMAT`            | `text`     | Output format: `text` (human-readable) or `json` (structured).  |
| `LOG_FILE`              | *(empty)*  | Optional path to a log file. Leave empty for stdout only.       |
| `LOG_FILE_MAX_BYTES`    | `10485760` | Maximum log file size in bytes before rotation (default 10 MB). |
| `LOG_FILE_BACKUP_COUNT` | `5`        | Number of rotated backup log files to keep.                     |

---

## Copy Engine Tuning

| Variable                           | Default   | Description                                                        |
| ---------------------------------- | --------- | ------------------------------------------------------------------ |
| `COPY_CHUNK_SIZE_BYTES`            | `1048576` | Chunk size in bytes for file copy and checksum computation (1 MB). |
| `COPY_DEFAULT_THREAD_COUNT`        | `4`       | Default worker thread pool size when not set on a job.             |
| `COPY_DEFAULT_MAX_RETRIES`         | `3`       | Default maximum per-file retries when not set on a job.            |
| `COPY_DEFAULT_RETRY_DELAY_SECONDS` | `1.0`     | Default retry delay in seconds when not set on a job.              |

---

## Subprocess & System Paths

| Variable                     | Default                | Description                                                    |
| ---------------------------- | ---------------------- | -------------------------------------------------------------- |
| `SUBPROCESS_TIMEOUT_SECONDS` | `30`                   | Timeout in seconds for subprocess calls (mount, umount, sync). |
| `MOUNT_BINARY_PATH`          | `/bin/mount`           | Path to the `mount` binary.                                    |
| `SYNC_BINARY_PATH`           | `/bin/sync`            | Path to the `sync` binary.                                     |
| `UMOUNT_BINARY_PATH`         | `/bin/umount`          | Path to the `umount` binary.                                   |
| `MOUNTPOINT_BINARY_PATH`     | `/bin/mountpoint`      | Path to the `mountpoint` binary (checks whether a path is currently mounted). |
| `BLKID_BINARY_PATH`          | `/sbin/blkid`          | Path to the `blkid` binary (primary filesystem type detection). |
| `LSBLK_BINARY_PATH`          | `/bin/lsblk`           | Path to the `lsblk` binary (filesystem detection fallback). |
| `MKFS_EXT4_PATH`             | `/sbin/mkfs.ext4`      | Path to the `mkfs.ext4` binary (used when formatting drives to ext4). |
| `MKFS_EXFAT_PATH`            | `/sbin/mkfs.exfat`     | Path to the `mkfs.exfat` binary (used when formatting drives to exFAT). |
| `USE_SUDO`                   | `true`                 | Prepends `sudo` to OS user/group management commands. Set `false` when running as root (for example inside Docker containers). |
| `USERADD_BINARY_PATH`        | `/usr/sbin/useradd`    | Path to `useradd` (must match sudoers whitelist).              |
| `USERMOD_BINARY_PATH`        | `/usr/sbin/usermod`    | Path to `usermod` (must match sudoers whitelist).              |
| `USERDEL_BINARY_PATH`        | `/usr/sbin/userdel`    | Path to `userdel` (must match sudoers whitelist).              |
| `GROUPADD_BINARY_PATH`       | `/usr/sbin/groupadd`   | Path to `groupadd` (must match sudoers whitelist).             |
| `GROUPDEL_BINARY_PATH`       | `/usr/sbin/groupdel`   | Path to `groupdel` (must match sudoers whitelist).             |
| `CHPASSWD_BINARY_PATH`       | `/usr/sbin/chpasswd`   | Path to `chpasswd` (must match sudoers whitelist).             |
| `PROCFS_MOUNTS_PATH`         | `/proc/mounts`         | Path to `/proc/mounts` for reading active mounts.              |
| `PROCFS_DISKSTATS_PATH`      | `/proc/diskstats`      | Path to `/proc/diskstats` for block-device I/O statistics. |
| `SYSFS_USB_DEVICES_PATH`     | `/sys/bus/usb/devices` | Sysfs USB devices directory.                                   |
| `SYSFS_BLOCK_PATH`           | `/sys/block`           | Sysfs block devices directory.                                 |

---

## Audit Log Pagination

| Variable                  | Default | Description                                      |
| ------------------------- | ------- | ------------------------------------------------ |
| `AUDIT_LOG_DEFAULT_LIMIT` | `100`   | Default page size for audit log queries.         |
| `AUDIT_LOG_MAX_LIMIT`     | `1000`  | Maximum allowed page size for audit log queries. |

---

## Reverse Proxy / Client IP

| Variable              | Default | Description                                                                                                                                                                                                                                 |
| --------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TRUST_PROXY_HEADERS` | `false` | When `true`, extract client IP from `X-Forwarded-For` / `X-Real-IP` headers for audit logging. Only enable when ECUBE runs behind a trusted reverse proxy that sets these headers. When `false`, the direct TCP connection address is used. |
| `API_ROOT_PATH`       | *(empty)* | ASGI root path passed to FastAPI. Set to `/api` when a reverse proxy strips the `/api` prefix before forwarding requests to uvicorn (the standard Docker and nginx configuration). This ensures Swagger UI generates correct server URLs when accessed through the proxy. Leave empty when uvicorn is accessed directly. |

---

## Database Connection Pool

| Variable                  | Default | Description                                                    |
| ------------------------- | ------- | -------------------------------------------------------------- |
| `DB_POOL_SIZE`            | `5`     | Number of persistent connections in the pool.                  |
| `DB_POOL_MAX_OVERFLOW`    | `10`    | Maximum overflow connections above pool size.                  |
| `DB_POOL_RECYCLE_SECONDS` | `-1`    | Seconds after which a connection is recycled. `-1` = disabled. |

---

## OpenAPI Metadata

| Variable            | Default               | Description                              |
| ------------------- | --------------------- | ---------------------------------------- |
| `API_CONTACT_NAME`  | `ECUBE Support`       | Contact name shown in the OpenAPI spec.  |
| `API_CONTACT_EMAIL` | `support@ecube.local` | Contact email shown in the OpenAPI spec. |

---

## Frontend Build Variables

These variables are consumed by **Vite at build time** (not at runtime). They must be set in the environment where `npm run build` executes — typically a CI step or a custom `Dockerfile` build argument.

| Variable             | Default   | Description                                                                                                                                                                               |
| -------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VITE_API_BASE_URL`  | *(unset)* | Override the API base URL for cross-origin or two-machine deployments where the API is hosted on a different server. Example: `https://api.corp.local:8443/api`. When unset the frontend resolves the API base as `/api` relative to the page origin, which is correct for standard single-server and Docker deployments. |

Use this variable only when the frontend cannot reach the API through same-origin `/api` proxying.

Examples:

- Same origin (recommended): UI `https://ecube.example.com` and API path `https://ecube.example.com/api` -> leave `VITE_API_BASE_URL` unset.
- Different domain: UI `https://portal.example.com` and API `https://api.example.com/api` -> set `VITE_API_BASE_URL=https://api.example.com/api`.
- Same domain, different port: UI `https://ecube.example.com` and API `https://ecube.example.com:9443/api` -> set `VITE_API_BASE_URL=https://ecube.example.com:9443/api`.
- Same host and port, different scheme (`http` vs `https`): treat as cross-origin and set `VITE_API_BASE_URL`.

Additional behavior notes:

- `VITE_API_BASE_URL` is embedded at build time. Changing it requires rebuilding the frontend assets.
- Trailing slashes are normalized by the frontend (`https://api.example.com/api/` becomes `https://api.example.com/api`).

**CORS note:** If you set `VITE_API_BASE_URL`, ensure the backend's `CORS_ALLOWED_ORIGINS` includes the frontend origin (for example `https://portal.example.com`), otherwise browser preflight requests will be rejected.
