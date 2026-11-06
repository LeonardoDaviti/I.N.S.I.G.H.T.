"""Mark X entities (issue 0119 A): the name key and the version parser (0090 B: the lab's gold cases, rewritten with
invented names), linking, the merge rules and guards, the review queue and the owner's answers, the collision judge,
surges, and the pages. Synthetic posts in one transaction rolled back after each test (the mx_* tables emptied inside
it), so only on a database whose name ends in _test."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.markx import decide, entity_answers, entity_stage, entity_views, identity as I, names as N
from insight_core.markx import repo, schemas, surges as S, tasks, validate
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

T0 = datetime(2100, 1, 5, 12, tzinfo=timezone.utc)
H, D = timedelta(hours=1), timedelta(days=1)


class Names(unittest.TestCase):
    """0090 B's gold (the lab's frozen parser cases), as regression tests with invented names."""

    def test_the_key(self):
        self.assertEqual(N.key("Nimbus3.8‑Flash"), N.key("nimbus 3.8 flash"))
        self.assertEqual(N.key("Nimbus3.8‑Flash"), "nimbus 3.8 flash")
        self.assertEqual(N.key("@acme_ai"), "acme ai")
        self.assertEqual(N.key("The Acme Times"), "acme times")
        self.assertEqual(N.key("Ёлка"), N.key("елка"))
        self.assertEqual(N.key("Acme­Box"), "acmebox")         # soft hyphen gone
        self.assertEqual(N.squash(N.key("Deep Kestrel")), N.squash(N.key("DeepKestrel")))

    def test_versions_are_tuples(self):
        self.assertNotEqual(N.vt("4.10"), N.vt("4.1"))
        self.assertEqual(N.vt("V4"), N.vt("4"))
        self.assertTrue(N.ver_eq(N.vt("K3.1"), N.vt("3.1")))
        self.assertFalse(N.ver_eq(N.vt("K3"), N.vt("K3.1")))

    def test_size_and_build_are_never_the_version(self):
        self.assertEqual(N.parse("Nimbus3.8-27B-GGUF", "model"),
                         {"family": "nimbus", "version": "3.8", "variant": None, "size": "27b", "build": "gguf"})
        self.assertEqual(N.parse("Kestrel-Large-4-1T-A52B", "model")["size"], "1t-a52b")
        self.assertEqual(N.parse("Orbit V4.1 Flash EXL3", "model")["build"], "exl3")
        self.assertEqual(N.parse("Orbit V4.1 Flash 1017", "model")["build"], "1017")

    def test_variants_and_families(self):
        self.assertEqual(N.parse("Orbit-6.1 Terra", "model"),
                         {"family": "orbit", "version": "6.1", "variant": "terra", "size": None, "build": None})
        self.assertEqual(N.parse("Kimo K3.1 Pro", "model")["version"], "k3.1")
        self.assertEqual(N.parse("Acme", "org"), N.NONE)                         # an org has no version
        self.assertEqual(N.parse("Kernel 6.x", "software")["version"], "6")
        self.assertEqual(N.parse("Saga VII", "product")["version"], "7")

    def test_the_maker_prefix(self):
        self.assertEqual(N.parse("Zeta Z200", "product", "Zeta"), N.parse("Z200", "product"))   # dropped
        # 0119's fix: the maker is the family ("Acme V4 Pro" by Acme) and stays
        self.assertEqual(N.parse("Acme V4 Pro", "model", "Acme"),
                         {"family": "acme", "version": "v4", "variant": "pro", "size": None, "build": None})
        self.assertEqual(N.fields_key(N.parse("Zeta Kestrel 5", "model", "Zeta"), "Zeta")[0], "kestrel")

    def test_handles_and_scripts(self):
        self.assertEqual(N.handle_forms("@acme_ai"), {"acmeai": False, "acme": True})
        self.assertTrue(N.is_handle("@acme_ai") and N.is_handle("acme_ai") and not N.is_handle("Acme"))
        self.assertTrue(N.mixed_word("Аcme"))                                  # a Cyrillic А
        self.assertFalse(N.mixed_word("Акме Acme"))
        self.assertTrue(N.word_contains("acme box", "the acme box pro"))
        self.assertFalse(N.word_contains("unity", "community"))


class Rules(unittest.TestCase):
    """decide_pair and the guards on hand-made entities (no database)."""

    def ent(self, eid, name, type_="model", maker=None, fields=None):
        fields = fields if fields is not None else N.parse(name, type_, maker)
        fk = N.fields_key(fields, maker)
        return I.Ent(eid, type_, name, N.key(name), "thing", None, maker, fk[0], fields.get("version"), fk[1],
                     fields.get("variant"), fields.get("size"), fields.get("build"), haiku=dict(fields))

    def book(self, *ents):
        b = I.Book()
        for e in ents:
            b.ents[e.id] = e
            b.alias[e.key] = e.id
        return b

    def decide(self, a, b, judge=None, auto=(), queue=()):
        book = self.book(a, b)
        p = I.Pooled(*I.pair(a.id, b.id))
        return I.decide_pair(book, p, set(auto), set(queue), judge, "call" if judge else None)

    def same(self, conf):
        return {"relation": "same", "confidence": conf}

    def test_other_versions_never_merge(self):
        a, b = self.ent("a", "Nimbus 4.1"), self.ent("b", "Nimbus 4.10")
        self.assertEqual(self.decide(a, b, self.same(0.99)).tier, "apart")
        a, b = self.ent("a", "Orbit-6.1 Sol"), self.ent("b", "Orbit-6.1 Terra")
        self.assertEqual(self.decide(a, b, self.same(0.99)).tier, "apart")

    def test_a_bare_family_and_its_version_are_parent_and_child(self):
        a, b = self.ent("a", "Nimbus"), self.ent("b", "Nimbus 5")
        self.assertEqual((self.decide(a, b, self.same(0.95)).tier, self.decide(a, b, self.same(0.95)).reason),
                         ("apart", "family"))

    def test_haiku_same_at_the_bar(self):
        a, b = self.ent("a", "Kestrel Coder", "software"), self.ent("b", "KestrelCoder CLI", "software")
        self.assertEqual(self.decide(a, b, self.same(0.9)).tier, "auto")
        d = self.decide(a, b, self.same(0.85))
        self.assertEqual((d.tier, d.reason), ("queue", "below_bar"))
        self.assertEqual(self.decide(a, b, {"relation": "part", "confidence": 0.9}).tier, "apart")
        self.assertEqual(self.decide(a, b).tier, "ask")

    def test_a_one_sided_version_and_a_type_mismatch_are_queued(self):
        a, b = self.ent("a", "Acme Box Pro", "product"), self.ent("b", "Acme Box 2 Pro", "product")
        self.assertEqual(self.decide(a, b, self.same(0.95)).reason, "version")
        a, b = self.ent("a", "Acme", "org"), self.ent("b", "Acme", "product")
        self.assertEqual(self.decide(a, b, None, auto={"squash"}).reason, "type")

    def test_an_edition_year_on_one_side(self):
        a, b = self.ent("a", "Acme Awards 2031", "event"), self.ent("b", "Acme Awards", "event")
        self.assertEqual(self.decide(a, b, self.same(0.95)).reason, "version")

    def test_queue_only_rules_never_merge_by_themselves(self):
        a, b = self.ent("a", "Boxwrap", "software"), self.ent("b", "Kernel", "software")
        d = self.decide(a, b, self.same(0.97), queue={"paren"})
        self.assertEqual((d.tier, d.reason), ("queue", "paren"))

    def test_the_fields_rule(self):
        a = self.ent("a", "Mimo-2.6", fields={"family": "MiMo", "version": "2.6", "variant": None, "size": None, "build": None})
        b = self.ent("b", "MiMo V2.6", fields={"family": "MiMo", "version": "2.6", "variant": None, "size": None, "build": None})
        self.assertEqual(I.fields_rule(a, b), "auto")
        c = self.ent("c", "Mimo 2.6 Bounty", fields={"family": "MiMo", "version": "2.6", "variant": None, "size": None,
                                                     "build": None})
        self.assertEqual(I.fields_rule(a, c), "queue")           # the parser reads a variant Haiku's fields drop
        d = self.ent("d", "Mimo-2.6", maker="Other", fields=dict(a.haiku))
        self.assertIsNone(I.fields_rule(self.ent("a", "Mimo-2.6", maker="Acme", fields=dict(a.haiku)), d))

    def test_the_chain_guard(self):
        ents = [self.ent(x, f"Name {x}", "software") for x in "abcd"]
        book = self.book(*ents)
        book.redirect = {"b": ("a", True), "d": ("c", True)}          # two clusters of two names
        d = I.Decision(("a", "c"), "auto", "haiku", 0.95)
        I.chain_guard(book, [d])
        self.assertEqual((d.tier, d.reason), ("queue", "chain"))


@requires_test_db
class _Db(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas.load_guides(self.cur)
        self.sources = [insert_scratch_source(self.cur, platform="telegram",
                                              settings_json=json.dumps({"display_name": f"Example {n}"}))
                        for n in range(5)]
        self.since = datetime.now(timezone.utc) - H     # the last run's start, by the database's clock

    def post(self, src, at, title="Acme released a thing", text=None, links=()):
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                         (self.sources[src], url, url, title, text or f"{title}. More words about it here.", at))
        pid = str(self.cur.fetchone()[0])
        for n, target in enumerate(links):
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, %s, %s)",
                             (pid, target, "example.com", n))
        return pid

    def mentions(self, pid, *ents):
        """ents: (name, type, role, maker, fields or None, span or None)."""
        task_id, _ = tasks.entities_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                             answer={"entities": []})
        rows = []
        for e in ents:
            name, type_, role = e[0], e[1], e[2]
            maker = e[3] if len(e) > 3 else None
            fields = (e[4] if len(e) > 4 else None) or {}
            span = (e[5] if len(e) > 5 else None) or name
            rows.append(dict({"span": span, "name": name, "name_key": tasks.name_key(name), "type": type_,
                              "role": role, "maker": maker}, **{f: fields.get(f) for f in N.FIELDS}))
        repo.add_mentions(self.cur, post_id=pid, guide="ent-v3", call_id=call, mentions=rows)

    def stage(self, full=False, since=None):
        run = repo.start_run(self.cur, code_version="test", config={})
        ask = decide.Ask(self.cur, T0)
        out, days = entity_stage.entities(self.cur, ask=ask, now=T0 + 2 * D, run_id=run, since=since, full=full)
        out["surges"] = entity_stage.surges(self.cur, now=T0 + 2 * D, run_id=run, days=days, since=since)
        repo.finish_run(self.cur, run, counts={"entities": out, "run": {"now": (T0 + 2 * D).isoformat()}})
        return out

    def entity_of(self, pid, n=0):
        self.cur.execute("SELECT entity_id::text FROM mx_mentions WHERE post_id = %s AND n = %s", (pid, n))
        return self.cur.fetchone()[0]

    def book(self):
        return I.load_book(self.cur)

    def answer_task(self, kind, answer, a=None):
        self.cur.execute("SELECT id FROM mx_tasks WHERE kind = %s AND (%s::uuid IS NULL OR a = %s::uuid OR b = %s::uuid) "
                         "ORDER BY created_at", (kind, a, a, a))
        out = []
        for (tid,) in self.cur.fetchall():
            repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=answer)
            repo.answer_task(self.cur, tid)
            out.append(tid)
        return out


class Linking(_Db):
    def test_an_exact_key_links_and_a_new_version_is_a_child_of_its_family(self):
        a = self.post(0, T0)
        b = self.post(1, T0 + H)
        c = self.post(2, T0 + 2 * H)
        v = {"family": "Nimbus", "version": "5", "variant": None, "size": None, "build": None}
        self.mentions(a, ("Nimbus 5", "model", "subject", "Acme", v), ("Acme", "org", "actor"))
        self.mentions(b, ("nimbus 5", "model", "subject", "Acme", v))
        self.mentions(c, ("Nimbus 5.1", "model", "subject", "Acme", dict(v, version="5.1")))
        out = self.stage()
        book = self.book()
        e5, e51 = self.entity_of(a), self.entity_of(c)
        self.assertEqual(self.entity_of(b), e5)                        # the same key, one entity
        self.assertNotEqual(e5, e51)                                   # another version, another entity
        fam = book.ents[e5].parent
        self.assertEqual(book.ents[e51].parent, fam)                  # both children of the family
        self.assertEqual((book.ents[fam].key, book.ents[fam].level, book.ents[fam].status), ("nimbus", "family", "provisional"))
        self.assertEqual(book.ents[book.ents[fam].parent].key, "acme")   # the family's maker: the org
        self.assertEqual(book.ents[e5].version_key, (5,))
        self.assertEqual(out["link"]["linked"], 4)

    def test_the_next_run_links_only_what_is_new_and_the_full_pass_matches(self):
        a = self.post(0, T0)
        self.mentions(a, ("Kestrel Coder", "software", "subject"))
        self.stage()
        b = self.post(1, T0 + H)
        self.mentions(b, ("Kestrel Coder", "software", "subject"))
        out = self.stage(since=self.since)
        self.assertEqual(out["link"]["mentions"], 1)
        self.assertEqual(self.entity_of(a), self.entity_of(b))
        full = self.stage(full=True)
        self.assertEqual(full["check"], {"same": True, "relinked": 0})


class Merging(_Db):
    def test_squashed_equal_names_merge_with_a_redirect_and_can_be_undone(self):
        a, b = self.post(0, T0), self.post(1, T0 + H)
        self.mentions(a, ("Deep Kestrel", "software", "subject"))
        self.mentions(b, ("DeepKestrel", "software", "subject"))
        out = self.stage()
        self.assertEqual(out["merged"], 1)
        book = self.book()
        self.assertEqual(book.root(self.entity_of(a)), book.root(self.entity_of(b)))
        self.cur.execute("SELECT id::text, by, automatic FROM mx_entity_redirects")
        rid, by, auto = self.cur.fetchone()
        self.assertEqual((by, auto), ("rule:squash", True))
        entity_answers.undo(self.cur, rid)
        book = self.book()
        self.assertNotEqual(book.root(self.entity_of(a)), book.root(self.entity_of(b)))
        self.stage(full=True)                                          # never merged again by a rule
        self.assertNotEqual(self.book().root(self.entity_of(a)), self.book().root(self.entity_of(b)))
        self.assertEqual([l["answer"] for l in repo.labels(self.cur, "entity")], ["different"])

    def test_the_maker_prefix_merges_only_when_the_maker_is_stated(self):
        a = self.post(0, T0, title="Zeta Z200 benchmarks")
        b = self.post(1, T0 + H, title="Z200 from Zeta is out")
        c = self.post(2, T0, title="Orbit Q7 numbers")
        d = self.post(3, T0 + H, title="Q7 is fast")
        self.mentions(a, ("Zeta Z200", "product", "subject", "Zeta"))
        self.mentions(b, ("Z200", "product", "subject", "Zeta"))
        self.mentions(c, ("Orbit Q7", "product", "subject", "Orbit"))
        self.mentions(d, ("Q7", "product", "subject", "Orbit"))         # Orbit only guessed: never written in d
        self.stage()
        book = self.book()
        self.assertEqual(book.root(self.entity_of(a)), book.root(self.entity_of(b)))
        self.assertNotEqual(book.root(self.entity_of(c)), book.root(self.entity_of(d)))
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'alias'")
        self.assertEqual(self.cur.fetchone()[0], 1)                    # asked of Haiku, queued only if same

    def test_haiku_answers_decide_the_next_run(self):
        a, b = self.post(0, T0), self.post(1, T0 + H)
        self.mentions(a, ("Kestrel Coder", "software", "subject"))
        self.mentions(b, ("Kestrel Coder CLI", "software", "subject"))
        self.stage()
        self.cur.execute("SELECT input FROM mx_tasks WHERE kind = 'alias'")
        text = self.cur.fetchone()[0]
        self.assertIn('A: name "Kestrel Coder', text)
        self.assertIn("example: [telegram", text)
        self.answer_task("alias", {"evidence": "one tool", "relation": "same", "confidence": 0.86})
        out = self.stage(since=self.since)
        self.assertEqual(out["queued"], 1)
        q = entity_views.queue(self.cur)
        self.assertEqual([(i["reason"], i["proposal"]) for i in q["open"]], [("below_bar", "same")])
        self.assertEqual(len(q["open"][0]["a"]["posts"]), 1)
        got = entity_answers.answer(self.cur, q["open"][0]["id"], "same")
        self.assertTrue(got["redirect"])
        book = self.book()
        self.assertEqual(book.root(self.entity_of(a)), book.root(self.entity_of(b)))
        self.assertEqual(book.ents[self.entity_of(a)].status, "confirmed")
        lab, = repo.labels(self.cur, "entity")
        self.assertEqual((lab["answer"], lab["split"]), ("same", "test"))
        entity_answers.answer(self.cur, q["open"][0]["id"], "different")   # changed: the merge undone, a new label
        book = self.book()
        self.assertNotEqual(book.root(self.entity_of(a)), book.root(self.entity_of(b)))
        self.assertEqual(len(repo.labels(self.cur, "entity")), 2)

    def test_an_org_handle_with_an_extra_word_is_asked_never_merged(self):
        a, b = self.post(0, T0), self.post(1, T0 + H)
        self.mentions(a, ("Acme", "org", "subject"))
        self.mentions(b, ("AcmeAI", "org", "subject", None, None, "@acmeai"))
        self.stage()
        self.assertNotEqual(self.book().root(self.entity_of(a)), self.book().root(self.entity_of(b)))
        self.answer_task("alias", {"relation": "same", "confidence": 0.95})
        self.stage(since=self.since)
        q = entity_views.queue(self.cur)["open"]
        self.assertEqual([i["reason"] for i in q], ["handle_extra_word"])

    def test_x_y_in_one_post_is_asked(self):
        a = self.post(0, T0, title="Boxwrap (Kernel) gets a sandbox")
        self.mentions(a, ("Boxwrap", "software", "subject"), ("Kernel", "software", "mention"))
        self.stage()
        self.answer_task("alias", {"relation": "same", "confidence": 0.99})
        self.stage(since=self.since)
        self.assertEqual([i["reason"] for i in entity_views.queue(self.cur)["open"]], ["paren"])
        self.assertEqual(self.cur.execute("SELECT count(*) FROM mx_entity_redirects").fetchone()[0], 0)


class Collisions(_Db):
    def test_a_split_two_runs_make_is_a_question_and_the_owner_applies_it(self):
        ps = [self.post(n, T0 + n * H, title=f"Luma {t} news {n}") for n, t in enumerate(["model", "model", "agent"])]
        self.mentions(ps[0], ("Luma", "model", "subject", "Acme"))
        self.mentions(ps[1], ("Luma", "model", "subject", "Acme"))
        self.mentions(ps[2], ("Luma", "product", "subject", "Orbit"))
        out = self.stage()
        self.assertEqual(out["collide"]["asked"], 1)
        self.cur.execute("SELECT id, input FROM mx_tasks WHERE kind = 'collide'")
        tid, text = self.cur.fetchone()
        n = validate.collide_mentions(text)
        self.assertEqual(n, 3)
        lines = {int(x.split(".")[0]): x for x in text.splitlines() if x[:1].isdigit()}
        agent = next(k for k, v in lines.items() if "type product" in v)
        rest = [k for k in lines if k != agent]
        split = {"evidence": "-", "senses": [{"m": rest, "what": "a model"}, {"m": [agent], "what": "a store agent"}],
                 "related": [], "unclear": [], "confidence": 0.8}
        self.assertIsNone(validate.check("collide", split, text)[1])
        self.assertIsNotNone(validate.check("collide", dict(split, unclear=[1]), text)[1])
        for k in range(3):
            repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True,
                          answer=split if k != 1 else {"senses": [{"m": [1, 2, 3]}]})
        repo.answer_task(self.cur, tid)
        out = self.stage(since=self.since)
        self.assertEqual(out["collide"]["queued"], 1)
        item, = entity_views.queue(self.cur)["open"]
        self.assertEqual((item["kind"], item["proposal"]), ("collision", "split"))
        e = self.entity_of(ps[0])
        self.assertEqual(self.cur.execute("SELECT count(*) FROM mx_entity_redirects").fetchone()[0], 0)
        got = entity_answers.answer(self.cur, item["id"], "different")
        self.assertEqual(got["pinned"], 1)
        book = self.book()
        new, = got["entities"]
        self.assertEqual(book.pins[(ps[2], "ent-v3", 0)], new)
        self.stage(since=self.since)
        self.assertEqual((self.entity_of(ps[2]), self.entity_of(ps[0])), (new, e))   # the run applies the pin
        self.assertIn("store agent", book.ents[new].name)

    def test_one_run_alone_never_splits(self):
        ps = [self.post(n, T0 + n * H) for n in range(2)]
        self.mentions(ps[0], ("Luma", "model", "subject", "Acme"))
        self.mentions(ps[1], ("Luma", "product", "subject", "Orbit"))
        self.stage()
        self.cur.execute("SELECT id FROM mx_tasks WHERE kind = 'collide'")
        tid, = self.cur.fetchone()
        repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True,
                      answer={"senses": [{"m": [1]}, {"m": [2]}]})
        repo.answer_task(self.cur, tid)
        out = self.stage(since=self.since)
        self.assertEqual(out["collide"]["asked_again"], 1)            # asked again until three runs
        self.assertEqual(self.cur.execute("SELECT status FROM mx_tasks WHERE id = %s", (tid,)).fetchone()[0], "open")
        self.assertEqual(entity_views.queue(self.cur)["open"], [])


class CollisionsAgree(_Db):
    def test_two_runs_that_agree_settle_it_without_a_third(self):
        ps = [self.post(n, T0 + n * H) for n in range(2)]
        self.mentions(ps[0], ("Luma", "model", "subject", "Acme"))
        self.mentions(ps[1], ("Luma", "product", "subject", "Orbit"))
        self.stage()
        self.cur.execute("SELECT id FROM mx_tasks WHERE kind = 'collide'")
        tid, = self.cur.fetchone()
        for _ in range(2):
            repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True,
                          answer={"senses": [{"m": [1, 2], "what": "one model"}]})
        repo.answer_task(self.cur, tid)
        out = self.stage(since=self.since)
        self.assertEqual((out["collide"]["asked_again"], out["collide"]["one_thing"]), (0, 1))


class Anchors(_Db):
    def test_an_address_names_a_thing_only_by_its_whole_name(self):
        """A short name inside a longer repository name is no anchor (the scratch copy: a maker's model merged into
        its coding tool by the lab's containment test); a build tag after the name is dropped."""
        url = "https://github.com/acme/kestrel-coder"
        a = self.post(0, T0, links=[url])
        b = self.post(1, T0 + H, links=[url])
        c = self.post(2, T0 + 2 * H, links=["https://huggingface.co/acme/Nimbus-7-GGUF"])
        self.mentions(a, ("Kestrel", "model", "subject"))
        self.mentions(b, ("Kestrel Coder", "software", "subject"))
        self.mentions(c, ("Nimbus 7", "model", "subject"))
        self.stage()
        an = I.anchors(self.cur, self.book(), "ent-v3")
        self.assertIn(self.entity_of(b), an)
        self.assertNotIn(self.entity_of(a), an)
        self.assertIn(self.entity_of(c), an)


class Surges(_Db):
    def test_three_voices_a_day_with_the_roll_up_through_the_child(self):
        v = {"family": "Nimbus", "version": "5", "variant": None, "size": None, "build": None}
        for n in range(3):
            p = self.post(n, T0 + n * H)
            self.mentions(p, ("Nimbus 5", "model", "subject", "Acme", v))
        p = self.post(3, T0 + 4 * H)
        self.mentions(p, ("Nimbus 4", "model", "compared", "Acme", dict(v, version="4")))   # a comparison: no credit
        p2 = self.post(0, T0 + 5 * H)                                                       # a second post, same voice
        self.mentions(p2, ("Nimbus 5", "model", "subject", "Acme", v))
        out = self.stage()
        self.assertEqual(out["surges"]["surges"], 3)                   # Nimbus 5, its family Nimbus, its maker Acme
        book = self.book()
        acme = book.by_key("acme")
        got = S.surging(self.cur, book, since=T0.date() - D)
        self.assertEqual(got[acme][0]["voices"], 3)
        self.assertEqual(got[acme][0]["posts"], 4)
        self.assertEqual(got[acme][0]["via"][0]["name"], "Nimbus 5")
        self.assertEqual(got[book.by_key("nimbus 5")][0]["via"], [])
        self.assertNotIn(book.by_key("nimbus 4"), got)

    def test_two_voices_are_no_surge_and_a_recount_closes_a_changed_row(self):
        for n in range(2):
            self.mentions(self.post(n, T0 + n * H), ("Kestrel Coder", "software", "subject"))
        self.assertEqual(self.stage()["surges"]["surges"], 0)
        self.mentions(self.post(2, T0 + 3 * H), ("Kestrel Coder", "software", "actor"))
        self.assertEqual(self.stage(since=self.since)["surges"]["opened"], 1)
        self.mentions(self.post(3, T0 + 4 * H), ("Kestrel Coder", "software", "subject"))
        got = self.stage(since=self.since)["surges"]
        self.assertEqual((got["opened"], got["closed"]), (1, 1))
        self.cur.execute("SELECT count(*), count(*) FILTER (WHERE valid_to IS NULL) FROM mx_entity_surges")
        self.assertEqual(self.cur.fetchone(), (2, 1))                   # kept: the old row closed, not deleted


class Pages(_Db):
    def test_the_list_ranks_by_voices_and_keeps_read_posts(self):
        ps = [self.post(n, T0 + n * H) for n in range(3)]
        self.mentions(ps[0], ("Kestrel Coder", "software", "mention"), ("Acme", "org", "subject"))
        for p in ps[1:]:
            self.mentions(p, ("Kestrel Coder", "software", "mention"))
        self.stage()
        self.cur.execute("INSERT INTO post_reader_state (post_id, read_at) VALUES (%s, now())", (ps[2],))
        got = entity_views.entity_list(self.cur, now=T0 + D)
        self.assertEqual([i["name"] for i in got["items"]], ["Kestrel Coder", "Acme"])
        top = got["items"][0]
        self.assertEqual((top["voices"], top["posts"], top["reports"], top["last_seen"]), (3, 3, 0, "yesterday"))
        self.assertEqual([n["read"] for n in top["newest"]], [True, False, False])   # read stays, marked
        page = entity_views.entity_page(self.cur, self.entity_of(ps[0]), now=T0 + D)
        self.assertEqual(len(page["loose"]), 3)
        self.assertEqual(page["loose"][0]["roles"], ["mention"])
        self.assertEqual(len(page["sources"]), 3)

    def test_a_family_page_lists_its_versions_and_a_merged_id_opens_its_cluster(self):
        v = {"family": "Orbit", "version": "6.1", "variant": "Terra", "size": None, "build": None}
        a, b = self.post(0, T0), self.post(1, T0)
        self.mentions(a, ("Orbit-6.1 Terra", "model", "subject", None, v))
        self.mentions(b, ("Orbit-6.1 Sol", "model", "subject", None, dict(v, variant="Sol")))
        self.stage()
        book = self.book()
        fam = book.ents[self.entity_of(a)].parent
        page = entity_views.entity_page(self.cur, fam)
        self.assertEqual(sorted(v["name"] for v in page["versions"]), ["Orbit-6.1 Sol", "Orbit-6.1 Terra"])
        child = entity_views.entity_page(self.cur, self.entity_of(a))
        self.assertEqual(child["family"]["id"], fam)

    def test_the_post_panel_names_each_entity_and_the_invariants_hold(self):
        from insight_core.checks import invariants
        from insight_core.markx import news
        a = self.post(0, T0)
        self.mentions(a, ("Kestrel Coder", "software", "subject"))
        self.stage()
        panel = news.post_panel(self.cur, a)
        self.assertEqual(panel["entities"][0]["entity_id"], self.entity_of(a))
        run = invariants.Run(db_url(), self.cur, T0)
        for inv in invariants.INVARIANTS:
            if inv.name.startswith("markx.entity_"):
                with self.subTest(inv.name):
                    self.assertEqual(inv.count(run)[0], [])


if __name__ == "__main__":
    unittest.main()
