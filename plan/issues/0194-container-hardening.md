# 0194 — Container hardening: non-root, pinned base images

Status: spec (future; owner 2026-11-13: not in the v10.16.2 hotfix, a user change risks the volumes' permissions
on his server). v10.16.2 did the two parts with no such risk: `yt-dlp` pinned in backend/requirements.txt, and
`npm ci` without the `|| npm install` fallback in frontend/Dockerfile.

## What the audit found (M3)

- Both images run as root: backend/Dockerfile (python:3.12-slim, uvicorn and the scheduler) and the frontend's
  nginx stage (nginx:alpine; nginx's master runs as root by design, the workers as `nginx`). A code-execution bug
  in a parser (feeds, HTML, yt-dlp) runs as root in the container, with write access to the image and the volumes.
- Base images by tag only (`python:3.12-slim`, `node:22-alpine`, `nginx:alpine`, `pgvector/pgvector:pg15`): a
  rebuild takes whatever the tag points at that day.

## Design

### Non-root backend
- `RUN useradd --system --uid 10001 --home /app insight`, `USER insight` after the install layers.
- What it must write: `/app/logs` (insight_logs volume: logs, the watchdog's restart file, api-stacks.log),
  `/app/secrets` (insight_secrets: the Fernet key, made once), `/app/insight_core/config` (a bind mount of the
  checkout: sources.json is rewritten after each source change), the export progress directory (tmp), yt-dlp's
  cache (`$HOME/.cache`).
- Existing volumes are owned by root: a new image as uid 10001 can't write them. Two ways: an entrypoint that
  `chown`s the volume directories once and drops privileges (`setpriv`/`gosu`; it starts as root), or a one-off
  `docker compose run --rm --user root backend chown -R 10001 /app/logs /app/secrets` documented in the update
  notes. The bind-mounted config directory is the owner's checkout: its files must be writable by 10001 (chown
  on the host, or keep sources.json writes going through a volume).
- Test with a separate compose project (`docker compose -p insight-hardening ...`) on fresh volumes AND on
  volumes copied from a root-owned set, before the owner's server.

### Non-root frontend
- `nginxinc/nginx-unprivileged` (port 8080, `/var/cache/nginx` writable) or `user nginx` with the cache path
  owned by it; compose maps `${FRONTEND_PORT}:8080`.

### Digests
- Pin `FROM` lines by digest with the tag in a comment, e.g. `FROM python:3.12-slim@sha256:<digest>`. The
  manifest-list digests on 2026-11-13 (docker buildx imagetools inspect):
  - python:3.12-slim `sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`
  - node:22-alpine `sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a`
  - nginx:alpine `sha256:713fc2ebfd92e8217db451477182ee91944b123d2b1ee9fd5a8c6e91ca6c3a11`
  - pgvector/pgvector:pg15: read it the day it is pinned (a database image: change it only on purpose).
- `./update --refresh` then no longer pulls newer bases by itself: refreshing is bumping the digests (a small
  script that prints the current ones), on purpose, for security patches.
