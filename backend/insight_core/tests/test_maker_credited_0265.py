"""Issue 0265: a maker's page reached through another source (Hacker News, a link blog, Saved) is credited to the
maker: the byline names the followed source whose site the page is on as its author and the carrier as `via`
("Example Labs News via Hacker News"), on Mark X's News lines and every view reading `bylines`. Display only.
Invented names only."""
from __future__ import annotations

import json
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from insight_core.markx import news  # noqa: E402
from insight_core.tests._db import db_url, requires_test_db  # noqa: E402
from insight_core.utils import byline as B  # noqa: E402

HN = ("rss", "https://hnrss.org/newest?points=100")
LINKBLOG = ("rss", "https://linkblog.example/feed")


class Pure(unittest.TestCase):
    sites = {
        "labs.example": [("Example Labs News", "rss", "https://labs.example/news")],
        "models.example": [("Models Blog", "rss", "https://models.example/blog/feed.xml"),
                           ("Acme Org Page", "rss", "https://models.example/acme-org")],
        "big.example": [("Big News", "rss", "https://big.example/news/rss.xml"),
                        ("Big Research", "rss", "https://www.big.example/research")],
    }

    def owner(self, url, holder=HN):
        return B.page_owner(url, holder[0], holder[1], self.sites)

    def test_an_aggregators_copy_of_a_makers_page_is_the_makers(self):
        self.assertEqual(self.owner("https://labs.example/news/widget-2-mini/"), "Example Labs News")
        self.assertEqual(self.owner("https://labs.example/news/widget-2-mini#!/cited-by/x"), "Example Labs News",
                         "the aggregator's citation of the page names the maker too")
        self.assertEqual(self.owner("https://www.labs.example/index/other-page", LINKBLOG), "Example Labs News",
                         "a link blog's post at the page, any section of the site's only source")
        self.assertEqual(self.owner("https://labs.example/x", ("saved", "saved")), "Example Labs News")

    def test_the_makers_own_post_and_unfollowed_sites_name_nobody(self):
        self.assertIsNone(B.page_owner("https://labs.example/news/widget", "rss", "https://labs.example/news", self.sites))
        self.assertIsNone(self.owner("https://elsewhere.example/news/widget"))
        self.assertIsNone(B.page_owner("https://labs.example/news/w", "rss", "https://nitter.local/acme/rss", self.sites),
                          "a platform post's address is never a site's page")
        self.assertIsNone(B.page_owner("https://labs.example/news/w", "telegram", "examplechan", self.sites))
        self.assertIsNone(B.page_owner("https://labs.example/news/w", *HN, {}), "no sites given: as before")

    def test_of_several_sources_on_one_site_the_section_decides(self):
        self.assertEqual(self.owner("https://big.example/research/a-result"), "Big Research")
        self.assertEqual(self.owner("https://big.example/news/a-post"), "Big News")
        self.assertIsNone(self.owner("https://big.example/legal/terms"), "two sources, the page under neither: nobody")
        self.assertEqual(self.owner("https://models.example/acme-org/model-7b"), "Acme Org Page")
        self.assertIsNone(self.owner("https://models.example/stranger-org/model-7b"),
                          "a platform site's user page is not its blog's")

    def test_the_byline(self):
        b = B.byline("Hacker News", *HN, url="https://labs.example/news/widget-2-mini/", sites=self.sites)
        self.assertEqual(b, {"author": "Example Labs News", "via": "Hacker News", "quoting": None})
        self.assertEqual(B.byline("Hacker News", *HN), {"author": None, "via": "Hacker News", "quoting": None},
                         "without a url and the sites: as before")


@requires_test_db
class SeededWorld(unittest.TestCase):
    """A maker's page watch, Hacker News holding the maker's page (the page watch not having fetched it yet), its
    citation of another page the maker holds, and an X feed's post: Mark X's News lines and `bylines` agree."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        sfx = uuid.uuid4().hex[:8]
        self.site = f"labs{sfx}.example"
        self.maker = self.source("rss", f"https://{self.site}/news", "Example Labs News")
        self.hn = self.source("rss", f"https://hnrss.org/newest?points=100&s={sfx}", "Hacker News")
        self.x = self.source("rss", f"https://nitter.local/acme{sfx}/rss", "Acme (X)")
        self.held = self.post(self.hn, f"https://{self.site}/news/widget-2-mini/", "Widget 2 Mini")
        self.own = self.post(self.maker, f"https://{self.site}/news/widget-2-small", "Introducing Widget 2 Small")
        self.cite = self.post(self.hn, f"https://{self.site}/news/widget-2-small#!/cited-by/{self.hn}", "Widget 2 Small")
        self.tweet = self.post(self.x, f"https://nitter.local/acme{sfx}/status/1", "A post", author=f"acme{sfx}")

    def source(self, platform, handle, name):
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest, settings) "
                         "VALUES (%s, %s, true, false, %s::jsonb) RETURNING id::text",
                         (platform, handle, json.dumps({"display_name": name})))
        return self.cur.fetchone()[0]

    def post(self, source, url, title, author=None):
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at, author) "
                         "VALUES (%s, %s, %s, %s, 'Words of its own.', %s, %s) RETURNING id::text",
                         (source, url, url, title, datetime.now(timezone.utc), author))
        return self.cur.fetchone()[0]

    def test_news_lines_and_bylines_credit_the_maker(self):
        want = {
            self.held: {"author": "Example Labs News", "via": "Hacker News", "quoting": None},
            self.own: {"author": None, "via": "Example Labs News", "quoting": None},
            self.cite: {"author": "Example Labs News", "via": "Hacker News", "quoting": None},
            self.tweet: {"author": None, "via": "Acme (X)", "quoting": None},
        }
        lines = news._posts(self.cur, want)
        self.assertEqual({p: lines[p]["byline"] for p in want}, want)
        self.assertEqual(lines[self.held]["source"], "Hacker News", "the stored source stays (display only)")
        self.assertEqual(B.bylines(self.cur, want), want)

    def test_a_disabled_maker_is_no_owner(self):
        self.cur.execute("UPDATE sources SET enabled = false WHERE id = %s", (self.maker,))
        self.assertIsNone(B.bylines(self.cur, [self.held])[self.held]["author"])


if __name__ == "__main__":
    unittest.main()
