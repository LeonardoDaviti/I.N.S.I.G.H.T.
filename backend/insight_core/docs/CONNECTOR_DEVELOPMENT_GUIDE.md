# Adding a source kind

A **source kind** is how INSIGHT fetches one type of source: a plain feed, a subreddit, a
YouTube channel, a Telegram channel, a site with no feed. Each kind is one class. The
ingestion runner, the archive and the scheduler only talk to kinds through one interface,
so a new kind needs no change anywhere else.

## Where things live

- `ingestion/kinds/base.py`: the interface (`SourceKind`), the `BaseKind` defaults,
  `PolitenessProfile`, `RateLimit`, `Inspection`, `ArchivePage`, `KindUnavailable`.
- `ingestion/kinds/__init__.py`: `KindRegistry`. `KindRegistry.default` lists the real kinds
  in resolution order. The first kind whose `matches()` is true wins. `page_watch` is first
  (its setting is the owner's explicit choice); `generic_rss` is last and matches everything.
- `ingestion/kinds/*.py`: the generic kinds (`page_watch`, `generic_rss`, `substack`,
  `reddit_subreddit`, `youtube_channel`, `telegram_rss`, `nitter_rss`, `telegram_mtproto`).
- `ingestion/kinds/page_watch.py` (issue 0028): a page with no feed, followed. It matches
  `settings.page_watch = {"prefix"?: "/news/"}` and reads the listing page's same-host links
  under the prefix (page order) plus the sitemap's URLs under it (robots.txt `Sitemap:`, else
  `/sitemap.xml`, each up to 5 MB), each article page through `extract_article_html`, dated
  from the page's own meta or its one `<time datetime>` (the sitemap's lastmod is a fallback:
  it is often a redeploy date). A page with no body, or with neither a date nor `og:type`
  article (a category page), is no post; a live fetch remembers such pages for the process's
  life (failed ones for a day) and reads at most 10 of them besides its posts. It extends
  `BaseSourceAdapter` for `index_pages`, one article per archive page. `preview()` is behind
  `POST /api/sources/page-watch/preview`. Before writing a site adapter, try it.
- `adapters/*.py`: the seven site kinds for sites with no usable feed (LessWrong, Gwern,
  Dario Amodei, The Batch, Phil Schmid, Zero to Mastery, pipecraft.me). They extend `BaseSourceAdapter`,
  which is a `BaseKind`.
- `ingestion/kinds/parsing.py`: pure helpers (feed parsing, `strip_html`, dates, article
  extraction, image URLs). The article reader (`read_article_page` / `extract_article_html`)
  is shared by full text, page watch and the site adapters, and tested on a corpus of real
  pages (`tests/fixtures/pages`, `test_page_corpus`): an adapter that reads article pages
  should use it rather than its own regexes, and a site it reads badly is added to the corpus
  with the fix (see `BACKEND.md`, "Reading an article page").
- `ingestion/http.py`: `KindHttp`, the one HTTP client every kind uses. It owns the
  User-Agent, the TLS-skip hosts and the politeness sleep, requests only http and https, and
  raises every failure (a dropped connection or a truncated body too) as an `HttpError`
  (status, Retry-After, timed out). `get_start` reads within its timeout overall, so a
  server dripping its answer is a timeout. The Add source dialog's client runs on its own
  threads (`executor`), not the loop's default ones.
- `ingestion/feed_finder.py`: `find_feeds(http, registry, url)`, behind Add source
  (`POST /api/sources/find-feed`). It turns a page address into its feeds: an address a
  kind other than `generic_rss` matches is left alone (`direct`), so a new kind's `matches()`
  is all it takes for Add source to keep its addresses as typed. Otherwise it tries platform
  rules (Medium, GitHub releases), the page's `<link rel="alternate">` and feed-like `<a>`
  links, the section and home pages, then common feed paths, proving each candidate from its
  first 64 KB (`KindHttp.get_start`).
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
    page_delay_s=2,                 # pause between pages (the archive loop waits it)
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
- Do not pause between archive pages: the archive loop waits `rate.delay_after(pages_fetched)`
  through the host's gate slot, so the wait is max(host gap, pause), never the sum. Pauses
  inside one page's work (Substack's post bodies) and between the pages of a live fetch are
  slept with `self.http.sleep(...)`.
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
