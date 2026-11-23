"""An entity pair's opinion holds only for what its question showed (0222: mx_opinion_inputs, identity's
void_opinions); the owner's queue shows only flagged items; the entity page's posts carry the sentences around their
mention. Synthetic posts, rolled back after each test."""
from __future__ import annotations

import unittest

from insight_core.markx import entity_answers, entity_views, identity as I, names as N, repo, schemas, tasks
from insight_core.tests.test_markx_entities import D, H, T0, _Db

SAME = {"evidence": "one tool", "relation": "same", "confidence": 0.86}   # below the bar: queued


class _Pairs(_Db):
    def reread(self, pid, *ents, guide="ent-v4"):
        """The post read again under another entities guide (its current set moves to these mentions)."""
        schemas.set_entities_arm(self.cur, guide, allow_placeholder=True)
        task_id, _ = tasks.entities_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                             answer={"entities": []})
        rows = [dict({"span": name, "name": name, "name_key": tasks.name_key(name), "type": type_, "role": role,
                      "maker": None}, **{f: None for f in N.FIELDS}) for name, type_, role in ents]
        repo.add_mentions(self.cur, post_id=pid, guide=repo.get_task(self.cur, task_id)["guide"], call_id=call,
                          mentions=rows)
        schemas.set_entities_arm(self.cur, "ent-v3")

    def kestrel(self):
        """Kestrel Coder (posts a0, a1) and Kestrel Coder CLI (b0, b1): asked, answered `same` below the bar, queued."""
        a = [self.post(n, T0 + n * H, title=f"Kestrel story {n}") for n in range(2)]
        b = [self.post(2 + n, T0 + (2 + n) * H, title=f"Kestrel CLI story {n}") for n in range(2)]
        for p in a:
            self.mentions(p, ("Kestrel Coder", "software", "subject"))
        for p in b:
            self.mentions(p, ("Kestrel Coder CLI", "software", "subject"))
        self.stage()
        self.answer_task("alias", SAME)
        out = self.stage(since=self.since)
        self.assertEqual(out["queued"], 1)
        return a, b

    def inputs(self):
        self.cur.execute("SELECT kind, a::text, b::text, basis, derived FROM mx_opinion_inputs ORDER BY created_at")
        return self.cur.fetchall()


