"""X Articles read for a tweet the Nitter bridge gives as its link alone (v10.13.10). No network: FakeHttp.

The accounts, ids and texts are made up.
"""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.db.repo_posts import FULL_TEXT_FLAG, PAGE_OUTCOME_KEY, X_ARTICLE_KEY, PostsRepository
from insight_core.ingestion import full_text
from insight_core.ingestion.kinds import KindRegistry, x_articles
from insight_core.ingestion.kinds.nitter_rss import NitterRssKind
from insight_core.scripts.repair_full_text import Repair
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp

USER = "example_founder"
FEED = f"https://nitter.local/{USER}/rss"
SOURCE = {"id": "s1", "platform": "rss", "handle_or_url": FEED, "settings": {}}
NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
ON = {}   # the defaults
TEXT_URL = "https://api.fxtwitter.com/{user}/status/{id}"
PREVIEW_URL = "https://cdn.syndication.twimg.com/tweet-result?id={id}&token=insight"


def _stub_html(article_id: str, host: str = "nitter.net") -> str:
    return f'<p><a href="https://{host}/i/article/{article_id}">{host}/i/article/{article_id[:12]}…</a></p>'


def _item(status: int, title: str, html: str, user: str = USER) -> str:
    return (f"<item><title>{title}</title><description><![CDATA[{html}]]></description>"
            f"<pubDate>Tue, 10 Nov 2026 10:00:00 +0000</pubDate>"
            f"<link>https://nitter.local/{user}/status/{status}#m</link></item>")


def _feed(*items: str) -> str:
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{"".join(items)}</channel></rss>'


def _stub_item(status: int, title_prefix: str = "") -> str:
    return _item(status, f"{title_prefix}x.com/i/article/{status + 7}…", _stub_html(str(status + 7)))


BLOCKS = [
    {"type": "unstyled", "text": "We are joining a larger company today."},
    {"type": "header-one", "text": "Why now"},
    {"type": "unstyled", "text": "Three reasons."},
    {"type": "unordered-list-item", "text": "Reach"},
    {"type": "unordered-list-item", "text": "Tools"},
    {"type": "atomic", "text": " "},
    {"type": "ordered-list-item", "text": "First step"},
    {"type": "unstyled", "text": "Thanks <everyone> & more."},
]


def _text_answer(title: str = "An example acquisition", blocks=None) -> str:
    return json.dumps({"code": 200, "tweet": {"article": {
        "id": "777", "title": title, "preview_text": "We are joining",
        "cover_media": {"media_info": {"original_img_url": "https://pbs.example.com/cover.jpg"}},
        "content": {"blocks": BLOCKS if blocks is None else blocks}}}})


def _preview_answer(title: str = "An example acquisition") -> str:
    return json.dumps({"__typename": "Tweet", "article": {
        "rest_id": "777", "title": title, "preview_text": "We are joining a larger company today. Three reasons"}})


def _text(status: int, user: str = USER) -> str:
    return TEXT_URL.format(user=user, id=status)


def _preview(status: int) -> str:
    return PREVIEW_URL.format(id=status)


def _kind(http: FakeHttp, env=None, stored=None) -> NitterRssKind:
    return NitterRssKind(http, env=ON if env is None else env, stored_articles=stored, clock=lambda: NOW)


