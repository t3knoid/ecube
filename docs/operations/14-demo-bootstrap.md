# Demo bootstrap

## Table of contents

- [Purpose](#purpose)
- [Configure demo mode](#configure-demo-mode)
- [Post-install demo setup steps](#post-install-demo-setup-steps)
- [Command syntax and option order](#command-syntax-and-option-order)
- [What the seed command does operationally](#what-the-seed-command-does-operationally)
- [demo-metadata.json as the demo source of truth](#demo-metadatajson-as-the-demo-source-of-truth)
- [demo-metadata.json property reference](#demo-metadatajson-property-reference)
- [Seeding your own sanitized demo data](#seeding-your-own-sanitized-demo-data)
- [Running from source in demo mode](#running-from-source-in-demo-mode)
- [Reset demo content](#reset-demo-content)
- [Operator expectations](#operator-expectations)
- [Validation checklist](#validation-checklist)
- [Safety notes](#safety-notes)

ECUBE demo mode uses a normal installation plus installer-configured post-install demo tasks.

## Purpose

The demo bootstrap command prepares a dedicated demo-only data root, stages the built-in synthetic sample set, seeds demo-safe role mappings, and can optionally create or reset shared demo OS accounts.

It is designed to make a standard ECUBE installation demo-ready without mixing sample content with live evidence locations.

## Configure demo mode

Set `DEMO_MODE=true` in the ECUBE environment configuration to enable demo mode.

For a package or native install, this is usually the root `.env` file at `/opt/ecube/.env`.

For local development, use the `.env` file in the repository root.

For Docker Compose, place the same variables in your compose `.env` file or under the application service environment section.

Minimal `.env` configuration:

```env
DEMO_MODE=true
```

For a native install, the installer generates `/opt/ecube/demo-metadata.json` and uses that file as the source of truth for the post-install demo workflow. That metadata can include the login message, shared demo password, password-change policy, demo account definitions, USB drive mappings, network mount mappings, and seeded job definitions.

If you want to override the defaults before the first seed, you may still set `DEMO_LOGIN_MESSAGE`, `DEMO_SHARED_PASSWORD`, `DEMO_DISABLE_PASSWORD_CHANGE`, `DEMO_DATA_ROOT`, or `DEMO_ACCOUNTS` in `.env`, but they are no longer required for a standard demo deployment.

Only the username, label, description, and the optional shared demo password are exposed publicly on the login screen.

## Post-install demo setup steps

1. Connect the USB drives that should participate in the demo before running the installer. The installer discovers the currently attached USB devices and generates one demo project, one USB seed entry, one network mount, and one pending demo job per discovered drive.

2. Install ECUBE with demo post-install task configuration enabled and provide the network-share server IP or hostname.

```bash
sudo ./install.sh --demo --server 192.168.2.250
```

3. If you only want the installer to generate `/opt/ecube/demo-metadata.json` and stop before updating `.env`, creating the database, or running Alembic, add `--metadata-only`.

```bash
sudo ./install.sh --demo --metadata-only --server 192.168.2.250
```

If you want `--metadata-only` to write the generated file somewhere else, pass `--metadata-output` with an absolute file path.

```bash
sudo ./install.sh --demo --metadata-only --server 192.168.2.250 --metadata-output /tmp/demo-metadata.json
```

In `--metadata-only` mode, the installer does not install or upgrade the ECUBE application, does not start services, and does not attempt any USB or network mount operations. It only discovers the currently attached USB devices and writes the generated metadata file.

4. Review the generated `/opt/ecube/demo-metadata.json` file. The installer builds the file from scratch, starting with the default demo configuration block and demo accounts, then generates the USB, mount, job, and project sections from live USB discovery.

When `--demo` is set, the installer updates `.env` with `DEMO_MODE=true`, ensures `DATABASE_URL` is set to `postgresql://ecube:ecube@localhost/ecube` when missing, creates the local `ecube` database if it does not already exist, runs `alembic upgrade head`, generates `/opt/ecube/demo-metadata.json` from the connected USB drives and `--server`, and prints the post-install demo seed command you should run after staging the shares.

If `DATABASE_URL` already points at a different PostgreSQL instance, the installer preserves it and skips local database creation.

5. Stage the server-side share content using the generated metadata. The installer prints these paths in its completion summary, and the generated metadata is the source of truth.

For each generated NFS mount, create the exported directory and add an `incoming/` subdirectory containing sanitized demo files:

```bash
sudo mkdir -p /mnt/Data/ecube/demo-case-001/incoming
```

For each generated SMB mount, create a share whose root name matches the case folder and add an `incoming/` subdirectory containing sanitized demo files:

```text
//192.168.2.250/demo-case-002
```

Each generated job reads from `/incoming`, so the staged demo content must live under that subdirectory for both NFS and SMB shares.

6. After staging the share content, run the demo bootstrap manually. For a native install, the command lives inside the ECUBE virtual environment and should be run from the ECUBE install root so it reads the appliance environment file:

```bash
sudo bash -lc 'cd /opt/ecube && /opt/ecube/venv/bin/ecube-demo-bootstrap --metadata-path /opt/ecube/demo-metadata.json seed 
```

If the shared password contains shell-special characters such as `$`, escape them for the inner shell when using `sudo bash -lc`, or choose a password value that does not rely on shell expansion.

7. Sign in and verify that the demo login guidance appears and that shared demo account password resets are blocked.

The seed command is safe to rerun for managed demo state. Each pass removes the previously seeded demo jobs and role assignments, recreates the managed demo root, stages the built-in sample content again, and writes a fresh audit entry.

## Command syntax and option order

Use this command shape when running the bootstrap manually:

```bash
ecube-demo-bootstrap [--actor NAME] [--data-root PATH] [--metadata-path PATH] seed [--shared-password "..."] [--skip-os-users]
ecube-demo-bootstrap [--actor NAME] [--data-root PATH] [--metadata-path PATH] reset
```

Place `--data-root`, `--metadata-path`, and `--actor` before `seed` or `reset`. These are global options, so if they are placed after the subcommand the CLI will reject them.

Keep the subcommand on the same shell command line. If you stop after `--metadata-path ...demo-metadata.json` and press Enter before adding `seed` or `reset`, the CLI exits with `the following arguments are required: command`.

Use `--skip-os-users` when you only want to seed the database and demo files and do not want ECUBE to create or reset host OS accounts.

USB and network-share seeding are configured in `demo-metadata.json`, not through CLI flags. If the JSON file contains a `usb_seed` section with `enabled: true`, the seed flow will discover real connected host USB devices, enable only the explicitly configured ECUBE USB ports, bind each matching device to its configured project, and mount it under the managed ECUBE USB mount root. If the JSON file contains a `mount_seed` section with `enabled: true`, ECUBE will register and mount the explicitly configured real NFS and SMB sources for their associated demo projects.

## What the seed command does operationally

When the seed command runs, ECUBE performs the following actions in order:

1. Resolves the target demo root from `--data-root` or `DEMO_DATA_ROOT`.
2. Deletes any previously seeded demo jobs from the database.
3. Removes and reapplies the configured demo role mappings for the demo usernames.
4. Recreates the managed demo directory and writes marker files so ECUBE knows the directory is safe to reset later.
5. Stages the built-in synthetic sample projects and metadata files.
6. If OS-user management is enabled, ensures the ECUBE groups exist, creates any missing demo accounts, and resets their password to the provided shared password when applicable.
7. If the `demo-metadata.json` file enables `usb_seed`, discovers the host's real currently connected USB drives, enables the configured USB ports for ECUBE use, matches each configured entry to the actual device attached at that port, binds it to the configured demo project, and mounts it into the managed USB mount root.
8. If the `demo-metadata.json` file enables `mount_seed`, registers the explicitly configured real NFS and SMB sources through the trusted mount service and mounts them for the associated projects.
9. Inserts demo-safe completed jobs into the database so the UI has realistic walkthrough state.
10. Writes an audit event for the bootstrap action.

The managed demo directory will contain files such as `README.txt`, `demo-metadata.json`, and the sample case folders. The directory is intentionally marked as demo-managed so the reset flow can clean it up safely.

The USB seeding path never fabricates hardware entries and never formats or wipes a device automatically. It only works with real USB media the host actually reports at seed time, and only mounts drives that already have a recognized filesystem on the explicitly configured host USB ports.

## demo-metadata.json as the demo source of truth

After a successful seed, the demo root contains a `demo-metadata.json` file that stores the operational demo configuration alongside the sample content.

A typical file now contains both the staged project list and the runtime demo settings, for example:

```json
{
  "managed_by": "ecube-demo-seed-v1",
  "generated_at": "2026-04-19T00:00:00+00:00",
  "demo_config": {
    "demo_mode": true,
    "login_message": "Use the shared demo accounts below.",
    "shared_password": "demo",
    "demo_disable_password_change": true,
    "password_change_allowed": false,
    "accounts": [
      {
        "username": "demo_manager",
        "label": "Manager demo",
        "description": "Drive lifecycle and job visibility review",
        "roles": ["manager"]
      }
    ]
  },
  "usb_seed": {
    "enabled": true,
    "drives": [
      {
        "id": 1,
        "port_system_path": "1-1",
        "project_id": 1,
        "device_identifier": "usb-demo-001"
      }
    ]
  },
  "mount_seed": {
    "enabled": true,
    "mounts": [
      {
        "id": 17,
        "type": "NFS",
        "remote_path": "192.168.10.25:/exports/demo-case-001",
        "project_id": 1
      },
      {
        "id": 14,
        "type": "SMB",
        "remote_path": "//fileserver/demo-share",
        "project_id": 2,
        "username": "demo-user",
        "credentials_file": "/opt/ecube/demo-smb.creds"
      }
    ]
  },
  "job_seed": {
    "jobs": [
      {
        "id": 101,
        "project_id": 1,
        "evidence_number": "EVID-DEMO-JOB-001",
        "mount_id": 17,
        "drive_id": 1,
        "source_path": "/incoming",
        "status": "PENDING",
        "ui_job_id": 101
      }
    ]
  },
  "projects": [
    {
      "project_id": 1,
      "project_name": "DEMO-CASE-001",
      "folder": "demo-case-001",
      "sanitized": true
    },
    {
      "project_id": 2,
      "project_name": "DEMO-CASE-002",
      "folder": "demo-case-002",
      "sanitized": true
    }
  ]
}
```

This means the normal steady-state configuration can be as small as `DEMO_MODE=true` in `.env`, with the rest of the demo presentation and account metadata living under the demo data root.

After the demo has been seeded, the managed metadata keeps the deployment in demo mode until you run the reset flow or remove the managed demo root. Simply changing `DEMO_MODE` back to `false` does not restore the full application behavior.

## demo-metadata.json property reference

The `demo-metadata.json` document supports both top-level metadata and the nested runtime demo configuration that ECUBE uses after seeding.

If you want the bootstrap to seed real connected USB devices, define that behavior in the JSON document before running the seed command.

### managed_by

Use this top-level string to mark the directory as ECUBE-managed demo content.

- Purpose: tells the reset flow that the directory is safe to recreate or remove.
- Typical value: `ecube-demo-seed-v1`
- Recommendation: leave this value unchanged for managed demo roots.

### generated_at

Use this top-level timestamp to record when the metadata file was last generated.

- Purpose: operator visibility and troubleshooting.
- Format: ISO 8601 timestamp.
- Recommendation: let the seed command write this automatically.

### demo_config

This object contains the runtime demo behavior that the backend and login UI use.

#### demo_config.demo_mode

Controls whether the seeded metadata keeps the deployment in demo mode.

- Type: boolean
- Typical value: `true`
- Effect: keeps demo restrictions and demo login guidance active after seed.

#### demo_config.login_message

Public-safe login instructions shown on the sign-in page.

- Type: string
- Use for: guidance such as who should sign in and what the demo environment represents.
- Do not include: internal paths, infrastructure details, or private operational notes.

#### demo_config.shared_password

Optional shared password for disposable demo accounts.

- Type: string or `null`
- Use for: controlled demo deployments where a common password is intentionally part of the walkthrough.
- Recommendation: rotate it whenever the demo environment is reset or handed to a new audience.

#### demo_config.demo_disable_password_change

Controls whether shared demo account passwords can be changed through the UI or API.

- Type: boolean
- Typical value: `true`
- Effect: blocks password reset actions for configured demo users.

#### demo_config.password_change_allowed

Operator-facing inverse of the password-lock setting.

- Type: boolean
- Typical value: `false` when demo password changes are disabled
- Effect: helps the frontend show the correct read-only behavior.

#### demo_config.accounts

List of demo accounts that should be seeded and shown in the public-safe login guidance.

- Type: array of account objects
- Use for: the usernames, labels, descriptions, roles, and optional passwords for demo personas.
- Recommendation: keep the list limited to intentional demo personas only.

##### demo_config.accounts[].username

The OS/login username for the demo account.

- Type: string
- Example: `demo_manager`
- Requirement: should be unique within the accounts list.

##### demo_config.accounts[].label

Short human-friendly label for the persona.

- Type: string
- Example: `Manager demo`
- Use for: making the login screen easier for evaluators to understand.

##### demo_config.accounts[].description

Brief explanation of what the account should be used for.

- Type: string
- Example: `Drive lifecycle and job visibility review`
- Use for: role guidance on the login page.

##### demo_config.accounts[].roles

List of ECUBE roles that should be applied to the account.

- Type: array of strings
- Supported values: `admin`, `manager`, `processor`, `auditor`
- Recommendation: assign only the minimum roles needed for the demo persona.

##### demo_config.accounts[].password

Optional per-account password override.

- Type: string or `null`
- Use for: cases where one demo account should not use the shared password.
- Recommendation: only set this intentionally; otherwise rely on `shared_password`.

### usb_seed

This object controls whether the demo bootstrap should use real USB devices that are physically connected to the host during seed time.

#### usb_seed.enabled

Turns real-device USB seeding on or off.

- Type: boolean
- Typical value: `false` by default, `true` when you want host-connected USB media included in the demo seed
- Effect: when `true`, ECUBE evaluates the configured USB drive list and only acts on matching real hardware.

#### usb_seed.drives

List of explicit USB port-to-project mappings for the demo seed.

- Type: array of USB seed objects
- Requirement: each entry should identify the real host USB port that ECUBE should use
- Recommendation: define only the ports and projects you want included in the demo workflow

#### usb_seed.drives[].id

Numeric drive ID shown in the ECUBE UI after the USB device has been discovered and seeded.

- Type: integer
- Example: `1`
- Effect: this matches the numeric USB drive ID shown in the drives list and can be used directly in `job_seed.jobs[].drive_id`
- Recommendation: do not invent this value; use the ID ECUBE shows in the UI or the one written back into `demo-metadata.json` after seed

#### usb_seed.drives[].port_system_path

The discovered ECUBE USB port path that must have a real device attached.

- Type: string
- Example: `1-1`
- Effect: this is the physical USB port ECUBE enables and checks during the demo seed

#### usb_seed.drives[].project_id

The numeric demo project reference for the real USB device on that configured port.

- Type: integer
- Example: `1`
- Effect: binds the attached USB device to the project described by `projects[].project_name`
- Compatibility note: older metadata that still uses the string project name is normalized automatically during seed, but new metadata should use the numeric project ID

#### usb_seed.drives[].device_identifier

Optional expected hardware identifier for the device attached at the configured port.

- Type: string or `null`
- Example: use the real discovered value for the attached device on that port
- Effect: when provided, ECUBE only seeds the USB drive if the actual attached device matches this identifier exactly
- Recommendation: replace any sample placeholder with the actual discovered identifier, or omit this property if you want the binding to rely on the configured USB port alone

To enumerate ready-to-paste `usb_seed.drives` objects for the currently connected host USB disks, run the repository helper from the project root.

```bash
bash ./scripts/print_demo_usb_seed_json.sh
```

The helper prints comma-separated JSON objects containing `id`, `port_system_path`, `project_id`, and `device_identifier`. Pass a different project ID as the first argument or a different starting ID as the second argument when you want to prepare entries for another demo project, for example `bash ./scripts/print_demo_usb_seed_json.sh 2 10`.

### mount_seed

This object controls whether the demo bootstrap should register and mount real network shares that are reachable from the host during seed time.

#### mount_seed.enabled

Turns real NFS and SMB mount seeding on or off.

- Type: boolean
- Typical value: `false` by default, `true` when you want real network shares included in the demo seed
- Effect: when `true`, ECUBE evaluates the configured network mount list and attempts to add and mount each explicitly defined share

#### mount_seed.mounts

List of explicit network-share-to-project mappings for the demo seed.

- Type: array of mount seed objects
- Requirement: each entry should identify the protocol, remote URI path, and associated numeric demo project reference
- Recommendation: define only the real shares you want included in the demonstration workflow

#### mount_seed.mounts[].id

Numeric mount ID shown in the ECUBE UI after the network share has been registered.

- Type: integer
- Example: `17`
- Effect: this matches the numeric mount ID shown in the mounts list and can be used directly in `job_seed.jobs[].mount_id`
- Recommendation: do not invent this value; use the ID ECUBE shows in the UI or the one written back into `demo-metadata.json` after seed

#### mount_seed.mounts[].type

The protocol for the configured remote source.

- Type: string
- Supported values: `NFS`, `SMB`
- Example: `NFS`

#### mount_seed.mounts[].remote_path

The real NFS export path or SMB URI that ECUBE should mount.

- Type: string
- Examples: `192.168.10.25:/exports/demo-case-001`, `//fileserver/demo-share`
- Effect: this is the actual remote source ECUBE registers and mounts during seed

#### mount_seed.mounts[].project_id

The numeric demo project reference that the mounted share should be associated with.

- Type: integer
- Example: `1`
- Effect: preserves project isolation for the demo workflow by resolving to the matching `projects[].project_name`

#### mount_seed.mounts[].username

Optional username for SMB authentication.

- Type: string or `null`
- Example: `demo-user`
- Recommendation: only set this when the share actually requires account-based access

#### mount_seed.mounts[].password

Optional password for SMB authentication.

- Type: string or `null`
- Recommendation: prefer a credentials file for repeatable appliance deployments when possible

#### mount_seed.mounts[].credentials_file

Optional host path to a credentials file used for SMB mounting.

- Type: string or `null`
- Example: `/opt/ecube/demo-smb.creds`
- Effect: when provided, ECUBE passes the credentials file to the trusted SMB mount operation

### job_seed

This object defines the job records that the demo bootstrap should create from the trusted component references defined in the metadata.

#### job_seed.jobs

List of job definitions that ECUBE should create during the demo seed.

- Type: array of job seed objects
- Requirement: each entry should define the numeric demo project reference, evidence number, numeric source mount ID, numeric destination USB ID, and source path

#### job_seed.jobs[].id

Optional numeric seeded job ID.

- Type: integer
- Example: `101`
- Effect: when provided, ECUBE uses this value as the actual `export_jobs.id` for the seeded database row
- Recommendation: use a stable numeric value if you want the same walkthrough job ID after every reseed

#### job_seed.jobs[].ui_job_id

Runtime confirmation of the actual job ID created by seed.

- Type: integer
- Example: `101`
- Effect: written back into the managed metadata after seeding so the JSON mirrors the real UI and database ID

#### job_seed.jobs[].project_id

The numeric demo project reference for the seeded job.

- Type: integer
- Example: `1`
- Effect: resolves to the matching `projects[].project_name` during trusted job creation

#### job_seed.jobs[].evidence_number

The evidence or matter number stored on the seeded job.

- Type: string
- Example: `EVID-DEMO-JOB-001`

#### job_seed.jobs[].mount_id

Numeric mount ID for the mounted source share.

- Type: integer
- Example: `17`
- Effect: use the same mount ID shown in the ECUBE mounts UI so the seeded job points at the intended trusted source

#### job_seed.jobs[].drive_id

Numeric USB drive ID for the destination device.

- Type: integer
- Example: `1`
- Effect: use the same drive ID shown in the ECUBE drives UI so the seeded job uses the intended USB destination

#### job_seed.jobs[].source_path

The path inside the selected source mount that the seeded job should use.

- Type: string
- Example: `/incoming`
- Effect: ECUBE resolves this path against the referenced source mount during job creation

#### job_seed.jobs[].status

Optional initial job status.

- Type: string
- Supported values: `PENDING`, `RUNNING`, `VERIFYING`, `COMPLETED`, `FAILED`
- Default: `PENDING`

### projects

List of seeded synthetic projects and their catalog metadata.

- Type: array of project objects
- Use for: demo-safe case references, relational mapping, and folder layout under the demo root.

#### projects[].project_id

Stable numeric demo project reference used by `usb_seed`, `mount_seed`, and `job_seed`.

- Type: integer
- Example: `1`
- Use for: relational references inside the managed demo metadata.

#### projects[].project_name

The actual ECUBE project identifier associated with the seeded sample content.

- Type: string
- Example: `DEMO-CASE-001`
- Use for: drive binding, mount association, and walkthrough scenarios shown in the UI and seeded database rows.

#### projects[].folder

Folder name created under the demo data root for this sample project.

- Type: string
- Example: `demo-case-001`
- Recommendation: keep this aligned with the staged directory structure.

#### projects[].sanitized

Marker showing the content is safe for demo use.

- Type: boolean
- Typical value: `true`
- Recommendation: keep all demo-seeded projects marked as sanitized.

### Copy-and-paste starter example

Use the following sample as a starting point for a managed demo deployment:

```json
{
  "managed_by": "ecube-demo-seed-v1",
  "generated_at": "2026-04-19T00:00:00+00:00",
  "demo_config": {
    "demo_mode": true,
    "login_message": "Use the shared demo accounts below.",
    "shared_password": "demo",
    "demo_disable_password_change": true,
    "password_change_allowed": false,
    "accounts": [
      {
        "username": "demo_admin",
        "label": "Admin demo",
        "description": "Guided administrator walkthrough",
        "roles": ["admin"],
        "password": "demo"
      },
      {
        "username": "demo_manager",
        "label": "Manager demo",
        "description": "Drive lifecycle and job visibility review",
        "roles": ["manager"],
        "password": "demo"
      },
      {
        "username": "demo_processor",
        "label": "Processor demo",
        "description": "Execute export jobs and review sample evidence state",
        "roles": ["processor"],
        "password": "demo"
      },
      {
        "username": "demo_auditor",
        "label": "Auditor demo",
        "description": "Read-only audit and verification review",
        "roles": ["auditor"],
        "password": "demo"
      }
    ]
  },
  "usb_seed": {
    "enabled": true,
    "drives": [
      {
        "id": 1,
        "port_system_path": "1-1",
        "project_id": 1,
        "device_identifier": "usb-demo-001"
      }
    ]
  },
  "mount_seed": {
    "enabled": true,
    "mounts": [
      {
        "id": 17,
        "type": "NFS",
        "remote_path": "192.168.10.25:/exports/demo-case-001",
        "project_id": 1
      },
      {
        "id": 14,
        "type": "SMB",
        "remote_path": "//fileserver/demo-share",
        "project_id": 2,
        "username": "demo-user",
        "credentials_file": "/opt/ecube/demo-smb.creds"
      }
    ]
  },
  "job_seed": {
    "jobs": [
      {
        "id": 101,
        "project_id": 1,
        "evidence_number": "EVID-DEMO-JOB-001",
        "mount_id": 17,
        "drive_id": 1,
        "source_path": "/incoming",
        "status": "PENDING",
        "ui_job_id": 101
      }
    ]
  },
  "projects": [
    {
      "project_id": 1,
      "project_name": "DEMO-CASE-001",
      "folder": "demo-case-001",
      "sanitized": true
    },
    {
      "project_id": 2,
      "project_name": "DEMO-CASE-002",
      "folder": "demo-case-002",
      "sanitized": true
    }
  ]
}
```

## Seeding your own sanitized demo data

The current bootstrap command does not import an arbitrary external evidence set automatically. It always stages the built-in synthetic sample content first.

If you want to present your own sanitized demo files, use this supported operator workflow:

1. Keep a master copy of your sanitized demo material outside the managed demo root, for example in a separate staging directory.
2. Run the ECUBE seed command to prepare the accounts, roles, audit state, and demo directory structure.
3. Copy your sanitized demo files into the demo root after the seed completes, either alongside the generated sample folders or in place of them.
4. Use only synthetic or fully sanitized content.
5. Keep the authoritative copy elsewhere, because rerunning `seed` or `reset` will recreate or remove the managed demo root.

Example copy step after the bootstrap completes:

```bash
sudo rsync -a /opt/ecube/demo-source/ /opt/ecube/demo-data/
```

If you want the seed flow to prepare only the database and demo directory while leaving existing OS accounts alone, run:

```bash
sudo bash -lc 'cd /opt/ecube && /opt/ecube/venv/bin/ecube-demo-bootstrap --data-root /opt/ecube/demo-data seed --skip-os-users'
```

If you need to populate `usb_seed.drives` before running the seed, generate the host USB entries first from the repository root and paste the output into `demo-metadata.json`.

```bash
bash ./scripts/print_demo_usb_seed_json.sh
```

## Running from source in demo mode

For local development or direct source execution, use the repository root `.env` file and a local demo-data directory.

1. Set the minimal local configuration:

```env
DEMO_MODE=true
```

2. Provision the database normally for a source-based development run. Ensure `DATABASE_URL` is configured, run the usual migrations or setup flow, and confirm the backend can connect successfully before seeding the demo.

Example local PostgreSQL provisioning flow:

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE ecube WITH LOGIN PASSWORD 'ecube';
ALTER ROLE ecube CREATEDB;
CREATE DATABASE ecube OWNER ecube;
SQL
```

Then set the repository root `.env` file with a matching connection string, for example:

```env
DATABASE_URL=postgresql://ecube:ecube@localhost:5432/ecube
DEMO_MODE=true
```

For local OS-backed login from source, remember that ECUBE authenticates through PAM. On hardened Linux hosts, the account running the backend may need access equivalent to the installed service account, including membership in the appropriate shadow-reading group, or the demo accounts may exist but still return 401 during login.

```bash
sudo usermod -aG shadow <local-dev-user>
```

Replace `<local-dev-user>` with the account that is running the backend, then start a fresh login session before retrying the backend.

3. Seed the demo state from the repository root.

```bash
source .venv/bin/activate
python -m app.demo_bootstrap --data-root ./demo-data seed --shared-password "demo"
```

If you also want the source-run demo to include real connected USB media or real NFS/SMB shares, add the `usb_seed` and/or `mount_seed` section to `./demo-data/demo-metadata.json`, then run the normal seed command.

4. Start the backend directly from source:

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --reload
```

5. In a separate terminal, start the frontend dev server normally:

```bash
cd frontend
npm install
npm run dev
```

The frontend does not require its own demo-mode flag. It reads the public demo configuration from the backend and updates the login experience automatically.

If you later want to remove the local demo state during source-based development, use the same module form:

```bash
source .venv/bin/activate
python -m app.demo_bootstrap --data-root ./demo-data reset
```

After the seed completes, the demo metadata stored in the demo root drives the login guidance and demo account behavior.

## Reset demo content

To remove the managed demo data and refresh the environment, run:

```bash
sudo bash -lc 'cd /opt/ecube && /opt/ecube/venv/bin/ecube-demo-bootstrap --data-root /opt/ecube/demo-data reset'
```

The reset flow removes only directories previously marked as demo-managed. It will refuse to delete an unmanaged path.

## Operator expectations

Use only sanitized or synthetic sample content in the demo environment.

Choose a strong deployment-specific shared password for demo accounts and rotate it whenever the demo appliance is reset or handed to a new audience.

Do not place real customer evidence, internal export paths, or production credentials inside the demo data root or the public login guidance message.

Use a dedicated demo-only directory so staged content never overlaps with live evidence locations.

## Validation checklist

After seeding the demo environment, confirm the following:

- the login page shows only public-safe demo guidance
- shared demo accounts appear with the intended roles and descriptions
- password reset is blocked for shared demo accounts
- rerunning the seed command restores the same sample state without duplicates
- the reset command removes only demo-managed files
- audit logs record the seed, reset, and denied password-change events

## Safety notes

All seeded content is synthetic and explicitly marked as demo-only.

The seed flow writes audit entries for both seed and reset operations.

A dedicated demo-only data root should be used so sample files never mix with real evidence sources.
