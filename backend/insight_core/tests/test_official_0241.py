"""Issue 0241 (Stealth v10.26, 0237 #4): official channels that work as expected. The company's news section (one rule,
discover_main_source.announcing), its site's news section as a candidate, a section proven by its path or its stream
(never by the event's page under it), the review view paged with what waits first, and an X account the bridge could
not read read again, never "gone". Invented names only."""
from __future__ import annotations

import json
import os
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import official as O
from insight_core.services import discover_main_source as D
from insight_core.tests._db import db_url
from insight_core.tests.test_official_0196 import FOLLOW, FakeReader, World, items

DAY = timedelta(days=1)


def event(pages=(), *, actor_name="Acme"):
    return D.Event(story="s1", headline="Acme ships Widget 5", event_type="model_release", voices=3, first_at=None,
                   actor="", actor_name=actor_name, pages=[D.OwnPage(u, "linked") for u in pages],
                   member_sources=set(), actor_sources=set(), posts=[])


def sections(table):
    def of(site):
        return [(O.channel(u), D.announcing(O.channel(u).address), n) for u, n in table.get(site, [])]
    return of


class TheNewsSection(unittest.TestCase):
    def test_a_section_announces_by_its_host_or_path_never_a_product_page(self):
        N, I, Z = D.NEWSROOM, D.INVESTORS, D.NOTHING
        cases = {
            "https://acme.example/blog": N, "https://acme.example/en/newsroom": N, "https://newsroom.acme.example/": N,
            "https://acme.example/news-events": N, "https://acme.example/newsevents": N,
            "https://blog.acme.example/p": N, "https://acme.example/press-releases": N,
            "https://ir.acme.example/news-events": I, "https://acme.example/investors/news": I,
            "https://acme.example/plans": Z, "https://studio.acme.example/prompts": Z,
            "https://acme.example/solutions": Z, "https://guides.acme.example/guides": Z,
            "https://family.acme.example/resources": Z, "https://acme.example/us/phones": Z,
            "https://acme.example/investor": Z,
        }
        for url, want in cases.items():
            self.assertEqual(D.announcing(url), want, url)
        self.assertGreater(D.announcing("https://newsroom.acme.example/"), D.announcing("https://ir.acme.example/news"))

    def test_a_quiet_path_announces_by_its_stream_not_by_the_events_page(self):
        # the read resolved a press feed, or most of its dated items sit in a news section, or a feed of its own posts
        self.assertTrue(D.announcing("https://acme.example/about", address="https://acme.example/about/newsroom"))
        self.assertTrue(D.announcing("https://acme.example/directorates", address="https://acme.example/feed/",
                                     items=["https://acme.example/news/a", "https://acme.example/news/b",
                                            "https://acme.example/missions/c/d"]))
        self.assertTrue(D.announcing("https://acme.example/p", via="feed",
                                     items=["https://acme.example/p/one", "https://acme.example/p/two"]))
        # a watched product page's own items, dated or not, announce nothing
        self.assertFalse(D.announcing("https://acme.example/phones", via="page",
                                      items=["https://acme.example/phones/a", "https://acme.example/phones/b"]))
        self.assertFalse(D.announcing("https://acme.example/plans", address="https://acme.example/plans",
                                      items=["https://acme.example/plans/pro"]))

    def test_the_root_of_an_announcing_host_is_a_section(self):
        self.assertEqual(O.channel("https://newsroom.acme.example/2026-11-04-widget-5").key, "newsroom.acme.example/")
        self.assertIsNone(O.channel("https://acme.example/widget-5"))