class DetectionTests(unittest.TestCase):
    def test_a_link_alone_on_either_host_or_shown_through_t_co_is_an_article_stub(self):
        for html in (_stub_html("1989104406691"), _stub_html("1989104406691", "x.com"),
                     '<p><a href="https://t.co/AbCdEf">x.com/i/article/198910440669…</a></p>'):
            post = {"content_html": html}
            self.assertTrue(x_articles.is_article_post(post), html)
            self.assertTrue(x_articles.is_stub(post), html)

    def test_words_with_the_link_are_an_article_post_but_no_stub(self):
        post = {"content_html": "<p>A long read. " + _stub_html("1989104406691")[3:]}
        self.assertTrue(x_articles.is_article_post(post))
        self.assertFalse(x_articles.is_stub(post))

    def test_an_article_only_in_the_quoted_tweet_or_an_ordinary_tweet_is_none(self):
        quoted = "<p>Worth reading.</p>\n<hr/>\n<blockquote><b>Someone</b>" + _stub_html("1989104406691") + "</blockquote>"
        self.assertFalse(x_articles.is_article_post({"content_html": quoted}))
        self.assertFalse(x_articles.is_article_post({"content_html": '<p>Hello <a href="https://example.com/a">example.com/a</a></p>'}))

    def test_env_switches(self):
        self.assertEqual(x_articles.configured({}), (x_articles.DEFAULT_TEXT_URL, x_articles.DEFAULT_PREVIEW_URL))
        self.assertEqual(x_articles.configured({x_articles.TEXT_URL_ENV: ""}), ("", x_articles.DEFAULT_PREVIEW_URL))
        self.assertFalse(x_articles.lookups_on({x_articles.TEXT_URL_ENV: " ", x_articles.PREVIEW_URL_ENV: ""}))


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_article_post_gets_the_whole_article_from_the_text_route(self):
        http = FakeHttp({FEED: _feed(_stub_item(100, "RT by @example_fan: ")), _text(100): _text_answer()})
        [post] = await _kind(http).fetch_latest(SOURCE, 20)
        self.assertEqual(post["title"], "RT by @example_fan: An example acquisition")
        self.assertEqual(post["url"], f"https://nitter.local/{USER}/status/100#m")
        self.assertEqual(post["date"], datetime(2026, 11, 10, 10, tzinfo=timezone.utc))
        self.assertEqual(post["external_id"], "100")
        self.assertEqual(post["content"], "An example acquisition\n\nWe are joining a larger company today.\n\nWhy now\n\n"
                                          "Three reasons.\n\n• Reach\n\n• Tools\n\n1. First step\n\nThanks <everyone> & more.")
        self.assertIn("<h2>Why now</h2>", post["content_html"])
        self.assertIn("<ul><li>Reach</li><li>Tools</li></ul><ol><li>First step</li></ol>", post["content_html"])
        self.assertIn("Thanks &lt;everyone&gt; &amp; more.", post["content_html"])
        self.assertNotIn("/i/article/", post["content_html"])
        self.assertEqual(post["media_urls"][0], "https://pbs.example.com/cover.jpg")
        meta = post["metadata"]
        self.assertTrue(meta[FULL_TEXT_FLAG])
        self.assertEqual(meta[PAGE_OUTCOME_KEY]["outcome"], full_text.FULL)
        self.assertEqual(meta[X_ARTICLE_KEY], {"id": "777", "via": "text", "complete": True, "at": NOW.isoformat()})
        self.assertIsNone(full_text.teaser_reason(meta))
        self.assertEqual(http.requests, [FEED, _text(100)])

    async def test_the_tweets_own_words_stay_before_the_article(self):
        html = "<p>A long read, finally. " + _stub_html("555")[3:]
        http = FakeHttp({FEED: _feed(_item(100, "A long read, finally. https://x.com/i/article/555", html)),
                         _text(100): _text_answer()})
        [post] = await _kind(http).fetch_latest(SOURCE, 20)
        self.assertTrue(post["content"].startswith("A long read, finally.\n\nAn example acquisition\n\nWe are joining"))
        self.assertEqual(post["title"], "An example acquisition")

    async def test_text_route_down_gives_the_preview_marked_partial(self):
        http = FakeHttp({FEED: _feed(_stub_item(100)), _text(100): ValueError("HTTP 503"), _preview(100): _preview_answer()})
        [post] = await _kind(http).fetch_latest(SOURCE, 20)
        self.assertEqual(post["title"], "An example acquisition")
        self.assertIn("Three reasons", post["content"])
        meta = post["metadata"]
        self.assertNotIn(FULL_TEXT_FLAG, meta)
        self.assertEqual(meta[PAGE_OUTCOME_KEY]["outcome"], full_text.PREVIEW_ONLY)
        self.assertFalse(meta[X_ARTICLE_KEY]["complete"])
        self.assertEqual(full_text.teaser_reason(meta), "X gave only the article's opening")

    async def test_an_answer_with_no_article_falls_through_to_the_preview(self):
        http = FakeHttp({FEED: _feed(_stub_item(100)), _text(100): json.dumps({"code": 200, "tweet": {"text": "x"}}),
                         _preview(100): _preview_answer()})
        [post] = await _kind(http).fetch_latest(SOURCE, 20)
        self.assertEqual(post["metadata"][X_ARTICLE_KEY]["via"], "preview")

    async def test_both_routes_down_leave_the_post_as_today(self):
        feed = _feed(_stub_item(100))
        http = FakeHttp({FEED: feed, _text(100): ValueError("HTTP 500"), _preview(100): "not json"})
        [post] = await _kind(http).fetch_latest(SOURCE, 20)
        [plain] = await NitterRssKind(FakeHttp({FEED: feed}), env={x_articles.TEXT_URL_ENV: "",
                                                                  x_articles.PREVIEW_URL_ENV: ""}).fetch_latest(SOURCE, 20)
        self.assertEqual(post, plain)
        self.assertNotIn(X_ARTICLE_KEY, post["metadata"])

    async def test_a_lookup_that_hangs_is_given_up(self):
        import asyncio

        class SlowHttp(FakeHttp):
            async def get_text(self, url, **kwargs):
                if url != FEED:
                    self.requests.append(url)
                    await asyncio.sleep(5)
                return await super().get_text(url, **kwargs)

        http = SlowHttp({FEED: _feed(_stub_item(100))})
        original = x_articles.LOOKUP_TIMEOUT_S
        x_articles.LOOKUP_TIMEOUT_S = 0.01
        try:
            kind = _kind(http)
            [post] = await asyncio.wait_for(kind.fetch_latest(SOURCE, 20), 2)
        finally:
            x_articles.LOOKUP_TIMEOUT_S = original
        self.assertNotIn(X_ARTICLE_KEY, post["metadata"])

    async def test_ordinary_tweets_are_untouched(self):
        feed = _feed(_item(101, "Hello", "<p>Hello there.</p>"),
                     _item(102, "Quote", "<p>Worth it.</p><hr/><blockquote>" + _stub_html("9") + "</blockquote>"))
        http = FakeHttp({FEED: feed})
        posts = await _kind(http).fetch_latest(SOURCE, 20)
        self.assertEqual(http.requests, [FEED])
        self.assertEqual(posts[0]["content"], "Hello there.")
        self.assertFalse(any(X_ARTICLE_KEY in p["metadata"] for p in posts))

    async def test_env_off_switches(self):
        http = FakeHttp({FEED: _feed(_stub_item(100)), _preview(100): _preview_answer()})
        [post] = await _kind(http, env={x_articles.TEXT_URL_ENV: ""}).fetch_latest(SOURCE, 20)
        self.assertEqual(http.requests, [FEED, _preview(100)])
        self.assertEqual(post["metadata"][X_ARTICLE_KEY]["via"], "preview")

        http = FakeHttp({FEED: _feed(_stub_item(100))})
        await _kind(http, env={x_articles.TEXT_URL_ENV: "", x_articles.PREVIEW_URL_ENV: ""}).fetch_latest(SOURCE, 20)
        self.assertEqual(http.requests, [FEED])

        http = FakeHttp({FEED: _feed(_stub_item(100)), "https://fx.example.org/s/100": _text_answer()})
        [post] = await _kind(http, env={x_articles.TEXT_URL_ENV: "https://fx.example.org/s/{id}"}).fetch_latest(SOURCE, 20)
        self.assertTrue(post["metadata"][FULL_TEXT_FLAG])

    async def test_lookups_are_capped_per_fetch_and_spaced(self):
        count = x_articles.MAX_PER_FETCH + 2
        statuses = [200 - i for i in range(count)]
        http = FakeHttp({FEED: _feed(*(_stub_item(s) for s in statuses)), **{_text(s): _text_answer() for s in statuses}})
        posts = await _kind(http).fetch_latest(SOURCE, 50)
        self.assertEqual(len(http.requests), 1 + x_articles.MAX_PER_FETCH)
        self.assertEqual(sum(X_ARTICLE_KEY in p["metadata"] for p in posts), x_articles.MAX_PER_FETCH)
        self.assertEqual(http.sleeper.calls, [x_articles.LOOKUP_DELAY_S] * (x_articles.MAX_PER_FETCH - 1))

    async def test_a_stored_article_is_kept_and_a_stub_or_old_preview_looked_up_again(self):
        whole = x_articles.with_article({"url": "u", "title": "", "content_html": _stub_html("1"), "metadata": {}},
                                        x_articles._from_text_answer(json.loads(_text_answer("Stored title"))), NOW)
        old = x_articles.with_article({"url": "u", "title": "", "content_html": _stub_html("1"), "metadata": {}},
                                      x_articles._from_preview_answer(json.loads(_preview_answer("Old preview"))),
                                      NOW - timedelta(days=2))
        urls = {s: f"https://nitter.local/{USER}/status/{s}#m" for s in (100, 101, 102)}
        stored = {urls[100]: {k: whole[k] for k in ("title", "content", "content_html", "media_urls", "metadata")},
                  urls[101]: {k: old[k] for k in ("title", "content", "content_html", "media_urls", "metadata")}}
        asked = []
        http = FakeHttp({FEED: _feed(_stub_item(100), _stub_item(101), _stub_item(102)),
                         _text(101): _text_answer("Fresh"), _text(102): _text_answer("New")})
        posts = await _kind(http, stored=lambda u: (asked.append(list(u)), stored)[1]).fetch_latest(SOURCE, 20)
        by = {p["url"]: p for p in posts}
        self.assertEqual(by[urls[100]]["title"], "Stored title")
        self.assertEqual(by[urls[101]]["title"], "Fresh")
        self.assertEqual(by[urls[102]]["title"], "New")
        self.assertEqual(http.requests, [FEED, _text(101), _text(102)])
        self.assertEqual(sorted(asked[0]), sorted(urls.values()))

    async def test_the_archive_reads_articles_too(self):
        http = FakeHttp({FEED: (_feed(_stub_item(100)), {}), _text(100): _text_answer()})
        pages = [page async for page in _kind(http).archive_pages(SOURCE, 20, None, None)]
        self.assertTrue(pages[0].posts[0]["metadata"][FULL_TEXT_FLAG])


