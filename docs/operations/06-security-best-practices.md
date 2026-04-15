# ECUBE Security Best Practices

| Field | Value |
|---|---|
| Title | Security Best Practices |
| Purpose | Provides operational security guidance for hardening ECUBE deployments, including network isolation, certificate management, and access control. |
| Updated on | 04/08/26 |
| Audience | Systems administrators, security engineers. |

## Table of Contents

1. [Network Isolation](#1-network-isolation)
2. [Certificate Management](#2-certificate-management)
3. [Credential Management](#3-credential-management)
4. [Access Control](#4-access-control)
5. [File Permissions](#5-file-permissions)
6. [Audit Log Monitoring](#6-audit-log-monitoring)
7. [Firewall Configuration](#7-firewall-configuration)
8. [Directory Browse Hardening](#8-directory-browse-hardening)
9. [Reverse Proxy Deployment](#9-reverse-proxy-deployment)

---

## 1. Network Isolation

- **Database (native):** Keep PostgreSQL reachable only from the ECUBE system layer or trusted admin hosts. Do not expose PostgreSQL broadly.
- **Database (Docker Compose):** PostgreSQL is not published to the host by default. If you add a `ports` mapping for external tooling, bind it to `127.0.0.1` only (e.g. `127.0.0.1:5432:5432`).
- **API (external access):** Expose HTTPS only to clients.
- **API (internal architecture):** Docker deployments may use internal HTTP between a reverse proxy container and the backend; this is acceptable only when that backend port is not externally exposed. Native installs serve HTTPS directly from uvicorn.
- **Mounts:** NFS/SMB shares on isolated VLAN if possible
- **USB:** Local USB hub, not exposed over network

### 1.1 Network Ports Reference

Use the table below to determine which ports should exist in each deployment and which ones should be externally reachable.

| Port / Protocol | Service | When Used | Exposure Guidance |
| --- | --- | --- | --- |
| `8443/tcp` | ECUBE service HTTPS | Default native install port; also used as alternate published UI port in Docker | Primary client-facing ingress. Allow from trusted client networks. |
| `80/tcp` | ECUBE service HTTP | Native `--no-tls` installs; also optional for Let's Encrypt HTTP-01 certificate issuance | Expose only in lab/testing or when TLS is terminated by an external load balancer. |
| `8000/tcp` | FastAPI backend HTTP | Internal-only backend port in Docker Compose | Do not publish externally. Keep reachable only from the Docker container network. |
| `5432/tcp` | PostgreSQL | Native local/remote DB, Docker Compose postgres service | Restrict to ECUBE backend host(s) and approved admin paths only. Avoid broad exposure. |
| `22/tcp` | SSH | Administrative access to host(s) | Restrict to management networks or VPN only. |
| `2049/tcp` | NFS | Evidence source mounts when using NFS | Allow only between ECUBE host(s) and approved file servers. |
| `445/tcp` / `139/tcp` | SMB/CIFS | Evidence source mounts when using SMB | Allow only between ECUBE host(s) and approved file servers. |

### 1.2 PostgreSQL and Reverse Proxy Best Practices

#### PostgreSQL exposure

- Prefer PostgreSQL on a private interface, loopback, or isolated backend subnet.
- Do not expose `5432/tcp` to general client networks.
- In Docker Compose, remove the PostgreSQL host port mapping unless operators explicitly need host-side access.
- If host-side access is required, bind PostgreSQL to `127.0.0.1` or a dedicated admin interface instead of all interfaces.
- Permit PostgreSQL ingress only from ECUBE backend hosts and tightly controlled admin sources.

#### PostgreSQL transport security (SSL/TLS)

- Require encrypted app-to-database transport when PostgreSQL is remote or crosses host boundaries.
- Prefer certificate validation (`sslmode=verify-full`) with a trusted CA bundle.
- Minimum acceptable fallback for internal trusted networks is `sslmode=require` when full verification cannot yet be configured.
- Avoid `sslmode=disable` outside local single-host lab scenarios.

Examples for `DATABASE_URL`:

```env
# Strongly recommended: full certificate verification
DATABASE_URL=postgresql://ecube:strong-pass@db.example.com:5432/ecube?sslmode=verify-full&sslrootcert=/etc/ssl/certs/org-db-ca.pem

# Transitional internal-only fallback: encryption without hostname/CA verification
DATABASE_URL=postgresql://ecube:strong-pass@db.internal:5432/ecube?sslmode=require
```

#### Reverse proxy ingress

When deploying ECUBE behind an external reverse proxy (load balancer, CDN, or Docker UI container):

- Terminate TLS at the reverse proxy.
- Keep backend application ports non-public and reachable only from the reverse proxy.
- Set `TRUST_PROXY_HEADERS=true` only when the proxy is trusted. If the proxy also strips an `/api` prefix before forwarding, set `API_ROOT_PATH=/api`.
- Use the reverse proxy to enforce HTTPS, constrain TLS versions, and centralize certificate rotation.

For native installs (the default), ECUBE serves the frontend directly and does not require a reverse proxy.

Recommended posture (when using a reverse proxy):

- Clients -> reverse proxy over HTTPS
- Reverse proxy -> backend over localhost or private container network
- Backend -> PostgreSQL over private network path only

## 2. Certificate Management

The installer generates a self-signed certificate by default. That is acceptable for lab bring-up only and should be replaced before production use.

Preferred certificate sources:

- Organization-managed CA certificate
- Let's Encrypt / certbot
- Self-signed certificate for temporary testing only

For full issuance and renewal procedures, see [05-tls-certificates-and-letsencrypt.md](05-tls-certificates-and-letsencrypt.md).

Example certbot command (standalone mode — temporarily binds port 80 for the ACME challenge):

```bash
sudo certbot certonly --standalone -d ecube.example.com
```

After issuance, copy the certificate files into `<install-dir>/certs/`, set appropriate ownership, and restart the service.

If you manage TLS settings directly in an external reverse proxy, enforce modern TLS versions in its configuration:

```
ssl_protocols TLSv1.2 TLSv1.3;
```

For standard deployments where uvicorn terminates TLS, replace the self-signed certificate in `<install-dir>/certs/` with a CA-signed certificate and restart the service.

## 3. Credential Management

```bash
# .env is already listed in .gitignore — never override this or commit secrets.
# Verify: grep '\.env' .gitignore

# Rotate SECRET_KEY annually
# Generate new key: openssl rand -hex 32
# Update .env and restart service

# Use strong LDAP/OIDC credentials
# Rotate LDAP bind password periodically
# Store in secrets manager (HashiCorp Vault, etc.) if available
```

Additional guidance:

- Keep `SESSION_COOKIE_SECURE=true` in production so browser session cookies are sent only over HTTPS.
- Leave `CALLBACK_ALLOW_PRIVATE_IPS=false` in production unless you have a tightly controlled internal webhook target and understand the SSRF tradeoff.
- In Docker Compose, replace the default/example secrets in `.env` before any real deployment.

## 4. Access Control

- Restrict API access to trusted networks (firewall rules)
- Use VPN or SSH tunnel for remote access
- Enable audit logging for all operations (enabled by default)
- Review audit logs regularly through the API or approved database access paths.

### 4.1 SSH Hardening For Backend Hosts

- Restrict SSH to management networks, bastion hosts, or VPN-only paths.
- Use dedicated host-admin accounts for OS administration.
- Do not assume members of `ecube-admins`, `ecube-managers`, `ecube-processors`, or `ecube-auditors` should automatically have shell access to the backend host.

For dedicated ECUBE hosts, consider explicitly denying SSH for ECUBE role groups so application users cannot log into the backend OS directly:

```sshconfig
# /etc/ssh/sshd_config.d/ecube-hardening.conf
DenyGroups ecube-admins ecube-managers ecube-processors ecube-auditors
```

Operational guidance:

- Apply this only when you have separate host-admin accounts that are not members of ECUBE role groups.
- Validate configuration before reload:

```bash
sudo sshd -t
```

- Reload SSH only after validation succeeds:

```bash
sudo systemctl reload ssh
```

- Prefer an `sshd_config.d` drop-in over editing the base sshd config file.
- On LDAP/SSSD/domain-managed hosts, verify group resolution carefully before using `DenyGroups`, because directory-backed group membership may be broader than expected.

If operators require SSH access and ECUBE access on the same account, do not use `DenyGroups`; instead restrict SSH by source network, VPN, bastion, or `AllowGroups`/`AllowUsers` rules that reflect the host administration model.

## 5. File Permissions

```bash
# Restrict .env file to ecube user only
sudo chmod 600 /opt/ecube/.env
sudo chown ecube:ecube /opt/ecube/.env
```

The application's `.env` rewrite logic (triggered by database provisioning or settings updates via the API) preserves the original file's ownership and permission mode. Operators do not need to re-apply `chown`/`chmod` after configuration changes made through the API.

# Restrict certificate files for backend-only TLS termination
sudo chmod 600 /opt/ecube/certs/key.pem
sudo chmod 644 /opt/ecube/certs/cert.pem

# Restrict venv
sudo chmod 750 /opt/ecube/venv
sudo chown -R ecube:ecube /opt/ecube
```

Certificate ownership:

- Native installs: private key and cert are owned by `ecube:ecube` (`600` for key, `644` for cert) since uvicorn terminates TLS directly.
- Docker deployments with a UI container: private key ownership depends on the container configuration.

Follow the topology-specific guidance in [01-installation.md](01-installation.md), [02-manual-installation.md](02-manual-installation.md), and [05-tls-certificates-and-letsencrypt.md](05-tls-certificates-and-letsencrypt.md).

## 6. Audit Log Monitoring

```bash
# Export audit logs via API (works regardless of whether PostgreSQL is local or managed)
curl -k -H "Authorization: Bearer $TOKEN" \
  "https://localhost:8443/audit?limit=1000"

# Direct database query example (only when direct PostgreSQL access is available)
psql -U ecube -d ecube << 'EOF'
SELECT user, COUNT(*) as failures 
FROM audit_logs 
WHERE action = 'AUTH_FAILURE' 
  AND timestamp >= NOW() - INTERVAL '1 hour'
GROUP BY user 
HAVING COUNT(*) > 5;
EOF
```

Notes:

- `AUTH_FAILURE` and `AUTH_SUCCESS` are both recorded by the application.
- For API-based reviews, remember that `client_ip` is redacted for some lower-privilege roles.

## 7. Firewall Configuration

```bash
# Native deployment: allow the ECUBE service port
sudo ufw allow 8443/tcp

# Deny all other inbound by default
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```

Topology-specific notes:

- Native install (default HTTPS): allow `8443/tcp` (or the configured `--api-port`).
- Native `--no-tls` install: allow `80/tcp` (or the configured `--api-port`).
- Docker Compose deployment: allow only the published UI HTTPS port (`8443` by default). The backend port `8000` should remain unpublished.
- Docker Compose PostgreSQL: if you do not need host access to PostgreSQL, remove the port mapping. If host access is required, bind it to localhost only instead of all interfaces.

## References

- [docs/operations/05-tls-certificates-and-letsencrypt.md](05-tls-certificates-and-letsencrypt.md)
- [docs/requirements/10-security-and-access-control.md](../requirements/10-security-and-access-control.md)

---

## 8. Directory Browse Hardening

The `GET /browse` endpoint allows authenticated users to list directory contents of active mount points (USB drives and network shares). Three layers protect against unauthorized filesystem access:

1. **Database validation:** The `path` parameter must match a registered, active mount root in the database. Arbitrary paths are rejected with `403`.
2. **Realpath containment:** The `subdir` parameter is resolved via `os.path.realpath` and checked to be within the mount root. Path-traversal attempts (`../../etc`) are rejected with `400`.
3. **Prefix allowlist:** The resolved path must start with one of the `BROWSE_ALLOWED_PREFIXES` values. This provides defence-in-depth against mount-root misconfiguration.

**Recommendations:**

- Override `BROWSE_ALLOWED_PREFIXES` to match your actual mount hierarchy. The default (`/mnt/ecube/`, `/nfs/`, `/smb/`) covers common layouts but may be broader than needed.
- Avoid adding broad prefixes like `/` or `/home` to the allowlist.
- Symlinks within browsed directories are listed as `type: "symlink"` but are not followed or navigable.
- All browse requests are audit-logged with action `BROWSE_DIRECTORY`, including the actor, resolved path, and client IP.

---

## 9. Reverse Proxy Deployment

ECUBE does not require a reverse proxy — uvicorn serves both the API and the SPA frontend directly, with optional built-in TLS. However, organizations may choose to place a reverse proxy (nginx, Caddy, HAProxy, etc.) in front of ECUBE for centralized certificate management, load balancing, or compliance with existing network architecture.

### 9.1 When to Use a Reverse Proxy

- Centralized TLS termination and certificate rotation (e.g. Let's Encrypt with automated renewal).
- Multiple services behind a single domain or IP.
- Organizational policy requires all web traffic to pass through an approved gateway.
- Advanced rate limiting, WAF, or access logging at the proxy layer.

### 9.2 ECUBE Backend Configuration

When ECUBE sits behind a reverse proxy, set the following in `<install-dir>/.env`:

```dotenv
# Trust X-Forwarded-For / X-Real-IP from the proxy for client IP detection.
TRUST_PROXY_HEADERS=true

# Leave empty — the frontend is served by the proxy or by ECUBE directly.
# Only set API_ROOT_PATH if the proxy strips a path prefix before forwarding.
# API_ROOT_PATH=/api
```

### 9.3 Using `--no-tls` Behind a Reverse Proxy

Running the ECUBE backend in plain HTTP mode (`--no-tls`) is acceptable when **both** of these conditions are met:

1. The reverse proxy terminates TLS for all client-facing traffic.
2. The reverse proxy and ECUBE backend communicate over a private network, loopback interface, or the same host — so unencrypted traffic never traverses an untrusted network segment.

For native installs:

```bash
sudo ./install.sh --no-tls --api-port 8000
```

For Docker Compose, set `ECUBE_NO_TLS=true` and `ECUBE_PORT=8000` in `.env`.

> **Warning:** Do not use `--no-tls` if the backend is reachable from untrusted networks without a TLS-terminating proxy in front of it.

### 9.4 Example: nginx Reverse Proxy

The following example configures nginx to terminate TLS and proxy requests to ECUBE running on `localhost:8000` (plain HTTP).

```nginx
server {
    listen 443 ssl http2;
    server_name ecube.example.com;

    ssl_certificate     /etc/letsencrypt/live/ecube.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ecube.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Pass client IP and protocol information to the backend.
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket support (if needed for future features).
    proxy_http_version 1.1;
    proxy_set_header   Upgrade    $http_upgrade;
    proxy_set_header   Connection "upgrade";

    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}

# Redirect HTTP to HTTPS.
server {
    listen 80;
    server_name ecube.example.com;
    return 301 https://$host$request_uri;
}
```

Key points:

- All client requests arrive over HTTPS; nginx forwards to the backend over plain HTTP on localhost.
- `TRUST_PROXY_HEADERS=true` must be set in ECUBE's `.env` so the backend reads `X-Forwarded-For` for client IP detection and audit logging.
- `SERVE_FRONTEND_PATH` should still be set — ECUBE serves the SPA and the API through the same backend process. The proxy simply forwards everything.
- If the proxy strips a path prefix (e.g. `/ecube/` → `/`), set `API_ROOT_PATH=/ecube` in `.env` so OpenAPI/Swagger URLs resolve correctly. For a simple passthrough proxy (no prefix stripping), leave `API_ROOT_PATH` empty.

### 9.5 Security Checklist (Reverse Proxy)

- [ ] TLS is terminated at the proxy — clients never connect over plain HTTP.
- [ ] Backend port (`8000`) is not published to external networks.
- [ ] `TRUST_PROXY_HEADERS=true` is set in ECUBE `.env`.
- [ ] `TRUST_PROXY_HEADERS` is **not** true when ECUBE is directly exposed without a proxy (enables client-IP spoofing).
- [ ] Proxy enforces `TLSv1.2` or later (`ssl_protocols TLSv1.2 TLSv1.3`).
- [ ] HTTP-to-HTTPS redirect is configured.
- [ ] Proxy forwards `X-Forwarded-For`, `X-Real-IP`, and `X-Forwarded-Proto` headers.
- [ ] Let's Encrypt / CA certificate renewal is automated and tested.