class AnOpinionHoldsForWhatItWasAskedOn(_Pairs):
    def test_the_question_records_what_it_showed_of_each_side(self):
        a, b = self.kestrel()
        (kind, x, y, basis, derived), = [r for r in self.inputs() if r[0] == "alias"]
        self.assertEqual((kind, derived), ("alias", False))
        sides = {s["id"]: s for s in basis["sides"]}
        self.assertEqual(set(sides), {self.entity_of(a[0]), self.entity_of(b[0])})
        self.assertEqual(sorted(sides[self.entity_of(a[0])]["posts"]), sorted(a))
        self.assertEqual(sides[self.entity_of(b[0])]["head"], ["Kestrel Coder CLI", "software", None])

    def test_new_posts_on_a_side_never_void_it(self):
        a, b = self.kestrel()
        for n in range(3):
            self.mentions(self.post(n % 5, T0 + (5 + n) * H, title=f"More Kestrel {n}"),
                          ("Kestrel Coder", "software", "mention"), ("Kestrel Coder CLI", "software", "mention"))
        out = self.stage(since=self.since)
        self.assertEqual((out["void"], out["alias_asked"]), ({"alias": 0, "alias2": 0, "alias3": 0}, 0))
        item, = entity_views.queue(self.cur)["open"]
        self.assertEqual((item["void"], item["opinion"]["confidence"], item["band"]), (None, 0.86, "0.85-0.90"))

    def test_a_side_that_lost_a_post_it_was_asked_on_voids_the_answer(self):
        """A post the question showed is now another entity's: the answer is never shown, banded or applied; the item
        is closed and the pair asked again with what it is now."""
        a, b = self.kestrel()
        self.reread(b[1], ("Borealis Shell", "software", "subject"))   # read again: it names another tool now
        item, = entity_views.queue(self.cur)["open"]
        self.assertEqual((item["void"], item["opinion"], item["band"], item["confidence"], item["evidence"]["judge"]),
                         ("posts", None, None, None, None))
        page = entity_views.entity_page(self.cur, self.entity_of(a[0]))
        self.assertEqual([q["void"] for q in page["queue"]], ["posts"])
        out = self.stage(since=self.since)
        self.assertEqual((out["void"]["alias"], out["queue"]["closed"].get("void"), out["alias_asked"]), (1, 1, 1))
        self.assertEqual(entity_views.queue(self.cur)["open"], [])
        self.cur.execute("SELECT closed_at IS NOT NULL, evidence->>'closed_by', evidence->>'void' FROM mx_entity_queue")
        self.assertEqual(self.cur.fetchall(), [(True, "void", "posts")])   # kept, with why
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'alias'")
        self.assertEqual(self.cur.fetchone()[0], 2)                        # asked again, on its posts now
        self.assertEqual(self.cur.execute("SELECT count(*) FROM mx_entity_redirects").fetchone()[0], 0)
        # the new answer decides: a `same` at the bar merges (the question asked first is the older one)
        self.cur.execute("""UPDATE mx_tasks SET created_at = created_at - interval '1 hour'
                             WHERE kind = 'alias' AND id IN (SELECT task_id FROM mx_calls)""")
        self.cur.execute("SELECT id FROM mx_tasks WHERE kind = 'alias' AND id NOT IN (SELECT task_id FROM mx_calls)")
        tid, = self.cur.fetchone()
        repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True,
                      answer={"evidence": "one tool", "relation": "same", "confidence": 0.95})
        repo.answer_task(self.cur, tid)
        out = self.stage(since=self.since)
        self.assertEqual((out["void"]["alias"], out["merged"]), (0, 1))

    def test_no_merge_is_applied_on_a_void_answer(self):
        a = [self.post(n, T0 + n * H, title=f"Kestrel story {n}") for n in range(2)]
        b = [self.post(2 + n, T0 + (2 + n) * H, title=f"Kestrel CLI story {n}") for n in range(2)]
        for p in a:
            self.mentions(p, ("Kestrel Coder", "software", "subject"))
        for p in b:
            self.mentions(p, ("Kestrel Coder CLI", "software", "subject"))
        self.stage()
        self.answer_task("alias", {"evidence": "one tool", "relation": "same", "confidence": 0.97})   # automatic
        self.reread(a[0], ("Borealis Shell", "software", "subject"))
        out = self.stage(since=self.since)
        self.assertEqual((out["void"]["alias"], out["merged"], out["alias_asked"]), (1, 0, 1))
        book = self.book()
        self.assertNotEqual(book.root(self.entity_of(a[1])), book.root(self.entity_of(b[0])))


class TheReport(_Pairs):
    def test_it_counts_the_automatic_merges_and_open_items_whose_answer_no_longer_holds(self):
        a = [self.post(n, T0 + n * H, title=f"Kestrel story {n}") for n in range(2)]
        b = [self.post(2 + n, T0 + (2 + n) * H, title=f"Kestrel CLI story {n}") for n in range(2)]
        for p in a:
            self.mentions(p, ("Kestrel Coder", "software", "subject"))
        for p in b:
            self.mentions(p, ("Kestrel Coder CLI", "software", "subject"))
        self.stage()
        self.answer_task("alias", {"evidence": "one tool", "relation": "same", "confidence": 0.97})
        self.assertEqual(self.stage(since=self.since)["merged"], 1)
        got = I.opinion_report(self.cur)
        self.assertEqual((got["merges"]["checked"], got["merges"]["void"], got["queue"]["checked"]), (1, 0, 0))
        self.cur.execute("DELETE FROM mx_opinion_inputs")   # asked before inputs were recorded
        self.reread(b[0], ("Borealis Shell", "software", "subject"))
        got = I.opinion_report(self.cur)
        self.assertEqual((got["merges"]["void"], got["merges"]["by_why"], got["merges"]["by"]), (1, {"unmatched": 1}, {"haiku": 1}))
        self.assertEqual(self.inputs(), [])                 # read only


