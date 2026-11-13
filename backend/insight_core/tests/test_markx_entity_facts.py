"""Identity facts (issue 0184, markx/entity_facts.py), invented names: bare names, facts rows kept, placement by the
stated maker, a split made into senses, makers stated in later posts, the readers behind the switch."""
from __future__ import annotations

import unittest

from insight_core.markx import entity_facts as F
from insight_core.markx import entity_views, identity as I, search
from insight_core.tests.test_markx_entities import H, T0, _Db


def switch(test: unittest.TestCase, **on: bool) -> None:
    saved = dict(I._BANDS) or dict(I.bands())
    I._BANDS.clear()
    I._BANDS.update(dict(saved, facts=dict(saved.get("facts") or {}, **on)))
    test.addCleanup(lambda: (I._BANDS.clear(), I._BANDS.update(saved)))


class Bare(unittest.TestCase):
    def test_a_bare_name(self):
        self.assertTrue(F.bare("Vexa"))
        self.assertTrue(F.bare("The Kestrel"))
        self.assertFalse(F.bare("Mara Quill"))       # two words: the alias question decides
        self.assertFalse(F.bare("Vela5"))            # a digit: versions tell it apart
        self.assertFalse(F.bare("Vexa", "Zentra"))   # a maker tells it apart


class Facts(_Db):
    def _entity(self, name="Vexa", type_="software", maker=None, title="Vexa news"):
        p = self.post(0, T0, title=title)
        self.mentions(p, (name, type_, "subject", maker))
        self.stage()
        return p, self.entity_of(p)

    def test_off_reads_nothing_and_a_new_fact_supersedes_never_updates(self):
        _, e = self._entity()
        self.assertIsNotNone(F.write(self.cur, e, by="haiku", what="a terminal app", kind="software", sense_key="vexa"))
        self.assertEqual(F.read(self.cur, [e]), {})                      # the switch is off: no page changes
        switch(self, on=True)
        self.assertEqual(F.read(self.cur, [e])[e].what, "a terminal app")
        self.assertIsNone(F.write(self.cur, e, by="haiku", what="a terminal app"))   # the same: no new row
        F.write(self.cur, e, by="owner", what="a terminal app for coding agents")
        self.assertIsNone(F.write(self.cur, e, by="haiku", what="a game"))          # the owner's is never superseded
        self.cur.execute("SELECT what, superseded_at IS NULL FROM mx_entity_facts WHERE entity_id = %s ORDER BY created_at, id",
                         (e,))
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(1 for _, cur in rows if cur), 1)            # one current row, the old one kept
        self.assertEqual(F.read(self.cur, [e])[e].by, "owner")

    def test_a_product_gets_the_maker_its_later_posts_state(self):
        p1 = self.post(0, T0, title="Tessel ships")
        self.mentions(p1, ("Tessel", "software", "subject"))
        p2 = self.post(1, T0 + H, title="Tessel by Zentra is out", text="Tessel by Zentra is out today.")
        self.mentions(p2, ("Tessel", "software", "subject", "Zentra"), ("Zentra", "org", "actor"))
        self.stage()
        e = self.entity_of(p1)
        switch(self, on=True)
        book = self.book()
        self.assertEqual(F.makers(self.cur, book, [book.root(e)], ["ent-v3"]), 1)
        f = F.read(self.cur, [book.root(e)])[book.root(e)]
        self.assertEqual((f.maker, f.by), ("Zentra", "rule:mentions"))
        self.cur.execute("SELECT maker FROM mx_entities WHERE id = %s", (e,))
        self.assertIsNone(self.cur.fetchone()[0])                       # identity's own maker stays as made

    def _two_senses(self):
        """"Kestrel" an org (Zentra's robots) and "Kestrel" a robot family by Orbis: two senses with facts."""
        p1 = self.post(0, T0, title="Kestrel raises a round")
        self.mentions(p1, ("Kestrel", "org", "subject"))
        self.stage()
        e = self.entity_of(p1)
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, status) VALUES ('product', 'Kestrel (robot)',
                            'kestrel robot', 'thing', 'provisional') RETURNING id::text""")
        other = self.cur.fetchone()[0]
        o = self.post(2, T0, title="Orbis")
        self.mentions(o, ("Orbis", "org", "subject"))
        self.stage(since=self.since)
        orbis = self.entity_of(o)
        F.write(self.cur, e, by="haiku", what="a startup", kind="org", sense_key="kestrel")
        F.write(self.cur, other, by="haiku", what="a robot family", kind="product", maker_id=orbis, maker_name="Orbis",
                sense_key="kestrel")
        return e, other

    def test_a_mention_stating_a_senses_maker_is_placed_there_by_rule(self):
        e, other = self._two_senses()
        switch(self, on=True, place=True)
        p = self.post(3, T0 + 2 * H, title="Orbis shows its Kestrel robots",
                      text="Orbis shows its Kestrel robots walking.")
        self.mentions(p, ("Kestrel", "product", "subject", "Orbis"))
        q = self.post(4, T0 + 2 * H, title="Kestrel news")
        self.mentions(q, ("Kestrel", "other", "subject"))
        out = self.stage(since=self.since)
        self.assertEqual(out["facts"]["placed"], {"rule:maker": 1, "wait": 1})
        self.cur.execute("SELECT post_id::text, placed FROM mx_mentions WHERE post_id IN (%s, %s)", (p, q))
        self.assertEqual(dict(self.cur.fetchall()), {p: "rule:maker", q: "wait"})
        self.cur.execute("SELECT entity_id::text, by, from_entity::text FROM mx_entity_pins WHERE post_id = %s", (p,))
        self.assertEqual(self.cur.fetchone(), (other, "facts", e))     # a pin, the link it replaced kept
        self.stage(since=self.since)                                    # the next linking honours it
        self.assertEqual(self.book().root(self.entity_of(p)), other)

    def test_search_shows_one_card_with_the_names_senses(self):
        e, other = self._two_senses()
        p = self.post(3, T0 + H, title="Orbis Kestrel")
        self.mentions(p, ("Kestrel (robot)", "product", "subject"))
        self.stage(since=self.since)
        switch(self, on=True)
        cards = search.with_senses(self.cur, [{"id": e, "name": "Kestrel", "type": "org", "maker": None, "posts": 1,
                                               "voices": 1, "matched": "kestrel"},
                                              {"id": other, "name": "Kestrel (robot)", "type": "product", "maker": None,
                                               "posts": 1, "voices": 1, "matched": "kestrel"}])
        self.assertEqual(len(cards), 1)
        self.assertEqual([s["what"] for s in cards[0]["senses"]], ["a startup", "a robot family"])

    def test_a_split_two_runs_agree_on_becomes_senses_with_their_facts(self):
        ps = [self.post(n, T0 + n * H, title=f"Vexa {t} {n}") for n, t in enumerate(["app", "app", "library"])]
        for p in ps:
            self.mentions(p, ("Vexa", "software", "subject"))
        self.stage()
        e = self.entity_of(ps[0])
        switch(self, on=True, split=True)
        senses = [{"m": [1, 2], "what": "a terminal app", "kind": "software", "maker": None, "context": ["terminal"]},
                  {"m": [3], "what": "an RSS parsing library", "kind": "software", "maker": None, "context": ["2003"]}]
        prop = {"senses": senses, "related": [], "unclear": [], "apart": [[1, 3], [2, 3]], "runs": 2, "split_runs": 2,
                "mentions": [{"n": k + 1, "span": "Vexa", "type": "software", "maker": None, "posts": [[p, 0]]}
                             for k, p in enumerate(ps)]}
        self.cur.execute("SELECT id::text FROM mx_calls LIMIT 1")
        call = self.cur.fetchone()[0]
        book = self.book()
        got = F.apply(self.cur, book, e, [(call, {"senses": senses})], "", prop=prop, run_id=None, guide="collide-v2")
        self.assertEqual((got["split"], got["senses"], got["pinned"]), (1, 1, 1))
        self.cur.execute("SELECT entity_id::text, by, from_entity::text FROM mx_entity_pins WHERE post_id = %s", (ps[2],))
        new, by, frm = self.cur.fetchone()
        self.assertEqual((by, frm), ("facts", e))
        facts = F.read(self.cur, [e, new], senses=True)
        self.assertEqual((facts[e].what, facts[new].what), ("a terminal app", "an RSS parsing library"))
        self.assertEqual([s["id"] for s in facts[e].senses], [new])
        self.assertEqual(entity_views.queue(self.cur)["open"], [])       # applied, not queued


class Handles(_Db):
    def test_a_first_name_in_a_post_by_the_persons_confirmed_account_is_that_person(self):
        p0 = self.post(0, T0, title="Kip Marlow on agents")
        self.mentions(p0, ("Kip Marlow", "person", "subject"))
        self.stage()
        person = self.entity_of(p0)
        self.cur.execute("INSERT INTO mx_entity_handles (entity_id, platform, handle, answer) VALUES (%s, 'x', 'kipm', 'yes')",
                         (person,))
        p = self.post(1, T0 + H, title="Kip: my agent skills")
        self.cur.execute("""INSERT INTO mx_handle_refs (post_id, digest, platform, handle, shown, form, role)
                            VALUES (%s, 'd', 'x', 'kipm', '@kipm', 'quote', 'by')""", (p,))
        self.mentions(p, ("Kip", "person", "subject"))
        switch(self, on=True, rule_handle=True)
        out = self.stage(since=self.since)
        self.assertEqual(out["facts"]["placed"], {"rule:handle": 1})
        self.stage(since=self.since)
        self.assertEqual(self.book().root(self.entity_of(p)), self.book().root(person))


class KnownSenses(Facts):
    def test_a_mention_the_answer_puts_in_a_known_sense_is_pinned_there(self):
        from insight_core.markx import tasks
        e, other = self._two_senses()
        p = self.post(3, T0 + 2 * H, title="The Kestrel robot walks")
        self.mentions(p, ("Kestrel", "product", "subject"))
        self.stage(since=self.since)
        self.assertEqual(self.entity_of(p), e)                           # linked by the name
        switch(self, on=True, known=True)
        book = self.book()
        order = [s.entity_id for s in F.known(self.cur, e)]
        text = F.known_block(self.cur, e) + I.collide_input(book.ents[e], 2, [(p, "Kestrel", "product", None)],
                                                            tasks.load_posts(self.cur, [p]))
        self.cur.execute("SELECT id::text FROM mx_calls LIMIT 1")
        call = self.cur.fetchone()[0]
        answer = {"senses": [{"m": [1], "known": f"S{order.index(other) + 1}", "what": "a robot family"}]}
        got = F.apply(self.cur, book, e, [(call, answer)], text, prop=None, run_id=None, guide="collide-v2",
                      mguide=["ent-v3"])
        self.assertEqual(got["known"], 1)
        self.cur.execute("SELECT entity_id::text, by FROM mx_entity_pins WHERE post_id = %s", (p,))
        self.assertEqual(self.cur.fetchone(), (other, "facts"))
        self.assertEqual(F.read(self.cur, [e])[e].what, "a startup")     # a known sense's facts never become e's
