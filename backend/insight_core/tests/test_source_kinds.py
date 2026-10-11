"""Source kinds behind one seam (Mark IX B3, spec §D and §5.5). No network: FakeHttp.

The resolution table was written first against Mark VIII SourceFetchService.classify_source
and its outputs copied here; every row except the labelled telegram divergence must stay
identical. The estimate fixtures were likewise copied from the Mark VIII _estimate_seconds.
"""
from __future__ import annotations

import ast
import asyncio
import re
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.adapters import ADAPTER_CLASSES
from insight_core.adapters.dario_adapter import DarioAmodeiAdapter
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import ArchivePage, KindUnavailable, RateLimit, SourceKind
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.ingestion.kinds.nitter_rss import NitterRssKind, extract_nitter_tweet_count
from insight_core.ingestion.kinds.reddit import RedditKind
from insight_core.ingestion.kinds.telegram_mtproto import TelegramKind
from insight_core.ingestion.kinds.telegram_rss import TelegramRssKind
from insight_core.ingestion.kinds.youtube import YouTubeKind
from insight_core.ingestion.schedule import Availability, DecisionKind, cadence_stats, decide_fetch
from insight_core.tests._kind_fakes import FakeHttp, FakeKind, RecordingSleeper


def _src(platform: str, handle: str, **settings) -> dict:
    return {"id": f"id-{handle}", "platform": platform, "handle_or_url": handle,
            "settings": dict(settings)}


class _StubYouTube:
    """Stands in for YouTubeService; records the blocking calls made through to_thread."""

    def __init__(self):
        self.calls: list[tuple[str, str, int]] = []

    def fetch_live_posts(self, handle, limit):
        self.calls.append(("live", handle, limit))
        return [{"url": f"https://youtube.com/watch?v={i}"} for i in range(min(limit, 3))]

    def archive_channel_posts(self, handle, limit):
        self.calls.append(("archive", handle, limit))
        return {"posts": [{"url": f"https://youtube.com/watch?v={i}"} for i in range(limit)],
                "pages_fetched": 1}

    def inspect_channel(self, handle):
        return {"available_posts": 40, "page_size": 20, "first_post_date": "2020-01-01T00:00:00+00:00",
                "channel": {"channel_url": handle}}


def _registry(http=None) -> KindRegistry:
    return KindRegistry.default(http or FakeHttp(), _StubYouTube())


# (platform, handle_or_url) -> kind name, copied from Mark VIII classify_source outputs.
PARITY_ROWS = [
    ("rss", "https://tg.i-c-a.su/rss/denissexy?limit=50", "telegram_rss"),
    ("rss", "https://telegram.local/rss/denissexy", "telegram_rss"),
    ("rss", "http://127.0.0.1:9504/rss/denissexy", "telegram_rss"),
    ("telegram", "https://tg.i-c-a.su/rss/ai_newz", "telegram_rss"),
    ("rss", "https://nitter.local/karpathy/rss", "nitter_rss"),
    ("rss", "https://nitter.net/karpathy/rss", "nitter_rss"),
    ("reddit", "r/LocalLLaMA", "reddit_subreddit"),
    ("reddit", "https://www.reddit.com/r/LocalLLaMA/.rss", "reddit_subreddit"),
    ("rss", "https://www.reddit.com/r/smartglasses/.rss", "generic_rss"),
    ("rss", "https://old.reddit.com/r/smartglasses/", "reddit_subreddit"),
    ("rss", "https://www.reddit.com/r/smartglasses/new.xml", "generic_rss"),
    ("youtube", "UCoryWpk4QVYKFCJul9KBdyw", "youtube_channel"),
    ("youtube", "https://www.youtube.com/feeds/videos.xml?channel_id=UC1xcV34QaE2icXZ21eSvSSw", "youtube_channel"),
    ("rss", "https://www.youtube.com/feeds/videos.xml?channel_id=UCHkYOD-3fZbuGhwsADBd9ZQ", "youtube_channel"),
    ("rss", "https://www.lesswrong.com/feed.xml", "lesswrong_graphql"),
    ("rss", "https://gwern.net", "gwern_site"),
    ("rss", "https://darioamodei.com", "dario_site"),
    ("rss", "https://www.deeplearning.ai/the-batch/", "deeplearning_batch_site"),
    ("rss", "https://www.philschmid.de/cloud-attention", "philschmid_cloud_attention"),
    ("rss", "https://zerotomastery.io/newsletters/machine-learning-monthly/1/", "zerotomastery_ml_monthly"),
    ("rss", "https://github.com/anthropics/claude-code/releases.atom", "generic_rss"),
    ("rss", "https://rss.arxiv.org/rss/cs.AI", "generic_rss"),
    ("rss", "http://export.arxiv.org/api/query?search_query=abs:%22smart+glasses%22", "generic_rss"),
    ("rss", "https://simonwillison.net/atom/everything/", "generic_rss"),
]


