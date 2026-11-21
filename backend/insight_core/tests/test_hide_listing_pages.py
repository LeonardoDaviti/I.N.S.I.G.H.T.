"""v10.35: stored listing pages hidden through the item filter's `listing` flag (never deleted), once by
scripts/hide_listing_pages and at store time for one that slips past the fetch's checks. Invented sites only."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone

import psycopg

from insight_core.ingestion.kinds.page_watch import stored_listing
from insight_core.scripts import hide_listing_pages as H
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.utils import item_filter as F

SITE = "https://blog.example.org"


class StoredListing(unittest.TestCase):
    def test_a_site_page_at_a_listing_address_only(self):
        self.assertTrue(stored_listing(f"{SITE}/tag/gaganode/", "/tag/gaganode/", "generic_rss"))
        self.assertTrue(stored_listing(f"{SITE}/blog/category/news", "/blog/category/news", "page_watch"))
        # a feed's own item (its guid), a saved page, a release's tag page, an article: never
        self.assertFalse(stored_listing(f"{SITE}/tag/gaganode/", "https://blog.example.org/?p=12", "generic_rss"))
        self.assertFalse(stored_listing(f"{SITE}/category/podcast/", "/category/podcast/", "saved"))
        self.assertFalse(stored_listing("https://github.com/acme/widget/releases/tag/v1.0", None, None))
        self.assertFalse(stored_listing(f"{SITE}/2026/11/botnet/", "/2026/11/botnet/", "generic_rss"))
        # a watched /topics/ section's pages are its articles
        self.assertFalse(stored_listing(f"{SITE}/topics/how-we-build", "/topics/how-we-build", "page_watch", "/topics/"))

    def test_the_flag_is_kept_through_the_rule_and_the_listing_rule_passes_the_check(self):
        rule = {"kind": "builds", "hide": [{"field": "tag", "regex": r"^b\d+$", "why": "builds"}], "listing": True}
        self.assertEqual(F.clean(rule)["listing"], True)
        self.assertIsNone(F.check({"kind": F.LISTING_KIND, "hide": [], "listing": True}, []))


@requires_test_db
class Repair(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        self.source = insert_scratch_source(self.cur, settings_json=json.dumps({"display_name": "Example Blog"}))
        self.addCleanup(self.cur.execute, "DELETE FROM source_filters WHERE source_id = %s", (self.source,))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.source,))
        self.host = f"{uuid.uuid4().hex[:8]}.example.org"

    def post(self, path, *, adapter="generic_rss", external_id=None):
        url = f"https://{self.host}{path}"
        self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, external_id, title, content, published_at,
                                               metadata)
                            VALUES (%s, %s, %s, %s, 'A title', 'text', %s, %s::jsonb) RETURNING id::text""",
                         (self.source, url, url, path if external_id is None else external_id,
                          datetime.now(timezone.utc), json.dumps({"adapter": adapter})))
        return self.cur.fetchone()[0]

    def hidden(self):
        self.cur.execute("SELECT url FROM posts WHERE source_id = %s AND filtered_by IS NOT NULL ORDER BY url",
                         (self.source,))
        return [u.split(self.host, 1)[1] for (u,) in self.cur.fetchall()]

    def test_a_dry_run_writes_nothing_and_a_run_hides_the_listing_pages_only(self):
        self.post("/tag/gaganode/")
        self.post("/author/brian/", adapter="page_watch")
        self.post("/2026/11/botnet/")
        self.post("/tag/feed-item/", external_id="guid-1")     # a feed's own item at such an address: kept
        with psycopg.connect(db_url()) as conn:
            dry = H.run(conn, dry_run=True, source_id=self.source)
        self.assertEqual((dry["posts"], dry["sources"][0]["rule"]), (2, "rule added"))
        self.assertEqual((self.hidden(), F.current(self.cur, [self.source])), ([], {}))
        with psycopg.connect(db_url()) as conn:
            done = H.run(conn, dry_run=False, source_id=self.source)
        self.assertEqual(done["sources"][0]["hidden"], 2)
        self.assertEqual(self.hidden(), ["/author/brian/", "/tag/gaganode/"])
        self.cur.execute("SELECT count(*) FROM posts WHERE source_id = %s", (self.source,))
        self.assertEqual(self.cur.fetchone()[0], 4)   # nothing deleted
        with psycopg.connect(db_url()) as conn:
            again = H.run(conn, dry_run=False, source_id=self.source)
        self.assertEqual(again["sources"][0]["rule"], "has the flag")

    def test_an_owners_rule_keeps_the_flag_and_clearing_it_leaves_the_flag(self):
        self.post("/tag/gaganode/")
        F.put(self.cur, self.source, {"kind": "builds", "hide": [{"field": "title", "regex": "^Nightly", "why": "n"}]},
              by="owner")
        with psycopg.connect(db_url()) as conn:
            self.assertEqual(H.run(conn, dry_run=False, source_id=self.source)["sources"][0]["rule"],
                             "flag joins its rule")
        rule = F.current(self.cur, [self.source])[self.source]["rule"]
        self.assertEqual((rule["kind"], rule["listing"], len(rule["hide"])), ("builds", True, 1))
        F.put(self.cur, self.source, None, by="owner")
        self.assertEqual(F.current(self.cur, [self.source])[self.source]["rule"],
                         {"kind": F.LISTING_KIND, "hide": [], "listing": True})
        self.assertEqual(self.hidden(), ["/tag/gaganode/"])

    def test_a_new_listing_page_that_slipped_past_the_fetch_is_hidden_at_store_time(self):
        from insight_core.db.repo_posts import PostDraft, PostsRepository
        base = f"https://{self.host}"
        drafts = [PostDraft(self.source, {"url": f"{base}{p}", "external_id": p, "title": p, "content": f"the text of {p}",
                                          "date": datetime.now(timezone.utc), "metadata": {"adapter": "generic_rss"}})
                  for p in ("/tag/slipped/", "/2026/11/article/")]
        with psycopg.connect(db_url()) as conn:
            PostsRepository(db_url()).save_batch(conn, drafts)
        self.assertEqual(self.hidden(), ["/tag/slipped/"])
        self.assertTrue(F.current(self.cur, [self.source])[self.source]["rule"]["listing"])
        self.assertEqual(F.current(self.cur, [self.source])[self.source]["by"], "insight")


if __name__ == "__main__":
    unittest.main()
