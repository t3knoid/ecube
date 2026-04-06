# ECUBE Security Best Practices

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, Security Engineers

---

## Table of Contents

1. [Network Isolation](#1-network-isolation)
2. [Certificate Management](#2-certificate-management)
3. [Credential Management](#3-credential-management)
4. [Access Control](#4-access-control)
5. [File Permissions](#5-file-permissions)
6. [Audit Log Monitoring](#6-audit-log-monitoring)
7. [Firewall Configuration](#7-firewall-configuration)

---

## 1. Network Isolation

- **Database (bare-metal):** Keep PostgreSQL reachable only from the ECUBE system layer or trusted admin hosts. Do not expose PostgreSQL broadly.
- **Database (Docker Compose):** PostgreSQL is published to the host by default via `POSTGRES_HOST_PORT` in the Compose file. For hardened deployments, remove the port mapping entirely or bind it to `127.0.0.1` only.
- **API (external access):** Expose HTTPS only to clients.
- **API (internal architecture):** nginx-fronted and Docker deployments use internal HTTP between the reverse proxy and backend; this is acceptable only when that backend port is not externally exposed.
- **Mounts:** NFS/SMB shares on isolated VLAN if possible
- **USB:** Local USB hub, not exposed over network

### 1.1 Network Ports Reference

Use the table below to determine which ports should exist in each deployment and which ones should be externally reachable.

| Port / Protocol | Service | When Used | Exposure Guidance |
| --- | --- | --- | --- |
| `443/tcp` | nginx / `ecube-ui` HTTPS ingress | Bare-metal full install and Docker UI ingress when using standard HTTPS frontend publishing | Primary client-facing ingress. Allow from trusted client networks. |
| `8443/tcp` | ECUBE backend HTTPS or alternate published UI port | Bare-metal backend-only installs, or deployments where UI/API HTTPS is intentionally published on 8443 instead of 443 | Expose only when this is the intentional client ingress port. Do not expose publicly if nginx already fronts the service on 443. |
| `8000/tcp` | FastAPI backend HTTP | Internal-only backend port in Docker Compose and some reverse-proxy topologies | Do not publish externally. Keep reachable only from the local reverse proxy or container network. |
| `5432/tcp` | PostgreSQL | Bare-metal local/remote DB, Docker Compose postgres service | Restrict to ECUBE backend host(s) and approved admin paths only. Avoid broad exposure. |
| `80/tcp` | HTTP challenge endpoint | Optional for Let's Encrypt HTTP-01 certificate issuance | Open only when needed for ACME validation or redirect-to-HTTPS behavior. |
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

- Prefer a reverse proxy such as nginx as the only client-facing ingress point.
- Terminate TLS at the reverse proxy for full installs and Docker UI ingress.
- Keep backend application ports non-public and reachable only from the reverse proxy.
- When proxying ECUBE behind `/api`, ensure the backend is configured with `TRUST_PROXY_HEADERS=true` only when the proxy is trusted and `API_ROOT_PATH=/api` when the proxy strips the prefix.
- Use the reverse proxy to enforce HTTPS, constrain TLS versions, and centralize certificate rotation.

Recommended posture:

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

Example certbot command for nginx-based deployments:

```bash
sudo certbot --nginx -d ecube.example.com
```

If you manage nginx TLS settings directly, enforce modern TLS versions explicitly in the reverse proxy configuration, for example:

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
```

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

# Restrict certificate files for backend-only TLS termination
sudo chmod 600 /opt/ecube/certs/key.pem
sudo chmod 644 /opt/ecube/certs/cert.pem

# Restrict venv
sudo chmod 750 /opt/ecube/venv
sudo chown -R ecube:ecube /opt/ecube
```

Certificate ownership depends on topology:

- nginx/fronted deployments: private key is typically `root:root` with mode `600`
- backend-only TLS termination: private key and cert can be owned by `ecube:ecube`

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
# Bare-metal backend-only deployment: allow direct API TLS
sudo ufw allow 8443/tcp

# Deny all other inbound by default
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```

Topology-specific notes:

- Bare-metal full install / nginx-fronted deployment: allow `443/tcp`; do not expose backend `8443/tcp` publicly.
- Docker Compose deployment: allow only the published UI HTTPS port (`8443` by default). The backend port `8000` should remain unpublished.
- Docker Compose PostgreSQL: if you do not need host access to PostgreSQL, remove the port mapping. If host access is required, bind it to localhost only instead of all interfaces.
