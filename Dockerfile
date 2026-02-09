FROM python:3.13-slim@sha256:3de9a8d7aedbb7984dc18f2dff178a7850f16c1ae7c34ba9d7ecc23d0755e35f AS builder

WORKDIR /app

COPY requirements.lock .
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .

FROM python:3.13-slim@sha256:3de9a8d7aedbb7984dc18f2dff178a7850f16c1ae7c34ba9d7ecc23d0755e35f

LABEL org.opencontainers.image.title="Loxone Prometheus Exporter" \
      org.opencontainers.image.description="Exports Loxone Miniserver control values as Prometheus metrics" \
      org.opencontainers.image.source="https://github.com/loxone-prometheus-exporter"

ARG VERSION=0.1.0
ARG COMMIT=unknown
ARG BUILD_DATE=unknown

ENV LOXONE_EXPORTER_VERSION=${VERSION} \
    LOXONE_EXPORTER_COMMIT=${COMMIT} \
    LOXONE_EXPORTER_BUILD_DATE=${BUILD_DATE}

RUN groupadd --gid 1000 exporter && \
    useradd --uid 1000 --gid exporter --shell /bin/false exporter

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /app/src /app/src

USER exporter

EXPOSE 9504

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9504/healthz')"

ENTRYPOINT ["python", "-m", "loxone_exporter"]
