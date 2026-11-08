"""Issue 0133 v4.2 (ent-v4.2 in Shadow): the switch arm, the main question at 6,000 characters, the second question
(`cite`: its schema, its input, planned only for cue posts), the merge (own-title drop, cite_fix, merge_cite, q2
marks), the citation rule off, and the owner's right / wrong labels and their running precision. Fixed answers,
never the guides' wording. Synthetic posts with invented names; the database tests roll back."""
from __future__ import annotations

import hashlib
import unittest

from insight_core.markx import ent42 as E, news, repo, schemas, tasks, validate
from insight_core.tests._db import requires_test_db
from insight_core.tests.test_markx_entities import T0, H, _Db

LONG = "Word " * 600 + "The tail names Kestrel Report."     # past 1,500 characters, inside 6,000


def ent(span, name, type_, role, **kw):
    return dict({"span": span, "name": name, "type": type_, "role": role, "maker": None, "family": None,
                 "version": None, "variant": None, "size": None, "build": None}, **kw)


def post(title="T", text="", links=()):
    return tasks.Post(id="x", kind="telegram", source="Example", source_id="s", at=T0, title=title, text=text,
                      links=[(u, a) for u, a in links])


class TheArm(unittest.TestCase):
    def test_the_guides_are_the_labs_byte_for_byte(self):
        md5 = lambda g: hashlib.md5((schemas.GUIDES_DIR / f"{g}.md").read_bytes()).hexdigest()
        self.assertEqual(md5("ent-v4.2"), "81c469a1a9a0dce9128e2672e3c40089")
        self.assertEqual(md5("cite-v1"), "4e46eca8e320f831d88dde2130bc681a")

    def test_the_arm_reads_6000_with_v4s_schema_and_no_rule_and_the_default_is_unchanged(self):
        arm = schemas.ENTITY_ARMS["ent-v4.2"]
        self.assertEqual((arm.chars, arm.rule, arm.schema), (6000, False, schemas.ENTITIES_V4_SCHEMA))
        self.assertEqual(schemas.DEFAULT_ARM, "ent-v3")
        self.assertFalse(schemas.is_placeholder("ent-v4.2"))
        self.assertEqual(schemas.KINDS["cite"].guide, "cite-v1")

    def test_the_cite_input_is_6000_characters_and_the_first_12_links(self):
        p = post(text=LONG, links=[(f"https://example.com/a/{n}", None) for n in range(15)])
        got = E.cite_input(p)
        self.assertIn("Kestrel Report", got)
        self.assertIn("https://example.com/a/11", got)
        self.assertNotIn("https://example.com/a/12", got)
        self.assertNotIn("Kestrel Report", tasks.entities_input(p))          # ent-v3's cut is unchanged


class TheCiteSchema(unittest.TestCase):
    INPUT = "Title: T\nText: Per Varga et al. (2021) and Acme Corp, read Deep Book; Ivo Lind said so."

    def check(self, *ents):
        return validate.check("cite", {"entities": list(ents)}, self.INPUT, "cite-v1")[1]

    def test_documents_orgs_and_people_in_their_roles(self):
        self.assertIsNone(self.check(ent("Varga et al. (2021)", "Varga et al. 2021", "document", "source"),
                                     ent("Deep Book", "Deep Book", "document", "recommended", by=None),
                                     ent("Deep Book", "Deep Book", "document", "subject"),
                                     ent("Acme Corp", "Acme Corp", "org", "source"),
                                     ent("Ivo Lind", "Ivo Lind", "person", "source")))

    def test_what_it_refuses(self):
        self.assertIsNotNone(self.check(ent("Acme Corp", "Acme Corp", "org", "recommended")))   # org: source only
        self.assertIsNotNone(self.check(ent("Ivo Lind", "Ivo Lind", "person", "subject")))
        self.assertIsNotNone(self.check(ent("Acme Corp", "Acme Corp", "model", "source")))      # three types only
        self.assertIsNotNone(self.check(ent("Nowhere Paper", "Nowhere Paper", "document", "source")))  # not in the post
        self.assertIsNotNone(self.check(*[ent("Acme Corp", "Acme Corp", "org", "source")] * 31))       # at most 30
        self.assertIsNone(self.check(*[ent("Acme Corp", "Acme Corp", "org", "source")] * 30))


