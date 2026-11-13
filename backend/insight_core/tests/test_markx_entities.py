"""Mark X entities (issue 0119 A): the name key and the version parser (0090 B: the lab's gold cases, rewritten with
invented names), linking, the merge rules and guards, the review queue and the owner's answers, the collision judge,
surges, and the pages. Synthetic posts in one transaction rolled back after each test (the mx_* tables emptied inside
it), so only on a database whose name ends in _test."""
from __future__ import annotations

import json
import re
import unittest
from unittest import mock
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
        self.assertEqual(self.decide(a, b, self.same(0.95)).reason, "version_one_side")   # 0130 A3: one Box version
        a, b = self.ent("a", "Acme", "org"), self.ent("b", "Acme", "product")
        self.assertEqual(self.decide(a, b, None, auto={"squash"}).reason, "type")

    def test_an_edition_year_on_one_side(self):
        a, b = self.ent("a", "Acme Awards 2031", "event"), self.ent("b", "Acme Awards", "event")
        d = self.decide(a, b, self.same(0.95))
        self.assertEqual((d.tier, d.reason, d.ask2), ("queue", "version_year", True))   # 0130 A3: the second opinion

    def test_the_version_guard_holds_a_family_with_several_versions(self):
        """0130 A3: one name states a version the other lacks and the family has several: held, never asked again."""
        a, b = self.ent("a", "Nimbus Phone Max", "product"), self.ent("b", "Nimbus Phone 17 Max", "product")
        c = self.ent("c", "Nimbus Phone 16 Max", "product")
        book = self.book(a, b, c)
        d = I.decide_pair(book, I.Pooled(*I.pair("a", "b")), set(), set(), self.same(0.95), "call")
        self.assertEqual((d.tier, d.reason, d.ask2), ("queue", "version", False))
        self.assertEqual(I.soft_reason(self.book(a, b), a, b), "version_one_side")

    def test_the_bands_are_config(self):
        """0130 A1: the measured table decides, not a constant in code."""
        self.assertEqual(I.band_of(0.93), ">=0.90")
        self.assertEqual(I.band_of(0.87), "0.85-0.90")
        self.assertEqual(I.band_of(0.5), "<0.80")
        self.assertTrue(I.first_auto(0.9))
        self.assertFalse(I.first_auto(0.89))
        for r in I.bands()["rows"]:     # a row is on only when it meets the bar (a second row: no wrong merge)
            if r["auto"] and r["opinion"] == "first":
                self.assertGreaterEqual(r["right"] / r["n"], I.bands()["bar"]["point"])
            if r["auto"] and r["opinion"] == "second":
                self.assertEqual(r["right"], r["n"])
        with_rows = dict(I.bands(), rows=[dict(r, auto=True) if r["guard"] == "none" and r["band"] == "0.85-0.90" else r
                                          for r in I.bands()["rows"]])
        saved = dict(I._BANDS)
        try:
            I._BANDS.clear()
            I._BANDS.update(with_rows)
            a, b = self.ent("a", "Kestrel Coder", "software"), self.ent("b", "KestrelCoder CLI", "software")
            self.assertEqual(self.decide(a, b, self.same(0.86)).tier, "auto")   # a band turned on in config merges
        finally:
            I._BANDS.clear()
            I._BANDS.update(saved)

    def test_the_second_opinion(self):
        """0130 A2: a held-back `same` >= 0.85 is asked again; two agreeing `same` >= 0.85 merge, a disagreement stays
        queued with the second answer; below 0.85, a type mismatch or a held version is never asked again."""
        a, b = self.ent("a", "Kestrel Coder", "software"), self.ent("b", "KestrelCoder CLI", "software")
        book = self.book(a, b)
        p = I.Pooled(*I.pair("a", "b"))
        d = I.decide_pair(book, p, set(), set(), self.same(0.87), "c1")
        self.assertEqual((d.tier, d.reason, d.ask2), ("queue", "below_bar", True))
        d = I.decide_pair(book, p, set(), set(), self.same(0.87), "c1", self.same(0.9), "c2")
        self.assertEqual((d.tier, d.reason, d.second_call), ("auto", "second", "c2"))
        self.assertAlmostEqual(d.conf, 0.87)
        d = I.decide_pair(book, p, set(), set(), self.same(0.87), "c1", {"relation": "part", "confidence": 0.8}, "c2")
        self.assertEqual((d.tier, d.reason, d.second["relation"]), ("queue", "below_bar", "part"))
        d = I.decide_pair(book, p, set(), set(), self.same(0.87), "c1", self.same(0.8), "c2")
        self.assertEqual(d.tier, "queue")                                   # the second below its bar
        self.assertFalse(I.decide_pair(book, p, set(), set(), self.same(0.84), "c1").ask2)
        d = I.decide_pair(book, p, set(), {"maker_unstated"}, self.same(0.95), "c1", self.same(0.95), "c2")
        self.assertEqual((d.tier, d.reason), ("auto", "second"))
        d = I.decide_pair(book, p, set(), {"paren"}, self.same(0.95), "c1")
        self.assertFalse(d.ask2)                                            # "X (Y)" is not measured: off
        a2 = self.ent("a", "Kestrel", "org")
        d = I.decide_pair(self.book(a2, b), p, set(), set(), self.same(0.95), "c1", self.same(0.95), "c2")
        self.assertEqual((d.tier, d.reason), ("queue", "type"))

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


