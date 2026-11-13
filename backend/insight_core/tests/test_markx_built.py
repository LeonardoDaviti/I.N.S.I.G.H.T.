"""0128 (Stealth v10.4, slice C): how Mark X stories are built. The story's event type from its members' read-v3
readings, leaks inside a story and leak stories linked "came true" to their release, the original by code shown first,
published order (a saved page by its own date), on the News page and the story view. Computed from rows Mark X keeps;
nothing is stored. Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from insight_core.markx import built as B, folds as F, news, perspective_views as PV, perspectives as P, repo
from insight_core.tests.test_markx_api import _Api, call, reading
from insight_core.tests.test_markx_folds import read3

T0 = datetime(2100, 4, 1, 12, tzinfo=timezone.utc)
H, D = timedelta(hours=1), timedelta(days=1)


def bp(n, event_type, origin="other", hours=None, source=None):
    return B.Post(id=f"p{n}", source=source or f"s{n}", at=T0 + (n if hours is None else hours) * H,
                  event_type=event_type, origin=origin)


class TheEventType(unittest.TestCase):
    def test_the_storys_news_type_from_its_members(self):
        ps = [bp(0, "leak_rumour"), bp(1, "model_release", "maker"), bp(2, "model_release"), bp(3, "opinion_analysis"),
              bp(4, "opinion_analysis"), bp(5, "opinion_analysis")]
        self.assertEqual(B.event_type(ps), "model_release")             # news types first, as the fold's story type

    def test_with_no_news_type_the_most_common_type_a_story_of_leaks_is_a_leak_story(self):
        self.assertEqual(B.event_type([bp(0, "leak_rumour"), bp(1, "leak_rumour"), bp(2, "opinion_analysis")]),
                         "leak_rumour")
        self.assertEqual(B.event_type([bp(0, "opinion_analysis"), bp(1, "digest")]), "opinion_analysis")  # a tie: the first

    def test_unread_members_never_count(self):
        self.assertIsNone(B.event_type([bp(0, None), bp(1, None)]))
        self.assertEqual(B.event_type([bp(0, None), bp(1, "incident")]), "incident")


class LeaksInside(unittest.TestCase):
    def test_a_leak_hours_before_the_release_joins_it(self):
        ps = [bp(0, "leak_rumour", hours=0), bp(1, "model_release", "maker", hours=9), bp(2, "model_release", hours=10)]
        self.assertEqual(B.release_at(ps), T0 + 9 * H)
        self.assertEqual(B.leaks_inside(ps), [{"post": "p0", "hours": 9.0, "joins": True, "own_coverage": False}])

    def test_a_lone_voice_leaking_days_earlier_still_joins(self):
        ps = [bp(0, "leak_rumour", hours=0), bp(1, "model_release", hours=72)]
        self.assertEqual(B.leaks_inside(ps)[0]["joins"], True)

    def test_two_voices_leaking_days_earlier_is_coverage_of_its_own(self):
        ps = [bp(0, "leak_rumour", hours=0), bp(1, "leak_rumour", hours=2), bp(2, "leak_rumour", hours=70),
              bp(3, "model_release", hours=72), bp(4, "model_release", hours=73)]
        got = {x["post"]: x for x in B.leaks_inside(ps)}
        self.assertEqual((got["p0"]["own_coverage"], got["p1"]["own_coverage"]), (True, True))
        self.assertEqual((got["p0"]["joins"], got["p1"]["joins"]), (False, False))
        self.assertEqual((got["p2"]["joins"], got["p2"]["own_coverage"]), (True, False))   # 2 hours before: joins

    def test_one_source_twice_is_one_voice(self):
        ps = [bp(0, "leak_rumour", hours=0, source="a"), bp(1, "leak_rumour", hours=1, source="a"),
              bp(2, "model_release", hours=72)]
        self.assertTrue(all(x["joins"] for x in B.leaks_inside(ps)))

    def test_a_leak_after_the_release_or_with_no_release_is_no_leak_here(self):
        self.assertEqual(B.leaks_inside([bp(0, "model_release", hours=0), bp(1, "leak_rumour", hours=1)]), [])
        self.assertEqual(B.leaks_inside([bp(0, "leak_rumour"), bp(1, "opinion_analysis")]), [])


class CameTrue(unittest.TestCase):
    LR = {frozenset(("L", "R"))}

    def leak(self, hours, sources=("a", "b")):
        return [bp(10 + n, "leak_rumour", hours=hours + n, source=s) for n, s in enumerate(sources)]

    def release(self, hours):
        return [bp(20, "model_release", "maker", hours=hours), bp(21, "model_release", hours=hours + 1)]

    def test_a_leak_story_days_earlier_with_coverage_of_its_own_is_linked_came_true(self):
        got = B.came_true({"L": self.leak(0), "R": self.release(96)}, connected=self.LR)
        self.assertEqual(got, [{"leak": "L", "release": "R", "hours": 96.0, "joins": False, "via": "connection"}])

    def test_a_one_voice_leak_hours_before_joins_the_release(self):
        got = B.came_true({"L": self.leak(0, sources=("a", "a")), "R": self.release(8)}, connected=self.LR)
        self.assertEqual([(x["leak"], x["joins"]) for x in got], [("L", True)])
        # with coverage of its own (two voices) it stays its own story, linked
        self.assertEqual(B.came_true({"L": self.leak(0), "R": self.release(8)}, connected=self.LR)[0]["joins"], False)

    def test_no_link_without_a_judged_connection_too_late_or_before_the_leak(self):
        # 0203: only a judged connection links (the shared-subject link, measured 0 of 5, is gone)
        self.assertEqual(B.came_true({"L": self.leak(0), "R": self.release(96)}), [])
        self.assertEqual(B.came_true({"L": self.leak(0), "R": self.release(31 * 24)}, connected=self.LR), [])
        self.assertEqual(B.came_true({"L": self.leak(100), "R": self.release(50)}, connected=self.LR), [])
        # a release story's type must be news; a leak story's must be a leak
        notnews = [bp(30, "opinion_analysis", hours=96), bp(31, "opinion_analysis", hours=97)]
        self.assertEqual(B.came_true({"L": self.leak(0), "R": notnews}, connected=self.LR), [])


def member(i, src, at, title, text="", url=None, links=(), kind="telegram", published=None):
    return P.Member(id=i, src=src, src_name=src, kind=kind, at=at, published=published, title=title, text=text,
                    url=url, nurl=url, links=list(links))


class TheOriginal(unittest.TestCase):
    def test_the_page_most_members_link_is_the_original_and_comes_first(self):
        by = {"a": member("a", "s1", T0, "Widget 4.1 is out", "Widget 4.1 is out today " * 5, links=["https://acme.example/w41"]),
              "b": member("b", "s2", T0 + H, "Acme: Widget 4.1", "Our announcement " * 10, url="https://acme.example/w41",
                          kind="site"),
              "c": member("c", "s3", T0 + 2 * H, "Widget 4.1 thoughts", "A long take " * 20, links=["https://acme.example/w41"])}
        st = P.Story(list(by), by)
        self.assertEqual(B.original(st), {"post": "b", "how": "links"})
        self.assertEqual(B.first_order(st, list(by)), ["b", "a", "c"])

    def test_no_member_is_the_original_the_source_page_and_the_earliest_first(self):
        by = {"a": member("a", "s1", T0, "Widget 4.1", "words " * 40, links=["https://acme.example/w41"]),
              "b": member("b", "s2", T0 + H, "Widget 4.1 again", "more words " * 40, links=["https://acme.example/w41"])}
        st = P.Story(list(by), by)
        self.assertIsNone(B.original(st))
        self.assertEqual(st.src_page, "acme.example/w41")
        self.assertEqual(B.first_order(st, ["b", "a"]), ["a", "b"])

    def test_a_saved_page_is_ordered_by_its_own_date(self):
        by = {"a": member("a", "s1", T0, "Report on the paper", "words " * 40),
              "b": member("b", "saved", T0 + 5 * D, "The paper", "the paper's text " * 40, kind="saved",
                          published=T0 - D)}
        st = P.Story(list(by), by)
        self.assertEqual(B.first_order(st, ["a", "b"]), ["b", "a"])


class Stored(_Api):
    """The built story from the database: readings, members, mentions, the News page and the story view."""

    def setUp(self):
        super().setUp()
        self.run = repo.start_run(self.cur, code_version="test", config={})

    def story(self, *posts, at=None):
        sid = repo.add_story(self.cur, first_at=at or datetime.now(timezone.utc), run_id=self.run)
        for p in posts:
            repo.open_membership(self.cur, story_id=sid, post_id=p, role="member", reason="test", run_id=self.run)
        return str(sid)

    def read(self, post, answer):
        with self.conn.transaction():
            task_id, _ = F.read3_task(self.cur, post)
        _, got = self.answer((task_id, answer))
        self.assertEqual(got["valid"], 1, got)

    def subject(self, post, name):
        """An ent-v3 mention of `name` as the post's subject, linked to one entity per name."""
        from insight_core.markx import tasks
        with self.conn.transaction():
            task_id, _ = tasks.entities_task(self.cur, post)
            cid = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                                answer={"entities": []})
            repo.add_mentions(self.cur, post_id=post, guide="ent-v3", call_id=cid, mentions=[
                {"span": name, "name": name, "name_key": tasks.name_key(name), "type": "model", "role": "subject",
                 "maker": None, "family": None, "version": None, "variant": None, "size": None, "build": None}])
            self.cur.execute("SELECT id::text FROM mx_entities WHERE key = %s", (tasks.name_key(name),))
            row = self.cur.fetchone()
            if row is None:
                self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, status)
                                    VALUES ('model', %s, %s, 'thing', 'provisional') RETURNING id::text""",
                                 (name, tasks.name_key(name)))
                row = self.cur.fetchone()
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (row[0], post))

    def test_a_leak_story_and_its_release_are_linked_on_both_pages(self):
        now = datetime.now(timezone.utc)
        l1 = self.post(title="Widget 5 leaked: coming next week", at=now - 5 * D)
        l2 = self.post(title="Rumour: Widget 5 soon", at=now - 5 * D + H, source=self.other)
        r1 = self.post(title="Acme releases Widget 5", at=now - D, source=self.other)
        r2 = self.post(title="Widget 5 is out", at=now - D + H)
        leak, rel = self.story(l1, l2, at=now - 5 * D), self.story(r1, r2, at=now - D)
        self.read(l1, read3(event_type="leak_rumour"))
        self.read(l2, read3(event_type="leak_rumour"))
        self.read(r1, read3(origin="maker"))
        self.read(r2, read3())
        for p in (l1, l2, r1, r2):
            self.subject(p, "Widget 5")
        got = B.build(self.cur, [leak, rel])
        self.assertEqual(got[leak]["event_type"], "leak_rumour")
        self.assertEqual(got[rel]["event_type"], "model_release")
        # a shared subject alone links nothing (only a judged connection links: 0128 measured the subject 0 of 5)
        self.assertEqual((got[leak]["came_true"], got[rel]["leaked_before"]), ([], []))
        repo.open_connection(self.cur, a_kind="story", a=leak, b_kind="story", b=rel, relation="development",
                             run_id=self.run, p=0.8, rule="test")
        got = B.build(self.cur, [leak, rel])
        self.assertEqual([(x["story"], x["joins"], x["via"]) for x in got[leak]["came_true"]], [(rel, False, "connection")])
        self.assertEqual([x["story"] for x in got[rel]["leaked_before"]], [leak])
        # the story view (the story page) carries it too
        status, view = call("GET", f"/api/markx/stories/{rel}")
        self.assertEqual(status, 200, view)
        self.assertEqual(view["built"]["event_type"], "model_release")
        self.assertEqual([x["story"] for x in view["built"]["leaked_before"]], [leak])
        self.assertEqual(view["built"]["read"], {"read": 2, "members": 2})

    def test_the_news_row_puts_the_original_first_in_published_order(self):
        now = datetime.now(timezone.utc)
        early = self.post(title="Widget 4.1 is out", text="First word of a release: Widget 4.1 shipped with a new "
                          "planner and more memory for every team.", at=now - 5 * H,
                          links=[("https://acme.example/w41", "post")])
        orig = self.post(title="Acme: Widget 4.1", text="Today we announce Widget 4.1, our fastest model, available to "
                         "all customers from this morning onwards.", at=now - 4 * H, source=self.other)
        self.cur.execute("UPDATE posts SET url = 'https://acme.example/w41', normalized_url = 'https://acme.example/w41' "
                         "WHERE id = %s", (orig,))
        late = self.post(title="Widget 4.1 tested", text="I ran my own benchmark suite on it overnight and the "
                         "numbers look strong on coding tasks.", at=now - 2 * H, links=[("https://acme.example/w41", "post")])
        # received long after its date: published order still puts it by its date
        old = self.post(title="Widget 4.1 a day on", text="Opinion piece about pricing changes and what they mean "
                        "for small companies everywhere.", at=now - 3 * H)
        self.cur.execute("UPDATE posts SET surfaced_at = %s WHERE id = %s", (now - H / 2, old))
        sid = self.story(early, orig, late, old, at=now - 5 * H)
        repo.add_news_rows(self.cur, self.run, [{"id": early, "first_at": now - 5 * H, "voices": 2, "reports": 4,
                                                  "shares": 0, "mentions": 0, "score": 9, "tag": "NEW",
                                                  "posts": [{"post_id": p, "role": "report", "story": sid}
                                                            for p in (early, late, old, orig)]}])
        repo.finish_run(self.cur, self.run, counts={})
        page = news.page(self.cur, now=now)
        row = page["items"][0]
        self.assertEqual([line["id"] for line in row["posts"]], [orig, early, old, late])
        self.assertEqual(row["posts"][0]["built"], {"role": "original", "how": "links"})
        self.assertEqual(row["built"]["original"], {"post": orig, "how": "links"})
        self.assertEqual(row["posts"][2]["at"], now - 3 * H)                # its date, not when it was received

    def test_the_folds_order_is_published_order(self):
        now = datetime.now(timezone.utc)
        a = self.post(at=now - 3 * H)
        b = self.post(at=now - 2 * H)
        self.cur.execute("UPDATE posts SET surfaced_at = %s WHERE id = %s", (now - H / 2, a))   # received later
        sid = self.story(a, b)
        self.read(a, read3(origin="relay"))
        self.read(b, read3(origin="relay"))
        self.assertEqual(F.story_folds(self.cur, [sid])[sid].head, a)          # the first relay by its date
        self.assertEqual([p["id"] for p in F.story_view(self.cur, sid)["posts"]], [a, b])

    def test_mark_ix_tables_are_untouched(self):
        from insight_core.tests.test_markx_decide import checksums
        now = datetime.now(timezone.utc)
        a, b = self.post(at=now - 2 * H), self.post(at=now - H)
        sid = self.story(a, b)
        self.read(a, read3(origin="maker"))
        before = checksums(self.cur)
        B.build(self.cur, [sid])
        PV.story_view(self.cur, sid)
        self.assertEqual(checksums(self.cur), before)


if __name__ == "__main__":
    unittest.main()
