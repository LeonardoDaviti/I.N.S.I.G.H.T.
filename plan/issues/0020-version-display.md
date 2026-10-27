# 0020 — The running version on the Ingestion tab

Status: **built** 2026-10-27, not deployed. Owner's design, built as decided.

## What the owner wants
- One quiet line at the bottom of Sources → Ingestion (every view) saying what runs, in the project's historical scheme: `I.N.S.I.G.H.T. Mark IX v9.1 · b9fcc6e · 27 Oct 2026`.
  - Mark = the major (Mark II … Mark IX); vN.x = its follow-up release. The server's build before this one counts as v9.0; this one is v9.1.
  - The commit is the short SHA, the date its commit date.
- The web app and the API each know their own build. When they differ the line says both: `I.N.S.I.G.H.T. Mark IX · Web v9.1 · b9fcc6e · API v9.0 · 0b1458d, out of step`.
- Unstamped (local dev, tests, a plain `docker compose build`): `I.N.S.I.G.H.T. dev build`.
- No update checks, no calls beyond INSIGHT's own API.

## Built
- **One source of truth:** the repo-root `VERSION` file (`Mark IX v9.1`), bumped by hand per release.
- **Stamped at build:** `./update` exports `INSIGHT_VERSION` (VERSION), `INSIGHT_COMMIT` (`git rev-parse --short HEAD`) and `INSIGHT_COMMIT_DATE` (`git log -1 --format=%cs`) after `git pull`, and passes them through `sudo` to `docker compose build`. Compose hands them as build args (empty by default) to the backend, ingestion and frontend images.
  - `backend/Dockerfile`: `ARG` → `ENV`; `GET /api/version` answers `{version, commit, commit_date}`, null when unset.
  - `frontend/Dockerfile`: `ARG` → `ENV VITE_INSIGHT_*`, inlined by Vite.
- **Frontend:** `lib/version.ts` `versionLine(web, api)` builds the line; `IngestionPanel` fetches the API's build once and shows it. Until the API answers, or when it can't, the line shows the web build alone.

## Tests
- `test_version_route.py`: stamped and unstamped answers.
- `lib/version.test.ts`: in sync, out of step (shared Mark and not), dev build, a bad date.
- `SourcesConfig.ingestion.test.tsx`: the line on the tab, and the out-of-step case.