class KindResolutionTests(unittest.TestCase):
    def test_resolution_matches_mark_viii_classify_source(self):
        registry = _registry()
        for platform, handle, expected in PARITY_ROWS:
            with self.subTest(platform=platform, handle=handle):
                self.assertEqual(registry.resolve(_src(platform, handle)).name, expected)

    def test_intentional_divergence_bare_telegram_handle_is_mtproto(self):
        """Intentional divergence: Mark VIII returned generic_rss (and failed as an RSS URL)."""
        self.assertEqual(_registry().resolve(_src("telegram", "ai_newz")).name, "telegram_mtproto")

    def test_every_kind_is_registered_once(self):
        names = [kind.name for kind in _registry().kinds]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 13, "6 sites + substack, reddit, youtube, telegram_rss, nitter, mtproto, generic")
        self.assertEqual(names[-1], "generic_rss", "generic_rss is the fallback")

    def test_resolution_is_cached_per_platform_and_handle(self):
        calls: list[str] = []

        def counting(source):
            calls.append(source["handle_or_url"])
            return True

        registry = KindRegistry([FakeKind("only", matches=counting)])
        source = _src("rss", "https://a.example.com/feed")
        for _ in range(3):
            registry.resolve(dict(source))
        registry.resolve(_src("rss", "https://b.example.com/feed"))
        self.assertEqual(calls, ["https://a.example.com/feed", "https://b.example.com/feed"])

    def test_by_name(self):
        registry = _registry()
        self.assertEqual(registry.by_name("nitter_rss").name, "nitter_rss")
        self.assertIsNone(registry.by_name("nope"))

    def test_site_adapters_satisfy_source_kind_directly(self):
        http = FakeHttp()
        for adapter_class in ADAPTER_CLASSES:
            with self.subTest(adapter=adapter_class.__name__):
                adapter = adapter_class(http)
                self.assertIsInstance(adapter, SourceKind)
                self.assertEqual(adapter.profile.concurrency_pool, "host-lock")
                self.assertEqual(adapter.profile.page_delay_s, adapter_class.PAGE_DELAY_SECONDS)

    def test_host_keys(self):
        registry = _registry()
        cases = [
            (_src("reddit", "r/LocalLLaMA"), "platform:reddit"),
            (_src("rss", "https://www.reddit.com/r/x/.rss"), "reddit.com"),
            (_src("telegram", "ai_newz"), "platform:telegram"),
            (_src("rss", "https://tg.i-c-a.su/rss/a?limit=50"), "tg.i-c-a.su"),
            (_src("rss", "https://www.github.com/a.atom"), "github.com"),
        ]
        for source, expected in cases:
            with self.subTest(handle=source["handle_or_url"]):
                kind = registry.resolve(source)
                self.assertEqual(kind.host_key(source), expected)


RSS_WITH_IMAGE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Example</title>
    <description><![CDATA[<p>Hello</p><img src="http://127.0.0.1:9504/media/test.jpg" />]]></description>
    <pubDate>Wed, 11 Mar 2026 18:01:01 GMT</pubDate>
    <link>https://t.me/example/123</link>
  </item>
  <item>
    <title>Older</title>
    <description>Older body</description>
    <pubDate>Tue, 10 Mar 2026 18:01:01 GMT</pubDate>
    <link>https://a.example.com/older</link>
  </item>
