"""Issue 0133 (ent-v4): the entities guide switch and its cut, `paper` read as `document`, the new roles, `by` as a
`published` edge, the citation rule (each first-set pattern on fixed English and Russian texts, the identifiers, the
document links) and its merge with the model's mentions, re-extraction as new tasks, the newest valid answer as the
current set, the pages, and surges that ignore `source` and `recommended`. Fixed answers, never the guide's wording.
Synthetic posts with invented names; the database tests roll back (a database whose name ends in _test)."""
from __future__ import annotations

import unittest
from datetime import timedelta

from insight_core.markx import citations as C
from insight_core.markx import entity_views, identity as I, news, repo, schemas, surges as S, tasks, validate
from insight_core.markx.candidates import SPECIFIC_TYPES
from insight_core.tests._db import requires_test_db
from insight_core.tests.test_markx_entities import T0, H, D, _Db

DOCS = "The Orbit Filing and the Deep Book, both."
LONG = "Word " * 600 + "The tail names Kestrel Report."     # past 1,500 characters, inside 6,000


def ent(span, name, type_, role, **kw):
    return dict({"span": span, "name": name, "type": type_, "role": role, "maker": None, "family": None,
                 "version": None, "variant": None, "size": None, "build": None}, **kw)


class TheSwitch(unittest.TestCase):
    def test_the_default_is_ent_v3_at_1500_without_the_rule(self):
        arm = schemas.ENTITY_ARMS[schemas.DEFAULT_ARM]
        self.assertEqual((arm.guide, arm.chars, arm.rule), ("ent-v3", 1500, False))
        self.assertEqual(schemas.KINDS["entities"].guide, "ent-v3")        # the readers that name it read ent-v3
        v4 = schemas.ENTITY_ARMS["ent-v4"]
        self.assertEqual((v4.chars, v4.rule), (tasks.ENTITY_TEXT_CHARS, True))
        self.assertEqual(tasks.ENTITY_TEXT_CHARS, 6000)

    def test_the_cut_is_used_by_entities_only(self):
        p = tasks.Post(id="x", kind="telegram", source="Example", source_id="s", at=T0, title="T", text=LONG)
        self.assertNotIn("Kestrel Report", tasks.read_input(p))            # read keeps 1,500
        self.assertNotIn("Kestrel Report", tasks.entities_input(p))        # ent-v3's default cut
        self.assertIn("Kestrel Report", tasks.entities_input(p, tasks.ENTITY_TEXT_CHARS))
        self.assertEqual(tasks.TEXT_CHARS, 1500)

    def test_the_placeholder_guide_is_marked(self):
        self.assertTrue(schemas.is_placeholder("ent-v4"))                   # until the lab's frozen guide replaces it
        self.assertFalse(schemas.is_placeholder("ent-v3"))
        self.assertEqual(schemas.guide_body("ent-v3-6k"), schemas.guide_body("ent-v3"))


class PaperIsDocument(unittest.TestCase):
    def test_every_reader_reads_paper_as_document(self):
        self.assertEqual(schemas.entity_type("paper"), "document")
        self.assertEqual(schemas.entity_type("org"), "org")
        self.assertTrue(I.types_ok("paper", "document"))                    # identity
        self.assertIn("document", SPECIFIC_TYPES)                           # candidates
        self.assertIn("paper", schemas.stored_types(SPECIFIC_TYPES))       # ... matching ent-v3's stored rows
        self.assertNotIn("paper", schemas.ENTITY_TYPES_V4)
        self.assertIn("paper", schemas.ENTITY_TYPES)                        # ent-v3's schema is unchanged