class AQuestionAskedBeforeIsReadBack(_Pairs):
    def test_its_input_says_what_it_showed(self):
        a, b = self.kestrel()
        self.cur.execute("DELETE FROM mx_opinion_inputs")   # asked before inputs were recorded
        item, = entity_views.queue(self.cur)["open"]
        self.assertIsNone(item["void"])                     # read back from its input: it holds
        self.assertEqual(self.inputs(), [])                 # a page writes nothing
        out = self.stage(since=self.since)
        self.assertEqual(out["void"]["alias"], 0)
        (kind, _x, _y, basis, derived), = [r for r in self.inputs() if r[0] == "alias"]
        self.assertTrue(derived)                             # kept by the run, read back once
        self.assertEqual(sorted(p for s in basis["sides"] for p in s["posts"]), sorted(a + b))
        self.reread(b[0], ("Borealis Shell", "software", "subject"))
        self.assertEqual(entity_views.queue(self.cur)["open"][0]["void"], "posts")

    def test_an_example_not_found_on_its_side_now_voids_it(self):
        a, b = self.kestrel()
        self.cur.execute("DELETE FROM mx_opinion_inputs")
        self.reread(b[0], ("Borealis Shell", "software", "subject"))   # moved before the answer was read back
        self.assertEqual(entity_views.queue(self.cur)["open"][0]["void"], "unmatched")
        book = I.lazy_book(self.cur)
        self.cur.execute("SELECT kind, input_hash, a::text, b::text, input FROM mx_tasks WHERE kind = 'alias'")
        rows = self.cur.fetchall()
        got, = I.derive_inputs(self.cur, book, entity_views._guide(), rows).values()
        self.assertEqual(sorted(s.get("unmatched", 0) for s in got["sides"]), [0, 1])


class TheOwnerSeesOnlyFlags(_Pairs):
    def test_the_flagged_view_lists_only_claudes_flags(self):
        self.kestrel()
        flagged = entity_views.queue(self.cur, view="flagged", limit=50)
        self.assertEqual((flagged["open"], flagged["counts"]["flagged"], flagged["counts"]["open"], flagged["view"]),
                         ([], 0, 1, "flagged"))
        item, = entity_views.queue(self.cur, view="all")["open"]
        self.assertIsNone(item["flag"])
        got = entity_answers.flag(self.cur, item["id"], True, note="a plugin, not the tool itself")
        self.assertTrue(got["open"] and got["flagged_by"] == "claude")
        flagged = entity_views.queue(self.cur, view="flagged", limit=50)
        self.assertEqual([i["id"] for i in flagged["open"]], [item["id"]])
        self.assertEqual((flagged["open"][0]["flag"]["note"], flagged["counts"]["flagged"]),
                         ("a plugin, not the tool itself", 1))
        self.assertEqual(entity_views.entity_list(self.cur, now=T0 + D)["flagged"], 1)
        entity_answers.flag(self.cur, item["id"], False)
        self.assertEqual(entity_views.queue(self.cur, view="flagged")["open"], [])
        with self.assertRaises(ValueError):
            entity_answers.flag(self.cur, item["id"], True, by="someone")
        with self.assertRaises(ValueError):
            entity_views.queue(self.cur, view="mine")


