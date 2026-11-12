"""Mark X Shadow's embeddings (issue 0086 B, the build plan's corrections 6) through the app, against the run's own
_test database: the embed tasks (the text, newest first, one task a text, a duplicate's vector copied), and
POST /api/markx/embeddings (base64 float16 checked and stored as sent, one build per database, invalid vectors
back to open, a second vector changing nothing, the switch). A fake embedder: fixed vectors, never the GGUF.

These suites commit (the API opens its own transactions), so they run only on a database whose name ends in
_test. Every post and source is synthetic."""
from __future__ import annotations

import base64
import math
import struct
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from insight_core.markx import embed, jobs, repo, schemas, tasks
from insight_core.tests._db import requires_test_db
from insight_core.tests.test_markx_api import _Api, call
from insight_core.tests.test_markx_candidates import H, T0, _Cands

BUILD = "a" * 64
OTHER_BUILD = "b" * 64


def unit(*parts, n=1024):
    """A unit vector from (dimension, weight) parts."""
    v = [0.0] * n
    for k, w in parts:
        v[k] += w
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def f16(v):
    """v as stored: rounded to float16."""
    return list(struct.unpack(f"<{len(v)}e", struct.pack(f"<{len(v)}e", *v)))


@requires_test_db
class _Embed(_Api):
    def setUp(self):
        super().setUp()

    def embed_task(self, post=None, priority=0):
        with self.conn.transaction():
            return embed.embed_task(self.cur, post or self.post(), priority=priority)[0]

    def upload(self, *rows, model="bge-m3", build=BUILD, token=None):
        return call("POST", "/api/markx/embeddings", token=self.token if token is None else token,
                    body={"worker": "device-1", "model": model, "model_sha256": build,
                          "vectors": [{"task_id": str(t), "vector": v if isinstance(v, str) else embed.encode(v),
                                       "ms": 40} for t, v in rows]})


class TheText(unittest.TestCase):
    def post(self, title, text):
        return tasks.Post(id=str(uuid.uuid4()), kind="telegram", source="Example", source_id="s", at=datetime.now(timezone.utc),
                          title=title, text=text)

    def test_title_and_the_first_1500_characters_without_addresses(self):
        p = self.post("Acme released  Widget 4.1", "See https://example.com/a?b=1 and example.org/notes now.\n\n" + "x" * 3000)
        text = embed.embed_text(p)
        self.assertTrue(text.startswith("Acme released Widget 4.1 See and now. xxx"))
        self.assertNotIn("example", text)
        self.assertEqual(len(text), len("Acme released Widget 4.1 See and now. ") + 1500 - len("See https://example.com/a?b=1 and example.org/notes now.\n\n"))

    def test_the_title_is_left_out_when_the_text_starts_with_it(self):
        self.assertEqual(embed.embed_text(self.post("Acme released Widget", "Acme released Widget 4.1 today.")),
                         "Acme released Widget 4.1 today.")

    def test_a_post_that_says_nothing_gets_no_text_never_a_constant(self):
        """embed text v2: v1 embedded these as "(empty)", "[Photo]", "Image", "paper:", one vector for them all."""
        for title, text in (("", ""), ("[Photo]", ""), ("Image", ""), ("[Video]", "[Video]"),
                            ("example.com/notes/2501…", "example.com/notes/2501…"),
                            ("paper:", "paper: https://papers.test.invalid/2501.01234"), ("😳", "😳"),
                            ("example.com", "example.com")):
            with self.subTest(title=title):
                self.assertIsNone(embed.embed_text(self.post(title, text)))

    def test_a_post_of_addresses_is_described_by_its_links(self):
        p = self.post("tools.test.invalid/acme-widget-launch-notes…", "tools.test.invalid/acme-widget-launch-notes…")
        p.links = [("https://tools.test.invalid/acme-widget-launch-notes", "tools.test.invalid/acme-widget-launch…")]
        self.assertEqual(embed.embed_text(p), "acme widget launch notes tools.test.invalid")
        # a stored post's title at that address says more than the slug, and comes first
        titles = {"https://tools.test.invalid/acme-widget-launch-notes": "Acme launches Widget 5"}
        self.assertEqual(embed.embed_text(p, titles),
                         "Acme launches Widget 5 acme widget launch notes tools.test.invalid")
        # an id, a hash or a media file says nothing: no text
        for url in ("https://video.test.invalid/watch/ncWRe-JIWRs", "https://papers.test.invalid/abs/2501.01234",
                    "https://cdn.test.invalid/media/1/Screen_Recording_at_noon.mp4",
                    "https://blog.test.invalid/p/abbed9b8edab"):
            with self.subTest(url=url):
                q = self.post("[Photo]", "")
                q.links = [(url, None)]
                self.assertIsNone(embed.embed_text(q))

    def test_a_post_that_says_something_keeps_its_v1_text(self):
        """Only the posts v1 embedded as nothing change: every other v1 vector stays current."""
        for title, text, want in (("Acme", "Acme released Widget https://example.com", "Acme released Widget"),
                                  ("[Photo]", "Look at this", "[Photo] Look at this"),
                                  ("", "Claude Opus дома", "Claude Opus дома"),
                                  ("", "新模型发布了", "新模型发布了")):
            with self.subTest(text=text):
                self.assertEqual(embed.embed_text(self.post(title, text)), want)

    def test_words_that_say_something(self):
        self.assertEqual(embed.words("[Photo] Image"), 1)
        self.assertEqual(embed.words("example.com"), 1)
        self.assertEqual(embed.words("a b c"), 0)
        self.assertEqual(embed.words("Next.js released"), 2)
        self.assertEqual(embed.words("新模型发布"), 2)
        self.assertFalse(embed.says_something("paper: https://papers.test.invalid/2501.01234"))
        self.assertFalse(embed.says_something("(empty)"))
        self.assertTrue(embed.says_something("Widget 5 out"))

    def test_the_kind_has_its_guide_and_schema(self):
        kind = schemas.KINDS["embed"]
        self.assertEqual((kind.guide, kind.subject), ("embed-v1", "post"))
        self.assertTrue((schemas.GUIDES_DIR / "embed-v1.md").is_file())
        self.assertEqual(len(embed.encode([0.0] * 1024)), kind.schema["properties"]["vector"]["maxLength"])


