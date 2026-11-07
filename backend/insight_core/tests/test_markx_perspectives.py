"""Mark X perspectives and the story sheet (issue 0119 B): the code steps (the lab's persp32.Story, with the maker from
identity instead of word lists), the final checks, the sheet, the stage (which stories, the tasks, re-asking a skipped
member, storage that closes and opens rows), the story view and the label buttons. Invented names only. The database
tests run in one transaction rolled back after each (the mx_* tables emptied inside it), on a _test database."""
from __future__ import annotations

import hashlib
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.markx import decide, identity as I, names as N, perspective_views as V, perspectives as P
from insight_core.markx import repo, schemas, tasks, validate
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

T0 = datetime(2100, 1, 5, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)
LONG = ("Acme released Nimbus 5 today, a model with 400 billion parameters, open weights under a permissive licence "
        "and a context of one million tokens, priced at two dollars per million input tokens for every developer.")


def member(pid, src, at, title="", text="", url=None, links=(), kind="telegram", name=None, published=None):
    return P.Member(id=pid, src=src, src_name=name or f"Example {src}", kind=kind, at=at, published=published,
                    title=title, text=text, url=url or f"https://example.org/{pid}", nurl=None, links=list(links))


def pid(n):
    return f"{n:08x}-0000-4000-8000-000000000000"


def book(*ents):
    """A hand-made entity book: (id, name, type, maker, parent)."""
    b = I.Book()
    for eid, name, type_, maker, parent in ents:
        b.ents[eid] = I.Ent(eid, type_, name, N.key(name), "thing", parent, maker)
        b.alias[N.key(name)] = eid
    return b


class Guides(unittest.TestCase):
    def test_the_guides_are_the_frozen_lab_files(self):
        """B3/B4: the port is checked as the same guide (the lab's md5s, recorded 2026-11-05)."""
        self.assertEqual(hashlib.md5((schemas.GUIDES_DIR / "persp-v1.md").read_bytes()).hexdigest(),
                         "ee89e27e2838d1655f110ba1a27570f4")
        self.assertEqual(hashlib.md5((schemas.GUIDES_DIR / "persp-merge-v1.md").read_bytes()).hexdigest(),
                         "8ce37bac480c915de91eaf096ee66b03")
        self.assertEqual(schemas.KINDS["perspective"].guide, "persp-v1")
        self.assertEqual(schemas.KINDS["sheet"].guide, "persp-merge-v1")

    def test_the_schemas_take_the_lab_answers_and_refuse_an_unknown_label(self):
        ok = {"members": [{"id": "aa:bb", "facts": [{"fact": "f", "span": "s", "correction": False, "about_story": True}],
                           "claims": [], "label": "new_facts", "point": None}]}
        self.assertIsNone(validate.check("perspective", ok, "input")[1])
        bad = {"members": [{"id": "aa:bb", "label": "adds"}]}
        self.assertIsNotNone(validate.check("perspective", bad, "input")[1])
        self.assertIsNone(validate.check("sheet", {"groups": [{"lines": [1, 2], "fact": "x", "correction": False}]}, "i")[1])


