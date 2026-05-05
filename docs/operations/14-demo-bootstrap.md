# Demo bootstrap

## Purpose

ECUBE demo mode turns a normal installation into a controlled product-demo environment. The supported workflow now focuses on demo-safe users, a shared demo password, and login guidance that the installer or bootstrap derives from `demo-metadata.json` and persists into runtime `DEMO_*` settings.

Demo bootstrap no longer seeds USB drives, network mounts, jobs, staged files, or sample projects.

## Configure demo mode

Set `DEMO_MODE=true` in the ECUBE environment configuration to enable demo mode.

For a package or native install, this is usually the root `.env` file at `/opt/ecube/.env`.

For local development, use the repository `.env` file.

For Docker Compose, place the same variables in your compose `.env` file or in the application service environment.

Minimal `.env` configuration:

```env
DEMO_MODE=true
```

For a native install, `install.sh --demo` looks for `demo-metadata.json` in the same directory as `install.sh`, uses it as trusted bootstrap input, and writes the resulting runtime `DEMO_*` values into the installed `.env` file.

At runtime, ECUBE reads only `.env` values such as `DEMO_MODE`, `DEMO_LOGIN_MESSAGE`, `DEMO_SHARED_PASSWORD`, `DEMO_DISABLE_PASSWORD_CHANGE`, and `DEMO_ACCOUNTS`. Running the app from source behaves normally unless you set those environment variables yourself. When `DEMO_MODE=true`, successful setup completion and later startup reconciliation both ensure the configured demo OS users and DB roles exist. Missing demo accounts are created with the effective shared password, existing demo accounts are reconciled back into the expected ECUBE groups, and existing non-setup-managed demo accounts have their password reset back to the effective shared password. During the setup-completion request itself, ECUBE skips an immediate redundant password reset for the setup-managed demo account so password-history or unchanged-password PAM rules do not block creation of the remaining demo users. If `DEMO_SHARED_PASSWORD` is empty, ECUBE derives that value from the active Password Policy settings before exposing it on the login screen and before applying it to demo accounts during setup completion or the next startup reconciliation. Because those resets use the normal local-account password path, the effective shared password must satisfy the active PAM password policy whenever host password-policy enforcement is enabled.

The login screen exposes the demo login message, the shared demo password when configured, the demo usernames, their labels and descriptions, and the password-change policy.

## Installer workflow

1. Prepare `demo-metadata.json` next to `install.sh`.
2. Run the installer in demo mode.

```bash
sudo ./install.sh --demo
```

When `--demo` is set during a real install, the installer updates `.env` with `DEMO_MODE=true`, `DEMO_LOGIN_MESSAGE`, `DEMO_SHARED_PASSWORD`, `DEMO_DISABLE_PASSWORD_CHANGE`, and `DEMO_ACCOUNTS`, ensures `DATABASE_URL` is set when missing, creates the local `ecube` database if needed, runs `alembic upgrade head`, and immediately runs `ecube-demo-bootstrap --metadata-path <install-root>/demo-metadata.json seed --shared-password <generated-or-configured-password>`. If the metadata leaves `demo_config.shared_password` blank, the installer generates a strong demo password, writes it into the installed `demo-metadata.json`, and writes the same password into `.env` for runtime login prefill. Any configured or generated shared password still has to pass the active PAM password policy before ECUBE can apply it to local demo accounts.

If `DATABASE_URL` already points at a different PostgreSQL instance, the installer preserves it and skips local database creation.

## Command syntax

Use this command shape when running the bootstrap manually:

```bash
ecube-demo-bootstrap [--actor NAME] [--metadata-path PATH] seed [--shared-password "..."] [--skip-os-users]
ecube-demo-bootstrap [--actor NAME] [--metadata-path PATH] reset
```

Place `--metadata-path` and `--actor` before `seed` or `reset`. These are global options, so if they are placed after the subcommand the CLI will reject them.

Use `--skip-os-users` when you only want to seed database role assignments and do not want ECUBE to create or reset host OS accounts.

## What the seed command does

When the seed command runs, ECUBE performs these actions in order:

