# 05. TLS Certificates and Let's Encrypt

**Version:** 1.0  
**Last Updated:** April 2026  
**Audience:** Systems Administrators, Security Engineers  
**Document Type:** Security / Operations Procedures

---

## Table of Contents

- [Table of Contents](#table-of-contents)
- [5.1 Scope](#51-scope)
- [5.2 Certificate Strategy](#52-certificate-strategy)
- [5.3 Hostname, IP, and TLS Name Matching](#53-hostname-ip-and-tls-name-matching)
- [5.4 Self-Signed Certificate (Bootstrap/Lab)](#54-self-signed-certificate-bootstraplab)
- [5.5 Let's Encrypt with Certbot (Recommended for Public Deployments)](#55-lets-encrypt-with-certbot-recommended-for-public-deployments)
- [5.6 Renewal and Monitoring](#56-renewal-and-monitoring)
- [5.7 Split-Host Notes (Frontend and Backend on Separate Hosts)](#57-split-host-notes-frontend-and-backend-on-separate-hosts)
- [5.8 Firewall Requirements for ACME and TLS](#58-firewall-requirements-for-acme-and-tls)
- [5.9 File Ownership and Permissions](#59-file-ownership-and-permissions)

---

## 5.1 Scope

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

```bash
sudo mkdir -p /opt/ecube/certs
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /opt/ecube/certs/key.pem \
  -out /opt/ecube/certs/cert.pem \
  -subj "/CN=$(hostname -f)"
```

If nginx terminates TLS (single-host frontend mode):

```bash
sudo chown root:root /opt/ecube/certs/key.pem
sudo chmod 600 /opt/ecube/certs/key.pem
sudo chown ecube:ecube /opt/ecube/certs/cert.pem
sudo chmod 644 /opt/ecube/certs/cert.pem
```

---

## 5.5 Let's Encrypt with Certbot (Recommended for Public Deployments)

### Prerequisites

- Public DNS record (for example `ecube.example.com`) points to your frontend host
- Inbound `80/tcp` and `443/tcp` are reachable from the internet
- nginx is installed and serving the target hostname

### Install certbot (Debian/Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y certbot python3-certbot-nginx
```

### Issue certificate using nginx plugin (HTTP-01)

```bash
sudo certbot --nginx -d ecube.example.com
```

For multiple names:

```bash
sudo certbot --nginx -d ecube.example.com -d www.ecube.example.com
```

### Validate and reload

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### Alternative: webroot mode

Use when you do not want certbot modifying nginx configuration directly.

```bash
sudo certbot certonly --webroot \
  -w /opt/ecube/www \
  -d ecube.example.com
```

You must then point nginx `ssl_certificate` and `ssl_certificate_key` to the certbot paths under `/etc/letsencrypt/live/<name>/`.

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

Post-renewal reload hook (if needed):

```bash
sudo certbot renew --deploy-hook "systemctl reload nginx"
```

---

## 5.7 Split-Host Notes (Frontend and Backend on Separate Hosts)

When frontend and backend are on separate hosts:

- Frontend host certificate protects user-to-frontend traffic.
- Frontend-to-backend TLS is separate and should also be verified.

For nginx proxying to HTTPS backend, prefer:

```nginx
proxy_ssl_verify on;
proxy_ssl_server_name on;
proxy_ssl_name backend.example.com;
```

Use one of:

- backend cert chain trusted by OS store, or
- explicit `proxy_ssl_trusted_certificate` bundle

---

## 5.8 Firewall Requirements for ACME and TLS

Minimum for public cert issuance and HTTPS serving:

- `80/tcp` inbound (ACME HTTP-01 challenge)
- `443/tcp` inbound (HTTPS)

If using DNS-01 challenge instead of HTTP-01, `80/tcp` may be unnecessary for issuance, but keep `443/tcp` for service traffic.

Restrict backend/API ports from public exposure where possible.

---

## 5.9 File Ownership and Permissions

Keep private keys non-world-readable.

Recommended patterns:

- TLS terminated by nginx:
  - key: `root:root`, mode `600`
  - cert: readable by nginx process (`644` typical)
- TLS terminated directly by ECUBE backend (uvicorn):
  - key: `ecube:ecube`, mode `600`
  - cert: `ecube:ecube`, mode `644`

After permission changes, validate and restart/reload affected services.