class CodeSteps(unittest.TestCase):
    def story(self, ms, makers=None):
        by = {m.id: m for m in ms}
        return P.Story([m.id for m in ms], by, makers)

    def test_copies_of_one_source_are_folded_never_judged(self):
        a = member(pid(1), "s1", T0, "Nimbus 5 is out", LONG)
        b = member(pid(2), "s1", T0 + H, "Nimbus 5 is out", LONG)                      # the same text again
        c = member(pid(3), "s1", T0 + 2 * H, "Nimbus 5 is out!", LONG + " Wow.")        # a little edited
        d = member(pid(4), "s2", T0 + 3 * H, "Nimbus 5 is out", LONG)                   # another source: a member
        st = self.story([a, b, c, d])
        self.assertEqual(st.ids, [a.id, d.id])
        self.assertEqual(sorted(st.dup[a.id]), [b.id, c.id])

    def test_the_page_most_members_link_is_the_original(self):
        page = "https://acme.example/blog/nimbus-5"
        a = member(pid(1), "s1", T0, "Nimbus 5", LONG, url=page, kind="site")
        b = member(pid(2), "s2", T0 + H, "A take", "Read this " + LONG.replace("Acme", "they"), links=[page])
        c = member(pid(3), "s3", T0 + 2 * H, "Another", "Look: " + LONG.replace("today", "now"), links=[page])
        st = self.story([a, b, c])
        self.assertEqual(st.code[a.id], ("original", "links"))
        self.assertTrue(st.ref_is_original)
        self.assertEqual(st.ref, a.id)

    def test_the_makers_own_account_is_a_hint_for_haiku_not_a_label(self):
        """v3.2f: the maker comes from identity (a mention's stated maker), and its own source is evidence only."""
        makers = P.Makers(book(("e1", "Acme", "org", None, None), ("e2", "Nimbus 5", "model", "Acme", None)),
                            {pid(n): [{"role": "subject", "type": "model", "maker": "Acme", "entity_id": "e2",
                                       "name": "Nimbus 5"}] for n in (1, 2, 3)})
        a = member(pid(1), "s1", T0, "We release Nimbus 5", LONG, name="Acme")
        b = member(pid(2), "s2", T0 + H, "Nimbus 5 out", "My first tests of Nimbus 5: " + LONG.replace("Acme", "it"))
        c = member(pid(3), "s3", T0 + 2 * H, "Nimbus 5 benchmarks", "Scores are in. " + LONG.replace("Acme", "the lab"))
        st = self.story([a, b, c], makers)
        self.assertEqual(st.maker, "e1")
        self.assertNotIn(a.id, st.code)
        self.assertIn(a.id, st.hint)
        self.assertIn("[the maker's own account or staff]", st.context())

    def test_a_link_post_carrying_the_makers_repository_is_the_original(self):
        mk = P.Makers(book(("e1", "Acme", "org", None, None), ("e2", "Nimbus 5", "model", "Acme", None)),
                      {pid(n): [{"role": "subject", "type": "model", "maker": "Acme", "entity_id": "e2", "name": "Nimbus 5"}]
                       for n in (1, 2, 3)})
        a = member(pid(1), "s1", T0, "Nimbus 5 is here", LONG)
        b = member(pid(2), "s2", T0 + H, "GitHub - acme-ai/nimbus-5: the weights", "", kind="reddit",
                   links=["https://github.com/acme-ai/nimbus-5"])
        c = member(pid(3), "s3", T0 + 2 * H, "Nimbus 5 reviewed", "A long look. " + LONG.replace("Acme", "they"))
        st = self.story([a, b, c], mk)
        self.assertEqual(st.code[b.id], ("original", "maker-link"))

    def test_no_member_is_the_source_the_page_they_link_is_shown(self):
        page = "https://acme.example/news/nimbus-5"
        ms = [member(pid(n), f"s{n}", T0 + n * H, f"Take {n}", f"Point {n}. " + LONG, links=[page]) for n in range(1, 4)]
        st = self.story(ms)
        self.assertEqual(st.src_page, "acme.example/news/nimbus-5")
        self.assertIn("SOURCE PAGE (the primary source; not a member, members link it): acme.example/news/nimbus-5",
                      st.context())
        self.assertIn("EARLIEST REPORT", st.context())

    def test_a_post_with_nothing_of_its_own_is_same_by_code(self):
        a = member(pid(1), "s1", T0, "Nimbus 5 is out", LONG)
        b = member(pid(2), "s2", T0 + H, "Nimbus 5 is out", "Acme released Nimbus 5 today")
        st = self.story([a, b])
        self.assertEqual(st.code[b.id], ("same", "nothing-own"))
        self.assertEqual(st.targets(), [st.mid(a.id)])

    def test_members_are_in_published_order_a_saved_page_by_its_own_date(self):
        a = member(pid(1), "s1", T0 + 5 * H, "Nimbus 5 page", LONG, kind="saved", published=T0 - H)
        b = member(pid(2), "s2", T0, "Nimbus 5 talk", "Thoughts. " + LONG.replace("Acme", "the maker"))
        st = self.story([b, a])
        self.assertEqual(st.ids, [a.id, b.id])

    def test_groups_of_at_most_five_members(self):
        ms = [member(pid(n), f"s{n}", T0 + n * H, f"Take {n}", f"Angle number {n} of many: {n * 7} things. " + LONG
                     .replace("Acme", f"Maker{n}").replace("400", str(400 + n))) for n in range(1, 13)]
        st = self.story(ms)
        gs = st.groups()
        self.assertTrue(all(len(g) <= P.PER_CALL for g in gs))
        self.assertEqual(sum(len(g) for g in gs), len(st.targets()))
        self.assertTrue(st.input(gs[0]).endswith("JUDGE: " + ", ".join(gs[0])))