class TheRoles(unittest.TestCase):
    TEXT = "Platform: telegram | Source: Example\nTitle: T\nText: Per the Orbit Filing by Acme Corp, read Deep Book."

    def check(self, guide, *ents):
        return validate.check("entities", {"entities": list(ents), "relations": []}, self.TEXT, guide)[1]

    def test_the_new_roles_and_type_validate_under_ent_v4_only(self):
        a = ent("Orbit Filing", "Orbit Filing", "document", "source", by="Acme Corp")
        b = ent("Deep Book", "Deep Book", "document", "recommended")
        c = ent("Acme Corp", "Acme Corp", "org", "source")
        self.assertIsNone(self.check("ent-v4", a, b, c))
        self.assertIsNotNone(self.check("ent-v3", a))                       # ent-v3: no document, no source
        self.assertIsNotNone(self.check(None, a))                           # the kind's own schema is ent-v3's
        self.assertIsNone(self.check("ent-v3", ent("Orbit Filing", "Orbit Filing", "paper", "mention")))

    def test_recommended_is_a_document_only(self):
        self.assertIn("only a document", self.check("ent-v4", ent("Acme Corp", "Acme Corp", "org", "recommended")))


class TheRule(unittest.TestCase):
    def names(self, text, links=()):
        return [(h.how, h.name) for h in C.find(text, links)]

    def test_each_in_text_shape_in_english(self):
        self.assertEqual(self.names("As Varga et al. (2021) showed"), [("etal", "Varga et al. 2021")])
        self.assertEqual(self.names("see Varga et al., 2021."), [("etal", "Varga et al. 2021")])
        self.assertEqual(self.names("Ostrom & Lind (2019) argue"), [("two_paren", "Ostrom and Lind 2019")])
        self.assertEqual(self.names("Ostrom and Lind (2019) argue"), [("two_paren", "Ostrom and Lind 2019")])
        self.assertEqual(self.names("as in Ostrom and Lind, 2019, the"), [("two_comma", "Ostrom and Lind 2019")])
        self.assertEqual(self.names("Hallberg (2018b) found"), [("one_paren", "Hallberg 2018b")])

    def test_each_in_text_shape_in_russian(self):
        self.assertEqual(self.names("Как показал Петров и др. (2020), рост"), [("etal", "Петров et al. 2020")])
        self.assertEqual(self.names("Петров и Сомов (2017) пишут"), [("two_paren", "Петров and Сомов 2017")])
        self.assertEqual(self.names("по данным Петров и Сомов, 2017, рост"), [("two_comma", "Петров and Сомов 2017")])
        self.assertEqual(self.names("Сомов (2016) считал"), [("one_paren", "Сомов 2016")])

    def test_a_longer_shape_takes_its_span_once(self):
        got = self.names("Varga et al. (2021) and Hallberg (2018) and Ostrom & Lind (2019)")
        self.assertEqual([n for _, n in got], ["Varga et al. 2021", "Hallberg 2018", "Ostrom and Lind 2019"])

    def test_no_hit_without_a_year_or_a_name(self):
        self.assertEqual(self.names("the results (2021) were good; acme (2020); Varga et al. said"), [])

    def test_identifiers(self):
        got = C.find("See arXiv:2401.01234v2, https://arxiv.org/abs/2402.05678 and doi 10.1145/3366423.3380000. "
                     "Also 10.48550/arXiv.2403.09999 and arxiv.org/pdf/2401.01234v3.")
        self.assertEqual([h.ref for h in got],
                         ["arXiv:2401.01234", "arXiv:2402.05678", "arXiv:2403.09999", "doi:10.1145/3366423.3380000"])
        self.assertTrue(all((h.ref, h.name) == (h.ref, h.ref) for h in got))

    def test_links_to_documents_only(self):
        got = C.find("", ["https://arxiv.org/abs/2405.00001", "https://example.com/blog/a-post",
                          "https://journal.example/doi/10.5555/abc.123"])
        self.assertEqual([h.ref for h in got], ["arXiv:2405.00001", "doi:10.5555/abc.123"])
        self.assertEqual(got[0].how, "link")

    def test_hits_are_cited_documents_of_the_rule(self):
        m = C.find("Varga et al. (2021)")[0].mention(tasks.name_key)
        self.assertEqual((m["type"], m["role"], m["rule"], m["span"]), ("document", "source", "citation", "Varga et al. (2021)"))


