ARG PYTHON_IMAGE=python:3.11.11-slim-bookworm
FROM ${PYTHON_IMAGE}

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
    && pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/ecube-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