class Planning(_Embed):
    def test_newest_first_one_task_a_text_and_a_duplicate_copied(self):
        now = datetime(2100, 1, 1, tzinfo=timezone.utc)   # no other test's post is in its 10 days
        old = self.post(title="Globex raised $300m", at=now - timedelta(days=3))
        new = self.post(at=now)
        same = "Initech shipped the same words twice, as one channel copies another, word for word."
        a = self.post(title="Initech", text=same, at=now - timedelta(days=1))
        b = self.post(title="Initech", text=same, source=self.other, at=now - timedelta(days=1, hours=1))
        with self.conn.transaction():
            added = embed.plan(self.cur, days=10, now=now)
        self.assertEqual(added, 3)
        self.cur.execute("SELECT a::text, priority, input FROM mx_tasks WHERE kind = 'embed' ORDER BY priority, created_at")
        rows = self.cur.fetchall()
        self.assertEqual([r[0] for r in rows], [new, a, old])          # b's text is a's task
        self.assertEqual([r[1] for r in rows], [0, 1, 3])
        posts = tasks.load_posts(self.cur, [new])
        self.assertEqual(rows[0][2], embed.embed_text(posts[new]))
        # a's vector arrives: the next plan copies it to b, and b goes to the candidates
        task_a = repo.task_for(self.cur, kind="embed", guide="embed-v1", input=rows[1][2])["id"]
        self.lease("embed", limit=10)
        self.assertEqual(self.upload((task_a, unit((0, 1.0))))[1]["stored"], 1)
        self.cur.execute("UPDATE mx_candidate_posts SET found_at = now()")   # found: none waits
        with self.conn.transaction():
            self.assertEqual(embed.plan(self.cur, days=10, now=now), 0)
        self.assertEqual(repo.embedding(self.cur, b, "bge-m3"), repo.embedding(self.cur, a, "bge-m3"))
        self.assertEqual(jobs.waiting_posts(self.cur), [b])
        self.assertEqual(repo.embedding_builds(self.cur, "bge-m3"), {BUILD: 2})

    def test_work_plans_and_leases_embed_tasks_with_their_guide(self):
        pid = self.post()
        self.addCleanup(setattr, tasks, "PLANNERS", tasks.PLANNERS)
        tasks.PLANNERS = {"embed": tasks._plan_embeds}
        status, body = self.lease("embed")
        self.assertEqual(status, 200, body)
        self.assertEqual({t["kind"] for t in body["tasks"]}, {"embed"})
        self.assertEqual(set(body["guides"]), {"embed-v1"})
        self.assertIn("No model reads this guide", body["guides"]["embed-v1"]["body"])
        self.assertIn(uuid.UUID(pid), [repo.get_task(self.cur, t["id"])["a"] for t in body["tasks"]])


