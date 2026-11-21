"""Issue 0268 (v10.31.1): a change of the dating rule re-dates the stories already stored.

0263's rule (a Saved page more than 72 h before its story's first report never dates it) was written by
decide.persist only for the stories a run reads, so a Mark X story stored before the deploy kept the date of a Saved
paper it cites. The rule is stamped now (decide.dates_stamp over stamps.story_dates): a run finding another stamp
than the one kept re-dates every current story once (decide.redate_due). Mark IX's stories regroup once by its own
stamp (stamps.posts' 0263 case; tests/test_stamps.py). Invented release "Glimmer 3"; the DB tests run on a database
whose name ends in _test, each in one transaction rolled back."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import psycopg

from insight_core.markx import decide, graph as G, news as N, repo, schemas
from insight_core.tests._db import clear_tables, db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES
from insight_core.utils import story_rules

T = datetime(2100, 5, 1, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)


class StampTests(unittest.TestCase):
    """No database."""

    def test_the_dating_rule_is_stamped_by_what_it_makes(self):
        now = decide.dates_stamp()
        self.assertEqual(decide.dates_stamp(), now)
        with mock.patch.object(story_rules, "background", lambda posts, times: set()):   # the rule before 0263
            self.assertNotEqual(decide.dates_stamp(), now)
        with mock.patch.object(story_rules, "BACKGROUND_BEFORE", timedelta(hours=48)):   # its tuned value moved
            self.assertNotEqual(decide.dates_stamp(), now)


@requires_test_db
class RedateTests(unittest.TestCase):

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, MX_TABLES)
        schemas.load_guides(self.cur)
        self.run_id = repo.start_run(self.cur, code_version="t", config={})
        patch = mock.patch.object(G, "chain_config", side_effect=lambda: {"on": True, "shown": (), "one_row": False})
        patch.start()
        self.addCleanup(patch.stop)

    def post(self, at, title, platform="telegram"):
        source = insert_scratch_source(self.cur, platform=platform, settings_json=json.dumps({"display_name": title[:8]}))
        url = f"https://test.invalid/redate/{uuid.uuid4().hex}"
        body = title + ". " + " ".join(f"word{k}{url[-6:]}" for k in range(30))
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (source, url, url, title, body, at))
        pid = str(self.cur.fetchone()[0])
        from insight_core.db.repo_post_parts import PostPartsRepository
        PostPartsRepository.write(self.cur, [pid])
        return pid

    def stored(self, first_at, members):
        sid = str(repo.add_story(self.cur, first_at=first_at, run_id=self.run_id, headline="Lumen releases Glimmer 3"))
        for pid in members:
            repo.open_membership(self.cur, story_id=sid, post_id=pid, role="member", reason="rule:citation",
                                 run_id=self.run_id)
        return sid

    def first_at(self, sid):
        self.cur.execute("SELECT first_at FROM mx_stories WHERE id = %s", (sid,))
        return self.cur.fetchone()[0]

    def test_a_stored_story_dated_by_an_old_saved_page_is_redated_once_and_its_row_returns(self):
        paper = self.post(T - 365 * 24 * H, "Sparse routing for small models", platform="saved")
        reports = [self.post(T, "Lumen introduces Glimmer 3"), self.post(T + H, "Glimmer 3 is out"),
                   self.post(T + 2 * H, "Trying Glimmer 3 today")]
        release = self.stored(T - 365 * 24 * H, [paper, *reports])        # stored by the rule before 0263
        # a leak's story: a voice's post 4 days early still dates it (never re-dated away)
        leak = [self.post(T - 96 * H, "Glimmer 3 spotted"), self.post(T, "Glimmer 3 launch")]
        early = self.stored(T - 96 * H, leak)
        got = decide.redate_due(self.cur)
        self.assertEqual(got, {"stories": 2, "moved": 1})
        self.assertEqual(self.first_at(release), T)
        self.assertEqual(self.first_at(early), T - 96 * H)
        self.assertIsNone(decide.redate_due(self.cur))                      # once a stamp: the next run reads it
        self.assertEqual(decide.redate(self.cur), {"stories": 2, "moved": 0})   # idempotent
        # the stamp of another rule re-dates again
        repo.set_setting(self.cur, decide.DATES_KEY, "an-older-rule")
        self.assertEqual(decide.redate_due(self.cur), {"stories": 2, "moved": 0})
        # News over the story: the release row is in a window that begins after the paper, first at the maker's post
        rows = N.rows_of(self.cur, {release: ([paper, *reports], set())}, T - 24 * H, window=set())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["first_at"], T)
        self.assertEqual(rows[0]["posts"][0]["post_id"], reports[0])
        self.assertEqual({p["post_id"] for p in rows[0]["posts"]}, {paper, *reports})   # the paper stays a member

    def test_a_merged_story_is_left_as_it_is(self):
        paper = self.post(T - 365 * 24 * H, "Sparse routing for small models", platform="saved")
        reports = [self.post(T, "Lumen introduces Glimmer 3"), self.post(T + H, "Glimmer 3 is out")]
        gone = self.stored(T - 365 * 24 * H, [paper, *reports])
        into = self.stored(T, reports)
        repo.merge_story(self.cur, gone, into=into)
        self.assertEqual(decide.redate(self.cur), {"stories": 1, "moved": 0})
        self.assertEqual(self.first_at(gone), T - 365 * 24 * H)


if __name__ == "__main__":
    unittest.main()
