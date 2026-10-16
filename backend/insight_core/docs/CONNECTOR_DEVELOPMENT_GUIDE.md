# Adding a source kind

A **source kind** is how INSIGHT fetches one type of source: a plain feed, a subreddit, a
YouTube channel, a Telegram channel, a site with no feed. Each kind is one class. The
ingestion runner, the archive and the scheduler only talk to kinds through one interface,
so a new kind needs no change anywhere else.

## Where things live

- `ingestion/kinds/base.py`: the interface (`SourceKind`), the `BaseKind` defaults,
  `PolitenessProfile`, `RateLimit`, `Inspection`, `ArchivePage`, `KindUnavailable`.
- `ingestion/kinds/__init__.py`: `KindRegistry`. `KindRegistry.default` lists the real kinds
  in resolution order. The first kind whose `matches()` is true wins. `generic_rss` is last
  and matches everything.
- `ingestion/kinds/*.py`: the generic kinds (`generic_rss`, `substack`, `reddit_subreddit`,
  `youtube_channel`, `telegram_rss`, `nitter_rss`, `telegram_mtproto`).
- `adapters/*.py`: the six site kinds for sites with no usable feed (LessWrong, Gwern,
  Dario Amodei, The Batch, Phil Schmid, Zero to Mastery). They extend `BaseSourceAdapter`,
  which is a `BaseKind`.
- `ingestion/kinds/parsing.py`: pure helpers (feed parsing, `strip_html`, dates, article
  extraction, image URLs).
- `ingestion/http.py`: `KindHttp`, the one HTTP client every kind uses. It owns the
  User-Agent, the TLS-skip hosts and the politeness sleep, and raises every failure as an
  `HttpError` (status, Retry-After, timed out).
- `ingestion/gates.py`: `FetchGates` turns a profile into concurrency limits.
  `HOST_FLOORS` holds each host's starting spacing; a 429 or a timeout doubles it (the
  learned pace, `BACKEND.md`).
- `ingestion/runner.py`: `IngestionRunner`, the live fetch (`run_ingestion(FetchRequest) ->
  RunReport`). `services/source_fetch_service.py` runs the archive.

## The interface

```python
class SourceKind(Protocol):
    name: str                         # stored as settings.archive.source_type
    profile: PolitenessProfile
    available_basis: AvailableBasis   # what inspect()'s available_posts means

    def matches(self, source) -> bool
    def host_key(self, source) -> str
    async def fetch_latest(self, source, limit) -> list[dict]
    async def inspect(self, source) -> Inspection
    def archive_pages(self, source, target, checkpoint, rate) -> AsyncIterator[ArchivePage]
    def checkpoint_resumable(self, checkpoint) -> bool
    async def start_checkpoint(self, source, stored) -> dict | None
    def estimate_pages(self, remaining, page_size) -> int
    def session(self) -> KindSession
```

`BaseKind` gives defaults for `host_key`, `checkpoint_resumable` (false), `start_checkpoint`
(None), `estimate_pages` and `session` (a no-op). You write `matches`, `fetch_latest`, `inspect` and `archive_pages`.

- **`matches(source)`** looks at `source["platform"]` and `source["handle_or_url"]`. Keep it
  cheap and with no I/O. The result is cached per source.
- **`fetch_latest(source, limit)`** returns the newest posts, at most `limit`. The runner calls
  it once per due source.
- **`inspect(source)`** returns `Inspection(available_posts, page_size, first_post_date, raw)`.
  Planning an archive calls it (a fetch run never does). Set `available_basis` to say what the
  count means (`exact`, `upper_bound`, `estimate`, `listing_cap`, `feed_window`, `unknown`).
- **`start_checkpoint(source, stored)`** says where an archive continues below the stored
  posts (`stored`: `post_count`, `oldest_published_at`, `oldest_external_id`): your own
  checkpoint shape with `collected_posts: 0, pages_fetched: 0` (`kinds.base.start_at`), one
  page early, or None when the kind cannot jump (the archive starts at the newest post).
- **`archive_pages(...)`**: see below.

