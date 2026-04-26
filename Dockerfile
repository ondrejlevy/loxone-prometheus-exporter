FROM python:3.15.0a8-alpine3.23 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

WORKDIR /app

# Install build dependencies for Alpine
RUN apk add --no-cache gcc musl-dev linux-headers libffi-dev

COPY uv.lock .
COPY pyproject.toml .
COPY src/ src/

RUN uv export --frozen --no-dev --no-emit-project --format requirements.txt --output-file requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip==26.0.1 \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip install --no-cache-dir --no-deps .

FROM python:3.15.0a8-alpine3.23

LABEL org.opencontainers.image.title="Loxone Prometheus Exporter" \
      org.opencontainers.image.description="Exports Loxone Miniserver control values as Prometheus metrics" \
      org.opencontainers.image.source="https://github.com/loxone-prometheus-exporter"

ARG VERSION=0.1.0
ARG COMMIT=unknown
ARG BUILD_DATE=unknown

ENV LOXONE_EXPORTER_VERSION=${VERSION} \
    LOXONE_EXPORTER_COMMIT=${COMMIT} \
    LOXONE_EXPORTER_BUILD_DATE=${BUILD_DATE}

# Alpine uses addgroup/adduser instead of groupadd/useradd
RUN addgroup -g 1000 exporter && \
    adduser -D -u 1000 -G exporter -s /sbin/nologin exporter

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /app/src /app/src

RUN rm -rf /usr/local/lib/python3.14/site-packages/pip \
    /usr/local/lib/python3.14/site-packages/pip-*.dist-info \
    /usr/local/lib/python3.14/ensurepip \
    /usr/local/bin/pip \
    /usr/local/bin/pip3 \
    /usr/local/bin/pip3.14

USER exporter

EXPOSE 9504

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9504/healthz')"

ENTRYPOINT ["python", "-m", "loxone_exporter"]
