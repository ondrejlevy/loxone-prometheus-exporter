FROM python:3.14-alpine@sha256:faee120f7885a06fcc9677922331391fa690d911c020abb9e8025ff3d908e510 AS builder

WORKDIR /app

# Install build dependencies for Alpine
RUN apk add --no-cache gcc musl-dev linux-headers libffi-dev

COPY requirements.lock .
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .

FROM python:3.14-alpine@sha256:faee120f7885a06fcc9677922331391fa690d911c020abb9e8025ff3d908e510

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

USER exporter

EXPOSE 9504

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9504/healthz')"

ENTRYPOINT ["python", "-m", "loxone_exporter"]