Raise `KindUnavailable(reason)` when the kind needs something this process does not have.
The source is marked unavailable, not failed, and does not back off. Any other exception
counts as a fetch error for that source only.

## Post dicts

A kind returns plain dicts. The posts repository saves them. Keys it reads:

- `url` (required, the dedupe key);
- `title`, `content` (plain text), `content_html`;
- `date` (a timezone-aware `datetime`, or `None`);
- `external_id` (optional, unique per source);
- `media_urls`, `categories` (lists);
- `lang`, `metadata` (a dict).

`parsing.parse_feed_posts` already returns this shape for RSS and Atom.

## Politeness

Declare limits in the class `profile`, not in code:

```python
PolitenessProfile(
    concurrency_pool="host-lock",   # or "ytdlp"
    page_delay_s=2,                 # pause between archive pages
    batch_size=0, batch_cooldown_s=0,
    live_pages_rate_limited=False,  # the live fetch reads several pages
    cadence_floor=timedelta(0),     # never fetch more often than this
    min_posts_per_fetch=0,
    requires="none",                # "ytdlp" or "telegram_creds"
    blocking_io=False,              # the kind's calls block; run them in a thread
)
```

- Make every request through `self.http` (`get_text`, `get_json`, `post_json`).
- Sleep only through `self.http.sleep(...)`, so tests can record the delays.
- If a host needs spacing between request starts, add it to `HOST_FLOORS` in `gates.py`.
  It is keyed by host, because several kinds can share one host (reddit).

## Archive pages

`archive_pages(source, target, checkpoint, rate)` is an async generator. It yields one
`ArchivePage(posts, checkpoint)` per page until it has `target` posts or the source ends.

- Each page is saved before the next one is fetched.
- `checkpoint` is a small dict that lets a stopped archive resume. Put a `mode` in it, plus
  `pages_fetched` and `collected_posts` (`resume_counts()` reads them back).
- `checkpoint=None` means finished.
- `checkpoint_resumable()` says whether a stored checkpoint belongs to your kind.
- Pause between pages with `await self.http.sleep(rate.delay_after(pages_fetched))`.
- A kind that can only read its feed uses the `SingleShotArchive` mixin: one page, from
  `fetch_latest`.
- A site kind with a discovered list of entries can use `BaseSourceAdapter.index_pages`.

`reddit.py` is a short paged example. `adapters/dario_adapter.py` is a short site example.

## Sessions

Most kinds need no session. `telegram_mtproto` does: it returns a `KindSession` whose `open()`
connects once per run and `close()` disconnects. The runner opens it before the kind's first
due source. `open()` may raise `KindUnavailable`. It must never prompt.

## Steps

1. Write the class in `ingestion/kinds/<name>.py`, or `adapters/<name>_adapter.py` for a site.
2. Register it in `KindRegistry.default`, above any kind that would also match its sources.
   Site adapters go in `ADAPTER_CLASSES` in `adapters/__init__.py`.
3. Add a host floor in `gates.py` if the host rate-limits.
4. Add tests (below).
5. Add a source of the new kind in the Sources page. The page also writes it to
   `config/sources.json`, which is mirrored into the database on every container start.

## Tests

No test touches the network. Use the fakes:

- `tests/_kind_fakes.py`: `FakeHttp` answers from a `{url: response}` dict and records every
  request; `RecordingSleeper` records the delays; `FakeKind` is a scripted kind for runner tests.
- `tests/_ingestion_fakes.py`: in-memory catalog, fetch state, saver, run lock and progress
  sink for the runner.

Where to add tests:

- `tests/test_source_kinds.py`:
  - add your rows to the resolution table;
  - update the kind count in `test_every_kind_is_registered_once`;
  - test `fetch_latest`, `inspect` and `archive_pages` with `FakeHttp`. Assert the posts, the
    checkpoints and `http.sleeper.calls`.
- `tests/test_source_adapters.py`: site adapters.
- `tests/test_ingestion_runner.py`: only if the kind changes how a run behaves. It should not.

Run the tests inside the backend image, for example
`./run-tests.sh insight_core.tests.test_source_kinds`.