class MentionContext(unittest.TestCase):
    TEXT = ("Acme shipped a lot this week. The team says it rewrote the planner. Kestrel Coder now runs hooks before "
            "each tool call. Users of kestrel coder can also share sessions. Pricing is unchanged. More next week.")

    def test_the_sentences_around_the_mention_with_every_mention_marked(self):
        parts = entity_views.mention_context(self.TEXT, ["Kestrel Coder"])
        text = "".join(p["t"] for p in parts)
        self.assertIn("Kestrel Coder now runs hooks", text)
        self.assertLessEqual(len(text), entity_views.CONTEXT_WINDOW + 4)
        self.assertEqual([p["t"] for p in parts if p.get("m")], ["Kestrel Coder", "kestrel coder"])
        self.assertTrue(2 <= text.count(". ") + 1 <= 4)

    def test_no_mention_no_context_and_whole_words_only(self):
        self.assertIsNone(entity_views.mention_context(self.TEXT, ["Borealis"]))
        self.assertIsNone(entity_views.mention_context("Uncommunity", ["unity"]))
        self.assertIsNone(entity_views.mention_context(None, ["Kestrel"]))

    def test_a_long_sentence_is_cut_around_the_mention(self):
        text = "word " * 300 + "Kestrel Coder is fast " + "word " * 300
        parts = entity_views.mention_context(text, ["Kestrel Coder"])
        whole = "".join(p["t"] for p in parts)
        self.assertTrue(whole.startswith("… ") and whole.endswith(" …"))
        self.assertLessEqual(len(whole), entity_views.CONTEXT_WINDOW + 4)
        self.assertEqual([p["t"] for p in parts if p.get("m")], ["Kestrel Coder"])

    def test_the_text_naming_it_before_a_web_address(self):
        text = "See https://github.com/acme/math for the code. Acme released the proofs today."
        parts = entity_views.mention_context(text, ["Acme"])
        whole = "".join(p["t"] for p in parts)
        self.assertIn("Acme released the proofs today.", whole)
        self.assertEqual(entity_views._find(text.lower(), ["acme"]), (47, 51))
        only = entity_views.mention_context("Code: github.com/acme/math", ["Acme"])
        self.assertEqual([p["t"] for p in only if p.get("m")], ["acme"])   # named nowhere else: the address

    def test_any_script_and_a_handle(self):
        parts = entity_views.mention_context("Строка\nКестрел вышел 🚀 сегодня.\nЕщё строка", ["Кестрел"])
        self.assertEqual([p["t"] for p in parts if p.get("m")], ["Кестрел"])
        parts = entity_views.mention_context("Using @acme_ai tools today.", ["acme_ai"])
        self.assertEqual([p["t"] for p in parts if p.get("m")], ["acme_ai"])


class ThePagesPostsCarryTheirMention(_Pairs):
    def test_each_post_about_it_shows_the_sentences_naming_it(self):
        p = self.post(0, T0, title="Weekly notes",
                      text="Weekly notes. Nothing about tools first. Then Kestrel Coder got hooks. The end.")
        q = self.post(1, T0 + H, title="Kestrel Coder ships", text="A short one.")
        self.mentions(p, ("Kestrel Coder", "software", "subject"))
        self.mentions(q, ("Kestrel Coder", "software", "subject"))
        self.stage()
        page = entity_views.entity_page(self.cur, self.entity_of(p), now=T0 + D)
        by = {ln["id"]: ln for ln in page["loose"]}
        marked = [x["t"] for x in by[p]["context"] if x.get("m")]
        self.assertEqual(marked, ["Kestrel Coder"])
        self.assertIn("Then Kestrel Coder got hooks.", "".join(x["t"] for x in by[p]["context"]))
        self.assertIsNone(by[q]["context"])   # named only in its title: the title stands alone
        entity_views.CONTEXT_ON = False
        try:
            off = entity_views.entity_page(self.cur, self.entity_of(p), now=T0 + D)
        finally:
            entity_views.CONTEXT_ON = True
        self.assertTrue(all("context" not in ln for ln in off["loose"]))


if __name__ == "__main__":
    unittest.main()
