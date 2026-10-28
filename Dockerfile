# syntax=docker/dockerfile:1
# Multi-stage build: React frontend -> FastAPI runtime image.
FROM node:22-bookworm AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BLUEKVM_ENV=production \
    BLUEKVM_EMBEDDED_WORKER=1

# KVM tooling needed for real virtualization on a privileged host
RUN apt-get update && apt-get install -y --no-install-recommends \
        qemu-kvm qemu-utils libvirt-clients libvirt-daemon-system \
        python3-libvirt \
        genisoimage cloud-image-utils curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/bluekvm/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /build/frontend/dist /opt/bluekvm/frontend/dist

RUN mkdir -p /var/lib/bluekvm/vms /var/lib/bluekvm/templates /var/lib/bluekvm/backups /var/log/bluekvm
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health/live || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
