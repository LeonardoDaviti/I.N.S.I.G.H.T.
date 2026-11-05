"""A mail or analytics tracker's query names no other page (issue 0109 B1).

The rule is url_normalization's (test_post_fields_utils); the story sample holds its case, so the
rules' stamp regroups every story once (test_stamps). Here: the links already stored with a tracker
are read again from their post's stored HTML (migration 0067), and only those.
"""
from __future__ import annotations

import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_stories import StoriesRepository
from insight_core.services.stories_service import SETTINGS_KEY, StoriesService
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils import url_normalization

MIGRATION = BACKEND_DIR / "insight_core" / "db" / "migrations" / "0067_tracking_queries.sql"


def _pattern() -> re.Pattern:
    """The migration's pattern of a stored link holding a tracker (Postgres ~* reads it as Python does here)."""
    [pattern] = re.findall(r"target_url ~\* '([^']+)'", MIGRATION.read_text(encoding="utf-8"))
    return re.compile(pattern, re.I)


class TheMigrationReadsTheClassTests(unittest.TestCase):
    def test_every_tracker_the_rule_drops_is_one_the_migration_reads_again(self):
        pattern = _pattern()
        keys = sorted(url_normalization.TRACKING_QUERY_KEYS - url_normalization.BEFORE_0109)
        self.assertGreater(len(keys), 20)
        for key in keys + [prefix + "x" for prefix in url_normalization.TRACKING_QUERY_PREFIXES if prefix != "utm_"]:
            self.assertTrue(url_normalization.is_tracking_key(key), key)
            self.assertTrue(pattern.search(f"https://a.example/p?id=1&{key}=v"), key)
            self.assertTrue(pattern.search(f"https://a.example/p?{key}=v"), key)
        for kept in ("id", "p", "cid", "share", "ga", "hs", "tag", "page_ga"):
            self.assertFalse(pattern.search(f"https://a.example/p?{kept}=v"), kept)
            self.assertFalse(url_normalization.is_tracking_key(kept), kept)


@requires_test_db
class MigrationTests(unittest.TestCase):
    def test_0067_reads_again_only_the_posts_whose_links_hold_a_tracker(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        conn = psycopg.connect(db_url())
        try:
            cur = conn.cursor()
            source = insert_scratch_source(cur)
            html = ('<p><a href="https://journal.example/issue/417?_hsenc=p2A&amp;_hsmi=1">one</a> and '
                    '<a href="https://journal.example/issue/417?_hsenc=p2B">again</a> and '
                    '<a href="https://forum.example/viewtopic?t=12&amp;_ga=2.1">a thread</a></p>')
            rows = {}
            for name, url, body, links in [
                ("tracked", "https://letter.example/p/weekly", html,
                 ["https://journal.example/issue/417?_hsenc=p2A&_hsmi=1", "https://journal.example/issue/417?_hsenc=p2B",
                  "https://forum.example/viewtopic?_ga=2.1&t=12"]),
                ("plain", "https://letter.example/p/other", '<a href="https://forum.example/viewtopic?t=9">t</a>',
                 ["https://forum.example/viewtopic?t=9"]),
            ]:
                cur.execute("""INSERT INTO posts (source_id, url, normalized_url, url_host, title, content, content_html,
                                                  links_scanned_at)
                               VALUES (%s, %s, %s, 'letter.example', %s, 'c', %s, now()) RETURNING id""",
                            (source, url, url, name, body))
                rows[name] = cur.fetchone()[0]
                for position, target in enumerate(links):
                    cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, %s, %s)",
                                (rows[name], target, target.split("/")[2], position))
            cur.execute(sql)
            cur.execute("SELECT id, links_scanned_at IS NULL FROM posts WHERE id = ANY(%s)", (list(rows.values()),))
            self.assertEqual(dict(cur.fetchall()), {rows["tracked"]: True, rows["plain"]: False})
            StoriesRepository().save_post_links(cur, str(rows["tracked"]))   # as fill_missing_links reads it
            cur.execute("SELECT target_url FROM post_links WHERE post_id = %s ORDER BY position", (rows["tracked"],))
            self.assertEqual([r[0] for r in cur.fetchall()],
                             ["https://journal.example/issue/417", "https://forum.example/viewtopic?t=12"],
                             "one page, its own query kept")
            cur.execute(sql)
            cur.execute("SELECT count(*) FROM posts WHERE id = ANY(%s) AND links_scanned_at IS NULL", (list(rows.values()),))
            self.assertEqual(cur.fetchone()[0], 0, "a second run reads nothing again")
        finally:
            conn.rollback()
            conn.close()


@requires_test_db
class ADeploysFirstStartTests(unittest.TestCase):
    """What a deploy's first start makes of it (issue 0110's check): the links read again, then the rule
    change's rebuild in batches, leave what a full run leaves. On the lab's copy the rebuild kept a classic
    at a tracked address no link points to any more, where the full run has it at the page's own."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mark = uuid.uuid4().hex[:8]
        self.service = StoriesService(db_url(), clock=lambda: self.now)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _classics(self, page):
        self.cur.execute("SELECT target_url, voices FROM classics WHERE target_url LIKE %s ORDER BY 1", (page + "%",))
        return self.cur.fetchall()

    def test_a_classic_at_a_tracked_address_moves_to_the_page_in_the_rebuild(self):
        page = f"https://journal-{self.mark}.test/issue/417"
        tracked = page + "?_hsenc=p2A"
        sources = {name: insert_source(self.cur, f"{name} {self.mark}", in_main_digest=True) for name in ("Letter", "Forward")}
        for name, days in (("Letter", 400), ("Forward", 300), ("Letter", 10)):   # two voices, cited 290 days on
            source = sources[name]
            insert_post(self.cur, source, f"https://{name.lower()}-{self.mark}.test/p/{days}", at=self.now - timedelta(days=days),
                        title=f"{name} post", content="Body", html=f'<p><a href="{tracked}">the issue</a></p>',
                        content_hash=uuid.uuid4().hex, links=[tracked])   # stored as the rules before 0109 read it
        self.service.full_on(self.cur)
        self.assertEqual(self._classics(page), [(tracked, 2)], "before: the classic at the tracked address")
        self.cur.execute(MIGRATION.read_text(encoding="utf-8"))
        setting = SystemSettingsRepository.get(self.cur, SETTINGS_KEY)[0]
        SystemSettingsRepository.upsert(self.cur, SETTINGS_KEY, {**setting, "rules": "the rules before 0109"})
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        self.service.update(self.cur)                    # the deploy's first start: the rebuild, to the end
        self.assertEqual(self._classics(page), [(page, 2)], "after: at the page's own address, once")
        rebuilt = self.service.full_on(self.cur)
        self.assertEqual(rebuilt["classics_changed"], 0, "a full run after it changes nothing")


if __name__ == "__main__":
    unittest.main()