class Candidates(unittest.TestCase):
    TABLE = {"acme.example": [("https://newsroom.acme.example/2026-widget-5", 9),
                              ("https://ir.acme.example/news-events/press/1", 4)]}

    def test_the_sites_newsroom_replaces_a_plans_page_the_events_page_sits_under(self):
        cands, refused = O.candidates(event(["https://acme.example/plans/pro"]),
                                      site_sections=sections(self.TABLE))
        self.assertEqual([(c.chan.key, c.origin) for c in cands], [("newsroom.acme.example/", "site_section")])
        self.assertIn("news section newsroom.acme.example/", refused[0]["why"])

    def test_the_newsroom_beats_the_investor_relations_section(self):
        lookup = {"actor": {"name": "Acme", "site": "https://acme.example"}, "official": True,
                  "channels": [{"url": "https://ir.acme.example/news-events/press-releases", "why": "its IR news"}]}
        cands, _ = O.candidates(event(), lookup=lookup, site_sections=sections(self.TABLE))
        self.assertEqual([c.chan.key for c in cands], ["newsroom.acme.example/"])

    def test_a_quiet_section_with_no_news_section_beside_it_stays_and_a_third_partys_site_is_never_taken(self):
        cands, _ = O.candidates(event(["https://acme.example/plans/pro"]), site_sections=sections({}))
        self.assertEqual([c.chan.key for c in cands], ["acme.example/plans/"])
        # an own page on a store's site: the store's newsroom is not the actor's
        table = {"store.example": [("https://store.example/news/a-sale", 9)]}
        ev = event(["https://store.example/apps/acme-widget"])
        cands, _ = O.candidates(ev, site_sections=sections(table))
        self.assertNotIn("store.example/news/", [c.chan.key for c in cands])


class Proof(unittest.TestCase):
    def row(self, follow, kind="section", **ev):
        return {"key": follow.split("://")[1] + "/", "kind": kind, "follow": follow, "evidence": ev,
                "page_watch": {"prefix": "/" + follow.rsplit("/", 1)[-1] + "/"}}

    def j(self, urls, *, address, via="page", status="asked", reason=None):
        now = datetime.now(timezone.utc)
        return {"status": status, "reason": reason, "resolved": {"handle_or_url": address, "via": via},
                "items": [{"url": u, "published_at": (now - n * DAY).isoformat()} for n, u in enumerate(urls)],
                "signals": {"rate": {"dated": len(urls)}}}

    def test_the_events_page_in_a_quiet_sections_read_is_no_proof(self):
        page = "https://acme.example/phones/widget-5"
        row = self.row("https://acme.example/phones", pages=[page])
        no, proof = O._proof(row, self.j([page, "https://acme.example/phones/a", "https://acme.example/phones/b"],
                                         address="https://acme.example/phones"))
        self.assertIn("no announcements", no)
        self.assertEqual((proof["holds"], proof["announces"]), (1, None))

    def test_a_path_or_a_stream_that_announces_proves_it(self):
        news = ["https://acme.example/blog/a", "https://acme.example/blog/b", "https://acme.example/blog/c"]
        no, proof = O._proof(self.row("https://acme.example/blog"), self.j(news, address="https://acme.example/blog"))
        self.assertEqual((no, proof["announces"]), (None, "path"))
        no, proof = O._proof(self.row("https://acme.example/about"),
                             self.j(news, address="https://acme.example/about/newsroom"))
        self.assertEqual((no, proof["announces"]), (None, "stream"))

    def test_an_account_the_bridge_could_not_read_is_read_again_never_gone(self):
        row = self.row("https://x.com/acme", kind="x")
        no, proof = O._proof(row, self.j([], address=None, status="unreadable", reason="gone"))
        self.assertTrue(no.startswith("not read: the bridge could not read it"), no)
        self.assertNotIn("no dated stream", no)
        self.assertEqual((proof["retry"], proof["tries"]), (True, 1))
        row["evidence"] = {"proof": {"tries": O.RETRIES}}
        no, proof = O._proof(row, self.j([], address=None, status="unreadable", reason="gone"))
        self.assertNotIn("retry", proof)


class TheBridge(unittest.TestCase):
    """An X or Telegram account's test read goes through the bridge the add path uses (feed_finder.bridge_feed), not
    a fixed nitter.local: the server's NITTER_HOSTS names its own."""

    def test_the_configured_nitter_is_read(self):
        from insight_core.ingestion.kinds import KindRegistry, nitter_rss
        from insight_core.services import discover_reads
        from insight_core.tests.test_discover_reads import FakeHttp
        registry = KindRegistry.default(FakeHttp({}), None)
        with mock.patch.dict(os.environ, {"NITTER_HOSTS": "bridge.example"}), \
                mock.patch.object(nitter_rss, "NITTER_HOSTS", frozenset({"nitter.local", "bridge.example"})):
            got = discover_reads.kind_source("x.com/acme", registry)
            self.assertEqual(got["handle_or_url"], "https://bridge.example/acme/rss")
        with mock.patch.dict(os.environ, {"NITTER_HOSTS": ""}):
            self.assertIsNone(discover_reads.kind_source("x.com/acme", registry))