class FinalChecks(unittest.TestCase):
    def setUp(self):
        self.a = member(pid(1), "s1", T0, "Nimbus 5 is out", LONG)
        self.b = member(pid(2), "s2", T0 + H,
                        "Nimbus 5 tested", "I ran Nimbus 5 on my own suite and it scored 81 percent on the coding set, "
                        "while it has 400 billion parameters as announced. It is slower than I hoped and "
                        "the context window seems fine.")
        self.st = P.Story([self.a.id, self.b.id], {self.a.id: self.a, self.b.id: self.b})
        self.k = self.st.mid(self.b.id)

    def fin(self, **ans):
        return P.final(self.st, {self.k: ans})[self.k]

    def test_a_fact_whose_span_is_not_in_the_post_is_dropped(self):
        got = self.fin(label="new_facts", facts=[{"fact": "x", "span": "it scored 99 percent on the coding set"}])
        self.assertEqual(got["facts"], [])
        self.assertEqual(got["dropped"], 1)
        self.assertEqual(got["label"], "same")                       # no facts, no claim, no point

    def test_facts_kept_make_new_facts_and_others_are_dropped(self):
        got = self.fin(label="opinion", facts=[
            {"fact": "81% on coding", "span": "it scored 81 percent on the coding set", "about_story": True},
            {"fact": "another model", "span": "It is slower than I hoped", "about_story": False},
            {"fact": "the size", "span": "it has 400 billion parameters as announced"}],   # 400 billion was said before
            point="slow")
        self.assertEqual(got["label"], "new_facts")
        self.assertEqual([f["fact"] for f in got["facts"]], ["81% on coding"])
        self.assertEqual(got["dropped"], 2)

    def test_new_facts_without_facts_is_opinion_when_it_argues_and_a_one_line_take_is_same(self):
        got = self.fin(label="new_facts", facts=[], point="it is slower than hoped")
        self.assertEqual(got["label"], "opinion")
        short = member(pid(3), "s3", T0 + 2 * H, "meh", "Nimbus 5 meh")
        st = P.Story([self.a.id, short.id], {self.a.id: self.a, short.id: short})
        k = st.mid(short.id)
        if k in st.code:
            self.assertEqual(st.code[short.id][0], "same")
        else:
            self.assertEqual(P.final(st, {k: {"label": "opinion", "point": "meh"}})[k]["label"], "same")

    def test_at_most_four_facts_and_original_is_kept(self):
        spans = ["I ran Nimbus 5 on my own suite", "it scored 81 percent on the coding set", "It is slower than I hoped",
                 "the context window seems fine", "on my own suite and it scored"]
        got = self.fin(label="original", facts=[{"fact": s, "span": s} for s in spans])
        self.assertEqual(got["label"], "original")
        self.assertEqual(len(got["facts"]), P.MAX_FACTS)


