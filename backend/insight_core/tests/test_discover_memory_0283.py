"""Discover's job reads less (0283): the platform rule streamed a host at a time, the reads' first page taken from a
projection of the served answer, and the kept counts read without their found rows where the recount never uses
them. Each answer is the one the whole reads gave.
"""
from __future__ import annotations

import random
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db import repo_discover as RD
from insight_core.db.repo_discover import KEPT_KEY, SERVED_KEY, DiscoverRepository
from insight_core.db.repo_stories import SourceFacts
from insight_core.services import discover_reads
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils.discover_rules import FIRST_PAGE, find_platforms, host_platform, platform_rows
from insight_core.utils.url_normalization import TWEET_SHAPE

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def _links(m: str):
    """(voice, address) links: a hub whose 20 owners 4 voices link (a platform), one whose owners sit under /profile/
    (a platform under a prefix), and a site whose pages are dated (no owners)."""
    out = []
    for v in range(4):
        for k in range(20):
            out.append((f"site:v{v}", f"https://hub-{m}.example/user{k}/post-{v}"))
            out.append((f"site:v{v}", f"https://prefixed-{m}.example/profile/user{k}/post/{v}"))
        out.append((f"site:v{v}", f"https://plain-{m}.example/2026/10/story-{v}"))
    return out


class HostAtATime(unittest.TestCase):
    def test_find_platforms_is_host_platform_a_host_in_any_row_order(self):
        rows = platform_rows(_links("x"))
        random.Random(7).shuffle(rows)
        by_host = {}
        for host, segs, n, voices in rows:
            by_host.setdefault(host, []).append((segs, n, voices))
        one_at_a_time = {h: p for h, p in ((h, host_platform(r)) for h, r in sorted(by_host.items())) if p is not None}
        self.assertEqual(find_platforms(rows), one_at_a_time)
        self.assertEqual(one_at_a_time, {"hub-x.example": (), "prefixed-x.example": ("profile",)})

    def test_a_host_under_the_voices_bar_is_none(self):
        self.assertIsNone(host_platform([(("ann", "*"), 3, {"site:a"}), (("bob", "*"), 3, {"site:b"})]))


def _by_key(found):
    """Found rows compared as test_discover_clean compares them (lists in no set order sorted)."""
    return {s["key"]: {**s, "voices": sorted(map(tuple, s["voices"])), "roundups": sorted(s["roundups"]),
                       "sources": sorted(map(tuple, s["sources"])), "classics": sorted(s["classics"]),
                       "articles": [(a[0], sorted(a[1]), *a[2:]) for a in s["articles"]]} for s in found}