class TheCue(unittest.TestCase):
    def test_what_picks_a_post(self):
        two = "A report by the lab and a survey of users. " + "More words here. " * 50       # >= 800, 2 cues
        self.assertTrue(E.cue(post(text=two)))
        self.assertFalse(E.cue(post(text=two[:300])))                                         # short: cues alone don't
        self.assertFalse(E.cue(post(text="A report. " + "More words here. " * 60)))           # one distinct cue
        self.assertTrue(E.cue(post(text="As Varga et al. (2021) showed.")))                    # an in-text citation
        self.assertTrue(E.cue(post(text="Петров и др. (2020) пишут.")))
        self.assertTrue(E.cue(post(text="See arXiv:2401.01234 now.")))
        self.assertTrue(E.cue(post(text="doi 10.1145/3366423.3380000 here")))
        self.assertTrue(E.cue(post(text="short", links=[("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7483387/", None)])))
        self.assertFalse(E.cue(post(text="Acme shipped a thing today.", links=[("https://example.com/blog/a-post", None)])))
        self.assertFalse(E.cue(post(text="In March (2021) it rained.")))                      # a month is no author

    def test_a_link_past_the_twelfth_is_not_read(self):
        links = [("https://example.com/blog/x", None)] * 12 + [("https://arxiv.org/abs/2401.01234", None)]
        self.assertFalse(E.cue(post(text="short", links=links)))

    def test_link_shapes(self):
        shapes = {
            "https://arxiv.org/abs/2401.01234": "arxiv",
            "https://journal.example/doi/10.5555/abc.123": "doi",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC7483387/": "pmc",
            "https://pubmed.ncbi.nlm.nih.gov/40472744/": "pubmed",
            "https://www.sciencedirect.com/science/article/pii/S2666560326001076": "pii",
            "https://www.rfc-editor.org/rfc/rfc9147.html": "rfc",
            "https://ecma-international.org/publications-and-standards/standards/ecma-404/": "ecma",
            "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3213954": "ssrn",
            "https://osf.io/abcde/": "osf",
            "https://www.nature.com/articles/s41586-025-08617-8": "natid",
            "https://aclanthology.org/2022.findings-naacl.130/": "acl",
            "https://example.com/blog/a-post": None,
            "https://example.com/": None,
        }
        self.assertEqual({u: (E.shape(u) or (None,))[0] for u in shapes}, shapes)


class TheMerge(unittest.TestCase):
    P = post(title="Scaling Laws for Tiny Orbit Models")

    def test_the_posts_own_title_is_dropped_from_both(self):
        own = ent("Scaling Laws for Tiny Orbit Models", "Scaling Laws for Tiny Orbit Models", "document", "subject")
        got = E.finish([own, ent("Acme", "Acme", "org", "actor")], self.P.title,
                       [dict(own, role="source"), ent("Varga et al. (2021)", "Varga et al. 2021", "document", "source")])
        self.assertEqual([(e["name"], bool(e.get("q2"))) for e in got], [("Acme", False), ("Varga et al. 2021", True)])

    def test_cite_fix_makes_an_author_year_person_a_document(self):
        got = E.cite_fix(ent("Varga et al. (2021)", "Varga et al.", "person", "source"))
        self.assertEqual((got["type"], got["role"], got["name"]), ("document", "source", "Varga et al. 2021"))
        plain = ent("Ivo Lind", "Ivo Lind", "person", "source")
        self.assertEqual(E.cite_fix(plain), plain)

    def test_what_merge_cite_skips_and_adds(self):
        main = [ent("Orbit-7", "Orbit-7", "model", "subject"), ent("Acme Corp", "Acme Corp", "org", "actor")]
        cite = [ent("The Nimbus Review", "The Nimbus Review", "document", "subject"),         # subject: the main's job
                ent("current state of the debate", "Debate Overview", "document", "source"),  # describes, not names
                ent("Orbit-7", "Orbit-7", "document", "source"),                              # the main typed it a model
                ent("Acme Corp", "Acme Corp", "org", "source"),                               # the main has it
                ent("Kestrel Report", "Kestrel Report", "document", "source", by="Acme Corp"),
                ent("Ivo Lind", "Ivo Lind", "person", "source")]
        got = E.merge_cite(main, cite)
        self.assertEqual([(e["name"], bool(e.get("q2"))) for e in got],
                         [("Orbit-7", False), ("Acme Corp", False), ("Kestrel Report", True), ("Ivo Lind", True)])

    def test_name_span(self):
        self.assertTrue(E.name_span("Kestrel Report"))
        self.assertTrue(E.name_span("“Deep Book”"))
        self.assertTrue(E.name_span("arxiv.org/abs/2401.01234"))
        self.assertTrue(E.name_span("2024 survey of users"))
        self.assertFalse(E.name_span("the current state"))


