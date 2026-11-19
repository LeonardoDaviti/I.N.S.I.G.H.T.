"""A wanted voice Discover found and buried (issue 0235, backlog #32): @mentions are links, growth is in the score,
the worker judges the fastest growing suggestions every day, and a suggestion judged "follow" leads the list.

The case, synthetic: an account six of your sources started linking or @mentioning in the last 60 days, against 35
outlets each linked by 50 sources for months (and 2 new ones). Before: its score sat below every outlet's and nothing
judged it. Now: the daily planner judges it among its 15, and once judged "follow" it is on Discover's first page.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_stories import StoriesRepository
from insight_core.markx import source_judge
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import SCRATCH_PREFIX, db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils import discover_rules as R
from insight_core.utils.post_links import extract_links, mentions

ID = 1900000000000000101


class Mentions(unittest.TestCase):
    def test_an_account_named_in_the_text_is_its_address(self):
        text = ".@Poteto's talk is excellent, cc @mattpocock and @poteto again."
        self.assertEqual(mentions(text, "x"), ["https://x.com/poteto", "https://x.com/mattpocock"])

    def test_not_the_replys_leading_handles_nor_the_author(self):
        self.assertEqual(mentions("@kent @swyx agreed, and @lauren said so", "x", author="Me"), ["https://x.com/lauren"])
        self.assertEqual(mentions("@kent @swyx agreed", "x"), [])
        self.assertEqual(mentions("as I (@me) wrote", "x", author="me"), [])

    def test_never_inside_an_address_or_an_email(self):
        text = ("mail a@b.example, see medium.com/@writer/a-post and https://x.com/@nobody, "
                "@fedi@mastodon.social, @alice.bsky.social, @sixteen_chars_xx, (@paren)")
        self.assertEqual(mentions(text, "x"), ["https://x.com/paren"])

    def test_a_bluesky_handle_is_a_domain(self):
        self.assertEqual(mentions("@r @me.bsky.social hi @alice.bsky.social and @lab.example.com. a@b.example.com",
                                  "bluesky", author="me.bsky.social"),
                         ["https://bsky.app/profile/alice.bsky.social", "https://bsky.app/profile/lab.example.com"])

    def test_an_x_posts_mentions_are_links_of_kind_mention_after_its_links(self):
        html = (f'<p><a href="https://nitter.local/kent">@kent</a> yes. .<a href="https://nitter.local/poteto" '
                f'title="@poteto">@poteto</a>\'s talk <a href="https://blog.example/a-long-post-slug">here</a>, '
                f'and <a href="https://nitter.local/poteto/status/{ID}#m">this</a></p><br>@own @after')
        links = extract_links(html, f"https://nitter.local/own/status/{ID + 1}#m", "x")
        self.assertEqual([(l.url, l.kind) for l in links],
                         [("https://blog.example/a-long-post-slug", "link"), (f"https://x.com/poteto/status/{ID}", "link"),
                          ("https://x.com/poteto", "mention"), ("https://x.com/after", "mention")])
        self.assertEqual([l.position for l in links], [0, 1, 2, 3])
        self.assertEqual(links[2].text, "@poteto")

    def test_a_site_posts_handles_are_no_links(self):
        self.assertEqual(extract_links("<p>by @someone</p>", "https://blog.example/p", "site"), [])

    def test_a_bluesky_post_without_html_reads_its_text(self):
        links = extract_links(None, "https://bsky.app/profile/me.bsky.social/post/3kabc", "site",
                              "great thread by @alice.bsky.social")
        self.assertEqual([(l.url, l.kind) for l in links], [("https://bsky.app/profile/alice.bsky.social", "mention")])

    def test_discover_keys_a_mention_by_its_account(self):
        self.assertEqual(R.discover_address("https://x.com/poteto"), ("x.com/poteto", "x.com", True))
        self.assertEqual(R.discover_address("https://bsky.app/profile/alice.bsky.social"),
                         ("bsky.app/profile/alice.bsky.social", "bsky.app", True))
        self.assertTrue(R.discover_article("https://bsky.app/profile/alice.bsky.social/post/3kabc"))


class Growth(unittest.TestCase):
    def test_mostly_new_linkers_grow_an_old_outlet_does_not(self):
        voice = R.growth(new=4, old=2)
        outlet = R.growth(new=2, old=50)
        self.assertGreater(voice, 1.0)
        self.assertLess(outlet, 0.1)
        self.assertEqual(R.growth(new=0, old=9), 0.0)
        self.assertGreater(R.growth(new=6, old=0), R.growth(new=3, old=0))

    def test_the_score_adds_it(self):
        base = dict(origins=0, classics=0, opened=0, voices=6, days=3)
        self.assertAlmostEqual(R.score(**base, grown=1.0) - R.score(**base), R.GROWTH_WEIGHT)

    def test_judged_follow_leads_every_section_but_the_unfollowable(self):
        rows = [{"key": "tested.example", "score": 9.0, "voices": 9, "follow_test": {"label": "feed"}},
                {"key": "x.com/voice", "score": 2.0, "voices": 6, "fit": "follow"},
                {"key": "walled.example", "score": 3.0, "voices": 4, "fit": "follow", "follow_test": {"label": "blocked"}},
                {"key": "untested.example", "score": 8.0, "voices": 5}]
        self.assertEqual([r["key"] for r in R.order(rows)],
                         ["x.com/voice", "tested.example", "walled.example", "untested.example"])

    def test_the_daily_pick_is_the_fastest_growing_not_judged(self):
        rows = [{"key": f"outlet{k}.example", "growth": 0.04, "score": 5.0 + k / 10} for k in range(30)]
        rows += [{"key": "x.com/voice", "growth": 1.07, "score": 4.5},
                 {"key": "judged.example", "growth": 3.0, "score": 1.0},
                 {"key": "walled.example", "growth": 3.0, "score": 1.0, "follow_test": {"label": "blocked"}}]
        got = source_judge.to_judge(rows, {"judged.example"}, 15)
        self.assertEqual(got[0], "x.com/voice")
        self.assertEqual(len(got), 15)
        self.assertNotIn("walled.example", got)
        self.assertEqual(got[1], "outlet29.example", "then by score")

    def test_the_reference_suggests_a_mentioned_account_by_its_voices(self):
        links = [(f"v{k}", "https://x.com/named", False) for k in range(3)]
        links += [("v0", "https://x.com/twice", False), ("v1", "https://x.com/twice", False)]
        found = {s.key for s in R.suggestions(links, followed=set(), hidden=set(),
                                              mentioned={"https://x.com/named", "https://x.com/twice"})}
        self.assertEqual(found, {"x.com/named"})
        self.assertEqual(R.suggestions(links, followed=set(), hidden=set()), [], "not mentioned: no article, no key")


@requires_test_db
class TheCase(unittest.TestCase):
    """The case on the test database: the planner and Discover's order, end to end (the worker's read mocked)."""

    OUTLETS = 35

    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.now = datetime.now(timezone.utc)
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self._clean)
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM system_settings WHERE key IN ('discover_counts', 'discover_list', 'discover_served')")
        self.conn.commit()

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM mx_source_judgements WHERE key LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM system_settings WHERE key IN ('discover_counts', 'discover_list', 'discover_served')")
        self.conn.commit()
        self.conn.close()

    def _post(self, source, k, links, *, days, mention=None):
        host = f"s{k}-{self.mark}.example"
        url = f"https://{host}/p/{uuid.uuid4().hex}"
        post = insert_post(self.cur, source, url, host=host, normalized=url, links=links,
                           at=self.now - timedelta(days=days))
        if mention:
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, kind, boilerplate) "
                             "VALUES (%s, %s, 'x.com', %s, 'mention', true)", (post, mention, len(links)))
        return post

    def _case(self):
        m = self.mark
        sources = [insert_source(self.cur, f"Voice {k} {m}") for k in range(58)]
        outlets = [[f"https://outlet{o}-{m}.example/2026/0{1 + a}/a-story-{a}" for a in range(2)]
                   for o in range(self.OUTLETS)]
        every = [u for pair in outlets for u in pair]
        for k in range(50):                   # 50 sources linking every outlet for months
            self._post(sources[k], k, every, days=200 - k)
        for k in (50, 51):                    # 2 new ones this week
            self._post(sources[k], k, every, days=2)
        self.voice = f"x.com/poteto{m}"
        tweet = lambda n: f"https://x.com/poteto{m}/status/{ID + n}"   # noqa: E731
        # six sources, all in the last 60 days: three link her posts, three @mention her
        for n, (k, days) in enumerate(((52, 10), (53, 20), (54, 45))):
            self._post(sources[k], k, [tweet(n), tweet(n + 10)], days=days)
        for k, days in ((55, 5), (56, 25), (57, 55)):
            self._post(sources[k], k, [], days=days, mention=f"https://x.com/poteto{m}")
        self.conn.commit()

    def _first_page(self):
        stories = StoriesService(db_url())
        stories.refresh()
        return [s["key"] for s in stories.discover_served(offset=0, limit=R.FIRST_PAGE)["suggestions"]]

    def test_judged_within_the_days_fifteen_and_on_the_first_page_once_judged_follow(self):
        self._case()
        listed = {s["key"]: s for s in StoriesService(db_url()).discover()["suggestions"]}
        her = listed[self.voice]
        self.assertEqual(her["voices"], 6, "her tweets' linkers and her mentioners, one voice each")
        outlets = [s for k, s in listed.items() if k.startswith("outlet")]
        self.assertEqual(len(outlets), self.OUTLETS)
        self.assertLess(her["score"], min(s["score"] for s in outlets), "by volume she stays below every outlet")
        self.assertGreater(her["growth"], max(s["growth"] for s in outlets))
        self.assertNotIn(self.voice, self._first_page(), "before a judgement: not on the first page")

        async def no_read(db, jid, **kw):
            return {"id": jid, "claimed": True}
        with mock.patch.object(source_judge, "read_and_ask", side_effect=no_read):
            asked = [source_judge.daily(db_url(), self.now) for _ in range(4)]   # the day's passes
        self.assertEqual(asked, [5, 5, 5, 0], "JUDGE_PASS a pass, JUDGE_DAILY a day")
        self.cur.execute("SELECT key FROM mx_source_judgements WHERE asked_by = 'daily' AND key LIKE %s "
                         "ORDER BY asked_at, key", (f"%{self.mark}%",))
        judged = [r[0] for r in self.cur.fetchall()]
        self.assertEqual(len(judged), source_judge.JUDGE_DAILY)
        self.assertIn(self.voice, judged)
        self.assertEqual(source_judge.to_judge(list(listed.values()), [], 1), [self.voice], "picked first")

        self.cur.execute("""UPDATE mx_source_judgements SET status = 'answered', verdict = 'follow',
                                   answer = '{"verdict": "follow", "fits": true}'::jsonb, answered_at = now()
                             WHERE key = %s""", (self.voice,))
        self.conn.commit()
        page = self._first_page()
        self.assertEqual(page[0], self.voice, "judged follow: first, though untested and low by volume")

    def test_tomorrow_it_is_not_asked_again(self):
        self._case()
        StoriesService(db_url()).discover()

        async def no_read(db, jid, **kw):
            return {"id": jid, "claimed": True}
        with mock.patch.object(source_judge, "read_and_ask", side_effect=no_read):
            for _ in range(3):
                source_judge.daily(db_url(), self.now)
            later = [source_judge.daily(db_url(), self.now + timedelta(days=1, minutes=k)) for k in range(4)]
        self.assertEqual(later, [5, 5, 5, 0])
        self.cur.execute("SELECT key, count(*) FROM mx_source_judgements WHERE key LIKE %s GROUP BY key HAVING count(*) > 1",
                         (f"%{self.mark}%",))
        self.assertEqual(self.cur.fetchall(), [], "a key judged within CACHE_DAYS is never picked again")


@requires_test_db
class Backfill(unittest.TestCase):
    """0235's resumable backfill (StoriesRepository.fill_mentions): stored X posts gain their mentions."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM system_settings WHERE key = %s", (StoriesRepository.MENTIONS_KEY,))
        self.conn.commit()
        self.addCleanup(self._clean)

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM system_settings WHERE key = %s", (StoriesRepository.MENTIONS_KEY,))
        self.conn.commit()
        self.conn.close()

    def test_a_batch_at_a_time_and_done(self):
        x = insert_source(self.cur, "An X account", handle=SCRATCH_PREFIX + "nitter-own/rss")
        site = insert_source(self.cur, "A blog")
        posts = []
        for n in range(3):
            html = f'<p>.<a href="https://nitter.local/voice{n}">@voice{n}</a> said <a href="https://blog.example/a-b-c-d">so</a></p>'
            posts.append(insert_post(self.cur, x, f"https://nitter.local/own/status/{ID + n}#m", html=html,
                                     links=["https://blog.example/a-b-c-d"]))
        insert_post(self.cur, site, "https://blog.example/p/1", html="<p>by @someone</p>", links=[])
        self.conn.commit()
        repo = StoriesRepository()
        with self.conn.transaction():
            self.assertEqual(repo.fill_mentions(self.cur, limit=2), 2)
        with self.conn.transaction():
            self.assertEqual(repo.fill_mentions(self.cur, limit=2), 1)
            self.assertFalse(StoriesRepository.mentions_left(self.cur))
        with self.conn.transaction():
            self.assertEqual(repo.fill_mentions(self.cur, limit=2), 0)
        self.cur.execute("SELECT target_url, kind, boilerplate FROM post_links WHERE post_id = ANY(%s) ORDER BY 1",
                         ([str(p) for p in posts],))
        rows = self.cur.fetchall()
        self.assertEqual(sorted(r for r in rows if r[1] == "mention"),
                         [(f"https://x.com/voice{n}", "mention", True) for n in range(3)])
        self.assertEqual([r for r in rows if r[1] == "link"], [("https://blog.example/a-b-c-d", "link", False)] * 3)

    def test_the_signature_pass_keeps_a_mention_boilerplate(self):
        x = insert_source(self.cur, "An X account", handle=SCRATCH_PREFIX + "nitter-own/rss")
        for n in range(6):   # the same mention in every post: a signature's share, still a mention
            p = insert_post(self.cur, x, f"https://nitter.local/own/status/{ID + n}#m", links=[])
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, kind, boilerplate) "
                             "VALUES (%s, 'https://x.com/cohost', 'x.com', 0, 'mention', true)", (p,))
        self.conn.commit()
        from insight_core.db.repo_stories import SourceFacts
        with self.conn.transaction():
            StoriesRepository.mark_boilerplate(self.cur, SourceFacts(self.cur), [x])
        self.cur.execute("SELECT DISTINCT boilerplate FROM post_links pl JOIN posts p ON p.id = pl.post_id "
                         "WHERE p.source_id = %s", (x,))
        self.assertEqual(self.cur.fetchall(), [(True,)])


if __name__ == "__main__":
    unittest.main()
