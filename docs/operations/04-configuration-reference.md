# ECUBE Configuration Reference

| Field | Value |
|---|---|
| Title | ECUBE Configuration Reference |
| Purpose | Documents all ECUBE application and deployment configuration settings, environment variables, and their defaults. |
| Updated on | 04/08/26 |
| Audience | Systems administrators, operators, IT staff. |

## Table of Contents

1. [Overview](#overview)
2. [Database](#database)
3. [Target Platform](#target-platform)
4. [Security and Authentication](#security-and-authentication)
5. [Local Group-to-Role Mapping](#local-group-to-role-mapping)
6. [LDAP Configuration](#ldap-configuration)
7. [OIDC/SSO Integration](#oidcsso-integration)
8. [Session Management](#session-management)
9. [Copy Engine](#copy-engine)
10. [Logging](#logging)
11. [Docker Compose Deployment Variables](#docker-compose-deployment-variables)

---

## Overview

ECUBE reads configuration from **environment variables** or a `.env` file placed in the application root (`/opt/ecube/.env`). Every setting has a built-in default; the `.env` file is **optional** — create one only when you need to override defaults.

> **Path resolution:** Pydantic-settings resolves `.env` relative to the **process working directory**, not the application package. The reference systemd unit ([00-operational-guide.md §4](00-operational-guide.md)) sets `WorkingDirectory=/opt/ecube`, so `.env` resolves to `/opt/ecube/.env`. If you run the application from a different directory (e.g. during development), place the `.env` file in that directory or export the variables directly.

See `.env.example` in the release package for a copy-paste starting point.

---

## Database

| Variable       | Default   | Description                |
| -------------- | --------- | -------------------------- |
| `DATABASE_URL` | *(empty)* | PostgreSQL connection URI. Left empty on fresh installs; the setup wizard writes this value after database provisioning. |

---

## Target Platform

| Variable   | Default | Description |
| ---------- | ------- | ----------- |
| `PLATFORM` | `linux` | Target platform for infrastructure implementations. Currently only `linux` adapters are implemented. `windows` is reserved for future use and will raise a runtime error if selected. |

---

## First-Run Setup

These settings control the behaviour of the first-run setup wizard before the application database is provisioned.

| Variable                       | Default       | Description                                                                                                                                                                                                                                                                                                                                                                      |
| ------------------------------ | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PG_SUPERUSER_NAME`            | *(empty)*     | PostgreSQL superuser (or CREATEDB-privileged role) name used by the setup wizard to provision the application database. Cleared from `.env` automatically after successful provisioning. Both Docker and native deployments default to `POSTGRES_USER` (then `ecube`) when not explicitly set. |
| `PG_SUPERUSER_PASS`            | *(empty)*     | Password for `PG_SUPERUSER_NAME`. Cleared from `.env` automatically after successful provisioning. Both Docker and native deployments default to `POSTGRES_PASSWORD` (then `ecube`) when not explicitly set. |
| `SETUP_DOCKER_DB_HOST`         | `postgres`    | PostgreSQL hostname suggested to the setup wizard when the application detects it is running inside a Docker container. The setup wizard pre-fills the database host field with this value when `GET /setup/database/system-info` reports `in_docker: true`. Set this to the Docker Compose service name of your PostgreSQL container if it differs from the default `postgres`. |
| `SETUP_DEFAULT_ADMIN_USERNAME` | *(empty)*     | PostgreSQL admin username suggested by the setup wizard as a last-resort fallback. The cascade is `PG_SUPERUSER_NAME` → `POSTGRES_USER` → this value. The native installer writes this to keep UI defaults aligned with the superuser it created. |

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

## Docker Compose Deployment Variables

These are deployment variables from Docker Compose (not `app/config.py` settings). They apply to Docker-based deployments where the `ecube-app` container serves both the API and the Vue SPA.

| Variable              | Default           | Description                                                                                                         |
| --------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------- |
| `UI_PORT`             | `8443`            | Host port mapped to the `ecube-app` listener. Use `8000` with `ECUBE_NO_TLS=true`.                                 |
| `ECUBE_NO_TLS`        | `false`           | Set to `true` to disable TLS and start uvicorn in plain HTTP mode. Also set `ECUBE_PORT=8000` and `UI_PORT=8000`.   |
| `ECUBE_PORT`          | `8443`            | Internal container port uvicorn listens on. Use `8000` with `ECUBE_NO_TLS=true`.                                   |
| `ECUBE_CERTS_DIR`     | *(not set)*       | Host directory containing `cert.pem` and `key.pem` for TLS. Mounted to `/opt/ecube/certs` inside the container. On first start the entrypoint generates a self-signed certificate if no cert files exist; set this variable and uncomment the certs volume in the compose file to supply your own certificate. Not required when `ECUBE_NO_TLS=true`. |
| `ECUBE_THEMES_DIR`    | `./deploy/themes` | Host directory for optional CSS theme overrides. Mounted to `/opt/ecube/www/themes` inside the container.           |
| `POSTGRES_USER`       | `ecube`           | PostgreSQL user for the `postgres` container. Also used as the default `PG_SUPERUSER_NAME` when not explicitly set. |
| `POSTGRES_PASSWORD`   | *(required)*      | PostgreSQL password for the `postgres` container. Also used as the default `PG_SUPERUSER_PASS` when not explicitly set. |
| `POSTGRES_DB`         | `ecube`           | PostgreSQL database name created by the `postgres` container.                                                       |
| `POSTGRES_HOST_PORT`  | `5432`            | Host port for the PostgreSQL container. Not published by default; add a `ports` mapping to the postgres service in the compose file if needed for external tools. |

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
| `READINESS_MOUNT_CHECK_TIMEOUT_SECONDS` | `1.0` | Timeout in seconds for each mount check in `GET /health/ready`. Keep low to preserve fail-fast readiness behavior. |
| `READINESS_MOUNT_CHECKS_TOTAL_TIMEOUT_SECONDS` | `1.0` | Total timeout budget in seconds for all mount checks in `GET /health/ready` to keep probe latency bounded as mount count grows. |
| `READINESS_USB_DISCOVERY_CACHE_TTL_SECONDS` | `5.0` | Cache TTL (seconds) for successful USB discovery readiness checks in `GET /health/ready`. Reduces repeated sysfs discovery scans under frequent probes while still re-validating periodically. |

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

To enable writing logs to disk, set `LOG_FILE` to an absolute path in your `.env` file (or export it as an environment variable). When `LOG_FILE` is set, ECUBE writes logs to both stdout and the file, rotating the file when it reaches `LOG_FILE_MAX_BYTES`.

Example:

```dotenv
LOG_FILE=/var/log/ecube/app.log
LOG_FILE_MAX_BYTES=10485760
LOG_FILE_BACKUP_COUNT=5
```

Operational notes:

- Ensure the ECUBE service account can create/write the target directory and files (for example `/var/log/ecube`).
- Keep `LOG_FORMAT` consistent with your ingestion pipeline (`text` for local troubleshooting, `json` for SIEM/centralized parsing).
- Leave `LOG_FILE` empty to disable file logging and keep console-only output.

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
| `USB_MOUNT_BASE_PATH`        | `/mnt/ecube`           | Base directory for USB drive mount points. Each drive is mounted at `<USB_MOUNT_BASE_PATH>/<drive_db_id>`. |

---

## Audit Log Pagination

| Variable                  | Default | Description                                      |
| ------------------------- | ------- | ------------------------------------------------ |
| `AUDIT_LOG_DEFAULT_LIMIT` | `100`   | Default page size for audit log queries.         |
| `AUDIT_LOG_MAX_LIMIT`     | `1000`  | Maximum allowed page size for audit log queries. |

---

## Reverse Proxy / Client IP

| Variable  | Default | Description |
| --------- | ------- | ----------- |
| `TRUST_PROXY_HEADERS` | `false` | When `true`, extract client IP from `X-Forwarded-For` / `X-Real-IP` headers for audit logging. Only enable when ECUBE runs behind a trusted reverse proxy that sets these headers. When `false`, the direct TCP connection address is used. |
| `API_ROOT_PATH`       | *(empty)* | ASGI root path passed to FastAPI. Set to `/api` when an external reverse proxy strips the `/api` prefix before forwarding requests to uvicorn. This ensures Swagger UI generates correct server URLs when accessed through the proxy. Leave empty for standard deployments (both native and Docker) where FastAPI serves the frontend directly. |
| `SERVE_FRONTEND_PATH` | *(empty)* | Path to the pre-built frontend directory (e.g. `/opt/ecube/www`). When set, FastAPI serves the SPA directly and enables an `/api` prefix-stripping middleware so the frontend's `/api/...` requests reach the correct routes. Set automatically in Docker images. Leave empty only when an external reverse proxy or separate web server handles frontend serving. |

---

## Directory Browsing

| Variable                    | Default                            | Description |
| --------------------------- | ---------------------------------- | ----------- |
| `BROWSE_ALLOWED_PREFIXES`   | `["/mnt/ecube/", "/nfs/", "/smb/"]` | JSON array of filesystem path prefixes permitted as browse roots. Only paths whose `realpath` starts with one of these prefixes are served by `GET /browse`. Override via environment variable to match the actual mount hierarchy on your deployment. |
| `BROWSE_MAX_DIR_ENTRIES`    | `50000`                            | Maximum number of entries a directory may contain before the browse endpoint rejects the request with HTTP 400. Prevents denial-of-service from directories with hundreds of thousands of files. Set to `0` to disable the limit. |

---

## Database Connection Pool

| Variable                  | Default | Description                                                    |
| ------------------------- | ------- | -------------------------------------------------------------- |
| `DB_POOL_SIZE`            | `5`     | Number of persistent connections in the pool.                  |
| `DB_POOL_MAX_OVERFLOW`    | `10`    | Maximum overflow connections above pool size.                  |
| `DB_POOL_RECYCLE_SECONDS` | `-1`    | Seconds after which a connection is recycled. `-1` = disabled. |

These settings control SQLAlchemy connection pooling behavior for API requests that need database access.

Effective maximum concurrent checked-out connections is `DB_POOL_SIZE + DB_POOL_MAX_OVERFLOW`.

Per-setting impact and tuning guidance:

| Setting | Increase value: typical effect | Decrease value: typical effect | When an administrator should modify it |
| ------- | ------------------------------ | ------------------------------ | -------------------------------------- |
| `DB_POOL_SIZE` | More warm (already-open) connections, usually lower connection-acquisition latency during steady load, higher baseline memory and DB connection usage. | Lower baseline memory and DB connection usage, but greater chance of waiting for a free connection during bursty traffic. | Increase when normal concurrent API traffic is consistently above current pool capacity. Decrease on small systems or when PostgreSQL `max_connections` is tight and ECUBE should use fewer reserved connections. |
| `DB_POOL_MAX_OVERFLOW` | Allows larger short bursts above the steady pool size, reducing queueing latency during spikes, but can create sudden load on PostgreSQL and increase peak memory usage. | Caps burst concurrency to protect PostgreSQL and reduce peak resource use, but requests are more likely to wait under spikes. | Increase when short traffic spikes cause connection-pool contention. Decrease when the database becomes unstable during bursts or when you need stricter connection caps. |
| `DB_POOL_RECYCLE_SECONDS` | Higher value (or `-1`) means fewer reconnects and lower reconnect overhead, but idle/stale connections may survive longer in environments with network idle timeouts. | Lower value forces more frequent reconnects, which can prevent stale-connection errors after NAT/LB/firewall idle drops, but adds reconnect overhead and can slightly increase tail latency. | Set a finite value when your infrastructure drops long-idle TCP connections (load balancers, firewalls, NAT gateways). Leave `-1` when stale-connection issues are not observed. |

Practical tuning workflow:

1. Keep defaults unless you observe pool contention or stale-connection failures.
2. If requests queue during normal load, raise `DB_POOL_SIZE` gradually (for example by 2-5) and monitor API latency plus PostgreSQL connection counts.
3. If contention occurs only during short spikes, adjust `DB_POOL_MAX_OVERFLOW` before making large steady-state `DB_POOL_SIZE` increases.
4. If you see intermittent failures after idle periods, set `DB_POOL_RECYCLE_SECONDS` to a value lower than your network idle timeout.

Operational notes:

- Every open connection consumes resources in both ECUBE and PostgreSQL, so larger pools trade memory for lower wait time.
- Changes in `.env` take effect after restarting the ECUBE application process.
- Coordinate pool sizing with PostgreSQL `max_connections` and other applications sharing the same database server.

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

## References

- [docs/operations/01-installation.md](01-installation.md)
