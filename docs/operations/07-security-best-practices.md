# ECUBE Security Best Practices

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, Security Engineers  
**Document Type:** Security Guidelines

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

- **Database:** Accessible only from ECUBE system layer (no external PostgreSQL access)
- **API:** HTTPS only (port 8443), no HTTP fallback
- **Mounts:** NFS/SMB shares on isolated VLAN if possible
- **USB:** Local USB hub, not exposed over network

## 2. Certificate Management

```bash
# Use strong certificates (not self-signed in production)
# Let's Encrypt free certificates recommended
sudo certbot certonly --standalone -d ecube.example.com

# Ensure TLS 1.2+ only
# (Configure in reverse proxy or ECUBE settings)
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

## 4. Access Control

- Restrict API access to trusted networks (firewall rules)
- Use VPN or SSH tunnel for remote access
- Enable audit logging for all operations (enabled by default)
- Review audit logs weekly: `curl -k -H "Authorization: Bearer $TOKEN" https://localhost:8443/audit?limit=1000`

## 5. File Permissions

```bash
# Restrict .env file to ecube user only
sudo chmod 600 /opt/ecube/.env
sudo chown ecube:ecube /opt/ecube/.env

# Restrict certificate files
sudo chmod 600 /opt/ecube/certs/key.pem
sudo chmod 644 /opt/ecube/certs/cert.pem

# Restrict venv
sudo chmod 750 /opt/ecube/venv
sudo chown -R ecube:ecube /opt/ecube
```

## 6. Audit Log Monitoring

```bash
# Export audit logs daily for compliance
psql -U ecube -d ecube -c "
SELECT * FROM audit_logs 
WHERE timestamp >= NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC
" | tee /mnt/audit-export/audit_$(date +%Y%m%d).csv

# Alert on suspicious activity (example: multiple failed logins)
psql -U ecube -d ecube << 'EOF'
SELECT user, COUNT(*) as failures 
FROM audit_logs 
WHERE action = 'AUTH_FAILURE' 
  AND timestamp >= NOW() - INTERVAL '1 hour'
GROUP BY user 
HAVING COUNT(*) > 5;
EOF
```

## 7. Firewall Configuration

```bash
# Allow HTTPS inbound (port 8443)
sudo ufw allow 8443/tcp

# Allow PostgreSQL only from localhost
sudo ufw allow from 127.0.0.1 to any port 5432

# Deny all other inbound
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```
