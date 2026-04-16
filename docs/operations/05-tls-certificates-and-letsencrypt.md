# ECUBE TLS Certificates and Let's Encrypt

| Field | Value |
|---|---|
| Title | TLS Certificates and Let's Encrypt |
| Purpose | Explains the ECUBE TLS certificate strategy, including self-signed certificate setup and Let's Encrypt automation for HTTPS. |
| Updated on | 04/08/26 |
| Audience | Systems administrators, security engineers. |

## Table of Contents

1. [Scope](#scope)
2. [Certificate Strategy](#52-certificate-strategy)
3. [Hostname, IP, and TLS Name Matching](#53-hostname-ip-and-tls-name-matching)
4. [Self-Signed Certificate (Bootstrap/Lab)](#54-self-signed-certificate-bootstraplab)
5. [Let's Encrypt with Certbot](#55-lets-encrypt-with-certbot-recommended-for-public-deployments)
6. [Renewal and Monitoring](#56-renewal-and-monitoring)
7. [Split-Host Notes](#57-split-host-notes-frontend-and-backend-on-separate-hosts)
8. [Firewall Requirements](#58-firewall-requirements-for-acme-and-tls)
9. [File Ownership and Permissions](#59-file-ownership-and-permissions)

---

## Scope

This document covers TLS certificate operations for ECUBE package deployments:

- self-signed bootstrap certificates
- public certificates from Let's Encrypt via certbot
- hostname validation behavior
- renewal operations and permissions

Use with:

- [01-installation.md](01-installation.md)
- [02-manual-installation.md](02-manual-installation.md)
- [06-security-best-practices.md](06-security-best-practices.md)

---

## 5.2 Certificate Strategy

Recommended order of preference:

1. Organization-managed CA certificate (best for enterprise PKI)
2. Let's Encrypt certificate (best for public DNS/internet-facing frontend)
3. Self-signed certificate (temporary bootstrap/testing only)

Do not keep self-signed certs in long-term production unless your client trust model explicitly supports internal trust distribution.

---

## 5.3 Hostname, IP, and TLS Name Matching

TLS validation checks the requested host against certificate SAN/CN.

Operational implications:

- If cert is issued for `ecube.example.com`, clients must connect using that hostname.
- Accessing the same endpoint via raw IP usually fails name validation.
- Self-signed certs may still fail trust validation even when hostname matches, unless client trust store is updated.

For operator and user URLs, prefer stable DNS names over IP literals.

---

## 5.4 Self-Signed Certificate (Bootstrap/Lab)

Use only for non-production or temporary bootstrap.

### Docker

On first start, if no certificate files exist at `/opt/ecube/certs/key.pem` and `cert.pem`, the container automatically generates a self-signed certificate and logs a warning. No manual steps are required — `docker compose up` works out of the box with HTTPS.

To use your own certificate, place `key.pem` and `cert.pem` in a host directory, set `ECUBE_CERTS_DIR` in `.env`, and uncomment the certs volume line in `docker-compose.ecube.yml`.

### Native

For native installs, generate a self-signed certificate manually:

```bash
sudo mkdir -p /opt/ecube/certs
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /opt/ecube/certs/key.pem \
  -out /opt/ecube/certs/cert.pem \
  -subj "/CN=$(hostname -f)"
```

Set ownership so the `ecube` service account can read the certificate files:

```bash
sudo chown ecube:ecube /opt/ecube/certs/key.pem /opt/ecube/certs/cert.pem
sudo chmod 600 /opt/ecube/certs/key.pem
sudo chmod 644 /opt/ecube/certs/cert.pem
```

> **Docker note:** The Docker image does not ship a certificate. On first container start the entrypoint generates a self-signed certificate at `/opt/ecube/certs/` if `key.pem` and `cert.pem` are missing (see Section 5.4 Docker above). To supply your own certificate, place `key.pem` and `cert.pem` in a host directory, set `ECUBE_CERTS_DIR` in `.env`, and uncomment the certs volume in the compose file — the entrypoint skips generation when the files already exist. See [04-configuration-reference.md](04-configuration-reference.md).

---

## 5.5 Let's Encrypt with Certbot (Recommended for Public Deployments)

### Prerequisites

- Public DNS record (for example `ecube.example.com`) points to the ECUBE host
- Inbound `80/tcp` and `443/tcp` are reachable from the internet
- A webroot directory is accessible for ACME challenges (e.g. `/opt/ecube/www`)

### Install certbot (Debian/Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y certbot
```

### Issue certificate using standalone or webroot mode

Standalone mode (temporarily binds port 80 for the ACME challenge):

```bash
sudo certbot certonly --standalone -d ecube.example.com
```

Webroot mode (uses an existing directory for the challenge):

```bash
sudo certbot certonly --webroot \
  -w /opt/ecube/www \
  -d ecube.example.com
```

For multiple names:

```bash
sudo certbot certonly --standalone \
  -d ecube.example.com -d www.ecube.example.com
```

After issuance, copy or symlink the certificate files into `/opt/ecube/certs/`:

```bash
sudo cp /etc/letsencrypt/live/ecube.example.com/fullchain.pem /opt/ecube/certs/cert.pem
sudo cp /etc/letsencrypt/live/ecube.example.com/privkey.pem /opt/ecube/certs/key.pem
sudo chown ecube:ecube /opt/ecube/certs/cert.pem /opt/ecube/certs/key.pem
sudo chmod 644 /opt/ecube/certs/cert.pem
sudo chmod 600 /opt/ecube/certs/key.pem
sudo systemctl restart ecube
```

---

## 5.6 Renewal and Monitoring

Test renewal:

```bash
sudo certbot renew --dry-run
```

Check timers/services:

```bash
systemctl list-timers | grep -i certbot || true
systemctl status certbot.timer || true
```

Post-renewal deploy hook (copies renewed certs and restarts ECUBE):

```bash
sudo certbot renew --deploy-hook "cp /etc/letsencrypt/live/ecube.example.com/fullchain.pem /opt/ecube/certs/cert.pem && cp /etc/letsencrypt/live/ecube.example.com/privkey.pem /opt/ecube/certs/key.pem && chown ecube:ecube /opt/ecube/certs/cert.pem /opt/ecube/certs/key.pem && systemctl restart ecube"
```

---

## 5.7 Split-Host Notes (Optional Reverse Proxy)

ECUBE serves both the API and the Vue SPA directly and terminates TLS in uvicorn. A separate reverse proxy is **not required** for standard deployments.

If your organization places an external reverse proxy (nginx, HAProxy, etc.) in front of ECUBE:

- Terminate TLS at the reverse proxy.
- Forward `Host`, `X-Forwarded-For`, and `X-Forwarded-Proto` headers.
- Set `TRUST_PROXY_HEADERS=true` in the ECUBE `.env`.
- Ensure the proxy-to-backend connection is also encrypted or on a trusted network segment.

---

## 5.8 Firewall Requirements for ACME and TLS

Minimum for public cert issuance and HTTPS serving:

- `80/tcp` inbound (ACME HTTP-01 challenge)
- `443/tcp` or `8443/tcp` inbound (HTTPS — depending on your port configuration)

If using DNS-01 challenge instead of HTTP-01, `80/tcp` may be unnecessary for issuance, but keep the HTTPS port open for service traffic.

Restrict backend/API ports from public exposure where possible.

---

## 5.9 File Ownership and Permissions

Keep private keys non-world-readable.

Recommended pattern (uvicorn terminates TLS directly):

- key: `ecube:ecube`, mode `600`
- cert: `ecube:ecube`, mode `644`

If an external reverse proxy terminates TLS instead:

- key: owned by the proxy service user, mode `600`
- cert: mode `644`

After permission changes, validate and restart affected services.

## References

- [docs/operations/06-security-best-practices.md](06-security-best-practices.md)