</channel></rss>
"""


def _telegram_page(username: str, start_id: int, count: int, sponsored: bool = False) -> str:
    items = []
    if sponsored:
        items.append("<item><title>[Sponsored] Buy now</title><description>Ad</description>"
                     "<link>838348a7075f39f185078f7eccc181f4</link></item>")
    for post_id in range(start_id, start_id - count, -1):
        items.append(
            f"<item><title>Post {post_id}</title>"
            f"<description><![CDATA[<p>Body {post_id}</p><img src=\"http://127.0.0.1:9504/media/{username}/{post_id}.jpg\" />]]></description>"
            f"<pubDate>Wed, 11 Mar 2026 18:18:59 +0000</pubDate>"
            f"<link>https://t.me/{username}/{post_id}</link></item>"
        )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{"".join(items)}</channel></rss>'


class GenericRssKindTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_latest_parses_the_feed(self):
        url = "https://telegram.local/rss/example"
        kind = GenericRssKind(FakeHttp({url: RSS_WITH_IMAGE}))
        posts = await kind.fetch_latest(_src("rss", url), 5)
        self.assertEqual([p["title"] for p in posts], ["Example", "Older"], "newest first")
        self.assertEqual(posts[0]["media_urls"], ["https://telegram.local/media/test.jpg"])
        self.assertEqual(posts[0]["content"], "Hello")

    async def test_fetch_latest_respects_the_limit(self):
        url = "https://a.example.com/rss"
        posts = await GenericRssKind(FakeHttp({url: RSS_WITH_IMAGE})).fetch_latest(_src("rss", url), 1)
        self.assertEqual(len(posts), 1)

    async def test_archive_pages_is_single_shot(self):
        url = "https://a.example.com/rss"
        kind = GenericRssKind(FakeHttp({url: RSS_WITH_IMAGE}))
        pages = [page async for page in kind.archive_pages(_src("rss", url), 10, None,
                                                            kind.profile.rate_limit())]
        self.assertEqual(len(pages), 1)
        self.assertIsNone(pages[0].checkpoint)
        self.assertEqual(len(pages[0].posts), 2)

    async def test_inspect(self):
        url = "https://a.example.com/rss"
        inspection = await GenericRssKind(FakeHttp({url: RSS_WITH_IMAGE})).inspect(_src("rss", url))
        self.assertEqual((inspection.available_posts, inspection.page_size), (2, 2))
        self.assertTrue(inspection.first_post_date.startswith("2026-03-10"))


class ReadableTitleTests(unittest.TestCase):
    def test_a_slug_title_becomes_words(self):
        self.assertEqual(parsing.readable_title("levers-in-the-brain",
                                                "https://chadnauseam.com/coding/random/levers-in-the-brain"),
                         "Levers in the brain")

    def test_real_titles_and_release_tags_are_kept(self):
        cases = [
            ("Rust", "https://chadnauseam.com/reference/Rust"),
            ("my-post", "https://example.com/another-post"),          # not the URL's slug
            ("2024-11-05", "https://github.com/o/r/releases/tag/2024-11-05"),
            ("2024-11-05-final", "https://github.com/o/r/releases/tag/2024-11-05-final"),
            ("A Real Title", "https://example.com/a-real-title"),
        ]
        for title, url in cases:
            with self.subTest(title=title):
                self.assertEqual(parsing.readable_title(title, url), title)

    def test_feed_parsing_applies_it(self):
        feed = ('<rss version="2.0"><channel><item><title>my-rustfmt-toml</title>'
                "<link>https://chadnauseam.com/coding/tips/my-rustfmt-toml</link></item></channel></rss>")
        self.assertEqual(parsing.parse_feed_posts(feed, "https://chadnauseam.com/rss.xml")[0]["title"],
                         "My rustfmt toml")


class RedditKindTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_fetch_reads_the_new_rss_endpoint_not_json(self):
        atom = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><id>t3_abc</id><title>Hello</title>
            <link href="https://www.reddit.com/r/x/comments/abc/hello/"/>
            <updated>2026-03-11T18:01:01+00:00</updated><content type="html">&lt;p&gt;Body&lt;/p&gt;</content>
          </entry>
        </feed>"""
        http = FakeHttp({"https://www.reddit.com/r/x/new/.rss": atom})
        posts = await RedditKind(http).fetch_latest(_src("reddit", "r/x"), 10)
        self.assertEqual(http.requests, ["https://www.reddit.com/r/x/new/.rss"])
        self.assertFalse(any(".json" in url for url in http.requests))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["external_id"], "abc")
        self.assertEqual(posts[0]["platform"], "reddit")


class TelegramRssKindTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = _src("rss", "https://tg.i-c-a.su/rss/chan?limit=20")

    def _http(self, pages: int = 5, page_size: int = 20) -> FakeHttp:
        responses = {
            f"https://tg.i-c-a.su/rss/chan/{n}?limit=20": _telegram_page("chan", 1000 - (n - 1) * page_size, page_size)
            for n in range(1, pages + 1)
        }
        return FakeHttp(responses)

    async def test_live_fetch_within_one_page_fetches_one_page(self):
        http = self._http()
        posts = await TelegramRssKind(http).fetch_latest(self.SOURCE, 20)
        self.assertEqual(len(posts), 20)
        self.assertEqual(http.requests, ["https://tg.i-c-a.su/rss/chan/1?limit=20"],
                         "the ?limit= of the source URL is honoured")
        self.assertEqual(http.sleeper.calls, [])

    async def test_live_fetch_pages_are_rate_limited(self):
        http = self._http()
        kind = TelegramRssKind(http)
        posts = await kind.fetch_latest(self.SOURCE, 45)
        self.assertEqual(len(posts), 45)
        self.assertEqual(len(http.requests), 3)
        self.assertEqual(http.sleeper.calls, [kind.profile.page_delay_s] * 2)

    async def test_sponsored_items_are_skipped_and_urls_canonical(self):
        url = "https://tg.i-c-a.su/rss/denissexy"
        http = FakeHttp({"https://tg.i-c-a.su/rss/denissexy/1": _telegram_page("denissexy", 11277, 1, sponsored=True)})
        posts = await TelegramRssKind(http).fetch_latest(_src("rss", url), 1)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["external_id"], "11277")
        self.assertEqual(posts[0]["url"], "https://t.me/denissexy/11277")
        self.assertEqual(posts[0]["media_urls"], ["https://tg.i-c-a.su/media/denissexy/11277.jpg"])

    async def test_the_bridge_media_tag_is_stripped_from_titles(self):
        url = "https://telegram.local/rss/chan"
        page = ('<?xml version="1.0"?><rss version="2.0"><channel>'
                "<item><title>[Photo] Opus spent a night on the board [...]</title>"
                "<description>Opus spent a night on the board</description>"
                "<link>https://t.me/chan/2</link></item>"
                "<item><title>[Video]</title><description></description>"
                "<link>https://t.me/chan/1</link></item>"
                "</channel></rss>")
        posts = await TelegramRssKind(FakeHttp({"https://telegram.local/rss/chan/1": page})).fetch_latest(
            _src("rss", url), 2)
        self.assertEqual([p["title"] for p in posts],
                         ["Opus spent a night on the board [...]", "[Video]"],
                         "a title that is only the tag keeps it: there is nothing else to show")

    async def test_archive_pages_sleep_the_overridden_delay(self):
        http = self._http()
        kind = TelegramRssKind(http)
        rate = kind.profile.rate_limit({"page_delay_seconds": 9})
        pages = [page async for page in kind.archive_pages(self.SOURCE, 45, None, rate)]
        self.assertEqual([len(p.posts) for p in pages], [20, 20, 5])
        self.assertEqual([p.checkpoint["next_page"] for p in pages], [2, 3, 4])
        self.assertEqual(pages[-1].checkpoint["collected_posts"], 45)
        self.assertEqual(http.sleeper.calls, [9, 9])

    async def test_archive_resumes_from_the_checkpoint(self):
        http = self._http()
        kind = TelegramRssKind(http)
        checkpoint = {"mode": "telegram_page", "next_page": 3, "pages_fetched": 2, "collected_posts": 40}
        pages = [page async for page in kind.archive_pages(self.SOURCE, 50, checkpoint, kind.profile.rate_limit())]
        self.assertEqual(http.requests, ["https://tg.i-c-a.su/rss/chan/3?limit=20"])
        self.assertEqual(len(pages[0].posts), 10)
        self.assertEqual(pages[0].checkpoint["pages_fetched"], 3)

    def test_checkpoint_resumable(self):
        kind = TelegramRssKind(FakeHttp())
        self.assertTrue(kind.checkpoint_resumable({"mode": "telegram_page", "next_page": 5}))
        self.assertFalse(kind.checkpoint_resumable({"mode": "generic_rss"}))
        self.assertFalse(kind.checkpoint_resumable(None))


