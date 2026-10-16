# I.N.S.I.G.H.T. Scripts

Scripts for data ingestion and its scheduler.

---

## 📥 Ingestion (Mark IX)

Every fetch - the scheduler tick, the UI's "Run cycle", track fetch, fetch-now and the CLI -
is one call to `insight_core.ingestion.run_ingestion(FetchRequest) -> RunReport`, so each
applies the same policy: the yt-dlp switch, backoff, politeness gates, fetch-state
recording, the per-source save and the archive-metadata (inspection) refresh.
`scripts/ingest.py` and the `/api/ingest-posts` and `/api/safe-ingest-posts` routes are gone.

### CLI: safe_ingest.py

```bash
cd backend
python -m insight_core.scripts.safe_ingest            # all enabled sources, due ones only
python -m insight_core.scripts.safe_ingest --force    # ignore cadence and backoff
python -m insight_core.scripts.safe_ingest --folder <folder-id>   # one track's enabled sources
python -m insight_core.scripts.safe_ingest --source <source-id>   # one source, even if disabled
```

It prints the run report as JSON and exits 1 when the run failed or was partial. `--force`
never overrides unavailability: with `INSIGHT_YTDLP_ENABLED=0` YouTube stays skipped.

### API

- `POST /api/ingestion/run {force?: bool}` - the manual cycle
- `POST /api/sources/{id}/fetch-now {limit?: int}` - one source, forced
- `POST /api/folders/{id}/ingest {limit?: int}` - one track, forced

Each answers `202 {job_id, job_type: "ingestion_run"}` and runs in the background; poll
`GET /api/operations/jobs/{job_id}` for the run report (in the job payload). When the job
cannot be tracked the answer is 503 and nothing runs. An archive plan or run on a kind the
process cannot fetch (yt-dlp off, no usable Telegram session) answers 409.

### Connections (credentials)

Secrets are added in the UI, **Sources → Connections**, and stored encrypted in the
`credentials` table (spec `plan/INSIGHT_mark_ix_plan.md` §10.1). No API ever returns a
saved value; the UI shows whether it is set and its last 4 characters. It is the only place
a secret is read from: no API key comes from `.env`. Providers: Telegram and Substack.

To move the keys of an older `.env` (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `SUBSTACK_SID`)
into the store once:

```bash
docker compose exec backend python -m insight_core.scripts.import_env_secrets
```

It skips empty values, template placeholders and anything already stored, and prints only
names, never values. Then delete those lines from `.env`.

The encryption key is `INSIGHT_SECRET_KEY` (a Fernet key) if set, else
`/app/secrets/secret.key`, generated on the first save into the `insight_secrets` volume that
the backend and ingestion containers share. Back that volume up with the database: without
the key, saved values are unreadable and must be saved again.

### Telegram session

The bare-handle Telegram sources (platform `telegram`, a handle such as `ai_newz`, no URL)
are read over MTProto by the `telegram_mtproto` kind. The fetcher never prompts for a login:
it needs an already-authorised session.

1. In Sources → Connections → Telegram, add the API ID (an integer) and API hash from
   https://my.telegram.org.
2. Sign in there: phone number, the code Telegram sends, then the 2FA password if the
   account has one. The session is saved encrypted (a Telethon StringSession).

That saved session is the only one used; there is no session file.

One fetch run (or archive run) at a time holds the session, under the Postgres advisory lock
`hashtext('insight.telegram_session')`; the run opens it before its first due telegram
source and closes it at the end. Every telegram source is spaced 2s apart (host key
`platform:telegram`) and paged at 1s with an 18s cooldown every 10 chunks.

What the unavailable reasons mean (the source is skipped, never put into backoff):

| Reason | Meaning / fix |
|---|---|
| `Telegram API ID is not set` / `is not an integer`, `Telegram API hash is not set` | add it in Sources → Connections |
| `no Telegram session; sign in under Sources → Connections` | no saved session: sign in |
| `Telegram session not authorised; sign in under Sources → Connections` | the session is logged out (revoked, or the sign-in was not finished): sign in again |
| `Telegram session in use by another run` | another run (the scheduler or the API) holds the session; the next tick retries |
| `Telegram flood wait until <time>` | Telegram asked the account to wait longer than 60s; the source that hit it is an error (normal backoff), the rest of the run's telegram sources are skipped |
| `Telegram connect failed: ...` / `Telegram session lock unavailable: ...` | network or database trouble opening the session; retried next run |

A channel problem (private, renamed, unknown username) is a normal source **error** with
backoff: the channel is the problem, not the account.

### Substack paid posts

