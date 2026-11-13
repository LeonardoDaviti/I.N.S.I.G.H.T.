"""0163 A (Stealth v10.13.11), what stays of later developments: long-lived stories, a story whose main subject is
one specific entity (its type and level), which back in the news and the anchors engine read. The follow-up trigger,
its questions, the pages and the follow switch were dropped in v10.18 (0203). Synthetic data only; the DB tests run on
a database whose name ends in _test."""
from __future__ import annotations

import json
import unittest

from insight_core.markx import later, repo, schemas, tasks
from insight_core.tests._db import insert_scratch_source
from insight_core.tests.test_markx_back import _Back


class Rules(unittest.TestCase):
    def ent(self, type="model", level="thing", version=None, variant=None, build=None, status="confirmed"):
        return later._Ent("e", type, status, "X", "x", level, version, variant, build)

    def test_specific_only(self):
        for t in ("paper", "document", "dataset"):
            self.assertTrue(later.specific(self.ent(t)), t)                       # by their type, always
        self.assertTrue(later.specific(self.ent("model", "version", "5")))
        self.assertTrue(later.specific(self.ent("model", "variant", "6", "Mini")))
        self.assertTrue(later.specific(self.ent("model", "checkpoint", "3.8")))
        self.assertTrue(later.specific(self.ent("model", "thing", "4.1")))       # a thing with a version
        self.assertTrue(later.specific(self.ent("software", "thing", build="2611")))
        self.assertFalse(later.specific(self.ent("model", "thing")))             # "<Assistant> AI": no version
        self.assertFalse(later.specific(self.ent("software", "thing")))          # a programming language
        self.assertFalse(later.specific(self.ent("model", "family", "5")))       # a family, even with a number
        self.assertFalse(later.specific(self.ent("product", "thing", "2")))      # a product: never
        for t in ("org", "person", "event", "place"):
            self.assertFalse(later.specific(self.ent(t, "thing", "1")), t)
        self.assertFalse(later.specific(self.ent("paper", status="not_entity")))
        self.assertFalse(later.specific(None))


class _Later(_Back):
    def setUp(self):
        super().setUp()
        self.saved = insert_scratch_source(self.cur, platform="saved", settings_json=json.dumps({"display_name": "Saved"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.saved,))

    def ent(self, name, type="model", family=None, version=None, level="thing", variant=None, key=None):
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, family_key, version, version_key, variant, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'confirmed') RETURNING id::text""",
                         (type, name, key or tasks.name_key(name), level, family,
                          ".".join(map(str, version)) if version else None, json.dumps(list(version)) if version else None,
                          variant))
        return self.cur.fetchone()[0]

    def release(self, name="Widget 4.1", type="model"):
        """A specific release: its version the name's last word."""
        return self.ent(name, type, version=tuple(int(x) if x.isdigit() else x for x in name.rsplit(" ", 1)[-1].split(".")))

    def subject(self, post, name="Widget 4.1", type="model", entity=None):
        super().subject(post, name, type)
        if entity:
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (entity, post))

    def subjects(self, post, *named):
        """A post whose one answer names several subjects: (name, type, entity or None) each."""
        with self.conn.transaction():
            tid, _ = tasks.entities_task(self.cur, post)
            call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="m", valid=True, answer={})
            repo.add_mentions(self.cur, post_id=post, guide=schemas.KINDS["entities"].guide, call_id=call_id,
                              mentions=[{"span": n, "name": n, "name_key": tasks.name_key(n), "type": t, "role": "subject"}
                                        for n, t, _e in named])
        for n, (_name, _t, e) in enumerate(named):
            if e:
                self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND n = %s", (e, post, n))

    def long(self, *, first=40, last=30, name="Widget 4.1", type="model", entity=None, links=()):
        """A story of two sources about `name`: by default a specific release of it (an entity of its own)."""
        if entity is None and name and type in later.LONG_TYPES:
            entity = self.release(name, type) if type in later.RELEASE_TYPES else self.ent(name, type)
        a = self.post(source=self.source, at=self.at(first), links=links)
        b = self.post(source=self.other, at=self.at(last), links=links)
        for p in (a, b):
            if name:
                self.subject(p, name, type, entity)
        return self.story(a, b), (a, b)

class LongLived(_Later):
    def test_only_a_paper_document_model_software_or_dataset_subject_keeps_listening(self):
        kept = {t: self.long(name=f"Thing {t}", type=t)[0] for t in ("model", "software", "dataset", "document")}
        dropped = {t: self.long(name=f"Thing {t}", type=t)[0] for t in ("event", "product", "org")}
        got = later.long_lived(self.cur)
        self.assertEqual(set(got) & set(kept.values()), set(kept.values()))
        self.assertEqual(set(got) & set(dropped.values()), set())

    def test_a_subject_of_one_post_of_two_read_is_no_subject(self):
        a, b = self.post(source=self.source, at=self.at(40)), self.post(source=self.other, at=self.at(30))
        self.subject(a, "Widget 4.1")
        self.subject(b, "Something Else", type="org")
        self.story(a, b)
        self.assertEqual(later.long_lived(self.cur), {})


if __name__ == "__main__":
    unittest.main()