@requires_test_db
class InShadow(_Db):
    CITED = "As Varga et al. (2021) showed, Acme grew. " + "More words. " * 10

    def switch(self, guide="ent-v4.2"):
        schemas.set_entities_arm(self.cur, guide)

    def answer(self, kind, pid, entities):
        task_id, _ = (tasks.entities_task if kind == "entities" else E.cite_task)(self.cur, pid)
        task = repo.get_task(self.cur, task_id)
        answer = {"entities": entities, "relations": []} if kind == "entities" else {"entities": entities}
        self.assertIsNone(validate.check(kind, answer, task["input"], task["guide"])[1])
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer=answer)
        repo.answer_task(self.cur, task_id)
        tasks.record(self.cur, task, call, answer)
        return task

    def now(self, p):
        self.cur.execute("SELECT name, type, role, rule FROM mx_mentions_now WHERE post_id = %s ORDER BY n", (p,))
        return self.cur.fetchall()

    def test_cite_tasks_are_planned_only_for_cue_posts_and_only_under_ent_v42(self):
        cited = self.post(0, T0, text=self.CITED)
        plain = self.post(1, T0, text="Acme shipped a thing. More words about it here.")
        self.assertEqual(tasks.PLANNERS["cite"](self.cur, days=1, now=T0 + H), 0)          # ent-v3: never
        self.switch()
        tasks.PLANNERS["entities"](self.cur, days=1, now=T0 + H)
        self.assertEqual(tasks.PLANNERS["cite"](self.cur, days=1, now=T0 + H), 1)
        self.assertEqual(tasks.PLANNERS["cite"](self.cur, days=1, now=T0 + H), 0)          # asked once
        self.cur.execute("SELECT kind, guide, a::text, input LIKE '%%Varga%%' FROM mx_tasks ORDER BY kind, a = %s DESC", (cited,))
        rows = self.cur.fetchall()
        self.assertEqual(sorted((k, g) for k, g, _a, _i in rows),
                         [("cite", "cite-v1"), ("entities", "ent-v4.2"), ("entities", "ent-v4.2")])
        self.assertEqual([(a, i) for k, _g, a, i in rows if k == "cite"], [(cited, True)])
        self.assertIn("cite", tasks.WINDOWED)
        self.assertNotIn(plain, [a for k, _g, a, _i in rows if k == "cite"])

    def test_main_then_cite_appends_the_q2_entities_and_runs_no_rule(self):
        self.switch()
        p = self.post(0, T0, title="Acme grew", text=self.CITED + " https://arxiv.org/abs/2401.01234")
        self.answer("entities", p, [ent("Acme", "Acme", "org", "subject")])
        self.assertEqual(self.now(p), [("Acme", "org", "subject", None)])                   # no citation rule
        self.answer("cite", p, [ent("Varga et al. (2021)", "Varga et al.", "person", "source"),
                                ent("Acme", "Acme", "org", "source")])
        self.assertEqual(self.now(p), [("Acme", "org", "subject", None),
                                       ("Varga et al. 2021", "document", "source", "q2")])
        self.assertEqual(repo.current_guide(self.cur, p), "ent-v4.2")

    def test_cite_then_main_merges_when_the_main_answer_comes(self):
        self.switch()
        p = self.post(0, T0, title="Acme grew", text=self.CITED)
        self.answer("cite", p, [ent("Varga et al. (2021)", "Varga et al. 2021", "document", "source")])
        self.assertEqual(self.now(p), [])                                                    # waits for the main answer
        self.answer("entities", p, [ent("Acme grew", "Acme grew", "document", "subject"),   # its own title: dropped
                                    ent("Acme", "Acme", "org", "actor")])
        self.assertEqual(self.now(p), [("Acme", "org", "actor", None),
                                       ("Varga et al. 2021", "document", "source", "q2")])

    def test_the_panel_marks_q2_and_labels_count_toward_the_running_precision(self):
        self.switch()
        p = self.post(0, T0, title="Acme grew", text=self.CITED + " Read Deep Book.")
        self.answer("entities", p, [ent("Acme", "Acme", "org", "subject"),
                                    ent("Deep Book", "Deep Book", "document", "recommended")])
        self.answer("cite", p, [ent("Varga et al. (2021)", "Varga et al. 2021", "document", "source")])
        panel = news.post_panel(self.cur, p)
        rows = {e["name"]: e for e in panel["entities"]}
        self.assertEqual({n: (e["q2"], e["new"]) for n, e in rows.items()},
                         {"Acme": (False, False), "Deep Book": (False, True), "Varga et al. 2021": (True, True)})
        E.label(self.cur, post=p, guide="ent-v4.2", n=rows["Deep Book"]["n"], answer="wrong")
        E.label(self.cur, post=p, guide="ent-v4.2", n=rows["Deep Book"]["n"], answer="right")   # the newest counts
        E.label(self.cur, post=p, guide="ent-v4.2", n=rows["Varga et al. 2021"]["n"], answer="wrong")
        with self.assertRaises(ValueError):
            E.label(self.cur, post=p, guide="ent-v4.2", n=rows["Acme"]["n"], answer="right")   # not a new entity
        got = E.precision(self.cur)
        self.assertEqual((got["labelled"], got["right"]), (2, 1))
        self.assertEqual((got["q2"]["labelled"], got["q2"]["right"]), (1, 0))
        self.assertEqual(got["lab"], "lab: 89–93% precise, finds about 62%; post hoc")
        self.assertEqual({e["name"]: e["label"] for e in news.post_panel(self.cur, p)["entities"]},
                         {"Acme": None, "Deep Book": "right", "Varga et al. 2021": "wrong"})

    def test_migration_0087_runs_again(self):
        from pathlib import Path
        sql = (Path(repo.__file__).resolve().parents[1] / "db" / "migrations" / "0087_markx_ent_v42.sql").read_text()
        self.cur.execute(sql)
        self.cur.execute(sql)
        self.cur.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'mx_labels_item_kind_check'")
        self.assertIn("'mention'", self.cur.fetchone()[0])


if __name__ == "__main__":
    unittest.main()
