"""Issue 0200 (v10.17.1): a source the owner switched off never feeds a suggestion. One rule (repo_stories:
suggestable_sql, switched_off, SourceFacts.suggestable), asked by every list that proposes something: here Discover's
sites (by links and by the stories that start there), its Pages and archive rows, and the voices' suggestions; the
tracks, the scout, 0170's main source, Discover's citations and entity Pages have theirs in their own modules
(test_markx_tracks.SwitchedOff, test_discover_main_source, test_entity_originals). Each time: the switched-off
source's posts are no evidence, an enabled source's still are, and switching it on again brings the suggestion back.
News and stories keep it (membership is no suggestion). Synthetic data only."""
from __future__ import annotations

import contextlib
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.db.repo_stories import SourceFacts, suggestable_sql, switched_off
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._stories import insert_post, insert_source

NOW = datetime.now(timezone.utc).replace(microsecond=0)


@requires_test_db
class TheRule(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)

    def test_one_rule_in_sql_and_in_python(self):
        on = insert_source(self.cur, "On")
        off = insert_source(self.cur, "Off", enabled=False)
        self.assertIn(off, switched_off(self.cur))
        self.assertNotIn(on, switched_off(self.cur))
        facts = SourceFacts(self.cur)
        self.assertEqual((facts.suggestable(on), facts.suggestable(off), facts.suggestable(None)), (True, False, True))
        self.cur.execute(f"SELECT id::text FROM sources WHERE id = ANY(%s::uuid[]) AND {suggestable_sql('id')}", ([on, off],))
        self.assertEqual(self.cur.fetchall(), [(on,)])
        # still followed: a switched-off source's own site is never suggested either
        self.assertIn(off, facts.kind)