class Sheet(unittest.TestCase):
    def test_merged_lines_and_the_sections(self):
        a = member(pid(1), "s1", T0, "Nimbus 5 is out", LONG, kind="site", url="https://acme.example/n5")
        b = member(pid(2), "s2", T0 + H, "t", "x")
        c = member(pid(3), "s3", T0 + 2 * H, "t", "y")
        st = P.Story([a.id, b.id, c.id], {m.id: m for m in (a, b, c)})
        fin = {st.mid(b.id): {"label": "new_facts", "facts": [{"fact": "3x faster"}, {"fact": "runs on a laptop"}],
                              "claims": [{"claim": "a bigger one soon"}], "before": False},
               st.mid(c.id): {"label": "new_facts", "facts": [{"fact": "2-3x faster", "correction": False}],
                              "claims": [], "before": False},
               st.mid(a.id): {"label": "same", "facts": [], "claims": []}}
        lines = P.fact_lines(st, fin)
        self.assertEqual(len(lines), 3)
        self.assertIn("FACT LINES:\n1. 3x faster (Example s2)", P.merge_input(st, lines))
        sheet = P.build_sheet(st, fin, {"groups": [{"lines": [1, 3], "fact": "2-3x faster"}, {"lines": [9, "x"]}]})
        self.assertEqual([f["fact"] for f in sheet["new_facts"]], ["2-3x faster", "runs on a laptop"])
        self.assertEqual(sheet["new_facts"][0]["posts"], [b.id, c.id])
        self.assertEqual(sheet["claims"][0]["claim"], "a bigger one soon")
        self.assertEqual((sheet["lines"], sheet["merged"], sheet["same"]), (3, 2, 1))
        self.assertIsNone(P.merge_input(st, lines[:1]))


