"""Stealth v10.44: track-v3 answers pass their checks. (1) A post written mostly in another script than English (a
Russian Habr article with Latin names and links) is not held to "the why names a word of the post": the English answer
cannot; its share of Latin words is counted on title and text, never links. (2) A quote of `Belongs:` needs most of
its words from it, by stem (a plural is its singular), function words aside. (3) The failed track-v3 questions are
asked again once (data repair reopen_failed_track_v3). Shaped on real answers Haiku gave (2026-11-23), with invented
tracks and posts; the DB test runs on a _test database."""
from __future__ import annotations

import unittest
import uuid

import psycopg

from insight_core.markx import repo, schemas, validate
from insight_core.scripts import reopen_failed_tracks
from insight_core.services import data_repairs
from insight_core.tests._db import db_url, requires_test_db

HEAD = ("TRACK: Local Setups\nBelongs: Running AI models on your own hardware: GPUs and machines, quantised models, "
        "inference engines and their settings, real speeds and memory on particular GPUs")
RU = HEAD + validate.POST_MARK + (
    "Platform: rss | Source: Example Хабр\nTitle: Министерство введёт для дата-центров и майнеров принцип оплаты\n"
    "Text: С 2027 года дата-центры и майнинговые фермы будут платить за заявленную мощность по принципу «бери или "
    "плати», сообщает Reuters со ссылкой на проект постановления; NVIDIA и AMD не комментируют.\n"
    "Links, in order:\n1. https://example.ru/articles/1111/?utm_source=feed&utm_medium=rss&utm_campaign=example\n"
    "2. https://example.com/news/energy-policy-datacenters-mining")
EN = HEAD + validate.POST_MARK + (
    "Platform: rss | Source: Example Blog\nTitle: Strata update doubles prefill on four R9700 cards\n"
    "Text: After the Strata update our four R9700 cards run the Flash model at 41 tok/s with prefill twice as fast; "
    "the quantised weights fit in 128 GB of memory.")


def answer(**kw):
    a = {"id": "x", "subject": "a take-or-pay electricity rule for data centres and miners", "fits": False,
         "matches": None, "excluded": None, "in": False, "confidence": 0.85, "subtopic": None,
         "why": "Electricity pricing policy for data centres and crypto miners; not about running models locally."}
    return {**a, **kw}


def check(a, q):
    return validate.check("track", a, q, "track-v3")[1]


class OtherScript(unittest.TestCase):
    def test_an_english_answer_to_a_russian_post_is_a_verdict(self):
        """Refused before v10.44: the links and names gave the post 5+ Latin words, none in the answer."""
        self.assertLess(validate._latin_share(RU), validate.LATIN_SHARE_MIN)
        self.assertIsNone(check(answer(), RU))

    def test_a_latin_post_still_needs_its_why_to_name_it(self):
        self.assertGreater(validate._latin_share(EN), validate.LATIN_SHARE_MIN)
        generic = answer(subject="a post", why="Not about the track.")
        self.assertIn("names nothing", check(generic, EN))
        self.assertIsNone(check(answer(subject="Strata update on R9700 cards", why="Prefill speeds after an update."), EN))

    def test_the_links_never_count_as_latin_text(self):
        only_links = HEAD + validate.POST_MARK + ("Platform: rss | Source: x\nTitle: Новости недели\nText: Короткий "
                                                  "обзор событий недели для читателей\nLinks, in order:\n"
                                                  "1. https://example.com/news/weekly-digest-latest-events-review")
        self.assertEqual(validate._latin_share(only_links), 0.0)


class Quotes(unittest.TestCase):
    def fit(self, matches):
        return check(answer(fits=True, matches=matches, **{"in": True, "subtopic": "inference engines",
                                                           "subject": "Strata update on R9700 cards",
                                                           "why": "Strata update: R9700 prefill twice as fast."}), EN)

    def test_a_quote_with_a_reworded_word_is_one(self):
        """Haiku's own quotes: one word of five or six its own, a plural, a function word."""
        self.assertIsNone(self.fit("real speeds and memory on specific GPUs"))
        self.assertIsNone(self.fit("inference engine settings"))   # "engines", "settings": one stem each
        self.assertIsNone(self.fit("quantised models with GPUs"))  # "with": a function word, not a quote's word

    def test_a_quote_mostly_of_other_words_is_refused(self):
        for q in ("inference tools for local serving", "Strata update speeds", "cheap cloud servers"):
            self.assertIn("its own words", self.fit(q), q)

    def test_the_stem(self):
        self.assertEqual(validate._stem("tools"), validate._stem("tool"))
        self.assertEqual(validate._stem("access"), validate._stem("accessed"))


@requires_test_db
class Reopen(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        schemas.ensure_guides(self.cur)
        tag = uuid.uuid4().hex
        self.ids = {}
        for name, kind, guide, subject in (("v3", "track", "track-v3", "post_track"),
                                           ("check", "track", "track-check-v2", "post_track"),
                                           ("v2", "track", "track-v2", "post_track"),
                                           ("read", "read", schemas.KINDS["read"].guide, "post")):
            tid, _ = repo.add_task(self.cur, kind=kind, guide=guide, subject_kind=subject, input=f"{name} {tag}")
            self.ids[name] = str(tid)
        self.cur.execute("UPDATE mx_tasks SET status = 'failed', attempts = 2, last_error = 'why: it names nothing' "
                         "WHERE id = ANY(%s::uuid[])", (list(self.ids.values()),))
        self.conn.commit()
        self.addCleanup(self._drop)

    def _drop(self):
        self.conn.rollback()
        self.cur.execute("DELETE FROM mx_tasks WHERE id = ANY(%s::uuid[])", (list(self.ids.values()),))
        self.conn.commit()

    def status(self):
        self.cur.execute("SELECT id::text, status, attempts FROM mx_tasks WHERE id = ANY(%s::uuid[])",
                         (list(self.ids.values()),))
        by_id = {i: (s, a) for i, s, a in self.cur.fetchall()}
        self.conn.commit()
        return {n: by_id[i] for n, i in self.ids.items()}

    def test_the_failed_track_v3_questions_open_once_the_rest_untouched(self):
        repair = data_repairs.by_name("reopen_failed_track_v3")
        self.assertEqual(repair.version, "v10.44")
        preview = reopen_failed_tracks.run(self.conn, dry_run=True)
        self.assertGreaterEqual(preview["reopened"], 2)
        self.assertEqual(self.status()["v3"], ("failed", 2), "a preview changes nothing")
        reopen_failed_tracks.run(self.conn, dry_run=False)
        got = self.status()
        self.assertEqual((got["v3"], got["check"]), (("open", 0), ("open", 0)))
        self.assertEqual((got["v2"], got["read"]), (("failed", 2), ("failed", 2)), "older guides and kinds stay")


if __name__ == "__main__":
    unittest.main()