1. Loads `demo_config.accounts` from the configured metadata file.
2. Deletes previously seeded demo jobs from the database if any exist from older demo state.
3. Removes and reapplies configured demo role mappings for the demo usernames.
4. If OS-user management is enabled, ensures the ECUBE groups exist, creates any missing demo accounts, and resets existing demo-account passwords to the provided shared password when applicable.
5. Writes an audit event for the bootstrap action. If the audit write itself fails, ECUBE logs the failure and still keeps the already-applied demo user and role reconciliation.

## demo-metadata.json

The installer-colocated metadata file is trusted demo bootstrap input and a rerun source for `ecube-demo-bootstrap`; the running application does not read it for runtime demo configuration.

```json
{
  "managed_by": "ecube-demo-seed-v1",
  "generated_at": "2026-04-19T00:00:00+00:00",
  "demo_config": {
    "demo_mode": true,
    "login_message": "Use the shared demo accounts below.",
    "shared_password": "",
    "demo_disable_password_change": true,
    "password_change_allowed": false,
    "accounts": [
      {
        "username": "demo_manager",
        "label": "Manager demo",
        "description": "Workflow review",
        "roles": ["manager"]
      }
    ]
  }
}
```

Supported top-level properties are `managed_by`, `generated_at`, and `demo_config`.

The `demo_config` object controls login messaging, shared-password behavior, password-change restrictions, and demo account definitions.

`usb_seed`, `mount_seed`, `job_seed`, and `projects` are no longer part of the supported demo metadata contract.

## Reset demo content

To remove demo-seeded role assignments and seeded jobs, run:

```bash
ecube-demo-bootstrap reset --metadata-path ./demo-metadata.json
```

Reset no longer manages filesystem cleanup.

## Operator expectations

- Demo mode disables user creation and password modification flows that are blocked by demo policy.
- If `shared_password` is blank in the source metadata, the installer or post-install helper generates one before seeding demo accounts.
- If `DEMO_SHARED_PASSWORD` is left empty at runtime, ECUBE derives the displayed shared password from the active Password Policy settings and reapplies that implicit password to demo accounts when setup completes and during later startup reconciliation.
- When demo-mode setup uses a configured demo admin account as the one-time setup account, the immediate post-setup reconciliation still creates the remaining demo accounts but skips reapplying the same password to that just-configured setup account during the same request.
- If a demo bootstrap or runtime demo audit entry cannot be written, ECUBE now logs a safe failure classification and keeps the demo-user and role reconciliation that already succeeded instead of aborting setup solely because of the trailing audit write.
- If a demo account reaches a `password_expired` state, the login screen does not offer self-service password change for that account. Operators should rerun the demo seed with a new shared password to reset the managed demo credentials.
- For an installed appliance, use one of these recovery paths:

```bash
sudo bash -lc 'cd /opt/ecube && /opt/ecube/venv/bin/ecube-demo-bootstrap --metadata-path /opt/ecube/demo-metadata.json seed --shared-password "Choose-A-New-Demo-Password"'
```

```bash
bash ./scripts/post_install_demo_setup.sh "Choose-A-New-Demo-Password"
```

- If you want the helper to generate a fresh password automatically, leave `demo_config.shared_password` blank in the source metadata and run `bash ./scripts/post_install_demo_setup.sh` without an argument. The helper writes the generated password into the installed metadata and prints it for the operator.
- Rerunning the seed command is safe for demo users and role assignments.
- Demo bootstrap is intended for demos only and must not be used with real evidence.

## Validation checklist

After running `install.sh --demo`, verify the following:

1. `.env` contains `DEMO_MODE=true` and the expected `DEMO_LOGIN_MESSAGE`, `DEMO_SHARED_PASSWORD`, `DEMO_DISABLE_PASSWORD_CHANGE`, and `DEMO_ACCOUNTS` values.
2. The demo users from `demo-metadata.json` exist and share the configured password.
3. If the setup wizard used a demo admin account to complete setup, the remaining configured demo users still exist after setup without requiring a retry or restart.
4. The login page shows the demo guidance and shared password, and prefills the password field for demo sign-in.
5. Password changes and demo-user-management writes remain blocked in demo mode.

## Safety notes

- Demo mode is for synthetic content only.
- Toggling `DEMO_MODE` alone does not remove demo users or role assignments. Use the reset command when you want to remove demo-seeded state.