class TheStagesOwnBudget(_Db):
    """0128: the full pass decides its entities in chunks; past its budget it stops after a chunk, and the next run
    resumes it where it stopped, until its last chunk (only then is the night's pass done)."""

    def names(self):
        pairs = [("Deep Kestrel", "DeepKestrel"), ("Orbit Labs", "OrbitLabs"), ("Nimbus Coder", "NimbusCoder")]
        for n, (x, y) in enumerate(pairs):
            a, b = self.post(n % 5, T0 + n * H), self.post((n + 1) % 5, T0 + n * H + H)
            self.mentions(a, (x, "software", "subject"))
            self.mentions(b, (y, "software", "subject"))
        return len(pairs)

    def run_stage(self, *, full=None, budget=None, chunk=1):
        run = repo.start_run(self.cur, code_version="test", config={})
        ask = decide.Ask(self.cur, T0)
        out, _ = entity_stage.entities(self.cur, ask=ask, now=T0 + 2 * D, run_id=run, since=self.since, full=full,
                                       budget=budget, chunk=chunk)
        repo.finish_run(self.cur, run, counts={"entities": out, "run": {"now": (T0 + 2 * D).isoformat()}})
        return out

    def test_a_full_pass_past_its_budget_stops_after_a_chunk_and_the_next_run_resumes_it(self):
        n = self.names()
        self.stage()                                        # linked and merged incrementally first
        self.cur.execute("DELETE FROM mx_entity_redirects")     # as if never merged: the full pass must find them
        first = self.run_stage(full=True, budget=0)
        self.assertEqual(first["kind"], "full")
        self.assertFalse(first["full"]["done"])
        # v10.13.9: the relinking's one page, then the budget is spent: the pool's first chunk is the next run's
        self.assertEqual((first["full"]["phase"], first["full"]["chunks"], first["full"]["after"]), ("pool", 0, None))
        self.assertEqual(first["check"], {"same": True, "relinked": 0})
        second = self.run_stage(budget=0)
        self.assertEqual((second["full"]["phase"], second["full"]["chunks"]), ("pool", 1))   # one chunk, then stops
        self.assertIsNotNone(second["full"]["after"])
        self.assertNotIn("check", second)                   # resumed: nothing relinked again
        seen = [first, second]
        while not seen[-1]["full"]["done"]:
            seen.append(self.run_stage(budget=0))           # not forced: the half-done pass is resumed
            self.assertEqual(seen[-1]["kind"], "full")
            self.assertTrue(seen[-1]["full"]["resumed"])
            self.assertLess(len(seen), 50)
        self.assertEqual(sum(o["merged"] for o in seen), n)    # every pair found once over the chunks
        self.assertEqual(seen[-1]["full"]["after"], None)
        self.assertFalse(entity_stage.full_due(self.cur, T0 + 2 * D))   # the night's pass is done now
        self.assertEqual(self.run_stage(budget=0)["kind"], "incremental")
        book = self.book()
        self.assertEqual(len({book.root(e) for e in book.ents if e in book.mentioned}), n)

    def test_a_half_done_pass_is_not_the_nights_pass(self):
        self.names()
        self.stage()
        self.cur.execute("UPDATE mx_runs SET counts = counts - 'entities'")   # no night's pass yet
        self.assertTrue(entity_stage.full_due(self.cur, T0 + 2 * D))
        out = self.run_stage(full=True, budget=0)
        self.assertFalse(out["full"]["done"])
        self.assertTrue(entity_stage.full_due(self.cur, T0 + 2 * D))
        self.assertIsNotNone(entity_stage.unfinished(self.cur))

    def test_without_a_budget_the_full_pass_runs_every_chunk(self):
        self.names()
        self.stage()
        out = self.run_stage(full=True, budget=None)
        self.assertTrue(out["full"]["done"])
        self.assertEqual(out["full"]["chunks"], out["full"]["of"])
        self.assertEqual(out["check"], {"same": True, "relinked": 0})