@requires_test_db
class Stage(unittest.TestCase):
    """The stage on synthetic stories: News rows name them, the tasks are answered by hand."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas.load_guides(self.cur)
        self.sources = [insert_scratch_source(self.cur, platform="telegram",
                                              settings_json=json.dumps({"display_name": f"Example {n}"}))
                        for n in range(6)]
        self.now = datetime.now(timezone.utc)
        self.run = repo.start_run(self.cur, code_version="test", config={})

    def post(self, src, title, text, at=None, links=()):
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                         (self.sources[src], url, url, title, text, at or self.now - 5 * H))
        p = str(self.cur.fetchone()[0])
        for n, target in enumerate(links):
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, %s, %s)",
                             (p, target, "example.com", n))
        return p

    def story(self, posts):
        sid = str(repo.add_story(self.cur, first_at=self.now - 5 * H, run_id=self.run))
        for p in posts:
            repo.open_membership(self.cur, story_id=sid, post_id=p, role="member", reason="test", run_id=self.run)
        return sid

    def news(self, *stories):
        rows = [{"id": ps[0], "first_at": self.now - 5 * H, "voices": len(ps), "reports": 0, "shares": 0, "mentions": 0,
                 "score": 1, "tag": "NEW", "posts": [{"post_id": p, "role": "report", "story": sid} for p in ps]}
                for sid, ps in stories]
        run = repo.start_run(self.cur, code_version="test", config={})
        repo.add_news_rows(self.cur, run, rows)
        repo.finish_run(self.cur, run, counts={})

    def stage(self):
        ask = decide.Ask(self.cur, self.now)
        return P.stage(self.cur, ask=ask, now=self.now, run_id=self.run)

    def tasks_of(self, kind, status=None):
        self.cur.execute("SELECT id::text, input, status FROM mx_tasks WHERE kind = %s AND (%s::text IS NULL OR status = %s) "
                         "ORDER BY created_at, input", (kind, status, status))
        return self.cur.fetchall()

    def answer(self, task_id, answer):
        repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer=answer)
        repo.answer_task(self.cur, task_id)

    def three(self, n0=0, word="Nimbus"):
        texts = [f"{word} 5 is out today from the lab, with 400 billion parameters and open weights for everyone to use.",
                 f"I tested {word} 5 on my own benchmark suite overnight and it scored 81 percent on the coding set, "
                 "better than the last release by a wide margin.",
                 f"Why {word} 5 matters: the open weights change who can build on it, and the price war is now on for "
                 "every lab that sells a closed model to developers."]
        ps = [self.post(n0 + n, f"{word} 5 post {n}", t, at=self.now - (6 - n) * H) for n, t in enumerate(texts)]
        return ps

    def answer_all(self, labels):
        """Answers each open perspective task: every member in its JUDGE list with labels[n % len]."""
        for tid, text, _ in self.tasks_of("perspective", "open"):
            keys = text.rsplit("JUDGE: ", 1)[1].split(", ")
            self.answer(tid, {"members": [dict(labels[n % len(labels)], id=k) for n, k in enumerate(keys)]})

    def test_a_story_is_asked_answered_stored_and_its_sheet_made(self):
        ps = self.three()
        sid = self.story(ps)
        self.news((sid, ps))
        out = self.stage()
        self.assertEqual(out["waiting"], 1)
        (tid, text, _), = self.tasks_of("perspective")
        self.assertIn("MEMBERS IN PUBLISHED ORDER:", text)
        self.cur.execute("SELECT a::text FROM mx_tasks WHERE id = %s", (tid,))
        self.assertEqual(self.cur.fetchone()[0], sid)
        keys = text.rsplit("JUDGE: ", 1)[1].split(", ")
        self.assertEqual(len(keys), 3)
        span = "it scored 81 percent on the coding set"
        self.answer(tid, {"members": [
            {"id": keys[0], "label": "new_facts", "facts": [], "claims": []},
            {"id": keys[1], "label": "new_facts", "facts": [{"fact": "81% on coding", "span": span, "about_story": True},
                                                            {"fact": "made up", "span": "it scored 99 percent"}]},
            {"id": keys[2], "label": "opinion", "point": "open weights change who can build", "facts": [], "claims": []}]})
        out = self.stage()
        self.assertEqual(out["done"], 1)                             # one fact line: no merge call needed
        rows = V.current(self.cur, sid)
        self.assertEqual({rows[p]["label"] for p in ps}, {"same", "new_facts", "opinion"})
        self.assertEqual(rows[ps[1]]["facts"][0]["span"], span)
        self.assertEqual(rows[ps[1]]["dropped"], 1)
        self.assertEqual(self.tasks_of("sheet"), [])
        sheet = V.sheet_of(self.cur, sid)
        self.assertEqual([f["fact"] for f in sheet["new_facts"]], ["81% on coding"])
        self.assertEqual(sheet["opinions"][0]["point"], "open weights change who can build")
        self.assertEqual(self.stage()["unchanged"], 1)               # nothing changed: nothing read again

    def test_a_new_member_rejudges_only_its_story_and_rows_close_never_delete(self):
        a, b = self.three(0, "Nimbus"), self.three(3, "Orbit")
        sa, sb = self.story(a), self.story(b)
        self.news((sa, a), (sb, b))
        self.stage()
        self.answer_all([{"label": "opinion", "point": "a point that argues at length about it"}])
        self.assertEqual(self.stage()["done"], 2)
        self.cur.execute("SELECT count(*) FROM mx_perspectives")
        before = self.cur.fetchone()[0]
        new = self.post(5, "Nimbus 5 again", "A fourth voice on Nimbus 5 with a detail: it runs on one GPU with 24 GB, "
                        "which nobody said before, and it loads in under a minute on my machine at home.")
        repo.open_membership(self.cur, story_id=sa, post_id=new, role="member", reason="test", run_id=self.run)
        self.news((sa, a + [new]), (sb, b))
        out = self.stage()
        self.assertEqual((out["unchanged"], out["waiting"]), (1, 1))  # only the story that changed is asked again
        self.answer_all([{"label": "same"}])
        out = self.stage()
        self.assertEqual(out["done"], 1)
        self.cur.execute("SELECT count(*), count(*) FILTER (WHERE valid_to IS NULL) FROM mx_perspectives")
        total, live = self.cur.fetchone()
        self.assertGreater(total, before)                            # closed rows stay
        self.assertEqual(live, 7)

    def test_a_skipped_member_is_asked_alone_then_once_more_then_given_up(self):
        ps = self.three()
        sid = self.story(ps)
        self.news((sid, ps))
        self.stage()
        (tid, text, _), = self.tasks_of("perspective")
        keys = text.rsplit("JUDGE: ", 1)[1].split(", ")
        self.answer(tid, {"members": [{"id": k, "label": "opinion", "point": "a long argument about it all"}
                                      for k in keys[:2]]})                    # the third skipped
        self.stage()
        solo = [t for t in self.tasks_of("perspective", "open")]
        self.assertEqual(len(solo), 1)
        self.assertTrue(solo[0][1].endswith("JUDGE: " + keys[2]))
        self.answer(solo[0][0], {"members": []})                       # skipped again
        self.assertEqual(self.stage()["reasked"], 1)                   # the same task reopened
        self.answer(solo[0][0], {"members": []})
        out = self.stage()
        self.assertEqual((out["done"], out["given_up"]), (1, 1))
        self.assertNotIn(ps[2], V.current(self.cur, sid))

    def test_fewer_than_three_voices_or_entities_still_coming_waits(self):
        ps = self.three()
        ps2 = [ps[0], ps[1], self.post(1, "Nimbus 5 more", "The same source again with other words about Nimbus 5 that "
                                       "nobody else wrote, long enough to count as a post of its own here today.")]
        sid = self.story(ps2)
        self.news((sid, ps2))
        self.assertEqual(self.stage()["fewer_voices"], 1)
        sid3 = self.story(ps)
        self.news((sid3, ps))
        tasks.entities_task(self.cur, ps[0])
        self.assertEqual(self.stage()["waiting_entities"], 1)
        self.assertEqual(self.tasks_of("perspective"), [])

    def test_the_view_and_the_label_buttons(self):
        ps = self.three()
        sid = self.story(ps)
        self.news((sid, ps))
        self.stage()
        span = "it scored 81 percent on the coding set"
        (tid, text, _), = self.tasks_of("perspective")
        keys = text.rsplit("JUDGE: ", 1)[1].split(", ")
        self.answer(tid, {"members": [{"id": keys[0], "label": "original"},
                                      {"id": keys[1], "label": "new_facts", "facts": [{"fact": "81%", "span": span}]},
                                      {"id": keys[2], "label": "opinion", "point": "the price war is on for every lab"}]})
        self.stage()
        view = V.story_view(self.cur, sid)
        self.assertTrue(view["judged"])
        self.assertEqual([m["sign"] for m in view["members"]], ["★", "+", "~"])
        self.assertEqual(view["header"]["text"], V.LAB["text"])
        V.label_perspective(self.cur, story=sid, post=ps[0], answer="right")
        V.label_perspective(self.cur, story=sid, post=ps[2], answer="wrong")
        V.label_perspective(self.cur, story=sid, post=ps[2], answer="same")          # the right label, one tap later
        V.label_fact(self.cur, story=sid, post=ps[1], index=0, answer="not_new")
        with self.assertRaises(ValueError):
            V.label_fact(self.cur, story=sid, post=ps[1], index=0, answer="nope")
        with self.assertRaises(KeyError):
            V.label_fact(self.cur, story=sid, post=ps[1], index=3, answer="right")
        self.cur.execute("SELECT item_kind, answer, split, note FROM mx_labels ORDER BY created_at, ctid")
        got = self.cur.fetchall()
        self.assertEqual([g[:3] for g in got], [("perspective", "right", "test"), ("perspective", "wrong", "test"),
                                                ("perspective", "same", "test"), ("fact", "not_new", "test")])
        self.assertEqual(json.loads(got[0][3])["shown"], "original")
        self.assertEqual(got[3][3], "0: 81%")
        acc = V.accuracy(self.cur)
        self.assertEqual((acc["four"]["k"], acc["four"]["n"]), (1, 2))
        self.assertEqual((acc["worth"]["k"], acc["worth"]["n"]), (1, 2))   # opinion -> same: worth opening wrong
        self.assertEqual(acc["facts"]["answers"], {"not_new": 1})
        self.assertEqual(acc["source"], "lab")
        view = V.story_view(self.cur, sid)
        self.assertEqual(view["members"][2]["mine"]["answer"], "same")
        self.assertEqual(view["members"][1]["facts"][0]["mine"], "not_new")


if __name__ == "__main__":
    unittest.main()