@requires_test_db
class StoredReads(unittest.TestCase):
    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT value FROM system_settings WHERE key = %s", (SERVED_KEY,))
        row = self.cur.fetchone()
        self.served = row[0] if row else None
        self.addCleanup(self._clean)

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM mx_source_judgements WHERE key LIKE %s", (f"%{self.mark}%",))
        if self.served is None:
            self.cur.execute("DELETE FROM system_settings WHERE key = %s", (SERVED_KEY,))
        else:
            DiscoverRepository.keep_served(self.cur, self.served["made_from"], self.served["built_at"],
                                           self.served["answer"])
        self.conn.commit()
        self.conn.close()

    # ---- the platform rule, streamed ------------------------------------------------------

    def test_platforms_streamed_are_the_whole_reads(self):
        m = self.mark
        for v in range(4):
            source = insert_source(self.cur, f"Voice {v} {m}")
            host = f"voice{v}-{m}.example"
            url = f"https://{host}/p/{uuid.uuid4().hex}"
            insert_post(self.cur, source, url, host=host, normalized=url,
                        links=[u for voice, u in _links(m) if voice == f"site:v{v}"])
        self.conn.commit()
        sf = SourceFacts(self.cur)
        own = {i: sf.publication(i) for i in sf.kind}
        selves = {i: sorted(sf.selves(i)) for i in sf.kind}
        streamed = DiscoverRepository.platforms(self.cur, kinds=sf.kind, own_sites=own, selves=selves)
        ids = sorted(sf.kind)
        self.cur.execute(RD._PLATFORMS, {"ids": ids, "kinds": [sf.kind[i] for i in ids],
                                         "sites": [own.get(i, "") for i in ids],
                                         "selves": [" ".join(sorted(selves.get(i, ()))) for i in ids],
                                         "tweet": TWEET_SHAPE, "depth": RD.OWNER_DEPTH,
                                         "listed": sorted(RD.DISCOVER_PLATFORMS),
                                         "under": ["%." + h for h in sorted(RD.DISCOVER_PLATFORMS)],
                                         "min_voices": RD.DISCOVER_MIN_VOICES})
        whole = find_platforms((h, tuple(s), n, v) for h, s, n, v in self.cur.fetchall())
        self.assertEqual(streamed, whole)
        self.assertEqual(streamed.get(f"hub-{m}.example"), ())
        self.assertEqual(streamed.get(f"prefixed-{m}.example"), ("profile",))
        self.assertNotIn(f"plain-{m}.example", streamed)

    # ---- the reads' first page, projected ---------------------------------------------------

    def _serve(self, n=FIRST_PAGE * 3):
        """A served answer of `n` rows (scores not in list order, so to_read's by-score rows lie past the first page),
        one row judged "follow" by the worker so `_by_fit` moves it, archives and an apart row."""
        m = self.mark
        rows = [{"key": f"s{k:03d}-{m}.example", "url": f"https://s{k:03d}-{m}.example", "voices": 3,
                 "score": round((k * 37 % n) / 10, 1), "articles": [{"url": f"https://s{k:03d}-{m}.example/a", "title": None}],
                 "origin_stories": [{"url": f"https://s{k:03d}-{m}.example/o", "title": "Told"}], "big": "x" * 200}
                for k in range(n)]
        moved = rows[n - 1]["key"]
        self.cur.execute("""INSERT INTO mx_source_judgements (key, address, asked_at, status, verdict, answer)
                            VALUES (%s, %s, now(), 'answered', 'follow', '{"fits": true}')""",
                         (moved, "https://" + moved))
        archives = [{"source_id": str(uuid.uuid4()), "name": "Arch", "pages": [f"https://arch-{m}.example/p"],
                     "origin_stories": [{"url": f"https://arch-{m}.example/p", "title": None}]}]
        answer = {"success": True, "suggestions": rows, "archives": archives, "also": [], "built_at": NOW.isoformat(),
                  "apart": {"quiet": {"total": 1, "rows": [{"key": f"quiet-{m}.example", "score": 1, "articles": []}]}}}
        DiscoverRepository.keep_served(self.cur, "test", NOW.isoformat(), answer)
        self.conn.commit()
        return answer, moved

    def _old_kept(self, stories):
        """HEAD's discover_kept: the whole served answer, paged."""
        return stories._page(DiscoverRepository.served(self.cur)["answer"])

    def test_the_first_page_and_work_are_the_whole_answers(self):
        answer, moved = self._serve()
        stories = StoriesService(db_url())
        stories.clock = lambda: NOW
        with mock.patch.object(DiscoverRepository, "archive_states", return_value={}):
            old = self._old_kept(stories)
            new = stories.discover_kept()
        self.assertEqual([s["key"] for s in new["suggestions"]], [s["key"] for s in old["suggestions"]], "_by_fit's order")
        self.assertEqual(new["suggestions"][0]["key"], moved, "the worker's follow leads")
        page_old, page_new = discover_reads.to_read(old), discover_reads.to_read(new)
        self.assertEqual([s["key"] for s in page_new], [s["key"] for s in page_old])
        self.assertGreater(len(page_new), FIRST_PAGE, "by-score rows past the first page")
        for got, was in zip(page_new, page_old):
            self.assertEqual({k: got[k] for k in was}, was, "a row the reads take is read whole")
        read = {s["key"] for s in page_new}
        rest = [s for s in new["suggestions"] if s["key"] not in read]
        self.assertTrue(rest and all("articles" not in s and "big" not in s for s in rest), "the others only outlined")
        self.assertEqual(new["archives"], old["archives"])
        reads = {"follow": {s["key"]: {"label": "feed", "at": "2020-01-01T00:00:00+00:00", "test": 1}
                            for s in answer["suggestions"][::5]}, "titles": {}}
        listed = lambda a: a["suggestions"][FIRST_PAGE:] + [s for g in a["apart"].values() for s in g["rows"]]
        self.assertEqual(discover_reads.work(page_new, reads, NOW, archives=new["archives"], listed=listed(new)),
                         discover_reads.work(page_old, reads, NOW, archives=old["archives"], listed=listed(old)))

    def test_an_answer_rebuilt_between_the_reads_is_read_again(self):
        self._serve()
        self.assertIsNone(DiscoverRepository.served_rows(self.cur, "an older build", [0]))
        self.assertEqual(DiscoverRepository.served_rows(self.cur, NOW.isoformat(), []), {})

    def test_before_the_first_build_the_list_is_made(self):
        self.cur.execute("DELETE FROM system_settings WHERE key = %s", (SERVED_KEY,))
        self.conn.commit()
        stories = StoriesService(db_url())
        with mock.patch.object(StoriesService, "discover", return_value={"suggestions": []}) as made:
            self.assertEqual(stories.discover_kept(), {"suggestions": []})
        made.assert_called_once()

    # ---- the kept counts, without their found rows ---------------------------------------------

    def test_the_kept_counts_without_found_are_the_rest(self):
        self.cur.execute("SELECT value FROM system_settings WHERE key = %s", (KEPT_KEY,))
        row = self.cur.fetchone()
        if row is None:
            self.skipTest("no kept counts on this database")
        whole = row[0]
        self.assertEqual(DiscoverRepository.kept(self.cur, found=False), {k: v for k, v in whole.items() if k != "found"})
        self.assertEqual(DiscoverRepository.kept_found(self.cur), whole["found"])
        self.assertEqual(DiscoverRepository.kept(self.cur), whole)

    def test_a_recount_never_reads_the_found_rows_and_a_reuse_returns_them(self):
        sf = SourceFacts(self.cur)
        StoriesService._counted(self.cur, sf)   # counted and kept
        self.conn.commit()
        whole = DiscoverRepository.kept(self.cur)
        reused = StoriesService._counted(self.cur, sf, keep=False)
        self.assertEqual(reused["found"], whole["found"], "the kept counts as they were")
        stamp = DiscoverRepository.stamp
        with mock.patch.object(DiscoverRepository, "kept_found", side_effect=AssertionError("found read")), \
                mock.patch.object(DiscoverRepository, "stamp", side_effect=lambda cur, facts: "moved-" + stamp(cur, facts)):
            recounted = StoriesService._counted(self.cur, sf, keep=False)
        self.assertEqual(_by_key(recounted["found"]), _by_key(whole["found"]), "a recount finds what was kept")
        self.conn.rollback()


if __name__ == "__main__":
    unittest.main()