class BothPassesKeepToTheBudget(_Db):
    """v10.13.9: the incremental pass links, pools and decides in chunks and stops after the chunk past its budget;
    the mentions it leaves stay unlinked and the next runs take them (nothing lost, nothing done twice). The full
    pass's relinking stops between its pages likewise."""

    names = TheStagesOwnBudget.names
    run_stage = TheStagesOwnBudget.run_stage

    def nights_pass_done(self):
        self.run_stage(full=True)    # nothing to read yet: the night's pass is done, so the next runs are incremental

    def unlinked(self):
        self.cur.execute("SELECT count(*) FROM mx_mentions WHERE entity_id IS NULL")
        return self.cur.fetchone()[0]

    def test_the_incremental_pass_stops_at_its_budget_and_the_next_run_goes_on(self):
        self.nights_pass_done()
        n = self.names()
        seen = []
        with mock.patch.object(I, "MENTION_CHUNK", 1):
            while not seen or not seen[-1]["incremental"]["done"]:
                seen.append(self.run_stage(budget=0))
                self.assertEqual(seen[-1]["kind"], "incremental")
                self.assertLess(len(seen), 20)
        first = seen[0]
        self.assertEqual((first["incremental"]["parts"], first["incremental"]["of"], first["incremental"]["left"]),
                         (1, 2 * n, 2 * n - 1))                            # one chunk, then the budget is spent
        self.assertEqual(first["link"]["entities_made"], 2 * n)            # every key's entity made at once
        self.assertEqual(len(seen), 2 * n)                                 # a mention a run
        self.assertEqual([o["link"]["linked"] for o in seen], [1] * (2 * n))   # each linked once
        self.assertEqual(sum(o["entities_made"] for o in seen), 2 * n)     # none made twice
        self.assertEqual(self.unlinked(), 0)
        self.assertEqual(sum(o["merged"] for o in seen), n)                # every pair, once
        self.cur.execute("SELECT count(*), count(DISTINCT from_id) FROM mx_entity_redirects")
        self.assertEqual(self.cur.fetchone(), (n, n))
        book = self.book()
        self.assertEqual(len({book.root(e) for e in book.mentioned}), n)
        self.assertEqual([o["days_linked"] for o in seen], [1] * (2 * n))

    def test_without_a_budget_one_incremental_run_does_every_chunk(self):
        self.nights_pass_done()
        n = self.names()
        with mock.patch.object(I, "MENTION_CHUNK", 1):
            out = self.run_stage(budget=None)
        self.assertEqual(out["incremental"], {"done": True, "parts": 2 * n, "of": 2 * n, "left": 0})
        self.assertEqual((out["link"]["linked"], out["merged"], self.unlinked()), (2 * n, n, 0))

    def test_the_relinking_stops_between_pages_and_the_pass_resumes_there(self):
        n = self.names()
        self.stage()
        self.cur.execute("DELETE FROM mx_entity_redirects")
        seen = []
        with mock.patch.object(I, "RELINK_PAGE", 1):
            seen.append(self.run_stage(full=True, budget=0))
            while not seen[-1]["full"]["done"]:
                seen.append(self.run_stage(budget=0))
                self.assertLess(len(seen), 50)
        relinking = [o for o in seen if "check" in o]
        self.assertEqual(len(relinking), 2 * n)                    # a post a run
        self.assertTrue(all(o["full"]["phase"] == "link" and o["full"]["link_after"] for o in relinking[:-1]))
        self.assertEqual(sum(o["link"]["mentions"] for o in relinking), 2 * n)   # every mention relinked once
        self.assertTrue(all(o["check"] == {"same": True, "relinked": 0} for o in relinking))
        self.assertEqual(sum(o["merged"] for o in seen), n)
        self.assertFalse(entity_stage.full_due(self.cur, T0 + 2 * D))

    def test_an_unfinished_pass_recorded_before_resumes_in_its_pool(self):
        self.names()
        self.stage()
        self.cur.execute("UPDATE mx_runs SET counts = jsonb_set(counts, '{entities,full}', %s::jsonb)",
                         (json.dumps({"done": False, "after": "00000000-0000-0000-0000-000000000000"}),))
        self.assertIsNotNone(entity_stage.unfinished(self.cur))
        out = self.run_stage(budget=None)
        self.assertEqual((out["kind"], out["full"]["resumed"], out["full"]["done"]), ("full", True, True))
        self.assertNotIn("check", out)                               # its relinking was done


