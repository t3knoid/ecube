# Stage 1: Build the Vue 3 SPA
FROM node:20-alpine3.21 AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Python application with bundled frontend
FROM python:3.11.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get -y upgrade && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    exfatprogs \
    iproute2 \
    mount \
    nfs-common \
    cifs-utils \
    openssl \
    procps \
    udev \
    usbutils \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ecube

COPY pyproject.toml /opt/ecube/pyproject.toml
COPY app /opt/ecube/app
COPY alembic /opt/ecube/alembic
COPY alembic.ini /opt/ecube/alembic.ini
COPY deploy/ecube-host/entrypoint.sh /usr/local/bin/ecube-entrypoint.sh

RUN chmod +x /usr/local/bin/ecube-entrypoint.sh

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir .

# Create the certs directory for TLS.  A self-signed certificate is
# generated on first container start (not at build time) so each
# deployment gets a unique private key.  Mount real certs to
# /opt/ecube/certs or set TLS_KEYFILE / TLS_CERTFILE to override.
RUN mkdir -p /opt/ecube/certs

# Seed an empty .env so the bind mount target is always a file.
# If the host mounts its own .env, it overlays this default.
RUN touch /opt/ecube/.env && chmod 600 /opt/ecube/.env

# Bundle the pre-built frontend into the image
COPY --from=frontend-build /app/dist /opt/ecube/www

ENV SERVE_FRONTEND_PATH=/opt/ecube/www

EXPOSE 8000 8443

ENTRYPOINT ["/usr/local/bin/ecube-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]