class TheMerge(unittest.TestCase):
    def merged(self, model, text, links=()):
        ms = [dict(e, name_key=tasks.name_key(e["name"])) for e in model]
        return C.merge(ms, C.find(text, links), tasks.name_key)

    def test_by_arxiv_id(self):
        got = self.merged([ent("the Nimbus paper (arXiv:2401.01234)", "Nimbus Scaling Paper", "document", "mention")],
                          "the Nimbus paper (arXiv:2401.01234)")
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["name"], got[0]["role"], got[0]["rule"], got[0]["ref"], got[0]["span"]),
                         ("Nimbus Scaling Paper", "mention", "citation", "arXiv:2401.01234", "arXiv:2401.01234"))

    def test_by_doi(self):
        got = self.merged([ent("doi:10.1145/3366423", "Orbit Study", "document", "source")], "doi:10.1145/3366423")
        self.assertEqual([(m["name"], m["role"], m["rule"]) for m in got], [("Orbit Study", "source", "citation")])

    def test_by_identity_key(self):
        got = self.merged([ent("Varga et al.", "Varga et al. 2021", "document", "subject")], "Varga et al. (2021)")
        self.assertEqual([(m["role"], m["rule"], m["span"]) for m in got], [("subject", "citation", "Varga et al. (2021)")])

    def test_a_different_thing_is_its_own_mention_after_the_models(self):
        got = self.merged([ent("Acme", "Acme", "org", "actor")], "Hallberg (2018) and https://arxiv.org/abs/2405.00001")
        self.assertEqual([(m["name"], m.get("rule")) for m in got],
                         [("Acme", None), ("arXiv:2405.00001", "citation"), ("Hallberg 2018", "citation")])


