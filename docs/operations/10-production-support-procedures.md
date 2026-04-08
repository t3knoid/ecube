# Production Support Procedures

## Overview

**Version:** 1.0  
**Last Updated:** April 2026  
**Audience:** Operations Engineers, Database Administrators, Support Teams, On-Call Engineers

---

## Table of Contents

1. [Troubleshooting & Diagnostics](#troubleshooting--diagnostics)
2. [Database Backup & Recovery](#database-backup--recovery)
3. [Application Upgrade & Migration](#application-upgrade--migration)
4. [Security Patching & Vulnerability Management](#security-patching--vulnerability-management)
5. [Secrets & Key Rotation](#secrets--key-rotation)
6. [Common Failure Modes](#common-failure-modes)
7. [Disaster Recovery](#disaster-recovery)

---

## Troubleshooting & Diagnostics

### 1. Service Won't Start / Readiness Check Failing

**Symptom:** `systemctl status ecube` shows failed/inactive, or `GET /health/ready` returns `503 Service Unavailable`.

**Diagnosis Steps:**

```bash
# A. Check service status
systemctl status ecube

# B. View service logs (last 100 lines)
journalctl -u ecube -n 100 --no-pager

# C. Follow logs in real-time
journalctl -u ecube -f

# D. Verify database connectivity
psql -U ecube_user -d ecube_db -h postgres.example.com -c "SELECT 1"

# E. Check migrations are applied
cd /opt/ecube && alembic current

# F. Verify filesystem mounts
mount | grep "/mnt"

# G. Check USB hub discovery
lsusb  # Check if hardware is visible

# H. Review environment variables
cat /etc/ecube/ecube.env

# I. Check service configuration
systemctl cat ecube | grep -E "ExecStart|Environment"
```

**Common Causes & Remedies:**

| Cause | Symptom | Remedy |
|-------|---------|--------|
| PostgreSQL not running or unreachable | `psql` command times out | `systemctl status postgresql` and verify DNS resolution and firewall rules |
| Database migrations pending | `alembic current` shows old version | Run `cd /opt/ecube && alembic upgrade head` |
| Network mounts not mounted | `mount` shows no NFS/SMB shares | Manually mount: `sudo mount -t nfs host:/path /mnt/evidence` |
| USB hub not detected | `lsusb` shows no hubs | Verify USB hub is powered; check `dmesg` for USB errors |
| JWT secret key missing | `403 Forbidden` on all requests | Edit `/etc/ecube/ecube.env` and set `TOKEN_SECRET_KEY` |
| Startup reconciliation timeout | Service fails to start after 5+ minutes | Increase `STARTUP_WAIT_TIMEOUT` in `/etc/ecube/ecube.env`; or investigate database/filesystem performance |
| Permission denied on /mnt | `mkdir` or `mount` fails | Verify ECUBE user owns mount points: `chown ecube:ecube /mnt/evidence` |

**Remediation:**

```bash
# Typical recovery steps
1. Check logs: journalctl -u ecube -n 200
2. Check service status: systemctl status ecube
3. Verify dependencies: PostgreSQL, mounts, USB
4. If migrations pending: cd /opt/ecube && alembic upgrade head
5. Restart service: sudo systemctl restart ecube
6. Verify health: curl -I http://localhost:8000/health/ready
7. If still failing: escalate to database or infrastructure team
```

### 2. High Memory Usage / Memory Leak Suspected

**Symptom:** `process_resident_memory_bytes` exceeds 2 GB, or ECUBE process is killed by OOM (check dmesg).

**Diagnosis:**

```bash
# Check memory metrics via API
curl http://localhost:8000/metrics | grep process_resident_memory_bytes

# Monitor memory over time
watch -n 5 'curl -s http://localhost:8000/metrics | grep process_resident_memory_bytes'

# Check ECUBE process memory usage directly
ps aux | grep ecube | grep -v grep
# Example: ecube 12345 15.3 25.2 2147483648 1234567 - shows RSS (resident set size) in KB

# Check for open file descriptors (file descriptor leak)
ls -l /proc/$(pgrep -f 'ecube' | head -1)/fd | wc -l

# Check system logs for OOM events
journalctl | grep -i "Out of memory"

# Check for stuck connections or hanging processes
journalctl -u ecube | grep -i "timeout\|hang\|stuck"
```

**Common Causes:**

| Cause | Evidence | Remedy |
|-------|----------|--------|
| Large audit log query | Memory spikes after `/audit` requests | Paginate audit log requests; add time range filters |
| Unbounded result sets | Memory grows monotonically over days | Restart service on maintenance window; update queries to use pagination/streaming |
| File descriptor leak | `ls /proc/PID/fd | wc -l` approaches system limit (default 1024) | Restart service; check code for unclosed file handles |
| Python garbage collection lag | Memory rises slowly over weeks | This is normal; restart service on maintenance schedule or increase available RAM |

**Remediation:**

```bash
# Temporary fix: restart service
sudo systemctl restart ecube

# Permanent fix: update queries to use pagination
# For very large audit log exports (> 100,000 records):
# Implement pagination:
GET /audit?limit=1000&offset=0  # Returns records 0-999
GET /audit?limit=1000&offset=1000  # Returns records 1000-1999

# Or use date range filters:
GET /audit?start=2026-04-01&end=2026-04-05

# Scale up: Increase memory available to ECUBE service
# Edit systemd service override
sudo systemctl edit ecube
# Add under [Service]:
# MemoryLimit=4G
# Or set ulimit in wrapper script /opt/ecube/bin/ecube
```
| Unbounded result sets | Memory grows monotonically | Restart container (temporary); upgrade query to use batch processing |
| File descriptor leak | `open files` limit approaches max | Restart container; check for unclosed file handles in code |
| Python garbage collection lag | Memory rises slowly over days | Restart container on a maintenance window; no urgent action needed |

**Remediation:**

```bash
# Temporary fix: restart service
sudo systemctl restart ecube

# Permanent fix: update queries or increase memory limit
# For very large audit log exports (> 100,000 records):
# Implement pagination:
GET /audit?limit=1000&offset=0  # Returns records 0-999
GET /audit?limit=1000&offset=1000  # Returns records 1000-1999

# Or use date range filters:
GET /audit?start=2026-04-01&end=2026-04-05

# Scale up: Increase memory limit for ECUBE service
sudo systemctl edit ecube
# Add under [Service]:
# MemoryLimit=4G
```

### 3. Job Copy Failures / High Error Rate

**Symptom:** `ecube_job_copy_errors_total` counter is high, or jobs show `FAILED` status.

**Diagnosis:**

```bash
# A. Check job status via API
curl http://localhost:8000/jobs | jq '.[] | select(.status == "FAILED")'

# B. Check error logs
journalctl -u ecube | grep -i "copy error\|FAILED\|retry"

# C. Check disk space on destination USB mount
df -h /mnt  # Where USB drives are mounted

# D. Check source filesystem
df -h /mnt/evidence  # Where source evidence mounts are

# E. Review individual file errors
curl http://localhost:8000/jobs/{job_id}/files?status=failed | head -20

# F. Check for permission errors
journalctl -u ecube | grep -i "permission denied\|access denied"

# G. Check if source filesystem is mounted and accessible
stat /mnt/evidence  # Should show device mounted
ls /mnt/evidence  # Should list files without hang or delay
```

**Common Causes:**

| Cause | Evidence | Remedy |
|-------|----------|--------|
| Disk full on USB drive | `df -h /mnt` shows 100% usage on destination | Eject drive; use larger capacity drive for future jobs |
| Network timeout on NFS/SMB source | Logs show timeout errors; job hangs mid-copy | Check network connectivity; increase mount timeout in `/etc/fstab` (add `timeo=600`) |
| Permission denied on source files | Logs show "Permission denied"; files not copied | Verify ECUBE user has read access; check POSIX permissions with `ls -la /mnt/evidence/` |
| File locked by another process | Logs show "Resource busy" during copy | Check `lsof /mnt/evidence` to identify lock holder; wait for lock release |
| Corrupted/unreadable file on source | Copy fails for specific file; others succeed | Test file on source: `file /mnt/evidence/problem.pst`; check filesystem for corruption |
| USB drive unexpectedly ejected | Copy stops abruptly; device not found in logs | Verify drive is securely seated; do not remove during active job |

**Remediation:**

```bash
# For disk full:
# Stop job and check capacity before starting next job
curl http://localhost:8000/drives | jq '.[] | {id, state, capacity_bytes, usb_drives_available}'

# For network/permission issues:
# Verify mount and permissions
mount | grep evidence  # Is mount active?
ls -la /mnt/evidence  # Can ECUBE user read?
stat /mnt/evidence  # Check mount options

# Remount with explicit options if needed
sudo umount /mnt/evidence
sudo mount -t nfs -o vers=3,rw,hard,intr,timeo=600 nfs.example.com:/export /mnt/evidence

# Retry job if transient error (use API or CLI)
curl -X POST http://localhost:8000/jobs/{job_id}/retry

# For corrupted file:
# Check filesystem integrity
sudo fsck.ext4 -n /dev/sdb1  # Read-only check
sudo dmesg | grep -i "error\|io"  # Check kernel errors
```

### 4. Network Mount Failures

**Symptom:** `ecube_network_mounts_failed > 0`, or jobs fail with "Mount not found" error.

**Diagnosis:**

```bash
# A. List all mounts managed by ECUBE
curl http://localhost:8000/mounts

# B. Check mount status in OS
df -h | grep -E "nfs|cifs"
mount | grep -E "nfs|cifs"

# C. Ping NFS/SMB server
ping -c 3 nfs.example.com
ping -c 3 smbhost.example.com

# D. Test NFS/SMB connectivity from command line
sudo mkdir -p /tmp/test-nfs
sudo mount -t nfs nfs.example.com:/export /tmp/test-nfs && ls /tmp/test-nfs && sudo umount /tmp/test-nfs

# E. Check firewall rules
sudo ufw status | grep -E "2049|445"

# F. Review service logs for mount errors
journalctl -u ecube | grep -i "mount.*error\|connection.*refused"

# G. Check stale NFS mounts (hanging)
timeout 5 ls /mnt/evidence  # If hangs, mount is stale
```

**Common Causes:**

| Cause | Evidence | Remedy |
|-------|----------|--------|
| NFS/SMB server down | `ping` fails; mount times out | Contact infrastructure team; verify server status; retry after server recovery |
| Network firewall blocking traffic | `ping` succeeds but mount times out | Allow ports 111, 2049 (NFS) or 445 (SMB) in UFW: `sudo ufw allow 2049/tcp` |
| Stale mount (server restarted) | Mount exists but `ls` hangs indefinitely | Force unmount: `sudo umount -f /mnt/evidence`; remount |
| Authentication failed (CIFS) | Permission denied; authentication error in logs | Verify CIFS credentials in `/etc/ecube/ecube.env`; or update `/etc/fstab` with correct credentials |
| Mount point does not exist | "No such file or directory" when mounting | Create mount point: `sudo mkdir -p /mnt/evidence` |
| Permissions on mount point | User cannot access mount point | Change ownership: `sudo chown ecube:ecube /mnt/evidence` |

**Remediation:**

```bash
# Unmount stale mount
sudo umount -f /mnt/evidence  # Force unmount even if hanging

# Wait a moment
sleep 5

# Remount manually
sudo mount -t nfs -o vers=3,rw,hard,intr nfs.example.com:/export /mnt/evidence

# Verify mount is working
ls /mnt/evidence  # Should list files
stat /mnt/evidence  # Should show mounted filesystem

# Or for CIFS/SMB:
sudo mount -t cifs -o username=user,password=pass //smbhost/evidence /mnt/evidence

# Test mount is accessible to ECUBE user
sudo -u ecube ls /mnt/evidence

# If mount failed, check logs
journalctl -u ecube -n 50 | grep -i mount
```

### 5. API Unresponsive / High Latency

**Symptom:** HTTP requests timeout or take > 5 seconds; `p95` latency spike in metrics.

**Diagnosis:**

```bash
# A. Check metrics
curl http://localhost:8000/metrics | grep request_duration

# B. Check database connections
curl http://localhost:8000/metrics | grep db_connection_pool

# C. Test simple endpoint
time curl http://localhost:8000/health/live

# D. Check for slow queries in logs
journalctl -u ecube | grep -i "slow query\|duration.*ms" | tail -20

# E. Check CPU usage
top -bn1 | grep ecube

# F. Check for deadlocks in database
sudo -u postgres psql ecube_db -c "SELECT * FROM pg_locks WHERE NOT granted;"
```

**Common Causes:**

| Cause | Evidence | Remedy |
|-------|----------|--------|
| Database connection pool exhausted | `db_connection_pool_size >= db_connection_pool_max` | Increase `DB_POOL_SIZE` env var; or optimize slow queries |
| Slow audit log query | Query to `GET /audit` takes > 1 second | Paginate results; add index on `audit_logs(timestamp)`; filter by date range |
| Large job with many files | Job status query takes long | Implement pagination on file lists; show only recent/failed files by default |
| CPU-bound operation (hash computation) | CPU at 100%; requests blocked | Reduce concurrent hash operations; or upgrade CPU |
| Network I/O bottleneck | API slow but database is fine | Check network connectivity to database; upgrade network link or reduce query size |

**Remediation:**

```bash
# Quick fix: restart service to clear stale connections
sudo systemctl restart ecube

# Check slow query log
sudo -u postgres psql ecube_db -c "SELECT pid, query, query_start FROM pg_stat_activity WHERE state = 'active' AND query_start < now() - interval '10 seconds';"

# Kill slow query if needed (carefully!)
sudo -u postgres psql ecube_db -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query LIKE '%SELECT%' AND query_start < now() - interval '30 seconds';"

# Optimize queries: Add database index
sudo -u postgres psql ecube_db -c "CREATE INDEX idx_audit_logs_timestamp ON audit_logs(timestamp DESC);"

# Increase connection pool (requires restart)
# Edit /etc/ecube/ecube.env and change DB_POOL_SIZE=10 to DB_POOL_SIZE=50
sudo systemctl restart ecube
```

---

## Database Backup & Recovery

### Backup Strategy

**Backup Frequency:**
- **Full backup:** Daily (e.g., 02:00 UTC)
- **Incremental/WAL archive:** Continuous (every 5 minutes or per transaction log)
- **Retention:** 30 days full backups + 60 days WAL logs (adjust per compliance requirements)

**Backup Tool:** `pg_dump` (logical backup) or `pg_basebackup` (physical backup)

### Automated Backup

**Backup Script (`/opt/ecube/backup-db.sh`):**

```bash
#!/bin/bash

BACKUP_DIR="/mnt/backups/ecube"
DB_HOST="postgres.example.com"
DB_PORT="5432"
DB_NAME="ecube_db"
DB_USER="ecube_backup"  # Read-only user with backup role

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/ecube_db_$DATE.sql.gz"

# Create backup directory if not exists
mkdir -p "$BACKUP_DIR"

# Create logical backup (compressed)
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  --no-password \
  --format=plain \
  --compress=9 \
  | gzip > "$BACKUP_FILE"

if [ $? -eq 0 ]; then
  echo "Backup successful: $BACKUP_FILE"
  
  # Retention: Keep only last 30 days
  find "$BACKUP_DIR" -name "ecube_db_*.sql.gz" -mtime +30 -delete
  
  # Optional: Upload to S3 for remote storage
  aws s3 cp "$BACKUP_FILE" "s3://ecube-backups/db/$(basename $BACKUP_FILE)"
else
  echo "Backup failed!" >&2
  exit 1
fi
```

**Cron Job:** Add to root crontab:

```bash
0 2 * * * /opt/ecube/backup-db.sh >> /var/log/ecube-backup.log 2>&1
```

**Verification:**

```bash
# Test backup integrity
gunzip -t /mnt/backups/ecube/ecube_db_20260405_020000.sql.gz

# Or restore to a test database
gunzip < ecube_db_20260405_020000.sql.gz | psql -U ecube_user -d ecube_test
```

### Manual Backup (Ad-Hoc)

```bash
# Full backup before major operations
pg_dump -h postgres.example.com -U ecube_user -d ecube_db --format=custom > /tmp/ecube_backup.dump

# Backup specific table (e.g., audit logs)
pg_dump -h postgres.example.com -U ecube_user -d ecube_db --format=custom -t audit_logs > /tmp/audit_logs_backup.dump
```

### Recovery Procedures

#### Scenario A: Restore Full Database

**Use case:** Catastrophic data loss; need to restore from backup point.

```bash
# 1. Stop ECUBE service
sudo systemctl stop ecube

# 2. Verify backup exists and is valid
gunzip -t /mnt/backups/ecube/ecube_db_20260405_020000.sql.gz

# 3. Drop and recreate database (WARNING: DESTRUCTIVE)
sudo -u postgres psql -h postgres.example.com -c "DROP DATABASE ecube_db;"
sudo -u postgres psql -h postgres.example.com -c "CREATE DATABASE ecube_db OWNER ecube_user;"

# 4. Restore backup
gunzip < /mnt/backups/ecube/ecube_db_20260405_020000.sql.gz | \
  psql -U ecube_user -h postgres.example.com -d ecube_db

# 5. Verify restoration
cd /opt/ecube && alembic current  # Check migrations applied

# 6. Start ECUBE
sudo systemctl start ecube

# 7. Verify service is healthy
curl -I http://localhost:8000/health/ready
```

#### Scenario B: Restore Specific Table (Audit Logs)

**Use case:** Accidental deletion of audit log entries; restore from backup table.

```bash
# 1. Create temporary schema for backup
psql -U ecube_user -h postgres.example.com -d ecube_db \
  -c "CREATE SCHEMA backup_restore;"

# 2. Restore table to backup schema
gunzip < /mnt/backups/ecube/audit_logs_backup.dump | \
  pg_restore -d ecube_db -U ecube_user -h postgres.example.com \
  -n backup_restore

# 3. Inspect restored data
psql -U ecube_user -h postgres.example.com -d ecube_db \
  -c "SELECT COUNT(*) FROM backup_restore.audit_logs;"

# 4. Restore specific records (e.g., entries after 2026-04-05)
psql -U ecube_user -h postgres.example.com -d ecube_db << EOF
INSERT INTO public.audit_logs
  SELECT * FROM backup_restore.audit_logs
  WHERE timestamp > '2026-04-05 00:00:00'
  AND timestamp NOT IN (SELECT timestamp FROM public.audit_logs);
EOF

# 5. Cleanup
psql -U ecube_user -h postgres.example.com -d ecube_db \
  -c "DROP SCHEMA backup_restore CASCADE;"
```

#### Scenario C: Point-in-Time Recovery (PITR)

**Use case:** Need to restore to a specific moment in time (not available in full backup alone).

**Prerequisite:** PostgreSQL WAL archiving must be enabled in PostgreSQL configuration.

**Recovery Steps:**

```bash
# 1. Stop ECUBE and PostgreSQL
sudo systemctl stop ecube
sudo systemctl stop postgresql

# 2. Move current data directory (for safety)
sudo mv /var/lib/postgresql/14/main /var/lib/postgresql/14/main.old

# 3. Create recovery.signal to trigger PITR
sudo touch /var/lib/postgresql/14/main/recovery.signal

# 4. Restore base backup from WAL archive
sudo -u postgres pg_basebackup -h localhost -D /var/lib/postgresql/14/main_recovery

# 5. Set recovery target time in recovery.conf
sudo tee /var/lib/postgresql/14/main_recovery/recovery.conf > /dev/null << EOF
restore_command = 'cp /mnt/wal_archive/%f %p'
recovery_target_timeline = 'latest'
recovery_target_time = '2026-04-05 14:30:00'
recovery_target_action = 'promote'
EOF

# 6. Move recovered data into place
sudo mv /var/lib/postgresql/14/main_recovery /var/lib/postgresql/14/main

# 7. Start PostgreSQL
sudo systemctl start postgresql

# 8. Verify recovery (check logs)
sudo tail -100 /var/log/postgresql/postgresql-14-main.log

# 9. Start ECUBE
sudo systemctl start ecube
```

---

## Application Upgrade & Migration

### Pre-Upgrade Checklist

Before upgrading ECUBE, complete:

- [ ] Read release notes and identify breaking changes
- [ ] Backup database (`/opt/ecube/backup-db.sh`)
- [ ] Test upgrade on staging environment first
- [ ] Schedule upgrade during maintenance window (downtime anticipated: 5–15 min)
- [ ] Notify users of planned downtime
- [ ] Ensure rollback plan is documented
- [ ] Have on-call engineer available during upgrade

### Upgrade Steps

#### 1. Review Migration Scripts

```bash
# Check pending migrations
cd /opt/ecube
alembic history --verbose

# Check which version is currently applied
alembic current
```

#### 2. Prepare New Version

```bash
# Download and extract new ECUBE package (from package manager or artifact repo)
# Using apt (if available) or manual download
wget https://artifacts.example.com/ecube-2.0.0.tar.gz
tar -xzf ecube-2.0.0.tar.gz -C /tmp

# Or using apt
sudo apt-get update
sudo apt-get install ecube=2.0.0

# Verify new version
/opt/ecube/bin/ecube --version  # Should show 2.0.0
```

#### 3. Stop Running Service

```bash
sudo systemctl stop ecube

# Verify service is down
curl -I http://localhost:8000/health/live  # Should fail (connection refused)
```

#### 4. Run Database Migrations

```bash
# Run Alembic migrations (applies all pending migrations)
cd /opt/ecube
alembic upgrade head

# Verify migrations applied
alembic current
```
```

#### 5. Start New Service

```bash
# Start ECUBE service with new version
sudo systemctl start ecube

# Wait for startup (may take 1–5 min for reconciliation)
sleep 10

# Verify health
curl -I http://localhost:8000/health/ready

# Check logs
journalctl -u ecube --tail 50
```

#### 6. Verify Upgrade

```bash
# Test key endpoints
curl -s http://localhost:8000/drives | jq .
curl -s http://localhost:8000/jobs | jq .
curl -s http://localhost:8000/metrics | head -20

# Check for errors in logs
journalctl -u ecube | grep -i "error\|critical" | tail -20
```

### Rollback Procedure

If upgrade fails, rollback to previous version:

```bash
# 1. Stop current service
sudo systemctl stop ecube

# 2. Restore database backup
# (See [Database Backup & Recovery](#database-backup--recovery) section)
gunzip < /mnt/backups/ecube/ecube_db_20260405_020000.sql.gz | \
  psql -U ecube_user -h postgres.example.com -d ecube_db

# 3. Revert to previous package version (if available)
sudo apt-get install ecube=1.9.0

# Or downgrade by reinstalling previous release:
wget https://artifacts.example.com/ecube-1.9.0.tar.gz
tar -xzf ecube-1.9.0.tar.gz -C /tmp
sudo cp -r /tmp/ecube-1.9.0/* /opt/ecube/

# 4. Start previous service
sudo systemctl start ecube

# 5. Verify rollback
curl -I http://localhost:8000/health/ready
```

### Breaking Changes & Compatibility

**Future versions** may include breaking changes. Before upgrading:

1. Check [CHANGELOG.md](../../CHANGELOG.md) for breaking changes.
2. If endpoints are removed or deprecated, update client code.
3. If database schema changes, review [alembic/versions/](../../alembic/versions/) for details.

---

## Security Patching & Vulnerability Management

### Vulnerability Detection

**Scan dependencies:**

```bash
# Scan Python dependencies for known vulnerabilities
cd /opt/ecube
pip install safety pip-audit

# Using safety
safety check --file requirements.txt

# Or using pip-audit
pip-audit -r requirements.txt

# Also scan system packages
sudo apt-get update
sudo apt list --upgradable  # Show available security patches
sudo apt-get install --only-upgrade security-updates  # Apply patches
```

**Monitor for CVEs:**

- Subscribe to PostgreSQL security advisories: https://www.postgresql.org/support/security/
- Monitor Python package security feeds: https://pyup.io/, https://safety.io/
- Subscribe to ECUBE GitHub release notifications

### Emergency Patch (Critical CVE)

**If critical CVE affects ECUBE:**

1. Immediately stop accepting new jobs (if mitigation available).
2. Contact affected users of in-flight jobs.
3. Apply patch ASAP: Follow [Application Upgrade & Migration](#application-upgrade--migration) expedited process.
4. If patch requires database change, test on backup first.
5. Deploy patch and resume normal operations.

**Example: Python library vulnerability**

```
CVE-2026-XXXX: Remote code execution in FastAPI < 0.95.0
Current version: 0.94.0 ❌
Fixed version: 0.95.1 ✅

Action:
1. Update /opt/ecube/requirements.txt: fastapi >= 0.95.1
2. Install updated dependencies: pip install --upgrade -r /opt/ecube/requirements.txt
3. Test on staging environment
4. Deploy to production (expedited)
5. Restart ECUBE: sudo systemctl restart ecube
6. Verify no regressions: curl http://localhost:8000/health/ready
```

### Patch Management Schedule

**Regular (Non-Critical):**
- Monthly security patch window (first Tuesday of month)
- Coordinate with maintenance window
- Test on staging before production

**Emergency (Critical):**
- Deploy within 24–48 hours of CVE publication
- Follow emergency escalation procedures
- Notify all stakeholders

---

## Secrets & Key Rotation

### Secret Types & Storage

| Secret | Location | Rotation | Lifetime |
|--------|----------|----------|----------|
| **Database Password** | Environment variable (`DATABASE_URL`) | Quarterly | N/A (handled by password change) |
| **JWT Secret Key** | Environment variable (`TOKEN_SECRET_KEY`) | Annually | N/A (no expiry; used for signing) |
| **TLS Private Key** | File: `/etc/ecube/tls.key` | On certificate renewal | Until cert expiry |
| **TLS Certificate** | File: `/etc/ecube/tls.crt` | Annually or per CA | 1–3 years |
| **API Keys (if used)** | Database table or vault | Per vendor policy | Varies |
| **LDAP Bind Password** | Environment variable or `~/.ldaprc` | Per security policy | N/A |

### Database Password Rotation

```bash
# 1. Generate new password
NEW_PASSWORD=$(openssl rand -base64 24)
echo "New password: $NEW_PASSWORD"  # Save to secure location (password manager)

# 2. Update database user password
sudo -u postgres psql -h postgres.example.com << EOF
ALTER USER ecube_user WITH PASSWORD '$NEW_PASSWORD';
EOF

# 3. Update ECUBE configuration
sudo sed -i "s|postgresql://ecube_user:[^@]*@|postgresql://ecube_user:$NEW_PASSWORD@|g" /etc/ecube/ecube.env

# 4. Restart service
sudo systemctl restart ecube

# 5. Verify new password works
psql -U ecube_user -h postgres.example.com -d ecube_db -c "SELECT 1;"

# 6. Test ECUBE is accessible
curl http://localhost:8000/health/ready

# 7. Old password: Disable in database
sudo -u postgres psql << EOF
ALTER USER ecube_user_old NOLOGIN;  -- If keeping old account
EOF
```

### JWT Secret Key Rotation

**Scenario:** Suspected compromise of JWT signing key.

```bash
# 1. Generate new secret
NEW_SECRET=$(openssl rand -hex 32)

# 2. Keep old secret in a separate env var for grace period
# ECUBE should accept both old and new secrets until tokens expire
# Edit /etc/ecube/ecube.env:
# TOKEN_SECRET_KEY="<new_secret>"
# TOKEN_SECRET_KEY_LEGACY="<old_secret>"  # Accept old key until midnight

# 3. Update environment file
echo "TOKEN_SECRET_KEY=$NEW_SECRET" | sudo tee -a /etc/ecube/ecube.env

# 4. Restart service
sudo systemctl restart ecube

# 5. Invalidate active sessions (tokens expire automatically)
# Tokens signed with old key will fail validation when new secret takes effect
# This forces re-authentication (desired behavior in compromise scenario)

# 6. Validate rotation
curl -s http://localhost:8000/health/ready  # Should pass
curl -s http://localhost:8000/audit  # Should pass with valid token

# 7. Update documentation
# Record rotation timestamp and reason in secure audit trail
```

### TLS Certificate Renewal

```bash
# 1. Check current certificate expiry
openssl x509 -enddate -noout -in /etc/ecube/tls.crt

# 2. If expiry < 30 days, request new certificate from CA
# (Use your organization's CA procedure; e.g., Let's Encrypt, internal PKI)

# Example: Let's Encrypt via certbot
sudo certbot certonly --standalone -d ecube.example.com

# 3. Copy new certificate and key to ECUBE directory
sudo cp /etc/letsencrypt/live/ecube.example.com/fullchain.pem /etc/ecube/tls.crt
sudo cp /etc/letsencrypt/live/ecube.example.com/privkey.pem /etc/ecube/tls.key
sudo chmod 600 /etc/ecube/tls.key
sudo chown ecube:ecube /etc/ecube/tls.*

# 4. Verify certificate
openssl x509 -enddate -noout -in /etc/ecube/tls.crt
openssl verify -CAfile /etc/ecube/tls.crt /etc/ecube/tls.crt

# 5. Reload ECUBE (graceful; no downtime)
# ECUBE should support graceful reload of TLS certs on SIGHUP
sudo systemctl kill -s HUP ecube

# Or restart with brief downtime:
sudo systemctl restart ecube

# 6. Test with new certificate
curl https://ecube.example.com:8000/health/live  # Should work with new cert

# 7. Log the renewal
echo "TLS renewal on $(date): $(openssl x509 -noout -enddate -in /etc/ecube/tls.crt)" >> /var/log/ecube/tls-rotations.log
```

---

## Common Failure Modes

### Mode 1: USB Drive Disconnected During Copy

**Symptom:** Job fails mid-copy; job status is `FAILED`; drive shows as `EMPTY`.

**Root Cause:** Physical disconnection, power loss, or USB error during transfer.

**Recovery:**

```bash
# 1. Re-insert USB drive
# (Wait 5–10 seconds for discovery)

# 2. Check drive state
curl http://localhost:8000/drives | jq '.[] | select(.id == "d-12345")'

# 3. Retry job (if supported)
curl -X POST http://localhost:8000/jobs/{job_id}/retry

# Or create new job with same parameters and reuse drive
curl -X POST http://localhost:8000/jobs \
  -d '{"source_path": "/mnt/evidence", "drive_id": "d-12345"}'
```

### Mode 2: Audit Log Growing Unbounded

**Symptom:** Database size grows rapidly; disk space alerts.

**Root Cause:** No log rotation or archival; audit logs kept forever.

**Recovery:**

```bash
# 1. Check audit log size
sudo -u postgres psql ecube_db \
  -c "SELECT COUNT(*) FROM audit_logs;"

# 2. Archive old logs (before pruning)
sudo -u postgres psql ecube_db << EOF
COPY audit_logs
  TO '/tmp/audit_logs_archive_2026q1.csv'
  (FORMAT CSV, HEADER)
  WHERE timestamp < '2026-04-01';
EOF
# Move archive to backup location
sudo mv /tmp/audit_logs_archive_2026q1.csv /mnt/backup/

# 3. Delete old audit logs (only if retention policy allows: e.g., > 3 years old)
sudo -u postgres psql ecube_db \
  -c "DELETE FROM audit_logs WHERE timestamp < '2023-01-01';"

# 4. Vacuum to reclaim space
sudo -u postgres psql ecube_db \
  -c "VACUUM FULL audit_logs;"

# 5. Monitor disk usage
df -h | grep ecube  # Or check postgres data directory
```

### Mode 3: Network Mount Becomes Stale

**Symptom:** Jobs fail; mount point exists but is unresponsive.

**Root Cause:** NFS/SMB server restarted or network interrupted; connection not re-established.

**Recovery:**

```bash
# 1. Check mount status
df -h | grep evidence
mount | grep evidence

# 2. Attempt to access mount point (with timeout)
timeout 5 ls /mnt/evidence  # If hangs, mount is stale

# 3. Force unmount
sudo umount -f /mnt/evidence

# 4. Remount
sudo mount -t nfs -o vers=3,rw nfs.example.com:/export /mnt/evidence

# 5. Verify connectivity
ls /mnt/evidence

# 6. Resume ECUBE job
```

---

## Disaster Recovery

### Tier 1: Complete System Loss

**Use case:** ECUBE host hardware failure; need to migrate to new host.

**RTO (Recovery Time Objective):** 4 hours  
**RPO (Recovery Point Objective):** 1 hour (loss of recent evidence copies is acceptable; preserve audit trail)

**Procedure:**

```bash
# 1. Provision new host with same specs (CPU, RAM, disk, network)
# OS: Ubuntu 22.04 LTS (or compatible version)

# 2. Install ECUBE dependencies
sudo apt-get update
sudo apt-get install -y postgresql-client nfs-common cifs-utils libffi-dev libssl-dev python3.11-dev

# 3. Extract ECUBE application
# From artifact repository or source:
wget https://artifacts.example.com/ecube-2.0.0.tar.gz
tar -xzf ecube-2.0.0.tar.gz -C /opt
sudo chown -R ecube:ecube /opt/ecube

# 4. Install Python dependencies
cd /opt/ecube
pip install -r requirements.txt

# 5. Configure environment
sudo cp /opt/ecube/ecube.env.example /etc/ecube/ecube.env
sudo nano /etc/ecube/ecube.env  # Update DATABASE_URL, etc.

# 6. Install systemd service
sudo cp /opt/ecube/ecube.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ecube

# 7. Restore database from backup
DATABASE_BACKUP="/mnt/backups/ecube/ecube_db_latest.sql.gz"
gunzip < "$DATABASE_BACKUP" | \
  psql -U ecube_user -h postgres.example.com -d ecube_db

# 8. Start ECUBE service
sudo systemctl start ecube

# 9. Re-mount network shares
sudo mount -t nfs nfs.example.com:/export /mnt/evidence
sudo mount -t cifs -o username=user,password=pass //smbhost/evidence /mnt/smb

# 10. Wait for startup reconciliation (2–5 minutes)
journalctl -u ecube -f | grep -m1 "reconciliation complete"

# 11. Verify all drives are in correct state
curl http://localhost:8000/drives | jq '.[] | {id, state, project_id}'

# 12. Resume operations
# Notify users; begin accepting new jobs
```

### Tier 2: Database Loss (Data Corruption)

**Use case:** Accidental data modification in database; cannot be used as-is.

**Procedure:**

```bash
# (See [Database Backup & Recovery](#database-backup--recovery) section)
# Use Point-in-Time Recovery (PITR) to restore to last known-good state
```

### Tier 3: USB Drives Lost / Inaccessible

**Use case:** Physical loss of USB drives containing evidence exports.

**Impact:** Evidence copies are lost; source data still exists in NFS/SMB mounts.

**Recovery:**

```bash
# 1. Report loss to legal team and audit team (for incident documentation)

# 2. Obtain new USB drives (matching capacity and encryption capability)

# 3. Re-export evidence from source
curl -X POST http://localhost:8000/jobs \
  -d '{
    "source_path": "/mnt/evidence/jane@acme.com",
    "evidence_number": "Reexport-2",
    "project_id": "p-67890"
  }'

# 4. Audit log will document reexport; chain-of-custody continues

# 5. Investigate root cause (shipping loss? Theft?)
# Update USB drive security procedures if needed
```

---

## Related Documents

- [01-operational-readiness.md](01-operational-readiness.md) — Health checks, metrics, alerting
- [02-compliance-and-evidence-handling.md](02-compliance-and-evidence-handling.md) — Chain-of-custody, regulations, incidents
- [docs/design/04-functional-design.md](../design/04-functional-design.md) — System behavior, recovery procedures
- [docs/design/13-build-and-deployment.md](../design/13-build-and-deployment.md) — Deployment models, configurations
