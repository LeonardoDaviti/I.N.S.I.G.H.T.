# 0193 — CSRF and trusted hosts

Status: spec (future; owner 2026-11-13: not in the v10.16.2 hotfix). Goes with 0192.

## What the audit found

- Any web page the owner opens can send requests to his INSIGHT: a form or `fetch(..., {mode: 'no-cors'})` to
  `http://<insight-host>:3000/api/...` reaches the API with the owner's network position (and, once 0192 ships,
  with his cookie unless SameSite stops it). Simple POSTs (form-encoded, text/plain) need no CORS preflight; the
  API answers JSON bodies, but several routes take no body at all (`POST /api/ingestion/run`,
  `POST /api/markx/token`, `POST /api/archive/resume-interrupted`); PUT and DELETE need a preflight, which the
  CORS list refuses, unless DNS rebinding (below) makes the page same-origin.
- DNS rebinding: a site whose name resolves first to itself, then to the owner's LAN address, reads INSIGHT's
  answers in its own origin. Nothing checks the Host header.

## Design

One check in the same middleware as 0192 (or alone, before it):

- **Origin.** A state-changing request (POST, PUT, PATCH, DELETE) must carry an `Origin` (or, without one, a
  `Referer`) whose host[:port] is the request's own `Host`, or one of the CORS origins (main.py `_cors_origins`,
  which already lists the dev server). Otherwise 403. A request with neither header is a non-browser client
  (curl, the checks in checks/job_checks.py): allowed (browsers always send Origin on these methods), and with
  0192 it still needs the session or the worker token.
- **Host.** `INSIGHT_ALLOWED_HOSTS` (comma separated, `*.ts.net` patterns): when set, any other Host is 400 (the
  rebinding defence). Unset: any Host (today), with the start's warning naming it.
- **Exempt.** The worker routes (token, no cookie, no browser) and `/health`, `/api/version`.
- **What it needs.** nginx must pass the port with the host (`proxy_set_header Host $http_host`, not `$host`), or
  Origin `http://h:3000` never equals Host `h`. The Vite dev proxy has `changeOrigin: true`, which rewrites Host
  to localhost:8000: set it to false, or rely on the CORS origins list.
- **The bookmarklet** opens INSIGHT's own save page in a tab and posts from there: same origin, unaffected.
- **Tests.** Cross-origin POST 403; same-origin POST passes; Referer fallback; no header passes; worker routes
  exempt; a wrong Host 400 only when INSIGHT_ALLOWED_HOSTS is set.