@requires_test_db
class StoredAndRead(_Db):
    def answer(self, pid, entities, guide=None):
        """An entities task of the post under the switched-to guide, answered with `entities` and recorded."""
        task_id, _ = tasks.entities_task(self.cur, pid)
        task = repo.get_task(self.cur, task_id)
        answer = {"entities": entities, "relations": []}
        self.assertIsNone(validate.check("entities", answer, task["input"], task["guide"])[1])
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer=answer)
        repo.answer_task(self.cur, task_id)
        tasks.record(self.cur, task, call, answer)
        return task

    def switch(self, guide):
        schemas.set_entities_arm(self.cur, guide, allow_placeholder=True)

    def test_the_placeholder_is_refused_and_the_default_is_ent_v3(self):
        self.assertEqual(schemas.entities_arm(self.cur).guide, "ent-v3")
        with self.assertRaises(ValueError):
            schemas.set_entities_arm(self.cur, "ent-v4")
        with self.assertRaises(ValueError):
            schemas.set_entities_arm(self.cur, "ent-v9")
        self.assertEqual(schemas.entities_arm(self.cur).guide, "ent-v3")

    def test_the_migration_fills_the_sets_from_stored_ent_v3_and_runs_again(self):
        from pathlib import Path
        sql = (Path(repo.__file__).resolve().parents[1] / "db" / "migrations" / "0082_markx_ent_v4.sql").read_text()
        p = self.post(0, T0)
        self.mentions(p, ("Acme", "org", "subject"))
        self.cur.execute("DELETE FROM mx_mention_sets WHERE post_id = %s", (p,))   # as before 0082
        self.cur.execute(sql)
        self.cur.execute(sql)                                                       # idempotent
        self.assertEqual(repo.current_guide(self.cur, p), "ent-v3")
        self.cur.execute("SELECT name, rule, by_name, ref FROM mx_mentions_now WHERE post_id = %s", (p,))
        self.assertEqual(self.cur.fetchall(), [("Acme", None, None, None)])

    def test_the_owners_split_carries_to_the_new_guides_mention_of_the_same_name(self):
        p = self.post(0, T0, text="Acme Labs shipped it.")
        self.mentions(p, ("Acme Labs", "org", "subject"))
        self.stage()
        self.cur.execute("INSERT INTO mx_entities (type, name, key) VALUES ('org', 'Acme Labs (the other)', 'acme labs the other') "
                         "RETURNING id::text")
        other = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO mx_entity_pins (post_id, guide, n, entity_id) VALUES (%s, 'ent-v3', 0, %s)", (p, other))
        self.switch("ent-v4")
        self.answer(p, [ent("Acme Labs", "Acme Labs", "org", "subject")])
        self.stage()
        self.cur.execute("SELECT entity_id::text FROM mx_mentions WHERE post_id = %s AND guide = 'ent-v4'", (p,))
        self.assertEqual(self.cur.fetchone()[0], other)

    def test_ent_v3_runs_no_rule(self):
        p = self.post(0, T0, text="As Varga et al. (2021) showed, Acme grew. https://arxiv.org/abs/2401.01234")
        self.answer(p, [ent("Acme", "Acme", "org", "subject")])
        self.assertEqual([(m["name"], m["rule"]) for m in repo.mentions(self.cur, p)], [("Acme", None)])

    def test_a_guide_change_plans_new_tasks_and_the_newest_answer_is_current(self):
        p = self.post(0, T0, text=LONG + " Varga et al. (2021) is cited.")
        self.answer(p, [ent("Word", "Word Corp", "org", "subject")])
        before = repo.mentions(self.cur, p)
        self.assertEqual(tasks.plan_posts(self.cur, "entities", days=1, now=T0 + H), 0)   # ent-v3: asked already
        self.switch("ent-v4")
        self.assertEqual(tasks.plan_posts(self.cur, "entities", days=1, now=T0 + H), 1)   # a new ent-v4 task
        self.cur.execute("SELECT guide, input LIKE %s FROM mx_tasks WHERE kind = 'entities' AND a = %s ORDER BY created_at",
                         ("%Kestrel Report%", p))
        self.assertEqual(self.cur.fetchall(), [("ent-v3", False), ("ent-v4", True)])        # the 6,000 cut
        self.assertEqual(repo.current_guide(self.cur, p), "ent-v3")
        self.answer(p, [ent("Kestrel Report", "Kestrel Report", "document", "source", by="Word Corp")])
        self.assertEqual(repo.current_guide(self.cur, p), "ent-v4")
        self.assertEqual(repo.mentions(self.cur, p, "ent-v3"), before)                      # no row rewritten
        self.cur.execute("SELECT guide, name, rule FROM mx_mentions_now WHERE post_id = %s ORDER BY n", (p,))
        self.assertEqual(self.cur.fetchall(), [("ent-v4", "Kestrel Report", None),
                                               ("ent-v4", "Varga et al. 2021", "citation")])
        panel = news.post_panel(self.cur, p)
        self.assertEqual(panel["entities_guide"], "ent-v4")
        self.assertEqual([e["name"] for e in panel["sources"]], ["Kestrel Report", "Varga et al. 2021"])
        self.assertEqual(panel["sources"][1]["rule"], "citation")

    def test_an_empty_newer_answer_is_current_too(self):
        p = self.post(0, T0)
        self.answer(p, [ent("Acme", "Acme", "org", "subject")])
        self.switch("ent-v3-6k")
        self.answer(p, [])
        self.assertEqual(repo.current_guide(self.cur, p), "ent-v3-6k")
        self.cur.execute("SELECT count(*) FROM mx_mentions_now WHERE post_id = %s", (p,))
        self.assertEqual(self.cur.fetchone()[0], 0)
        self.cur.execute("SELECT count(*) FROM mx_mentions WHERE post_id = %s", (p,))
        self.assertEqual(self.cur.fetchone()[0], 1)                                           # kept

    def test_by_is_a_published_edge_and_the_document_page_shows_who_cites_and_recommends(self):
        self.switch("ent-v4")
        a = self.post(0, T0, text="Per the Orbit Filing by Acme Corp, revenue rose.")
        b = self.post(1, T0 + H, text="Read the Orbit Filing, then decide.")
        self.answer(a, [ent("Orbit Filing", "Orbit Filing", "document", "source", by="Acme Corp"),
                        ent("Acme Corp", "Acme Corp", "org", "actor")])
        self.answer(b, [ent("Orbit Filing", "Orbit Filing", "document", "recommended")])
        out = self.stage()
        self.assertEqual(out["link"]["published"], 1)
        doc, acme = self.entity_of(a, 0), self.entity_of(a, 1)
        self.assertEqual(self.entity_of(b, 0), doc)
        self.cur.execute("""SELECT a::text, b::text, rule FROM mx_connections WHERE relation = 'published'
                              AND a_kind = 'entity' AND b_kind = 'entity' AND valid_to IS NULL""")
        self.assertEqual(self.cur.fetchall(), [(acme, doc, "mention_by")])
        page = entity_views.entity_page(self.cur, doc, now=T0 + D)
        self.assertEqual(page["entity"]["type"], "document")
        self.assertEqual([x["name"] for x in page["published_by"]], ["Acme Corp"])
        self.assertEqual([x["id"] for x in page["citing"]], [a])
        self.assertEqual([x["id"] for x in page["recommending"]], [b])
        self.assertEqual([x["name"] for x in entity_views.entity_page(self.cur, acme, now=T0 + D)["published"]],
                         ["Orbit Filing"])
        self.assertEqual(self.stage(full=True)["check"], {"same": True, "relinked": 0})

    def test_one_arxiv_id_is_one_entity_whatever_each_post_calls_it(self):
        self.switch("ent-v4")
        a = self.post(0, T0, text="The Nimbus paper (arXiv:2401.01234) is out.")
        b = self.post(1, T0 + H, text="Cited: https://arxiv.org/abs/2401.01234v2 again.")
        self.answer(a, [ent("The Nimbus paper (arXiv:2401.01234)", "Nimbus Scaling Paper", "document", "subject")])
        self.answer(b, [])
        self.stage()
        self.cur.execute("SELECT post_id::text, name, ref, rule FROM mx_mentions_now ORDER BY post_id = %s DESC", (a,))
        self.assertEqual([r[1:] for r in self.cur.fetchall()],
                         [("Nimbus Scaling Paper", "arXiv:2401.01234", "citation"),    # merged: the model's name
                          ("arXiv:2401.01234", "arXiv:2401.01234", "citation")])      # the rule's alone
        self.assertEqual(self.entity_of(a), self.entity_of(b))                          # one entity by the id

    def test_surges_ignore_source_and_recommended(self):
        self.switch("ent-v4")
        for n in range(3):
            self.answer(self.post(n, T0 + n * H, title="Post a", text=DOCS), [ent("Orbit Filing", "Orbit Filing", "document", "source")])
        for n in range(3):
            self.answer(self.post(n, T0 + (n + 4) * H, title="Post b", text=DOCS), [ent("Deep Book", "Deep Book", "document", "recommended")])
        self.assertEqual(self.stage()["surges"]["surges"], 0)
        for n in range(3):
            self.answer(self.post(n, T0 + (n + 8) * H, title="Post c", text=DOCS), [ent("Orbit Filing", "Orbit Filing", "document", "subject")])
        self.assertEqual(self.stage(full=True)["surges"]["surges"], 1)
        for role in schemas.NOT_SURGING:
            self.assertEqual(S.credits(I.load_book(self.cur), role, "x", None, None), {})


if __name__ == "__main__":
    unittest.main()
