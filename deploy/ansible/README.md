# Ansible Test Update Helper

This directory contains a lightweight Ansible helper for pushing a locally built ECUBE source tree into an existing native install on a designated test host.

The playbook assumes the target host already has a working ECUBE installation, including the virtual environment, `.env`, service unit, runtime OS packages, and any required host bootstrap from the normal installer flow.

## Requirements

### Controller requirements

Run the playbook from a machine that has:

- Ansible installed and available as `ansible-playbook`.
- SSH connectivity to the target host.
- A local ECUBE source checkout that already contains the files the playbook pushes:
  - `install.sh`
  - `app/`
  - `alembic/`
  - `deploy/`
  - `pyproject.toml`
  - `alembic.ini`
  - `README.md`
  - `LICENSE`
  - `frontend/dist/`

The playbook reads the local checkout directly. It does not build the frontend, create a tarball, or download release assets.

Install the Ansible toolchain there before running the playbook.

```bash
pip install \
  ansible==12.0.0 \
  ansible-dev-tools==25.8.3 \
  ansible-lint==25.9.2 \
  requests==2.32.5 \
  pycdlib==1.14.0 \
  proxmoxer==2.2.0 \
  jmespath==1.0.1 \
  passlib==1.7.4 \
  psycopg2-binary==2.9.10
```

If you use a different controller virtual environment path or Python version, adjust the path in the commands below. The key requirement is that the controller runs `ansible-playbook` from an environment that has the same Ansible packages installed.

### Target host requirements

The target host must already be an existing ECUBE native install. In practice that means all of the following are already in place before this playbook runs:

- The install root exists, typically `/opt/ecube`.
- `ecube.service` already exists and is managed by systemd.
- The ECUBE service account exists, typically `ecube`.
- The existing install already has a working virtual environment at `<install-dir>/venv`.
- The host-level prerequisites from the normal installer flow are already configured, including runtime OS packages, sudoers, PAM configuration, and any TLS/runtime settings.
- The remote machine has a usable Python interpreter for Ansible modules.

This playbook does not bootstrap a host from scratch. It updates files inside an existing install and restarts the service.

### Ansible Python interpreter requirement

The playbook assumes the Ansible Python environment on the target host is already available and should be specified explicitly when you run the playbook.

Use the remote interpreter path that matches the target host. On Debian and Ubuntu this is usually `/usr/bin/python3`.

If the host uses a different interpreter path, replace it in the command examples below.

The examples below also invoke `ansible-playbook` from the controller virtual environment created above.

Before running the playbook, build the frontend locally so `frontend/dist` is current.

```bash
cd frontend
npm install
npm run build
```

## What the playbook does

The playbook:

- validates that the required local payload exists in the source checkout,
- checks that the target install directory already exists,
- stops `ecube.service` by default,
- copies the backend payload into the existing install root,
- refreshes `frontend/dist` in the install tree,
- resolves the live frontend path from `SERVE_FRONTEND_PATH` in `.env` when present,
- replaces the deployed frontend bundle,
- runs `pip install -e <install-dir>` inside the existing virtualenv by default,
- restarts `ecube.service` by default.

It does not run the native installer, provision OS packages, recreate the virtualenv, write `.env`, generate certificates, or initialize the database.

## Basic usage

Run the update against a single host by passing that host directly on the Ansible command line.

```bash
/opt/python_3.12/bin/ansible-playbook \
  -k -i test-host.example.com, \
  deploy/ansible/push-existing-install.yml \
  --user ubuntu \
  --become \
  -e ansible_python_interpreter=/usr/bin/python3
```

If the current user authenticates to the target host, the user option can be omitted.

```bash
/opt/python_3.12/bin/ansible-playbook \
  -k -i test-host.example.com, \
  deploy/ansible/push-existing-install.yml \
  --become \
  -e ansible_python_interpreter=/usr/bin/python3
```

## Recommended preflight check

Before pushing files, confirm Ansible can reach the host and use the selected Python interpreter.

```bash
/opt/python_3.12/bin/ansible all \
  -k -i test-host.example.com, \
  -u ubuntu \
  --become \
  -e ansible_python_interpreter=/usr/bin/python3 \
  -m ping
```

If this fails, fix the SSH access, privilege escalation, or interpreter path before using the update playbook.

## Useful overrides

```bash
/opt/python_3.12/bin/ansible-playbook \
  -k -i test-host.example.com, \
  deploy/ansible/push-existing-install.yml \
  --user ubuntu \
  --become \
  -e ansible_python_interpreter=/usr/bin/python3 \
  -e ecube_install_dir=/srv/ecube \
  -e ecube_service_name=ecube.service \
  -e ecube_frontend_path_override=/srv/ecube-www
```

Useful variables:

- `ansible_python_interpreter`: remote Python used by Ansible modules.
- `ecube_install_dir`: install root on the target host.
- `ecube_service_name`: systemd unit to stop and restart.
- `ecube_frontend_path_override`: explicit frontend deployment path when you do not want to rely on `SERVE_FRONTEND_PATH` from `.env`.
- `ecube_restart_service`: set to `false` if you want to leave the service stopped or manage restart separately.
- `ecube_refresh_editable_install`: set to `false` if you want to skip `pip install -e`.

Example without service restart:

```bash
/opt/python_3.12/bin/ansible-playbook \
  -k -i test-host.example.com, \
  deploy/ansible/push-existing-install.yml \
  --user ubuntu \
  --become \
  -e ansible_python_interpreter=/usr/bin/python3 \
  -e ecube_restart_service=false
```

## Notes

The playbook copies the same core payload paths used by the local installer/package flow, refreshes the editable install in the existing virtual environment, updates the served frontend directory derived from `SERVE_FRONTEND_PATH` in `.env` when present, and restarts `ecube.service` by default.

This helper is intended for test-host refreshes from a working source checkout. For release-like deployments, continue using the package artifact flow documented in `scripts/package-local.sh` and the native installer documentation.