class SaidNothing(_Embed):
    """embed text v2 on the database: a post that says nothing is skipped (recorded, not read again); a v1 vector of
    a text that said nothing is set aside (kept under SET_ASIDE) and its post planned again; a late answer to a
    v1 task of nothing is kept aside; the decision run reads embedding candidates by the vectors now."""

    def setUp(self):
        super().setUp()
        embed._set_aside.clear()
        self.addCleanup(embed._set_aside.clear)

    def v1_vector(self, pid, text, v):
        """A post embedded under v1 as `text` (its task answered, its vector stored)."""
        task_id, _ = repo.add_task(self.cur, kind="embed", guide="embed-v1", subject_kind="post", input=text, a=pid)
        repo.answer_task(self.cur, task_id)
        repo.put_embedding(self.cur, post_id=pid, model="bge-m3", text_hash=repo.sha256_hex(text), vector=v,
                           model_sha256=BUILD)

    def test_a_post_that_says_nothing_is_skipped_once(self):
        now = datetime(2100, 1, 1, tzinfo=timezone.utc)
        photo = self.post(title="[Photo]", text="", at=now)
        said = self.post(at=now - timedelta(hours=1))
        with self.conn.transaction():
            self.assertEqual(embed.plan(self.cur, days=10, now=now), 1)
        self.cur.execute("SELECT a::text FROM mx_tasks WHERE kind = 'embed'")
        self.assertEqual([r[0] for r in self.cur.fetchall()], [said])
        self.cur.execute("SELECT post_id::text, text_version FROM mx_embed_skips")
        self.assertEqual(self.cur.fetchall(), [(photo, embed.TEXT_VERSION)])
        with self.conn.transaction():
            self.assertEqual(embed.plan(self.cur, days=10, now=now), 0)
            self.assertEqual(embed.embed_task(self.cur, photo), (None, False))

    def test_v1_vectors_of_nothing_are_set_aside_and_planned_again(self):
        now = datetime(2100, 1, 1, tzinfo=timezone.utc)
        slug = "https://tools.test.invalid/acme-widget-launch-notes"
        a = self.post(title="tools.test.invalid/acme-widget…", text="tools.test.invalid/acme-widget…", at=now,
                      links=[(slug, "tools.test.invalid/acme-widget…")])
        b = self.post(title="papers.test.invalid/abs/2501…", text="papers.test.invalid/abs/2501…", at=now,
                      source=self.other, links=[("https://papers.test.invalid/abs/2501.01234", None)])
        kept = self.post(at=now - timedelta(hours=2))
        with self.conn.transaction():
            self.v1_vector(a, "(empty)", unit((0, 1.0)))
            self.cur.execute("""INSERT INTO mx_embeddings (post_id, model, model_sha256, text_hash, v)
                                SELECT %s, model, model_sha256, text_hash, v FROM mx_embeddings WHERE post_id = %s""",
                             (b, a))                                    # v1 copied the vector to b: one text
            self.v1_vector(kept, embed.embed_text(tasks.load_posts(self.cur, [kept])[kept]), unit((1, 1.0)))
            self.assertEqual(embed.plan(self.cur, days=10, now=now), 1)
        self.cur.execute("SELECT post_id::text, model FROM mx_embeddings")
        self.assertEqual(sorted(self.cur.fetchall()),
                         sorted([(a, embed.SET_ASIDE), (b, embed.SET_ASIDE), (kept, "bge-m3")]))   # kept, not deleted
        self.cur.execute("SELECT a::text, input FROM mx_tasks WHERE kind = 'embed' AND status = 'open'")
        self.assertEqual(self.cur.fetchall(), [(a, "acme widget launch notes tools.test.invalid")])
        self.cur.execute("SELECT post_id::text FROM mx_embed_skips")
        self.assertEqual([r[0] for r in self.cur.fetchall()], [b])
        self.assertEqual(repo.embedding_builds(self.cur, "bge-m3"), {BUILD: 1})

    def test_a_late_vector_of_a_v1_text_of_nothing_is_kept_aside(self):
        pid = self.post(title="[Photo]", text="")
        with self.conn.transaction():
            task_id, _ = repo.add_task(self.cur, kind="embed", guide="embed-v1", subject_kind="post", input="[Photo]",
                                       a=pid)
        self.lease("embed")
        status, body = self.upload((task_id, unit((0, 1.0))))
        self.assertEqual((status, body["stored"]), (200, 1))
        self.assertIsNone(repo.embedding(self.cur, pid, "bge-m3"))
        self.assertIsNotNone(repo.embedding(self.cur, pid, embed.SET_ASIDE))
        self.assertEqual(jobs.waiting_posts(self.cur), [])                 # no candidates from it

    def test_the_decision_run_reads_embedding_candidates_by_the_vectors_now(self):
        a, b, c, d = (self.post(title=f"Post {n}", text=f"Words of post {n} about something else entirely {n}.")
                      for n in "abcd")
        copy1 = self.post(title="Acme", text="Acme released Widget 5 today for everyone who asked.")
        copy2 = self.post(title="Acme", text="Acme released Widget 5 today for everyone who asked.", source=self.other)
        e = self.post(title="Other", text="Globex raised money from investors this week, a round of $300m.")
        with self.conn.transaction():
            for pid, v in ((a, unit((0, 1.0))), (b, unit((0, 0.8), (1, 0.6))), (c, unit((2, 1.0))),
                           (copy1, unit((3, 1.0))), (copy2, unit((3, 1.0))), (e, unit((3, 1.0)))):
                repo.put_embedding(self.cur, post_id=pid, model="bge-m3", text_hash="h-" + pid, vector=v,
                                   model_sha256=BUILD)
            repo.put_embedding(self.cur, post_id=d, model=embed.SET_ASIDE, text_hash="h-" + d, vector=unit((2, 1.0)),
                               model_sha256=BUILD)
        rows = [(a, b, "embedding", 0.95),          # a's vector replaced since: its cosine now (0.8)
                (a, d, "embedding", 1.0),           # d set aside: not asked
                (c, d, "entity", None),             # another source: as it was
                (c, a, "embedding", 0.7),           # below the bar now: carried, plan_pass1 leaves it
                (copy1, copy2, "embedding", 1.0),   # one vector, near-copies: kept
                (copy1, e, "embedding", 1.0)]       # one vector, two texts: not asked
        got = embed.current_candidates(self.cur, rows)
        self.assertEqual([(x, y, s, None if sc is None else round(sc, 2)) for x, y, s, sc in got],
                         [(a, b, "embedding", 0.8), (c, d, "entity", None), (c, a, "embedding", 0.0),
                          (copy1, copy2, "embedding", 1.0)])

    def test_a_name_of_no_letter_is_not_embedded(self):
        with self.conn.transaction():
            self.cur.execute("INSERT INTO mx_entities (name, key, type) VALUES ('—', 'x-dash', 'product'), "
                             "('Acme Widget', 'acme widget', 'product')")
            self.assertEqual(embed.plan_names(self.cur), 1)
        self.cur.execute("SELECT input FROM mx_tasks WHERE kind = 'embed_name'")
        self.assertEqual([r[0] for r in self.cur.fetchall()], ["Acme Widget"])


