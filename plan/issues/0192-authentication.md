# 0192 — Authentication: a password in front of every owner action

Status: spec (future; owner 2026-11-13: no login in the v10.16.2 hotfix, it would add a step to his deploy).

## What the audit found (C1, H2)

- No API route has authentication. The backend's port is published on 127.0.0.1 only (issue 0071), but that
  protects nothing: the frontend's nginx proxies all of `/api` to the backend (frontend/nginx.conf, `location /api`)
  and compose publishes the frontend on every interface (`"${FRONTEND_PORT:-3000}:80"`).
- So anyone who reaches port 3000 (the LAN, a tailnet, a forwarded port) can do everything the owner can: delete
  sources and tracks, read every post and the reading history, export the whole database (`/api/export/everything`,
  with `logins=true` the encrypted credentials), change the Substack cookie and the Telegram API keys, start and
  take over a Telegram sign-in (`/api/credentials/telegram/login/*`), queue fetches, archives and Mark X work
  (Haiku tokens on the owner's account through the worker), and mint a new Mark X worker token
  (`POST /api/markx/token`), which both locks out the owner's worker and hands the caller the worker routes.
- The worker routes (`/api/markx/work`, `/answers`, `/release`, `/status`, `/embeddings`) are the only ones with
  their own check (`_worker_auth`, a bearer token compared in constant time).

## Design (when the owner wants it)

One middleware in the backend, opt-in, so a deploy without the setting behaves as today.

- **Switch.** `INSIGHT_PASSWORD` in .env. Unset: today's behaviour, plus one loud warning line at the API's start
  and a thin banner in the app ("No password set: anyone who can reach this address controls INSIGHT"), from
  `GET /api/auth/status` → `{password_set, signed_in}`.
- **Scope.** Every `/api` route except `/health`, `/api/version` (the healthcheck and the watchdog ask it), the
  auth routes, and the worker routes. The worker routes are not listed by hand: markx/api.py exports the set of
  its routes that depend on `_worker_auth` (built from its router), and they keep the bearer token alone. The
  worker script (scripts/markx-worker) uses only those routes, so it keeps working; a test asserts it.
- **Login.** `POST /api/auth/login {password}` compares with `hmac.compare_digest` and answers a session cookie:
  HttpOnly, SameSite=Strict, Secure when the request came over https (X-Forwarded-Proto from nginx), Path=/,
  30 days. `POST /api/auth/logout` clears it.
- **The session.** Stateless and signed: `<expiry>.<nonce>.<hmac>`, the HMAC over expiry, nonce and a hash of
  the password, so changing the password ends every session. The signing key is a file in the existing
  `insight_secrets` volume (`/app/secrets/session.key`, made once with O_EXCL like the Fernet key in
  ingestion/credentials.py, shared by both API processes). No table, nothing kept per session.
- **Rate limit.** Failed logins per client address: 5 a minute, then 429 with Retry-After; a bounded map (at most
  1,000 addresses, oldest dropped), per process.
- **Token minting.** `POST /api/markx/token` is behind the session like every other owner route.
- **Frontend.** The API client turns any 401 into a minimal login page (one password field) and, after it, retries
  the request; the banner when no password is set.
- **Media cache.** nginx's `/api/media` cache answers cached images without asking the backend: bypass the cache
  for requests without the session cookie, or accept it (the posts' public images).
- **Tests.** 401 without a session when the password is set; today's answers when it isn't; the worker routes
  with the token and without a session; login, logout, a wrong password, the rate limit; the password change
  ending sessions; the key file shared by two processes.

## Deploy notes (for when it ships)

Set `INSIGHT_PASSWORD` in .env (document in .env.example and DEPLOYMENT.md), `docker compose up -d`; the first
visit asks for it. The worker needs nothing new.
