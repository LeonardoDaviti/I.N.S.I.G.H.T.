"""v10.16.1 (issue 0186): a page's entity book. The News page read the whole entity book twice a request (250k entities
on the server) and walked every typed story of ~60 days for its "came true" links: 20 s a load. A page's book
(identity.lazy_book) reads only what it is asked and answers as the whole book; the maker's names are found through
migration 0127's indexes; the News page's reads don't grow with the book. Invented names only; a _test database."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import built as B, identity as I, names as N, news, perspectives as P, repo
from insight_core.tests.test_markx_built import D, H, Stored
from insight_core.tests.test_markx_folds import read3


class Ents:
    """Entities, aliases and merges written straight to the tables."""

    def ent(self, name, type_="org", maker=None, parent=None, status="provisional", key=None):
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, parent, maker, status)
                            VALUES (%s, %s, %s, 'thing', %s, %s, %s) RETURNING id::text""",
                         (type_, name, key or N.key(name), parent, maker, status))
        eid = self.cur.fetchone()[0]
        self.alias(key or N.key(name), eid)
        return eid

    def alias(self, key, eid):
        self.cur.execute("INSERT INTO mx_entity_aliases (key, entity_id, source) VALUES (%s, %s, 'rule') "
                         "ON CONFLICT DO NOTHING", (key, eid))

    def merge(self, frm, to):
        self.cur.execute("INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic) VALUES (%s, %s, 'test', true)",
                         (frm, to))

    def pad(self, n):
        """n more entities nobody names (the rest of a big book)."""
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, status)
                            SELECT 'org', 'Filler ' || i, 'filler ' || i, 'thing', 'provisional'
                              FROM generate_series(1, %s) i""", (n,))
        self.cur.execute("""INSERT INTO mx_entity_aliases (key, entity_id, source)
                            SELECT key, id, 'rule' FROM mx_entities WHERE key LIKE 'filler %%' ON CONFLICT DO NOTHING""")


class APagesBook(Ents, Stored):
    """identity.lazy_book answers what load_book answers, by id and by key, reading only what it is asked."""

    def setUp(self):
        super().setUp()
        self.acme = self.ent("Acme Labs")
        self.acme2 = self.ent("ACME")                         # merged into Acme Labs
        self.merge(self.acme2, self.acme)
        self.alias("acme-ai", self.acme2)                      # an alias of the merged one: Acme Labs' name too
        self.nimbus = self.ent("Nimbus 5", "model", maker="Acme")
        self.zeta = self.ent("Zeta Café", "person")
        self.orbit = self.ent("Orbit", "product", maker="Zeta Café")   # makes Zeta Café a maker
        self.lone = self.ent("Lone Widget", "product")
        self.pad(50)

    def test_it_answers_as_the_whole_book(self):
        whole, page = I.load_book(self.cur, counts=False), I.lazy_book(self.cur)
        ids = list(whole.ents) + ["00000000-0000-4000-8000-00000000dead"]
        for eid in ids:
            self.assertEqual((page.root(eid), page.label(eid), eid in page.ents), (whole.root(eid), whole.label(eid),
                                                                                eid in whole.ents), eid)
        for k in list(whole.alias) + ["nobody", ""]:
            self.assertEqual(page.by_key(k), whole.by_key(k), k)
        self.assertEqual(page.maker_roots(), whole.maker_roots())
        self.assertEqual(page.cluster(self.acme), whole.cluster(self.acme))
        keep = lambda r: r in (self.acme, self.zeta)           # noqa: E731
        fw, fp = whole.name_forms(keep), page.name_forms(keep)
        for r in ids:
            self.assertEqual(fp.of(r), fw.of(r), r)
        for f in {f for r in ids for f in fw.of(r)} | {"acmeai", "zetacafé", "nobody", ""}:
            self.assertEqual(fp.roots(f), fw.roots(f), f)
        self.assertEqual(fw.roots("acmeai"), {self.acme})     # an alias of a merged entity names the cluster

    def test_the_maker_found_by_the_names_is_the_same(self):
        whole, page = P.Makers(I.load_book(self.cur, counts=False), {}), P.Makers(I.lazy_book(self.cur), {})
        for owner in ("acme", "@acme_ai", "acmelabs", "zetacafe", "zeta_café", "orbit", "nimbus5", "nobody", ""):
            self.assertEqual(page.of_owner(owner), whole.of_owner(owner), owner)
        self.assertEqual(whole.of_owner("@acme_ai"), self.acme)
        for o in ("acme", "acme-ai", "zetacafé"):
            for mk in (self.acme, self.zeta, self.lone):
                self.assertEqual(page.is_maker(o, mk), whole.is_maker(o, mk), (o, mk))
        self.assertEqual(page.ancestors(self.nimbus), whole.ancestors(self.nimbus))

    def test_it_cannot_be_walked(self):
        page = I.lazy_book(self.cur)
        for walk in (lambda: list(page.ents), lambda: page.alias.items(), lambda: len(page.ents), page.members):
            with self.assertRaises(TypeError):
                walk()

    def test_squash_is_the_same_in_postgres(self):
        """names.SQUASH_SQL (migration 0127's index expression) gives names.squash's answer."""
        keys = ["Acme Labs", "acme-ai", "zeta café", "deep_seek v3.1", "c++ / c#", "Ünïcødé ТЕСТ тест", "日本語 モデル",
                "한국어", "x y", ""]
        self.cur.execute(f"SELECT key, {N.SQUASH_SQL} FROM unnest(%s::text[]) AS t(key)", (keys,))
        self.assertEqual(dict(self.cur.fetchall()), {k: N.squash(k) for k in keys})
        for idx in ("mx_entity_aliases_squash_idx", "mx_entities_squash_idx"):
            self.cur.execute("SELECT pg_get_indexdef(%s::regclass)", (idx,))
            self.assertIn(N.SQUASH, self.cur.fetchone()[0])


class TheNewsPageReadsWhatItShows(Ents, Stored):
    """The News page reads the entities its rows name, never the whole book: its reads don't grow with the book."""

    def page_reads(self, now):
        """news.page with the whole-book read forbidden; -> (the page, the entity rows read)."""
        got = {"rows": 0}
        read = I.read_ents

        def counted(cur, b, ids=None):
            before = len(dict(b.ents)) if not isinstance(b.ents, I._Reads) else 0
            read(cur, b, ids)
            got["rows"] += len(dict.keys(b.ents)) - before

        with mock.patch.object(I, "load_book", side_effect=AssertionError("the whole book")), \
                mock.patch.object(I, "read_ents", counted):
            page = news.page(self.cur, now=now)
        return page, got["rows"]

    def test_its_reads_dont_grow_with_the_book(self):
        now = datetime.now(timezone.utc)
        acme = self.ent("Acme")
        a = self.post(title="Acme releases Widget 5", at=now - 2 * H, links=[("https://acme.example/w5", "post")])
        b = self.post(title="Widget 5 is out", at=now - H, source=self.other, links=[("https://acme.example/w5", "post")])
        sid = self.story(a, b, at=now - 2 * H)
        for p in (a, b):
            self.read(p, read3(origin="maker"))
            self.subject(p, "Widget 5")
        self.cur.execute("""INSERT INTO mx_entity_surges (entity_id, day, voices, posts, rule, evidence)
                            VALUES (%s, %s, 2, 2, 'test', jsonb_build_object('posts', jsonb_build_array(%s::text)))""",
                         (acme, now.date(), a))
        repo.add_news_rows(self.cur, self.run, [{"id": a, "first_at": now - 2 * H, "voices": 2, "reports": 2,
                                                  "shares": 0, "mentions": 0, "score": 5, "tag": "NEW",
                                                  "posts": [{"post_id": p, "role": "report", "story": sid}
                                                            for p in (a, b)]}])
        repo.finish_run(self.cur, self.run, counts={})
        self.pad(20)
        small, small_reads = self.page_reads(now)
        self.pad(2000)
        big, big_reads = self.page_reads(now)
        self.assertEqual(big, small)
        self.assertEqual(big_reads, small_reads)
        self.assertLess(big_reads, 20)
        self.assertEqual([s["name"] for s in small["items"][0]["surging"]], ["Acme"])


class CameTrueReadsTheConnectedStories(Stored):
    """With SUBJECT_LINKS off only a judged connection links a leak story to its release: built.build reads the
    stories connected to the viewed ones, not every typed story of the window."""

    def test_an_unconnected_story_of_the_window_is_not_read(self):
        now = datetime.now(timezone.utc)
        l1 = self.post(title="Widget 5 leaked", at=now - 5 * D)
        l2 = self.post(title="Rumour: Widget 5", at=now - 5 * D + H, source=self.other)
        r1 = self.post(title="Acme releases Widget 5", at=now - D, source=self.other)
        r2 = self.post(title="Widget 5 is out", at=now - D + H)
        o1 = self.post(title="Gizmo 2 leaked", at=now - 3 * D)
        o2 = self.post(title="Gizmo 2 rumour", at=now - 3 * D + H, source=self.other)
        leak, rel, other = self.story(l1, l2, at=now - 5 * D), self.story(r1, r2, at=now - D), self.story(o1, o2, at=now - 3 * D)
        for p in (l1, l2, o1, o2):
            self.read(p, read3(event_type="leak_rumour"))
        for p in (r1, r2):
            self.read(p, read3())
        repo.open_connection(self.cur, a_kind="story", a=leak, b_kind="story", b=rel, relation="development",
                             run_id=self.run, p=0.8, rule="test")
        loaded = []
        load = B._load

        def recorded(cur, ids):
            loaded.extend(ids)
            return load(cur, ids)

        with mock.patch.object(B, "_load", recorded):
            got = B.build(self.cur, [rel])
        self.assertEqual([x["story"] for x in got[rel]["leaked_before"]], [leak])
        self.assertIn(leak, loaded)
        self.assertNotIn(other, loaded)                  # typed, in the window, but connected to nothing viewed
        with mock.patch.object(B, "SUBJECT_LINKS", True):   # with subjects on, the whole window is read again
            loaded.clear()
            with mock.patch.object(B, "_load", recorded):
                B.build(self.cur, [rel])
            self.assertIn(other, loaded)


if __name__ == "__main__":
    unittest.main()