class NitterKindTests(unittest.TestCase):
    def test_extract_nitter_tweet_count(self):
        html = """
        <li class="posts">
          <span class="profile-stat-header">Tweets</span>
          <span class="profile-stat-num">10,030</span>
        </li>
        """
        self.assertEqual(extract_nitter_tweet_count(html), 10030)

    def test_checkpoint_resumable(self):
        kind = NitterRssKind(FakeHttp())
        self.assertTrue(kind.checkpoint_resumable({"mode": "nitter_cursor", "cursor": "abc"}))
        self.assertFalse(kind.checkpoint_resumable({"mode": "nitter_cursor", "cursor": None}))


class ProfileTests(unittest.TestCase):
    def test_rate_limit_override_keeps_the_profile_batch_values(self):
        profile = TelegramRssKind(FakeHttp()).profile
        rate = profile.rate_limit({"page_delay_seconds": 9})
        self.assertEqual(rate, RateLimit(page_delay_s=9, batch_size=10, batch_cooldown_s=30))
        self.assertEqual(profile.estimate_seconds(3, rate), 3 + 2 * 9)

    def test_rate_limit_layers_apply_in_order(self):
        profile = TelegramRssKind(FakeHttp()).profile
        rate = profile.rate_limit(
            {"page_delay_seconds": 7, "batch_size": 8, "batch_cooldown_seconds": 20},
            {"page_delay_seconds": 3, "batch_size": 4, "batch_cooldown_seconds": None},
        )
        self.assertEqual(rate, RateLimit(page_delay_s=3, batch_size=4, batch_cooldown_s=20))

    def test_batch_overrides_are_ignored_for_kinds_without_a_batch_cooldown(self):
        rate = GenericRssKind(FakeHttp()).profile.rate_limit({"batch_size": 3}, {"page_delay_seconds": 9})
        self.assertEqual(rate.as_settings(), {"page_delay_seconds": 9})

    def test_estimate_seconds_matches_mark_viii(self):
        # Mark VIII _estimate_seconds(kind, pages, _resolve_rate_limit(kind)) for these pages.
        pages = (0, 1, 2, 10, 11, 12, 25)
        expected = {
            "telegram_rss": [0, 1, 7, 55, 86, 92, 195],
            "nitter_rss": [0, 1, 12, 100, 131, 142, 305],
            "reddit_subreddit": [0, 1, 4, 28, 31, 34, 73],
            "youtube_channel": [0, 1, 4, 28, 31, 34, 73],
            "generic_rss": [0, 1, 2, 10, 11, 12, 25],
            "lesswrong_graphql": [0, 1, 3, 19, 21, 23, 49],
            "gwern_site": [0, 1, 3, 19, 21, 23, 49],
        }
        registry = _registry()
        for name, values in expected.items():
            with self.subTest(kind=name):
                profile = registry.by_name(name).profile
                rate = profile.rate_limit()
                self.assertEqual([profile.estimate_seconds(p, rate) for p in pages], values)

    def test_youtube_profile(self):
        profile = YouTubeKind(_StubYouTube()).profile
        self.assertTrue(profile.blocking_io)
        self.assertEqual(profile.requires, "ytdlp")
        self.assertEqual(profile.concurrency_pool, "ytdlp")
        self.assertEqual(profile.cadence_floor, timedelta(hours=168))
        self.assertEqual(profile.min_posts_per_fetch, 15)


class YouTubeKindTests(unittest.IsolatedAsyncioTestCase):
    async def test_archive_pages_is_single_shot_and_off_the_loop(self):
        youtube = _StubYouTube()
        kind = YouTubeKind(youtube)
        pages = [page async for page in kind.archive_pages(_src("youtube", "UCx"), 4, None, kind.profile.rate_limit())]
        self.assertEqual(len(pages), 1)
        self.assertIsNone(pages[0].checkpoint)
        self.assertEqual(len(pages[0].posts), 4)
        self.assertEqual(youtube.calls, [("archive", "UCx", 4)])

    async def test_inspect_drops_nothing_but_the_rate_limit(self):
        inspection = await YouTubeKind(_StubYouTube()).inspect(_src("youtube", "UCx"))
        self.assertEqual(inspection.available_posts, 40)
        self.assertIn("channel", inspection.raw)


