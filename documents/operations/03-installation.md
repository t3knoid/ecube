# ECUBE Installation Guide

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, IT Staff  
**Document Type:** Installation Procedures

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Hardware Requirements](#hardware-requirements)
3. [Software Requirements](#software-requirements)
4. [Deployment Options](#deployment-options)

---

## Prerequisites

### Hardware Requirements

**Recommended Minimum:**

- CPU: Quad-core 2.0 GHz x86-64
- RAM: 8 GB
- Storage: 256 GB SSD (for system, database, logs)
- USB: USB 3.1 hub with ≥4 ports
- Network: 1Gbps Ethernet

**Connectivity:**

- HTTPS network access to identity provider (LDAP, OIDC provider, or local authentication)
- NFS/SMB mount access to evidence source shares
- PostgreSQL 14+ database over network or localhost

### Software Requirements

**Operating System:**

- Ubuntu 20.04 LTS, 22.04 LTS, or later (recommended)
- CentOS/RHEL 8+ (supported, similar steps)
- Linux kernel 5.10+ (for USB device handling)

**System Packages:**

```bash
sudo apt update
sudo apt install -y \
  python3.11 \
  python3.11-venv \
  python3-pip \
  postgresql \
  postgresql-contrib \
  nfs-common \
  cifs-utils \
  usbutils \
  udev \
  git
```

## Deployment Options

Two deployment methods are supported:

- **Package Deployment (Systemd Service):** See [04-package-deployment.md](04-package-deployment.md)
- **Docker Compose:** See [05-docker-deployment.md](05-docker-deployment.md)
