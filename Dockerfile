# PinSaver in a container: the site on 0.0.0.0:8000.
# The archive (database, originals, backups) is not baked in - docker-compose.yml mounts it.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    PINSAVER_ADMIN_HOST=0.0.0.0 \
    PINSAVER_ADMIN_PORT=8001 \
    PINSAVER_DATA_DIR=/data

WORKDIR /app

# Runtime dependencies only: Playwright, BeautifulSoup and Pillow live in
# src/requirements-tools.txt and belong to the host scripts, never to the image.
COPY src/requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . .

# Build metadata: declared after the dependency layer so a new commit does not invalidate
# the pip layer. deploy/windows/update.ps1 passes these as --build-arg; when they are empty
# - a plain `docker compose up -d --build` after `git pull` - the commit is read from the
# trimmed .git that COPY brings in (see .dockerignore and src/buildinfo.py).
ARG PINSAVER_COMMIT=""
ARG PINSAVER_COMMIT_DATE=""
ARG PINSAVER_VERSION=""
ARG PINSAVER_CREATED=""
ENV PINSAVER_COMMIT=${PINSAVER_COMMIT} PINSAVER_COMMIT_DATE=${PINSAVER_COMMIT_DATE}
LABEL org.opencontainers.image.source="https://github.com/northis/PinSaver" \
      org.opencontainers.image.revision="${PINSAVER_COMMIT}" \
      org.opencontainers.image.version="${PINSAVER_VERSION}" \
      org.opencontainers.image.created="${PINSAVER_CREATED}"

# Mount point used by docker-compose.yml: the archive lives on the host.
RUN mkdir -p /data

# 8000 - site. 8001 - maintenance page (the admin listener; published on local addresses only).
EXPOSE 8000 8001

# Liveness probe (GET /api/version): every 5 minutes, it is only for docker ps status.
HEALTHCHECK --interval=5m --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/version', timeout=3)"

CMD ["python", "src/server.py"]