@requires_test_db
class StoredStubTests(unittest.IsolatedAsyncioTestCase):
    """A tweet stored as its article's link alone gets its article: by a later fetch, or by the repair."""

    def setUp(self):
        self.url = db_url()
        self.repo = PostsRepository(self.url)
        self.user = f"example_{uuid.uuid4().hex[:10]}"
        self.feed = f"https://nitter.local/{self.user}/rss"
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest) VALUES ('rss', %s, false, false)"
                        " RETURNING id", (self.feed,))
            self.source_id = str(cur.fetchone()[0])
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sources WHERE id = %s", (self.source_id,))
            conn.commit()

    def _save(self, posts) -> list:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            ids = [self.repo.upsert_post(cur, post, self.source_id)[0] for post in posts]
            conn.commit()
        return ids

    def _row(self, post_id: str) -> tuple:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT title, content, metadata FROM posts WHERE id = %s", (post_id,))
            return cur.fetchone()

    def _stub_post(self, status: int) -> dict:
        feed = _feed(_item(status, f"x.com/i/article/{status}…", _stub_html(str(status)), self.user))
        return feed

    async def _stub(self, status: int) -> str:
        source = {**SOURCE, "id": self.source_id, "handle_or_url": self.feed}
        off = {x_articles.TEXT_URL_ENV: "", x_articles.PREVIEW_URL_ENV: ""}
        posts = await NitterRssKind(FakeHttp({self.feed: self._stub_post(status)}), env=off).fetch_latest(source, 20)
        [post_id] = self._save(posts)
        return post_id

    async def test_a_later_fetch_writes_the_article_over_a_stored_stub_and_keeps_it(self):
        post_id = await self._stub(300)
        self.assertTrue(self._row(post_id)[0].startswith("x.com/i/article/"))
        source = {**SOURCE, "id": self.source_id, "handle_or_url": self.feed}
        http = FakeHttp({self.feed: self._stub_post(300), _text(300, self.user): _text_answer()})
        kind = NitterRssKind(http, env=ON, stored_articles=self.repo.stored_x_articles, clock=lambda: NOW)
        self.assertEqual(self._save(await kind.fetch_latest(source, 20)), [post_id])
        title, content, metadata = self._row(post_id)
        self.assertEqual(title, "An example acquisition")
        self.assertIn("Three reasons.", content)
        self.assertTrue(metadata[FULL_TEXT_FLAG])

        # Fetched again: kept as stored, not looked up again.
        http = FakeHttp({self.feed: self._stub_post(300)})
        kind = NitterRssKind(http, env=ON, stored_articles=self.repo.stored_x_articles, clock=lambda: NOW)
        self._save(await kind.fetch_latest(source, 20))
        self.assertEqual(http.requests, [self.feed])
        self.assertEqual(self._row(post_id)[:2], (title, content))

    async def test_the_repair_reads_a_stored_stub_once(self):
        post_id = await self._stub(400)
        ordinary = self._save([{"url": f"https://nitter.local/{self.user}/status/401#m", "title": "Plain tweet",
                                "content": "Plain tweet", "content_html": "<p>Plain tweet</p>", "date": NOW}])[0]
        http = FakeHttp({_text(400, self.user): _text_answer()})
        registry = KindRegistry.default(http, object(), db_url=self.url)
        summary = await Repair(self.url, http=http, registry=registry, clock=lambda: NOW).run(
            rule=True, source_id=self.source_id)
        self.assertEqual(summary["repaired"], 1)
        self.assertEqual(http.requests, [_text(400, self.user)])
        title, content, metadata = self._row(post_id)
        self.assertEqual(title, "An example acquisition")
        self.assertIn("We are joining", content)
        self.assertTrue(metadata[FULL_TEXT_FLAG])
        self.assertEqual(metadata[X_ARTICLE_KEY]["via"], "text")
        self.assertEqual(self._row(ordinary)[1], "Plain tweet")
        again = await Repair(self.url, http=FakeHttp(), registry=registry, clock=lambda: NOW).run(
            rule=True, source_id=self.source_id)
        self.assertEqual(again.get("to_read"), 0)

    async def test_the_repair_counts_an_article_it_could_not_read(self):
        post_id = await self._stub(500)
        http = FakeHttp({})
        registry = KindRegistry.default(http, object(), db_url=self.url)
        summary = await Repair(self.url, http=http, registry=registry, clock=lambda: NOW).run(
            rule=True, source_id=self.source_id)
        self.assertEqual(summary["failed"], 1)
        title, _, metadata = self._row(post_id)
        self.assertTrue(title.startswith("x.com/i/article/"))
        self.assertEqual(metadata[PAGE_OUTCOME_KEY]["outcome"], "error:ArticleUnavailable")


if __name__ == "__main__":
    unittest.main()