class PublishedIndexed(unittest.TestCase):
    """v10.13.9: published() reads a publisher's type from an index of the mentions, not a scan of them for each
    document; on random mentions it does exactly what the scan did."""

    class Cur:
        def __init__(self):
            self.calls, self.rowcount = [], 1

        def execute(self, sql, params=None):
            self.calls.append(params)

    class Writer:
        def __init__(self, book):
            self.book, self.made = book, []

        def entity(self, *, type_, name, key, level, parent, maker, fields, first_seen):
            eid = f"made-{len(self.made)}"
            self.made.append((eid, type_, name, key, first_seen))
            self.book.alias.setdefault(key, eid)
            return eid

    @staticmethod
    def scan(cur, book, w, ms):
        """published() as it was before v10.13.9 (the scan), the reference."""
        added = 0
        for m in ms:
            if not (m.by_name and m.entity_id and I.schemas_type(m.type) == "document"):
                continue
            k = N.key(m.by_name)
            if not k or k == m.key:
                continue
            pub = book.by_key(k)
            if pub is None:
                typ = next((x.type for x in ms if x.post_id == m.post_id and x.key == k and x.type in ("org", "person")),
                           "org")
                pub = w.entity(type_=typ, name=m.by_name.strip(), key=k, level="thing", parent=None, maker=None,
                               fields=dict(N.NONE), first_seen=m.at)
            cur.execute("INSERT", (pub, m.entity_id, m.call_id,
                                   json.dumps({"post": m.post_id, "guide": m.guide, "n": m.n, "by": m.by_name})))
            added += cur.rowcount
        return added

    def test_random_mentions(self):
        import random
        names = ["Acme Corp", "acme corp", "Ivo Kestrel", "Orbit Labs", "The Orbit Labs", "Nimbus Paper", ""]
        types = ["document", "paper", "org", "person", "product", None]
        for seed in range(400):
            rnd = random.Random(seed)
            ms = [I.Mention(f"p{rnd.randrange(4)}", "ent-v3", n, "", rnd.choice(names), rnd.choice(types), "subject",
                            None, {}, rnd.choice([None, f"e{n}"]), T0 + n * H, None,
                            rnd.choice([None, None] + names), f"c{n}")
                  for n in range(rnd.randrange(0, 25))]
            known = {N.key(x): f"k-{x}" for x in rnd.sample(names, 2) if N.key(x)}
            got = []
            for f in (self.scan, I.published):
                book = I.Book()
                book.alias = dict(known)
                cur, w = self.Cur(), self.Writer(book)
                added = f(cur, book, w, ms)
                got.append((added, cur.calls, w.made))
            self.assertEqual(got[0], got[1], f"seed {seed}")


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

    def test_the_queue_answers_its_open_items_a_page_at_a_time(self):
        # Issue 0195: 12,572 open items answered 28.9 MB in 14.7 s; a page is the whole queue's top items.
        for n, (x, y) in enumerate([("Acme", "AcmeAI"), ("Borealis", "BorealisHQ"), ("Corvid", "CorvidLabs")]):
            a, b = self.post(n, T0 + n * H), self.post((n + 3) % 5, T0 + n * H)
            self.mentions(a, (x, "org", "subject"))
            self.mentions(b, (y, "org", "subject", None, None, "@" + y.lower()))
        self.stage()
        for _ in range(3):
            self.answer_task("alias", {"relation": "same", "confidence": 0.95})
        self.stage(since=self.since)
        whole = entity_views.queue(self.cur)
        self.assertEqual(len(whole["open"]), 3)
        self.assertNotIn("next_offset", whole)
        first = entity_views.queue(self.cur, limit=2)
        self.assertEqual((first["open"], first["next_offset"], first["counts"]), (whole["open"][:2], 2, whole["counts"]))
        rest = entity_views.queue(self.cur, limit=2, offset=2)
        self.assertEqual((rest["open"], rest["next_offset"]), (whole["open"][2:], None))
        self.assertEqual({k: v for k, v in first.items() if k not in ("open", "next_offset")},
                         {k: v for k, v in whole.items() if k != "open"})
        # the entity page's questions: the open items naming it, as the whole queue shows them
        root = whole["open"][1]["a"]["id"]
        page = entity_views.entity_page(self.cur, root)
        self.assertEqual(page["queue"], [q for q in whole["open"] if root in (q["a"]["id"], (q.get("b") or {}).get("id"))])
        self.assertTrue(page["queue"])

    def _queued_below_the_bar(self):
        ps = [self.post(n % 5, T0 + n * H, title=f"Kestrel news {n}") for n in range(8)]
        for p in ps[:4]:
            self.mentions(p, ("Kestrel Coder", "software", "subject"))
        for p in ps[4:]:
            self.mentions(p, ("Kestrel Coder CLI", "software", "subject"))
        self.stage()
        self.answer_task("alias", {"evidence": "one tool", "relation": "same", "confidence": 0.87})
        out = self.stage(since=self.since)
        self.assertEqual((out["queued"], out["second"]["asked"]), (1, 1))
        item, = entity_views.queue(self.cur)["open"]
        self.assertEqual((item["reason"], item["band"], item["evidence"]["second_asked"]), ("below_bar", "0.85-0.90", True))
        self.cur.execute("SELECT t.input, f.input FROM mx_tasks t, mx_tasks f WHERE t.kind = 'alias2' AND f.kind = 'alias'")
        second, first = self.cur.fetchone()
        titles = lambda t: set(re.findall(r'"(Kestrel news \d)"', t))
        self.assertEqual(len(titles(first)), 4)
        self.assertEqual(len(titles(second)), 4)
        self.assertFalse(titles(first) & titles(second))   # two other example posts per name
        return ps, item

    def test_two_agreeing_opinions_merge_and_close_the_queued_item(self):
        """0130 A2: the second opinion agrees: a redirect by 'second' (undoable), the queue item closed, kept."""
        ps, item = self._queued_below_the_bar()
        self.since = datetime.now(timezone.utc) - H
        self.answer_task("alias2", {"evidence": "same tool", "relation": "same", "confidence": 0.9})
        out = self.stage(since=self.since)
        self.assertEqual(out["second"]["cleared"], 1)
        book = self.book()
        self.assertEqual(book.root(self.entity_of(ps[0])), book.root(self.entity_of(ps[4])))
        q = entity_views.queue(self.cur)
        self.assertEqual(q["open"], [])
        self.assertEqual([(m["by"], m["automatic"]) for m in q["merges"]], [("second", True)])
        self.cur.execute("SELECT closed_at IS NOT NULL, evidence->>'closed_by' FROM mx_entity_queue WHERE id = %s",
                         (item["id"],))
        self.assertEqual(self.cur.fetchone(), (True, "second"))
        entity_answers.undo(self.cur, q["merges"][0]["id"])
        book = self.book()
        self.assertNotEqual(book.root(self.entity_of(ps[0])), book.root(self.entity_of(ps[4])))
        self.stage(full=True)                               # an owner's undo is never merged again
        self.assertNotEqual(self.book().root(self.entity_of(ps[0])), self.book().root(self.entity_of(ps[4])))

    def test_a_disagreeing_second_opinion_stays_queued_and_marked(self):
        ps, item = self._queued_below_the_bar()
        self.since = datetime.now(timezone.utc) - H
        self.answer_task("alias2", {"evidence": "a plugin of it", "relation": "part", "confidence": 0.8})
        out = self.stage(since=self.since)
        self.assertEqual((out["merged"], out["second"]["marked"]), (0, 1))
        got, = entity_views.queue(self.cur)["open"]
        self.assertEqual((got["id"], got["evidence"]["disagree"], got["evidence"]["second"]["relation"]),
                         (item["id"], True, "part"))

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
        an = I.anchors(self.cur, self.book(), schemas.mention_guides())   # 0133: the current set, any guide
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
        # issue 0195: the loose posts and the story blocks listed are capped; the totals count them all
        capped = entity_views.entity_page(self.cur, self.entity_of(ps[0]), now=T0 + D, loose_limit=2, stories_limit=1)
        self.assertEqual((capped["loose"], capped["loose_total"]), (page["loose"][:2], 3))
        self.assertEqual({k: v for k, v in capped.items() if k != "loose"}, {k: v for k, v in page.items() if k != "loose"})

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
