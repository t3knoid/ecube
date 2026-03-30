#!/usr/bin/env python3
"""Generate a production docker-compose.yml that references pre-built registry images.

This script is invoked by the docker-build CI workflow to produce the release
docker-compose artifact. It replaces the `build:` directives in the development
compose files with `image:` references pointing to the published registry images.

Usage:
    python scripts/generate_release_compose.py \\
        --app-image ghcr.io/t3knoid/ecube-app:v1.2.3 \\
        --ui-image  ghcr.io/t3knoid/ecube-ui:v1.2.3 \\
        --output    dist/docker-compose.yml
"""

import argparse
import os
import textwrap


def build_compose(app_image: str, ui_image: str, version: str) -> str:
    return textwrap.dedent(f"""\
    # ECUBE Production Docker Compose — {version}
    #
    # Pre-built images are referenced directly; no source code needed.
    #
    # Minimum required .env settings:
    #   SECRET_KEY=<random string, at least 32 characters>
    #   LOCAL_GROUP_ROLE_MAP={{}}
    #   ECUBE_CERTS_DIR=./certs
    #
    # See README.md for full deployment instructions.
    #
    # Only the UI port (8443 by default) is published to the host.
    # The API and database are reachable only within the Docker network.

    services:
      ecube-app:
        image: {app_image}
        container_name: ecube-app
        restart: unless-stopped
        privileged: true
        cap_add:
          - SYS_ADMIN
          - DAC_READ_SEARCH
        security_opt:
          - apparmor:unconfined
        environment:
          DATABASE_URL: postgresql://ecube:ecube@postgres:5432/ecube
          PYTHONUNBUFFERED: "1"
          TRUST_PROXY_HEADERS: "true"
          ECUBE_RUN_MIGRATIONS_ON_START: "true"
          ECUBE_DB_WAIT_MAX_RETRIES: "30"
          ECUBE_DB_WAIT_SECONDS: "2"
          USE_SUDO: "false"
          SECRET_KEY: "${{SECRET_KEY}}"
          LOCAL_GROUP_ROLE_MAP: "${{LOCAL_GROUP_ROLE_MAP:-{{}}}}"
          USB_DISCOVERY_INTERVAL: "${{USB_DISCOVERY_INTERVAL:-30}}"
        volumes:
          - ecube_runtime_data:/var/lib/ecube
          - /dev/bus/usb:/dev/bus/usb
          - /run/udev:/run/udev:ro
          - /sys/bus/usb:/sys/bus/usb:ro
          - /proc:/host_proc:ro
        depends_on:
          postgres:
            condition: service_healthy

      ecube-ui:
        image: {ui_image}
        container_name: ecube-ui
        restart: unless-stopped
        ports:
          - "${{UI_PORT:-8443}}:443"
        volumes:
          - ${{ECUBE_CERTS_DIR:-./certs}}:/etc/nginx/certs:ro
          - ${{ECUBE_THEMES_DIR:-./deploy/themes}}:/usr/share/nginx/html/themes:ro
        depends_on:
          - ecube-app

      postgres:
        image: postgres:16
        container_name: ecube-postgres
        restart: unless-stopped
        environment:
          POSTGRES_DB: ecube
          POSTGRES_USER: ecube
          POSTGRES_PASSWORD: ecube
        volumes:
          - ecube_postgres_data:/var/lib/postgresql/data
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U ecube -d ecube"]
          interval: 5s
          timeout: 5s
          retries: 10

    volumes:
      ecube_runtime_data:
      ecube_postgres_data:
    """)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-image", required=True, help="Fully-qualified ecube-app image reference")
    parser.add_argument("--ui-image", required=True, help="Fully-qualified ecube-ui image reference")
    parser.add_argument("--output", default="dist/docker-compose.yml", help="Output file path")
    args = parser.parse_args()

    # Infer a display version from the image tag (e.g. ghcr.io/org/ecube-app:v1.2.3 → v1.2.3)
    version = args.app_image.rsplit(":", 1)[-1] if ":" in args.app_image else "unknown"

    content = build_compose(
        app_image=args.app_image,
        ui_image=args.ui_image,
        version=version,
    )

    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(f"Generated {output_path}")
    print(f"  ecube-app: {args.app_image}")
    print(f"  ecube-ui:  {args.ui_image}")


if __name__ == "__main__":
    main()
