FROM python:3.14.7-alpine3.23 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /bin/

WORKDIR /app

# Install build dependencies for Alpine
RUN apk add --no-cache gcc g++ musl-dev linux-headers libffi-dev

COPY uv.lock .
COPY pyproject.toml .
COPY src/ src/

RUN uv export --frozen --no-dev --no-emit-project --format requirements.txt --output-file requirements.txt

# Install into a self-contained venv so the runtime stage never has to
# reference an interpreter-version-specific site-packages path.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip==26.2.1 \
    && /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements.txt \
    && /opt/venv/bin/python -m pip install --no-cache-dir --no-deps . \
    && /opt/venv/bin/python -m pip uninstall -y pip setuptools wheel || true

FROM python:3.14.7-alpine3.23

LABEL org.opencontainers.image.title="Loxone Prometheus Exporter" \
      org.opencontainers.image.description="Exports Loxone Miniserver control values as Prometheus metrics" \
      org.opencontainers.image.source="https://github.com/loxone-prometheus-exporter"

ARG VERSION=0.1.0
ARG COMMIT=unknown
ARG BUILD_DATE=unknown

ENV LOXONE_EXPORTER_VERSION=${VERSION} \
    LOXONE_EXPORTER_COMMIT=${COMMIT} \
    LOXONE_EXPORTER_BUILD_DATE=${BUILD_DATE} \
    PATH="/opt/venv/bin:${PATH}"

# Alpine uses addgroup/adduser instead of groupadd/useradd
RUN apk upgrade --no-cache \
    && addgroup -g 1000 exporter && \
    adduser -D -u 1000 -G exporter -s /sbin/nologin exporter

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Drop the interpreter's own installer tooling from the runtime image.
RUN rm -rf /usr/local/lib/python*/site-packages/pip \
    /usr/local/lib/python*/site-packages/pip-*.dist-info \
    /usr/local/lib/python*/ensurepip \
    /usr/local/bin/pip \
    /usr/local/bin/pip3 \
    /usr/local/bin/pip3.*

USER exporter

EXPOSE 9504

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9504/healthz')"

ENTRYPOINT ["python", "-m", "loxone_exporter"]