`*.substack.com` sources (and a custom domain with `settings.substack: true`) use the
`substack` kind: newest posts from `/api/v1/archive` (RSS `/feed` as fallback), each body from
`/api/v1/posts/<slug>`. Paid posts come in full only with the owner's `substack.sid` cookie,
pasted into Sources → Connections → Substack (see
`plan/INSIGHT_mark_ix_plan.md` §10 for how to copy it). The Test button reads the newest paid
post of a Substack source. Without a cookie the teaser is stored with
`metadata.paywalled = true` and the health row's `credential_notice` says so. All Substack sources share host key
`substack.com` (2s floor); post requests within a source are 1s apart.

| Reason | Meaning / fix |
|---|---|
| `Substack session expired — update it in Sources → Connections` | the cookie was rejected (401/403) or a paid post still came back truncated: paste a fresh `substack.sid` in Connections (applies on the next fetch, no restart). Unavailable, never backoff. |

### Full text

A feed item's `<content:encoded>` (the full article) is stored over its `<description>`
(often only a summary). When a generic RSS feed still gives only a teaser (under 1,400
characters), the article page of each **new** post is read once and its text stored, marked
`metadata.full_content_fetched` - a later fetch never puts the feed's summary back over it.
Pages of one feed are read 2s apart. Links to GitHub, arXiv, Reddit, YouTube, Telegram and
X are never read as pages. `settings.fetch_full_content: false` turns it off for one source.
Code: `ingestion/full_text.py`.

Posts stored before that are repaired once, by hand:

```bash
docker compose exec backend python -m insight_core.scripts.repair_full_text --dry-run   # what it would read
docker compose exec backend python -m insight_core.scripts.repair_full_text             # read them
#   --source <source-id>   one source     --limit N   newest N posts     --retry   include posts already tried
```

Substack sources are read from Substack's API (paid posts only with the Substack session),
generic RSS sources from the article page; every other kind is skipped. One site at a time,
2s apart, up to 4 sites at once; a site that fails 3 times in a row is left for the next run.
Every post read is marked `metadata.full_text_checked_at`, so a second run does not read it
again. The summary is printed as JSON.

### How a source is decided

`ingestion.schedule.decide_fetch`, fed by the source's cadence columns and its row in
`source_fetch_state`:

1. **Unavailable** (yt-dlp switched off, no Telegram session) → skipped as unavailable,
   never as backoff, even when forced
2. **Forced** → fetched
3. **In backoff** after consecutive errors (1h, 2h, 4h ... 24h; 7d once dormant) → skipped
   until the retry time, then retried
4. **New source** (no successful fetch, 0 posts) → fetched
5. **Due**: the adaptive fetch interval has elapsed since the last *successful* fetch (an
   empty fetch counts) → fetched, otherwise deferred

The interval comes from the mean gap between the source's latest 20 posts (half the gap,
clamped to 24h..21d; 24h probation while there are fewer than 3 dated posts; 168h minimum
for yt-dlp), capped by a backlog guard so a fast feed is polled before it can overflow.
`sources.fetch_interval_hours_override` replaces all of that for one source.

### Scheduler (run_scheduler.py, the ingestion container)

- **Ingestion tick** every `scheduler_config.ingest_tick_minutes` (default 60, minimum 15):
  one run over all enabled sources; cadence makes it touch only the due ones. Two full runs
  never overlap (a Postgres advisory run lock); a second one reports `skipped_busy`.
- **Daily work** once `interval_hours` have passed since the last one: prune job_runs,
  refresh source cadence, sync sources.json. The first
  tick after a deploy seeds the gate from the last successful `scheduler_cycle` job.
- The state (`last_tick_at`, `next_tick_at`, `last_daily_work_at`, `next_daily_work_at`) is in
  `system_settings['scheduler_state']` and served by `GET /api/operations/scheduler`.

### Configuration

- `INSIGHT_YTDLP_ENABLED` (default 1)
- `INSIGHT_INGEST_TICK_MINUTES` (60, the default for `ingest_tick_minutes`),
  `INSIGHT_INGEST_INTERVAL_HOURS` (20, the default daily-work interval)
- `INSIGHT_BACKOFF_BASE_MINUTES` (60), `INSIGHT_BACKOFF_MAX_HOURS` (24),
  `INSIGHT_BACKOFF_DORMANT_AFTER` (10), `INSIGHT_BACKOFF_DORMANT_MAX_HOURS` (168)
- `INSIGHT_FETCH_MAX_CONCURRENCY` (8), `INSIGHT_YTDLP_CONCURRENCY` (2), `INSIGHT_YTDLP_MIN_INTERVAL` (3s)
- `INSIGHT_SAVE_COMMIT_BATCH` (20)
- `INSIGHT_ARCHIVE_INSPECT_INTERVAL_HOURS` (168), `INSIGHT_REFRESH_ARCHIVE_METADATA` (1; 0 skips
  the inspection refresh)