class ThePassAndTheView(World):
    def test_the_sites_newsroom_is_the_candidate_not_the_plans_page(self):
        plans = "https://acme.example/plans/pro"
        self.event(links=[plans], voices=3)
        for n in range(2):
            self.post(title=f"Elsewhere {n}", links=[(f"https://newsroom.acme.example/2026-widget-{n}", "here")])
        self.cur.execute("UPDATE post_links SET target_site = 'acme.example' WHERE target_url LIKE '%%acme.example%%'")
        counts = self.plan()
        self.assertEqual([r[:2] for r in self.channels()], [("newsroom.acme.example/", "candidate")], counts)
        self.cur.execute("SELECT evidence FROM mx_official_channels WHERE superseded_at IS NULL")
        self.assertEqual(self.cur.fetchone()[0]["from"], "site_section")

    def test_the_view_pages_what_waits_first_with_counts(self):
        with self.conn.transaction():
            for n in range(3):
                O.put(self.cur, f"acme{n}.example/blog/", "section", "refused", why="no")
            O.put(self.cur, "x.com/acme", "x", "would_add", why="Shadow: would be added")
            O.put(self.cur, "acme.example/news/", "section", "candidate", why="found")
            O.put(self.cur, "github.com/acme/widget", "releases", "added", why="added")
        got = O.view(self.cur, limit=2)
        self.assertEqual([r["state"] for r in got["rows"]], ["would_add", "added"])
        self.assertEqual((got["total"], got["counts"]["refused"], got["offset"], got["limit"]), (6, 3, 0, 2))
        got = O.view(self.cur, offset=2, limit=2)
        self.assertEqual([r["state"] for r in got["rows"]], ["candidate", "refused"])
        got = O.view(self.cur, states=["refused"], offset=1, limit=5)
        self.assertEqual((len(got["rows"]), got["total"]), (2, 3))

    def test_an_account_the_bridge_failed_on_is_read_again_after_retry_days(self):
        with self.conn.transaction():
            cid = O.put(self.cur, "x.com/acme", "x", "refused", why="no dated stream: gone", follow="https://x.com/acme",
                        evidence={"from": "web_search"})
            self.cur.execute("UPDATE mx_official_channels SET decided_at = now() - interval '4 days' WHERE id = %s",
                             (cid,))
        reader = FakeReader(items(["https://x.com/acme/status/1", "https://x.com/acme/status/2"]), via="kind")
        O.advance(db_url(), datetime.now(timezone.utc), Counter(), reader=reader)
        self.assertEqual([r[1] for r in self.channels()], ["candidate"])
        self.assertEqual(reader.asked, ["https://x.com/acme"])

    def test_rows_refused_before_the_v1026_rules_are_read_again_once(self):
        from insight_core.markx import repo
        with self.conn.transaction():
            self.cur.execute("DELETE FROM mx_settings WHERE key = %s", (O.REREAD_MARK,))
            old = O.put(self.cur, "acme.example/newsroom/", "section", "refused", why="no dated stream: none found",
                        follow="https://acme.example/newsroom")
            self.cur.execute("UPDATE mx_official_channels SET decided_at = now() - interval '1 day' WHERE id = %s",
                             (old,))
        reader = FakeReader(items(["https://acme.example/newsroom/a", "https://acme.example/newsroom/b",
                                   "https://acme.example/newsroom/c"]))
        O.advance(db_url(), datetime.now(timezone.utc), Counter(), reader=reader)
        self.assertEqual(self.channels(), [("acme.example/newsroom/", "candidate", O.REREAD_WHY)])
        self.assertEqual(reader.asked, ["https://acme.example/newsroom"])
        self.assertIsNotNone(repo.get_setting(self.cur, O.REREAD_MARK))
        # refused again after the mark: never read again by it
        with self.conn.transaction():
            row = O.current(self.cur, "acme.example/newsroom/")
            O.put(self.cur, row["key"], "section", "refused", why="no dated stream: 0 dated items read", before=row)
        O.advance(db_url(), datetime.now(timezone.utc), Counter(), reader=reader)
        self.assertEqual([r[1] for r in self.channels()], ["refused"])


if __name__ == "__main__":
    unittest.main()