class TelegramKindTests(unittest.TestCase):
    def test_profile(self):
        profile = TelegramKind().profile
        self.assertEqual(profile.requires, "telegram_creds")
        self.assertTrue(profile.live_pages_rate_limited)
        self.assertEqual((profile.page_delay_s, profile.batch_size, profile.batch_cooldown_s), (1, 10, 18))

    def test_without_credentials_even_force_is_unavailable(self):
        source = _src("telegram", "ai_newz")
        kind = _registry().resolve(source)
        decision = decide_fetch(
            cadence_stats({**source, "post_count": 0}, None),
            kind.profile,
            datetime(2026, 10, 9, tzinfo=timezone.utc),
            force=True,
            availability=Availability(ytdlp_enabled=True, telegram_credentials=False),
        )
        self.assertEqual(decision.kind, DecisionKind.SKIP_UNAVAILABLE)
        self.assertFalse(decision.fetch)

    def test_fetch_without_an_open_session_is_unavailable(self):
        # The B8 behaviour tests (session lifecycle, flood wait, archive) are in test_telegram_kind.py.
        with self.assertRaises(KindUnavailable):
            asyncio.run(TelegramKind().fetch_latest(_src("telegram", "ai_newz"), 5))

    def test_importing_kinds_does_not_import_connectors_or_telethon(self):
        script = (
            "import sys\n"
            "import insight_core.adapters\n"
            "from insight_core.ingestion.kinds import KindRegistry\n"
            "from insight_core.ingestion.http import KindHttp\n"
            "r = KindRegistry.default(KindHttp(), object())\n"
            "k = r.resolve({'platform': 'telegram', 'handle_or_url': 'ai_newz'})\n"
            "assert k.name == 'telegram_mtproto' and k.profile.requires == 'telegram_creds'\n"
            "bad = [m for m in sys.modules if m == 'telethon' or m.startswith('telethon.') "
            "or m.startswith('insight_core.' 'connectors')]\n"
            "assert not bad, bad\n"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=str(BACKEND_DIR),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


# The dead-connector names from the spec §D.5 grep; after B5 no .py file under backend/ may
# mention them. Split so that this file does not match the grep itself.
_DEAD = ["rss_" "connector", "reddit_" "connector", "youtube_" "connector", "tool_" "registry"]
DEAD_CONNECTOR_NAMES = re.compile("|".join(
    _DEAD + ["discover_" "connectors", "AVAILABLE_" "CONNECTORS", "create_" "connector"]))


class ConnectorRemovalTests(unittest.TestCase):
    """B5 deleted the dead connectors; B8 deleted the Telegram one and the package with it."""

    def test_importing_ingestion_does_not_import_connectors_or_telethon(self):
        script = (
            "import sys\n"
            "import insight_core.adapters\n"
            "import insight_core.ingestion\n"
            "from insight_core.ingestion import (archive_metadata, gates, http, inspection,\n"
            "    ports, runner, schedule, types)\n"
            "from insight_core.ingestion.kinds import (base, generic_rss, nitter_rss, parsing, reddit,\n"
            "    telegram_mtproto, telegram_rss, youtube)\n"
            "import insight_core.services.source_fetch_service\n"
            "bad = [m for m in sys.modules if m == 'telethon' or m.startswith('telethon.') "
            "or m.startswith('insight_core.' 'connectors') or m.startswith('insight_core.engines')]\n"
            "assert not bad, bad\n"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=str(BACKEND_DIR),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_dead_connector_modules_are_deleted(self):
        core = BACKEND_DIR / "insight_core"
        for relative in [f"connectors/{name}.py" for name in _DEAD] + [
                         "connectors", "engines", "tests/connector_test.py", "tests/upsert_test.py",
                         "tests/upsert_multiple_test.py", "tests/read_posts.py"]:
            self.assertFalse((core / relative).exists(), relative)

    def test_no_python_file_imports_the_connectors_package_or_the_telegram_one(self):
        pattern = re.compile("insight_core" r"\.connectors|\.\.connectors|" "telegram_" "connector|" "Telegram" "Connector")
        hits = [str(path.relative_to(BACKEND_DIR)) for path in BACKEND_DIR.rglob("*.py")
                if path != Path(__file__).resolve() and pattern.search(path.read_text(errors="replace"))]
        self.assertEqual(hits, [])

    def test_no_python_file_references_a_dead_connector(self):
        hits = []
        for path in BACKEND_DIR.rglob("*.py"):
            if path == Path(__file__).resolve():
                continue
            for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if DEAD_CONNECTOR_NAMES.search(line):
                    hits.append(f"{path.relative_to(BACKEND_DIR)}:{number}: {line.strip()}")
        self.assertEqual(hits, [])


class SiteAdapterArchivePagesTests(unittest.IsolatedAsyncioTestCase):
    async def test_dario_yields_one_page_per_batch_with_checkpoints(self):
        hrefs = "".join(f'<a href="/essay/e{i}">E</a>' for i in range(6))
        detail = ('<h1 class="post-title">T</h1><div class="post-date">April 2025</div>'
                  '<div data-toc-contents="" class="rich-text w-richtext"><p>Body text.</p></div>')

        def respond(url):
            return hrefs if url == "https://darioamodei.com" else detail

        http = FakeHttp(respond)
        adapter = DarioAmodeiAdapter(http)
        source = _src("rss", "https://darioamodei.com")
        pages = [page async for page in adapter.archive_pages(source, 6, None, adapter.profile.rate_limit())]
        self.assertEqual([len(p.posts) for p in pages], [4, 2])
        self.assertEqual([p.checkpoint["next_index"] for p in pages], [4, 6])
        self.assertEqual([p.checkpoint["pages_fetched"] for p in pages], [1, 2])
        self.assertTrue(all(isinstance(p, ArchivePage) for p in pages))
        self.assertEqual(http.sleeper.calls, [1], "one page delay between the two batches")
        self.assertTrue(adapter.checkpoint_resumable(pages[-1].checkpoint))


class ParsingTests(unittest.TestCase):
    def test_extract_article_html_prefers_substantial_main_content(self):
        paragraph = "<p>" + ("This is a long-form intelligence paragraph. " * 25) + "</p>"
        html = f"""
        <html><body>
          <header><p>Short intro</p></header>
          <main><h1>Deep analysis</h1>{paragraph}{paragraph}</main>
          <footer><p>Footer links</p></footer>
        </body></html>
        """
        extracted = parsing.extract_article_html(html)
        self.assertIn("<h1>Deep analysis</h1>", extracted)
        self.assertGreater(len(parsing.strip_html(extracted)), 500)

    def test_origin_resolution_uses_source_host(self):
        self.assertEqual(parsing.origin_from_source("https://tg.i-c-a.su/rss/denissexy?limit=50", "x"),
                         "https://tg.i-c-a.su")
        self.assertEqual(parsing.origin_from_source("@handle", "https://fallback.local"),
                         "https://fallback.local")


class KindHttpTests(unittest.TestCase):
    def test_tls_verification_is_skipped_for_local_hosts_only(self):
        http = KindHttp(insecure_tls_hosts=set())
        self.assertTrue(http.should_skip_tls_verify("telegram.local"))
        self.assertTrue(http.should_skip_tls_verify("nitter.local"))
        self.assertFalse(http.should_skip_tls_verify("tg.i-c-a.su"))

    def test_sleep_goes_through_the_injected_sleeper(self):
        sleeper = RecordingSleeper()
        http = KindHttp(sleep=sleeper)
        asyncio.run(http.sleep(3))
        asyncio.run(http.sleep(0))
        self.assertEqual(sleeper.calls, [3], "a zero delay is not a sleep")


class AvailableBasisTests(unittest.TestCase):
    """What each kind's inspected available_posts means, so the archive UI can say it honestly."""

    EXPECTED = {
        "lesswrong_graphql": "exact",          # counted through the GraphQL API
        "gwern_site": "estimate",              # candidate pages discovered on the index
        "dario_site": "exact",
        "deeplearning_batch_site": "exact",
        "philschmid_cloud_attention": "exact",
        "zerotomastery_ml_monthly": "exact",
        "substack": "unknown",                 # the archive API reports no total
        "reddit_subreddit": "listing_cap",     # listings stop at ~250 whatever the size
        "youtube_channel": "exact",            # every video yt-dlp lists
        "telegram_rss": "upper_bound",         # the newest post number; deleted posts count
        "nitter_rss": "estimate",              # the profile's tweet count
        "telegram_mtproto": "exact",           # the channel's message total
        "generic_rss": "feed_window",          # only what the feed lists right now
    }

    def test_every_kind_declares_what_its_available_count_means(self):
        declared = {kind.name: kind.available_basis for kind in _registry().kinds}
        self.assertEqual(declared, self.EXPECTED)


if __name__ == "__main__":
    unittest.main()
