"""Discussions (0280): a thread's address and its two hosts' answers read and capped, the fetch schedule, the
discussion-v1 checks, the jobs pass (want, plan, fetch, keep, ask), the post page's view and News rows' counts; and
the byline of an aggregator's page (its site, "via Hacker News") with the thread linked in the post page's header.
Synthetic data only; the DB tests run on a _test database."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from insight_core.ingestion import discussions as D
from insight_core.ingestion.gates import HostLimiter
from insight_core.markx import discussions as MD, jobs, repo, schemas, validate
from insight_core.tests._db import db_url, insert_scratch_source
from insight_core.tests.test_markx_api import _Api, call
from insight_core.utils import byline

T0 = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)


def hn_tree(n_top=3, replies=2, story=50557661):
    """An Algolia item: n_top top-level comments, each with `replies` replies, one reply with a reply of its own; one
    deleted comment (no author) whose reply stays."""
    kids, cid = [], story
    for i in range(n_top):
        cid += 1
        top = {"id": cid, "type": "comment", "author": f"user{i}", "created_at_i": T0.timestamp() + i * 60,
               "text": f"<p>Top comment {i} says zram works.<p>See <a href=\"https:&#x2F;&#x2F;example.org&#x2F;z{i}\">"
                       f"this</a> &amp; more.", "children": []}
        for j in range(replies):
            cid += 1
            r = {"id": cid, "type": "comment", "author": f"reply{i}{j}", "created_at_i": T0.timestamp() + 600 + j,
                 "text": f"Reply {j} to {i}.", "children": []}
            if j == 1:
                cid += 1
                r["children"].append({"id": cid, "type": "comment", "author": "deep", "text": "Deep one.",
                                      "created_at_i": T0.timestamp() + 900, "children": []})
            top["children"].append(r)
        kids.append(top)
    cid += 1
    kids.append({"id": cid, "type": "comment", "author": None, "text": None, "children": [
        {"id": cid + 1, "type": "comment", "author": "orphan", "text": "Still here.", "children": []}]})
    tree = {"id": story, "type": "story", "title": "Do not buy RAM, compress", "created_at_i": T0.timestamp(),
            "points": 341, "children": kids}
    order = {"id": story, "descendants": 99, "kids": [k["id"] for k in reversed(kids)]}   # the site ranks the last first
    return tree, order


class Addresses(unittest.TestCase):
    def test_threads_are_told_from_their_addresses(self):
        self.assertEqual(D.thread_of("https://news.ycombinator.com/item?id=50557661"),
                         D.Thread("hn", "50557661", "https://news.ycombinator.com/item?id=50557661"))
        self.assertEqual(D.thread_of("https://lobste.rs/s/vldbcn/signal_is_serious").url, "https://lobste.rs/s/vldbcn")
        for no in (None, "", "https://news.ycombinator.com/user?id=pg", "https://news.ycombinator.com/item?id=abc",
                   "https://example.com/item?id=1", "https://lobste.rs/t/rust", "https://reddit.com/r/x/comments/1"):
            self.assertIsNone(D.thread_of(no), no)
        # a feed's comments address first; the post itself when it is a thread; a blog's own comments page is none
        self.assertEqual(D.post_thread("https://curiousbits.nl/x", {"comments_url": "https://news.ycombinator.com/item?id=7"}).id, "7")
        self.assertEqual(D.post_thread("https://news.ycombinator.com/item?id=8", {}).id, "8")
        self.assertIsNone(D.post_thread("https://antirez.com/news/1", {"comments_url": "https://antirez.com/news/1#c"}))
        self.assertEqual(D.requests(D.thread_of("https://news.ycombinator.com/item?id=7")),
                         ["https://hn.algolia.com/api/v1/items/7", "https://hacker-news.firebaseio.com/v0/item/7.json"])

    def test_html_is_read_once_links_kept_apart(self):
        text, links = D.plain('<p>One &amp; two<p>See <a href="https:&#x2F;&#x2F;x.org&#x2F;a" rel="nofollow">x.org/a</a>'
                              '<pre><code>  zramctl\n</code></pre>')
        self.assertEqual(text, "One & two\nSee x.org/a\nzramctl")
        self.assertEqual(links, ["https://x.org/a"])


class Parsing(unittest.TestCase):
    def test_hn_tree_ranked_by_the_site_deleted_comments_skipped(self):
        t = D.thread_of("https://news.ycombinator.com/item?id=50557661")
        p = D.parse(t, list(hn_tree()))
        self.assertEqual((p.total, p.created_at, p.title), (99, T0, "Do not buy RAM, compress"))
        ids = {c.id: c for c in p.comments}
        self.assertNotIn(None, [c.author for c in p.comments])               # the deleted comment is not kept
        orphan = next(c for c in p.comments if c.author == "orphan")
        self.assertIsNone(orphan.parent)                                       # its reply stands at the top
        top0 = next(c for c in p.comments if c.author == "user0")
        self.assertEqual((top0.replies, top0.links), (3, ["https://example.org/z0"]))
        kept = D.cap(p.comments)
        self.assertEqual(kept[0].author, "orphan")                            # the site's rank order
        self.assertEqual([c.author for c in kept if c.parent is None], ["orphan", "user2", "user1", "user0"])
        after = [c.author for c in kept][kept.index(ids[top0.id]):][:4]
        self.assertEqual(after, ["user0", "reply01", "deep", "reply00"])     # most replies under it first, depth first

    def test_the_cap_keeps_many_voices_and_their_best_replies(self):
        t = D.thread_of("https://news.ycombinator.com/item?id=1")
        p = D.parse(t, list(hn_tree(n_top=80, replies=3, story=1)))
        kept = D.cap(p.comments)
        self.assertEqual(len(kept), D.CAP)
        self.assertEqual(len([c for c in kept if c.parent is None]), D.TOP_LEVEL)
        self.assertTrue(all(c.parent is None or c.parent in {k.id for k in kept} for c in kept))   # no reply alone
        self.assertEqual(len(D.cap(p.comments, 10)), 10)

    def test_lobsters_by_score(self):
        t = D.thread_of("https://lobste.rs/s/abcd12")
        story = {"comment_count": 4, "created_at": "2026-11-23T04:00:00.000-06:00", "title": "Signal", "comments": [
            {"short_id": "aaa1", "parent_comment": None, "depth": 0, "score": 3, "commenting_user": "a",
             "comment": "<p>Low</p>", "created_at": "2026-11-23T05:00:00.000-06:00"},
            {"short_id": "bbb2", "parent_comment": None, "depth": 0, "score": 30, "commenting_user": "b",
             "comment": "<p>High</p>", "created_at": "2026-11-23T05:01:00.000-06:00"},
            {"short_id": "ccc3", "parent_comment": "bbb2", "depth": 1, "score": 2, "commenting_user": "c",
             "comment": "<p>Reply</p>", "created_at": "2026-11-23T05:02:00.000-06:00"},
            {"short_id": "ddd4", "parent_comment": None, "depth": 0, "score": 9, "commenting_user": "d",
             "comment": "", "is_deleted": True}]}
        kept = D.cap(D.parse(t, [story]).comments)
        self.assertEqual([(c.id, c.parent, c.score) for c in kept], [("bbb2", None, 30), ("ccc3", "bbb2", 2),
                                                                      ("aaa1", None, 3)])
        self.assertEqual(kept[0].replies, 1)

    def test_fetched_while_young_then_never(self):
        self.assertEqual(MD.next_fetch(T0, T0), T0 + timedelta(hours=2))
        self.assertEqual(MD.next_fetch(T0, T0 + timedelta(hours=3)), T0 + timedelta(hours=12))
        self.assertEqual(MD.next_fetch(T0, T0 + timedelta(hours=13)), T0 + timedelta(hours=48))
        self.assertIsNone(MD.next_fetch(T0, T0 + timedelta(hours=48)))
        self.assertIsNone(MD.next_fetch(None, T0))
        self.assertEqual([MD.ask_due(k, a) for k, a in ((4, None), (5, None), (20, 15), (23, 15))],
                         [False, True, False, True])


INPUT = MD.render("Do not buy RAM, compress", "curiousbits.nl", "Use zram.", "Hacker News", 99, [
    ("101", None, "a", "macOS compresses memory by default since 2013."),
    ("102", "101", "b", "Windows does too, see https://learn.example/x."),
])
ANSWER = {"stance": "Agrees; adds that macOS and Windows already compress.",
          "points": [{"kind": "context", "text": "macOS compresses by default.", "comments": ["c101"],
                      "quote": "macOS compresses memory by default"},
                     {"kind": "data", "text": "Made up.", "comments": ["c102"], "quote": "Linux invented it"}],
          "tools": [{"name": "zram", "url": None, "what": None, "comments": ["c101"]}]}


class TheGuide(unittest.TestCase):
    def test_the_input_and_the_checks(self):
        self.assertIn("THREAD: Hacker News, 99 comments, 2 shown", INPUT)
        self.assertIn("\n  [c102] b, reply to c101: Windows", INPUT)
        self.assertEqual(validate.discussion_comments(INPUT), {"c101", "c102"})
        self.assertIsNone(validate.check("discussion", ANSWER, INPUT)[1])
        bad = {**ANSWER, "points": [{**ANSWER["points"][0], "comments": ["c999"]}]}
        self.assertIn("c999", validate.check("discussion", bad, INPUT)[1])
        self.assertIn("comments", validate.check("discussion", {**ANSWER, "points": [{**ANSWER["points"][0],
                                                                                       "comments": []}]}, INPUT)[1])
        self.assertTrue(schemas.guide_body("discussion-v1").startswith("You read ONE post"))

    def test_a_point_is_shown_only_with_its_quote_in_a_cited_comment(self):
        comments = {"c101": {"text": "macOS compresses memory by default since 2013."},
                    "c102": {"text": "Windows does too."}}
        points, tools, dropped = MD.kept(ANSWER, comments)
        self.assertEqual(([p["kind"] for p in points], dropped, [t["name"] for t in tools]), (["context"], 1, ["zram"]))


class FakeHttp:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    async def get_json(self, url):
        self.asked.append(url)
        got = self.answers[url]
        if isinstance(got, Exception):
            raise got
        return got


async def _no_sleep(_s):
    return None


class Pass(_Api):
    def setUp(self):
        super().setUp()
        self.hn = insert_scratch_source(self.cur, platform="rss", enabled=True,
                                        settings_json=json.dumps({"display_name": "Hacker News"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.hn,))

    def hn_post(self, item="50557661", at=None):
        pid = self.post(title="Do not buy RAM, compress", source=self.hn, at=at)
        self.cur.execute("UPDATE posts SET url = %s, metadata = %s::jsonb WHERE id = %s",
                         (f"https://curiousbits.example/blog/{item}",
                          json.dumps({"comments_url": f"https://news.ycombinator.com/item?id={item}"}), pid))
        return pid

    def run_pass(self, now, item="50557661", answers=None):
        tree, order = hn_tree(story=int(item))
        http = FakeHttp(answers or {f"https://hn.algolia.com/api/v1/items/{item}": tree,
                                    f"https://hacker-news.firebaseio.com/v0/item/{item}.json": order})
        out = MD.run(db_url(), now=now, http=http, limiter=HostLimiter(D.FLOORS, sleep=_no_sleep))
        return out, http

    def test_want_fetch_ask_answer_and_view(self):
        pid = self.hn_post()
        status, v = call("GET", f"/api/markx/posts/{pid}/discussion")
        self.assertEqual((status, v["status"], v["wanted"], v["thread"]["name"]), (200, "waiting", False, "Hacker News"))
        self.cur.execute("SELECT count(*) FROM discussion_threads")
        self.assertEqual(self.cur.fetchone()[0], 0)                            # a GET writes nothing
        self.assertEqual(call("POST", f"/api/markx/posts/{pid}/discussion/want")[1], {"wanted": True})
        self.assertEqual(call("POST", f"/api/markx/posts/{pid}/discussion/want")[1], {"wanted": False})
        self.assertIsNotNone(jobs.state(self.cur)["discussions"]["wanted_at"])
        now = datetime.now(timezone.utc)
        out, http = self.run_pass(now)
        self.assertEqual((out["fetched"], out["requests"], out["asked"]), (1, 2, 1))
        self.cur.execute("SELECT kept, total, next_at, fetches, task_id, bytes FROM discussion_threads WHERE post_id = %s",
                         (pid,))
        kept, total, nxt, fetches, task_id, size = self.cur.fetchone()
        self.assertEqual((kept, total, fetches, nxt), (13, 99, 1, None))     # the thread began in T0: no more fetches
        self.assertGreater(size, 100)
        self.cur.execute("SELECT count(*) FROM discussion_links WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchone()[0], 3)
        task = repo.get_task(self.cur, task_id)
        self.assertEqual((task["kind"], str(task["a"]), task["priority"]), ("discussion", pid, MD.ASKED))
        self.assertIn("SITE: curiousbits.example", task["input"])
        self.assertEqual(self.run_pass(now)[0]["fetched"], 0)                  # done: not fetched again
        # the worker answers; the view shows the points whose quote is in a cited comment
        self.cur.execute("SELECT comment_id FROM discussion_comments WHERE post_id = %s AND author = 'user0'", (pid,))
        c0 = "c" + self.cur.fetchone()[0]
        answer = {"stance": "Agrees.", "points": [
            {"kind": "experience", "text": "zram works for them.", "comments": [c0], "quote": "says zram works"},
            {"kind": "data", "text": "Invented.", "comments": [c0], "quote": "not in the comment"}],
                  "tools": [{"name": "zram", "url": None, "what": None, "comments": [c0]}]}
        self.lease("discussion")
        self.assertEqual(self.answer((task_id, answer))[1]["valid"], 1)
        v = call("GET", f"/api/markx/posts/{pid}/discussion")[1]
        self.assertEqual((v["status"], v["stance"], len(v["points"]), v["dropped"]), ("answered", "Agrees.", 1, 1))
        self.assertEqual(v["comments"][c0]["author"], "user0")
        self.assertEqual(v["comments"][c0]["url"], f"https://news.ycombinator.com/item?id={c0[1:]}")
        status, counts = call("GET", "/api/markx/discussions", query={"posts": f"{pid},not-an-id"})
        self.assertEqual((status, counts), (200, {pid: {"points": 1, "total": 99, "name": "Hacker News"}}))

    def test_news_rows_young_posts_are_planned_and_refetches_keep_everything(self):
        now = datetime.now(timezone.utc)
        young, old = self.hn_post("700", at=now - timedelta(hours=1)), self.hn_post("701", at=now - timedelta(days=5))
        other = self.post()                                                     # no thread
        run = repo.start_run(self.cur, code_version="test", config={})
        self.cur.execute("""INSERT INTO mx_news (run_id, id, first_at, voices, reports, shares, mentions, score, posts)
                            VALUES (%s, %s, now(), 1, 1, 0, 0, 1, %s::jsonb)""",
                         (run, young, json.dumps([{"post_id": p, "role": "report"} for p in (young, old, other)])))
        tree, order = hn_tree(story=700)
        tree["created_at_i"] = (now - timedelta(hours=1)).timestamp()
        answers = {"https://hn.algolia.com/api/v1/items/700": tree,
                   "https://hacker-news.firebaseio.com/v0/item/700.json": order}
        out, _ = self.run_pass(now, answers=answers)
        self.assertEqual((out["planned"], out["fetched"]), ({"news": 1, "track": 0}, 1))
        self.cur.execute("SELECT post_id::text, wanted_by, next_at FROM discussion_threads")
        rows = self.cur.fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [(young, "news")])
        self.assertAlmostEqual((rows[0][2] - now).total_seconds(), 3600, delta=5)   # 2 h after the thread began
        # the next fetch: a comment gone from the site stays stored; the question is not asked again (no growth)
        tree["children"] = tree["children"][1:]
        out, _ = self.run_pass(now + timedelta(hours=2), answers=answers)
        self.assertEqual((out["fetched"], out["asked"]), (1, 0))
        self.cur.execute("SELECT count(*), count(*) FILTER (WHERE seen_at = %s) FROM discussion_comments",
                         (now + timedelta(hours=2),))
        self.assertEqual(self.cur.fetchone(), (13, 9))

    def test_a_failing_thread_stops_after_three(self):
        pid = self.hn_post("702")
        with self.conn.transaction():
            MD.want(self.cur, pid)
        from insight_core.ingestion.http import HttpError
        boom = {"https://hn.algolia.com/api/v1/items/702": HttpError("HTTP 500", status=500),
                "https://hacker-news.firebaseio.com/v0/item/702.json": {}}
        now = datetime.now(timezone.utc)
        for n in range(3):
            self.assertEqual(self.run_pass(now + timedelta(hours=n * 2), answers=boom)[0]["failed"], 1)
        self.cur.execute("SELECT failures, next_at, last_error FROM discussion_threads WHERE post_id = %s", (pid,))
        failures, nxt, error = self.cur.fetchone()
        self.assertEqual((failures, nxt), (3, None))
        self.assertIn("500", error)


class Due(unittest.TestCase):
    def states(self, **over):
        base = {j: {"job": j, "wanted_at": None, "started_at": None, "stage": None, "stage_at": None,
                    "finished_at": None, "last": None, "failures": 0} for j in jobs.JOBS}
        now = datetime.now(timezone.utc)
        base["decide"]["started_at"] = now           # a decision run just started: nothing else is due
        for job, values in over.items():
            base[job].update(values)
        return base, now

    def test_a_readers_want_first_then_every_ten_minutes(self):
        states, now = self.states(discussions={"started_at": datetime.now(timezone.utc)})
        self.assertIsNone(jobs.due(states, now, discussions_every=jobs.DISCUSSIONS_EVERY))
        states["discussions"]["wanted_at"] = now
        self.assertEqual(jobs.due(states, now, discussions_every=jobs.DISCUSSIONS_EVERY), "discussions")
        states["discussions"].update(wanted_at=None, started_at=now - timedelta(seconds=jobs.DISCUSSIONS_EVERY))
        self.assertEqual(jobs.due(states, now, discussions_every=jobs.DISCUSSIONS_EVERY), "discussions")
        self.assertIsNone(jobs.due(states, now))      # off when the runner names no period


class Bylines(_Api):
    """An aggregator's page names its site, its thread is linked in the post page's header; a re-hosted feed's own
    pages are unchanged."""

    def feed(self, name, hosts):
        sid = insert_scratch_source(self.cur, platform="rss", enabled=True,
                                    settings_json=json.dumps({"display_name": name}))
        self.cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s",
                         (f"https://feeds.{name.lower().replace(' ', '')}.example/rss", sid))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (sid,))
        ids = []
        for n, host in enumerate(hosts):
            pid = self.post(title=f"Page {n}", source=sid)
            self.cur.execute("UPDATE posts SET url = %s, url_host = %s WHERE id = %s",
                             (f"https://{host}/p/{n}", host, pid))
            ids.append(pid)
        return sid, ids

    def test_an_aggregators_page_names_its_site(self):
        hn, (page, *_rest) = self.feed("Hacker News", ["www.curiousbits.example", "a.example", "b.example",
                                                       "c.example", "a.example"])
        self.cur.execute("UPDATE posts SET metadata = %s::jsonb WHERE id = %s",
                         (json.dumps({"comments_url": "https://news.ycombinator.com/item?id=50557661"}), page))
        rehosted, (own, *_r) = self.feed("Academy", ["academy.example"] * 4 + ["cdn.example"])
        self.assertEqual(byline.aggregators(self.cur, [hn, rehosted, self.source]), {hn})
        got = byline.bylines(self.cur, [page, own])
        self.assertEqual(got[page], {"author": "curiousbits.example", "via": "Hacker News", "quoting": None})
        self.assertEqual(got[own]["author"], None)
        from insight_core.services.post_detail_service import PostDetailService
        post = PostDetailService(db_url()).get_post_by_id(page)
        self.assertEqual(post["byline"]["author"], "curiousbits.example")
        self.assertEqual(post["discussion"], {"name": "Hacker News", "url": "https://news.ycombinator.com/item?id=50557661",
                                              "total": None})
        post = PostDetailService(db_url()).get_post_by_id(own)
        self.assertEqual((post["byline"]["author"], post["discussion"]), (None, None))


if __name__ == "__main__":
    unittest.main()