class OneVector(_Cands):
    """The candidate finder never pairs two posts of one vector unless their texts are near-copies that say
    something (embed.same_vector)."""

    def test_one_vector_two_texts_is_no_candidate(self):
        s1, s2, s3 = self.source(), self.source(), self.source()
        a = self.post(s1, T0, vector=unit((0, 1.0)), title="Acme released Widget 4.1")
        other = self.post(s2, T0 + H, vector=unit((0, 1.0)), title="Globex raised $300m from investors")
        copy = self.post(s3, T0 + 2 * H, vector=unit((0, 1.0)), title="Acme released Widget 4.1")
        self.find(a)
        self.assertEqual(self.pairs("embedding"), {(a, copy)})
        del other


class Uploads(_Embed):
    def test_a_vector_is_stored_as_sent_and_closes_its_task(self):
        pid = self.post()
        t = self.embed_task(pid)
        self.lease("embed")
        v = unit((0, 0.6), (5, 0.8), (1023, 0.05))
        status, body = self.upload((t, v))
        self.assertEqual((status, body), (200, {"stored": 1, "invalid": [], "repeated": 0}))
        self.assertEqual(self.row(t)["status"], "answered")
        self.assertEqual(f16(repo.embedding(self.cur, pid, "bge-m3")), f16(v))   # halfvec: the float16 sent
        self.cur.execute("SELECT model_sha256, text_hash FROM mx_embeddings WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchone(), (BUILD, self.row(t)["input_hash"]))
        self.assertEqual(jobs.waiting_posts(self.cur), [pid])
        self.assertIsNotNone(jobs.state(self.cur)["candidates"]["wanted_at"])   # the API marks; ingestion finds
        self.assertEqual(repo.calls(self.cur, t), [])          # a vector is not a model call

    def test_a_second_vector_changes_nothing(self):
        pid = self.post()
        t = self.embed_task(pid)
        self.upload((t, unit((0, 1.0))))
        status, body = self.upload((t, unit((1, 1.0))))
        self.assertEqual((status, body), (200, {"stored": 0, "invalid": [], "repeated": 1}))
        self.assertEqual(repo.embedding(self.cur, pid, "bge-m3")[:2], [1.0, 0.0])

    def test_invalid_vectors_come_back_with_their_errors_and_fail_at_the_third(self):
        cases = {
            "short": (base64.b64encode(b"\0" * 100).decode(), "vector: 100 bytes, not 2048"),
            "not base64": ("!!!" * 900, "vector: not base64"),
            "norm": ([2 * x for x in unit((0, 1.0))], "vector: norm 2.0000, not 1"),
            "nan": (base64.b64encode(struct.pack("<1024e", *([float("nan")] + [0.0] * 1023))).decode(),
                    "vector: a number that is not finite"),
        }
        for name, (vector, error) in cases.items():
            with self.subTest(name=name):
                t = self.embed_task()
                _, body = self.upload((t, vector))
                self.assertEqual(body["stored"], 0)
                self.assertTrue(body["invalid"][0]["error"].startswith(error), body["invalid"][0]["error"])
                self.assertEqual((self.row(t)["status"], self.row(t)["attempts"]), ("open", 1))
        t = self.embed_task()
        for _ in range(3):
            self.upload((t, "x"))
        self.assertEqual(self.row(t)["status"], "failed")

    def test_another_build_is_refused_whole(self):
        a, b = self.embed_task(), self.embed_task()
        self.upload((a, unit((0, 1.0))))
        status, body = self.upload((b, unit((1, 1.0))), build=OTHER_BUILD)
        self.assertEqual(status, 409)
        self.assertIn(BUILD, body["detail"])
        self.assertEqual(self.row(b)["status"], "open")
        self.assertEqual(repo.embedding_builds(self.cur, "bge-m3"), {BUILD: 1})

    def test_another_model_or_not_a_sha256_is_a_bad_request(self):
        t = self.embed_task()
        self.assertEqual(self.upload((t, unit((0, 1.0))), model="bge-small")[0], 400)
        self.assertEqual(self.upload((t, unit((0, 1.0))), build="not-a-sha")[0], 400)
        self.assertEqual(self.row(t)["status"], "open")

    def test_no_such_embed_task(self):
        read = self.task("read")
        _, body = self.upload((read, unit((0, 1.0))), (uuid.uuid4(), unit((0, 1.0))), ("nope", unit((0, 1.0))))
        self.assertEqual([x["error"] for x in body["invalid"]], ["no such embed task"] * 3)
        self.assertEqual(self.row(read)["status"], "open")

    def test_an_embed_task_answered_at_answers_is_invalid(self):
        t = self.embed_task()
        _, body = self.answer((t, {"vector": embed.encode(unit((0, 1.0)))}))
        self.assertEqual(body["valid"], 0)
        self.assertIn("POST /api/markx/embeddings", body["invalid"][0]["error"])

    def test_the_route_needs_the_token_and_the_switch(self):
        t = self.embed_task()
        self.assertEqual(self.upload((t, unit((0, 1.0))), token="wrong")[0], 401)
        import os
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertEqual(self.upload((t, unit((0, 1.0))))[0], 404)
        self.assertEqual(self.row(t)["status"], "open")


if __name__ == "__main__":
    unittest.main()