@requires_test_db
class DiscoverLists(unittest.TestCase):
    """Through the service (it opens its own connections), as test_discover_origins."""

    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self._clean)

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM stories WHERE origin_url LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        self.conn.commit()
        self.conn.close()

    def _voices(self, n=3):
        out = []
        for k in range(n):
            host = f"voice{k}-{self.mark}.example"
            source = insert_source(self.cur, f"Voice {k} {self.mark}", handle=f"https://{host}/feed")
            insert_post(self.cur, source, f"https://{host}/p/home", at=NOW, normalized=f"https://{host}/p/home")
            out.append((source, host))
        return out

    def _cite(self, voices, origin, *, days=0):
        posts = []
        for source, host in voices:
            url = f"https://{host}/p/{uuid.uuid4().hex}"
            pid = insert_post(self.cur, source, url, at=NOW - timedelta(days=days), normalized=url, links=[origin])
            posts.append((pid, f"site:{host}"))
        story = posts[0][0]
        self.cur.execute("INSERT INTO stories (id, first_at, voices, origin_url, origin_linked_by) VALUES (%s, %s, %s, %s, %s)",
                         (story, NOW - timedelta(days=days), len(posts), origin, len(posts)))
        for pid, voice in posts:
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_reason, parent_url) "
                             "VALUES (%s, %s, 'report', %s, 'citation', %s)", (pid, story, voice, origin))

    def _switch(self, source, on):
        self.cur.execute("UPDATE sources SET enabled = %s WHERE id = %s", (on, source))

    def _discover(self):
        self.conn.commit()
        return StoriesService(db_url()).discover()

    def _keys(self, result):
        return [s["key"] for s in result["suggestions"] if self.mark in s["key"]]

    def test_a_site_linked_and_started_at_by_three_voices_one_of_them_switched_off(self):
        m = self.mark
        voices = self._voices(3)
        for source, host in voices:                                        # links only: 3 voices, 2 articles
            insert_post(self.cur, source, f"https://{host}/p/x", at=NOW, normalized=f"https://{host}/p/x",
                        links=[f"https://busy-{m}.example/2026/11/story-{n}" for n in range(2)])
        for n in range(2):                                                  # and 2 stories of the 3 start there
            self._cite(voices, f"https://origin-{m}.example/2026/11/launch-{n}")
        on = self._discover()
        self.assertEqual(sorted(self._keys(on)), [f"busy-{m}.example", f"origin-{m}.example"])
        farm = voices[2][0]
        self._switch(farm, False)
        off = self._discover()
        self.assertEqual(self._keys(off), [], "2 voices left: under the bar, by links and by stories")
        self.assertFalse([s for s in off["suggestions"] if f"Voice 2 {m}" in s.get("voice_names", ())])
        self.cur.execute("SELECT count(*) FROM story_posts sp JOIN posts p ON p.id = sp.post_id WHERE p.source_id = %s",
                         (farm,))
        self.assertEqual(self.cur.fetchone()[0], 2, "its posts keep their stories")
        self._switch(farm, True)
        self.assertEqual(sorted(self._keys(self._discover())), sorted(self._keys(on)))

    def test_four_voices_one_switched_off_still_suggest_without_it(self):
        m = self.mark
        voices = self._voices(4)
        for source, host in voices:
            insert_post(self.cur, source, f"https://{host}/p/x", at=NOW, normalized=f"https://{host}/p/x",
                        links=[f"https://wide-{m}.example/2026/11/story-{n}" for n in range(2)])
        self._switch(voices[3][0], False)
        [s] = [s for s in self._discover()["suggestions"] if s["key"] == f"wide-{m}.example"]
        self.assertEqual(s["voices"], 3)
        self.assertNotIn(f"Voice 3 {m}", s["voice_names"])
        self.assertFalse([a for a in s["articles"] if f"Voice 3 {m}" in a["linked_by"]])

    def test_no_archive_row_for_a_switched_off_source_and_its_site_is_still_followed(self):
        m = self.mark
        site = f"lab-{m}.example"
        research = insert_source(self.cur, f"Lab research {m}", handle=f"https://{site}/research")
        for n in range(3):
            insert_post(self.cur, research, f"https://{site}/research/paper-{n}", at=NOW,
                        normalized=f"https://{site}/research/paper-{n}")
        voices = self._voices(3)
        for n in range(3):
            self._cite(voices, f"https://{site}/news/model-{n}")
        self.assertEqual([a["source_id"] for a in self._discover()["archives"] if a["source_id"] == research], [research])
        self._switch(research, False)
        result = self._discover()
        self.assertFalse([a for a in result["archives"] if a["source_id"] == research])
        self.assertFalse([k for k in self._keys(result) if k.startswith(site)], "switched off, still not suggested")

    def test_a_page_two_voices_started_one_switched_off(self):
        m = self.mark
        voices = self._voices(2)
        page = f"https://paper-{m}.example/2026/11/a-result"
        self._cite(voices, page, days=1)
        self.assertIn(page, [p["url"] for p in self._discover()["pages"]])
        self._switch(voices[0][0], False)
        self.assertNotIn(page, [p["url"] for p in self._discover()["pages"]])


@requires_test_db
class Voices(unittest.TestCase):
    """The voices' suggestions as the page reads them: a switched-off source is in none, at once (the kept verdicts
    stay, so switching it on brings them back)."""

    def setUp(self):
        from insight_core.services.voices_service import VoicesService
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.mark = uuid.uuid4().hex[:8]

        @contextlib.contextmanager
        def mine():
            yield self.cur
        self.voices = VoicesService(db_url(), after_change=lambda *_: None, background=False, cursor=mine)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_a_same_channel_pair_with_a_switched_off_source_is_not_suggested(self):
        handle = f"quietchan{''.join(ch for ch in self.mark if ch.isalpha())}"
        native = insert_source(self.cur, "Quiet", platform="telegram", handle=handle, in_main_digest=True)
        bridge = insert_source(self.cur, "Quiet", platform="telegram", handle=f"https://tg.bridge.example/rss/{handle}",
                               in_main_digest=True)

        def pairs():
            return [g for g in self.voices.suggestions()["voices"] if {s["id"] for s in g["sources"]} == {native, bridge}]
        self.assertEqual(len(pairs()), 1)
        self.cur.execute("UPDATE sources SET enabled = false WHERE id = %s", (bridge,))
        self.assertEqual(pairs(), [])
        self.assertFalse([g for g in self.voices.suggestions()["voices"] if bridge in {s["id"] for s in g["sources"]}])
        self.cur.execute("UPDATE sources SET enabled = true WHERE id = %s", (bridge,))
        self.assertEqual(len(pairs()), 1)


if __name__ == "__main__":
    unittest.main()
