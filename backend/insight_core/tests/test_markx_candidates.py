"""Mark X Shadow's candidates (issue 0086 B) on synthetic posts with fixed vectors (a fake embedder: never the
GGUF), in one transaction rolled back after each test: the four sources at 0086 B's thresholds (embedding with
the prototype's 8 nearest, story centroids, Mark IX's joins, specific entities, late bursts), what each leaves
out, idempotence, Mark IX's tables only read, and the debounce.

Runs only on a database whose name ends in _test (it empties the mx_* tables inside its transaction)."""
from __future__ import annotations

import json
import math
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.db.repo_post_parts import PostPartsRepository
from insight_core.markx import candidates as C
from insight_core.markx import repo, schemas, tasks
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

T0 = datetime(2100, 1, 1, tzinfo=timezone.utc)   # no other test's post is near
H = timedelta(hours=1)
D = timedelta(days=1)


def unit(*parts, n=1024):
    v = [0.0] * n
    for k, w in parts:
        v[k] += w
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def at_cos(c, axis=1):
    """A unit vector at cosine c to e0."""
    return unit((0, c), (axis, math.sqrt(1 - c * c)))


@requires_test_db
class _Cands(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas.load_guides(self.cur)

    def source(self, platform="telegram"):
        return insert_scratch_source(self.cur, platform=platform, settings_json=json.dumps({"display_name": "Example"}))

    def post(self, source, at, *, vector=None, title="Acme released Widget 4.1", links=()):
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                         (source, url, url, title, f"{title}: the details of the release ({url[-6:]}).", at))
        pid = str(self.cur.fetchone()[0])
        for n, target in enumerate(links):
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, %s, %s)",
                             (pid, target, "example.com", n))
        if vector is not None:
            repo.put_embedding(self.cur, post_id=pid, model="bge-m3", text_hash="h-" + pid, vector=vector,
                               model_sha256="a" * 64)
        return pid

    def story(self, *members, reason="citation"):
        """A Mark IX story: the first member its root, each next one joined to the one before."""
        self.cur.execute("SELECT min(published_at) FROM posts WHERE id = ANY(%s::uuid[])", (list(members),))
        first_at = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, %s)", (members[0], first_at, len(members)))
        for n, m in enumerate(members):
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_id, parent_reason) "
                             "VALUES (%s, %s, 'report', %s, %s, %s)",
                             (m, members[0], f"v{n}", members[n - 1] if n else None, reason if n else None))
        return members[0]

    def pairs(self, source=None, kind=C.POST_POST):
        return {(str(r["a"]), str(r["b"])) for r in repo.candidates(self.cur, kind, source=source)}

    def find(self, *ids):
        return C.find(self.cur, ids)


class Embedding(_Cands):
    def test_other_sources_within_72_hours_at_065_not_one_story(self):
        s1, s2, s3 = self.source(), self.source(), self.source()
        a = self.post(s1, T0, vector=unit((0, 1.0)))
        near = self.post(s2, T0 + 10 * H, vector=at_cos(0.70))
        low = self.post(s2, T0 + 11 * H, vector=at_cos(0.60, axis=2))
        same_source = self.post(s1, T0 + 12 * H, vector=at_cos(0.95, axis=3))
        late = self.post(s3, T0 + 73 * H, vector=at_cos(0.95, axis=4))
        saved = self.post(self.source("saved"), T0 + 2 * H, vector=at_cos(0.95, axis=5))
        joined = self.post(s3, T0 + 3 * H, vector=at_cos(0.90, axis=6))
        self.story(a, joined)
        got = self.find(a)
        self.assertEqual(self.pairs("embedding"), {(a, near)})
        self.assertEqual(got["embedding"], 1)
        row, = repo.candidates(self.cur, C.POST_POST, source="embedding")
        self.assertAlmostEqual(row["score"], 0.70, places=2)
        del low, same_source, late, saved

    def test_the_earlier_post_is_a(self):
        s1, s2 = self.source(), self.source()
        b = self.post(s1, T0 + 5 * H, vector=unit((0, 1.0)))
        a = self.post(s2, T0, vector=at_cos(0.9))
        self.find(b)
        self.assertEqual(self.pairs("embedding"), {(a, b)})

    def test_the_8_nearest_of_either_post(self):
        """i's 9 neighbours are nearer each other than to i: i's 8 nearest make pairs, the 9th (0.73 to i) none,
        since i is not among its 8 nearest either."""
        i = self.post(self.source(), T0, vector=unit((0, 0.8), (1000, 0.6)))
        qs = [self.post(self.source(), T0 + (k + 1) * H, vector=unit((0, 1.0), (k + 1, 0.05 * (k + 1)))) for k in range(9)]
        self.find(i, *qs)
        got = self.pairs("embedding")
        with_i = {b if a == i else a for a, b in got if i in (a, b)}
        self.assertEqual(with_i, set(qs[:8]))
        self.assertEqual(len(got - {(i, q) for q in qs}), 36)   # the 9 neighbours among themselves

    def test_found_once_and_never_removed(self):
        s1, s2 = self.source(), self.source()
        a = self.post(s1, T0, vector=unit((0, 1.0)))
        b = self.post(s2, T0 + H, vector=at_cos(0.8))
        self.assertEqual(self.find(a)["embedding"], 1)
        self.assertEqual(self.find(a, b)["embedding"], 0)
        self.story(a, b)                    # Mark IX joins them later: the candidate stays
        self.find(a, b)
        self.assertEqual(self.pairs("embedding"), {(a, b)})


class Stories(_Cands):
    def test_story_centroids_at_070_within_14_days(self):
        s = [self.source() for _ in range(6)]
        x1 = self.post(s[0], T0, vector=unit((0, 1.0), (1, 0.2)))
        x2 = self.post(s[1], T0 + H, vector=unit((0, 1.0), (2, 0.2)))
        y1 = self.post(s[2], T0 + 10 * D, vector=unit((0, 0.8), (3, 0.6)))
        y2 = self.post(s[3], T0 + 10 * D + H, vector=unit((0, 0.8), (4, 0.6)))
        far1 = self.post(s[4], T0 + 15 * D, vector=unit((0, 1.0), (5, 0.1)))
        far2 = self.post(s[5], T0 + 15 * D + H, vector=unit((0, 1.0), (6, 0.1)))
        x, y, far = self.story(x1, x2), self.story(y1, y2), self.story(far1, far2)
        got = self.find(x2)
        self.assertEqual(self.pairs(kind=C.STORY_STORY), {(x, y)})    # far is 15 days from x
        self.assertEqual(got["embedding:story"], 1)
        self.find(far2)
        self.assertEqual(self.pairs(kind=C.STORY_STORY), {(x, y), (y, far)})


class Links(_Cands):
    def test_mark_ix_joins_are_link_candidates(self):
        s1, s2, s3 = self.source(), self.source(), self.source()
        a = self.post(s1, T0, vector=unit((0, 1.0)))
        b = self.post(s2, T0 + H, vector=unit((1, 1.0)))
        c = self.post(s3, T0 + 2 * H, vector=unit((2, 1.0)))
        self.story(a, b, c)
        self.find(b)
        self.assertEqual(self.pairs("link"), {(a, b), (b, c)})


class Entities(_Cands):
    def subjects(self, pid, *ents):
        task_id, _ = tasks.entities_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="claude-haiku-5-5", valid=True,
                             answer={"entities": []})
        repo.add_mentions(self.cur, post_id=pid, guide="ent-v3", call_id=call, mentions=[
            {"span": name, "name": name, "name_key": tasks.name_key(name), "type": type_, "role": role, "version": version}
            for name, type_, role, version in ents])

    def test_a_specific_main_subject_with_the_same_version(self):
        s = [self.source() for _ in range(6)]
        a = self.post(s[0], T0)
        b = self.post(s[1], T0 + 20 * H)
        other_version = self.post(s[2], T0 + 21 * H)
        an_org = self.post(s[3], T0 + 22 * H)
        late = self.post(s[4], T0 + 80 * H)
        an_actor = self.post(s[5], T0 + 2 * H)
        self.subjects(a, ("Widget 4.1", "model", "subject", "4.1"), ("Acme", "org", "subject", None))
        self.subjects(b, ("widget 4.1", "model", "subject", "4.1"))
        self.subjects(other_version, ("Widget 4.2", "model", "subject", "4.2"))
        self.subjects(an_org, ("Acme", "org", "subject", None))
        self.subjects(late, ("Widget 4.1", "model", "subject", "4.1"))
        self.subjects(an_actor, ("Widget 4.1", "model", "actor", "4.1"))
        got = self.find(a)
        self.assertEqual(self.pairs("entity"), {(a, b)})
        self.assertEqual(got["entity"], 1)

    def test_mentions_written_since_the_last_run_are_run(self):
        s1, s2 = self.source(), self.source()
        a, b = self.post(s1, T0), self.post(s2, T0 + H)
        self.subjects(a, ("FlashProve", "software", "subject", None))
        self.subjects(b, ("FlashProve", "software", "subject", None))
        C.run(self.cur, since=datetime.now(timezone.utc) - H)
        self.assertEqual(self.pairs("entity"), {(a, b)})


class Bursts(_Cands):
    PAGE = "https://example.com/research/page"

    def test_a_late_burst_on_one_page(self):
        s = [self.source() for _ in range(4)]
        first = self.post(s[0], T0, links=[self.PAGE])
        x = self.post(s[1], T0 + 5 * D, links=[self.PAGE])
        y = self.post(s[2], T0 + 5 * D + 10 * H, links=[self.PAGE])
        z = self.post(s[3], T0 + 9 * D, links=[self.PAGE])                          # 3.6 days after y: alone
        roundup = self.post(s[3], T0 + 5 * D + H, links=["https://example.com/other", "https://example.com/b",
                                                         self.PAGE])               # about its first link only
        PostPartsRepository.write(self.cur, [first, x, y, z, roundup])
        got = self.find(y)
        self.assertEqual(self.pairs("burst"), {(x, y)})
        self.assertEqual(got["burst"], 1)

    def test_a_burst_inside_mark_ixs_window_or_one_story_is_none(self):
        s = [self.source() for _ in range(3)]
        first = self.post(s[0], T0, links=[self.PAGE])
        x = self.post(s[1], T0 + 2 * D, links=[self.PAGE])                          # within 72 h of the first
        y = self.post(s[2], T0 + 2 * D + H, links=[self.PAGE])
        PostPartsRepository.write(self.cur, [first, x, y])
        self.find(y)
        self.assertEqual(self.pairs("burst"), set())

    def test_mark_ixs_tables_are_only_read(self):
        """A linker Mark IX hasn't read (no post_parts) is left out, never parsed: Mark X writes no Mark IX table."""
        s = [self.source() for _ in range(3)]
        first = self.post(s[0], T0, links=[self.PAGE])
        x = self.post(s[1], T0 + 5 * D, links=[self.PAGE])
        y = self.post(s[2], T0 + 5 * D + H, links=[self.PAGE])
        PostPartsRepository.write(self.cur, [first, x])
        self.cur.execute("SELECT count(*) FROM post_parts")
        before = self.cur.fetchone()[0]
        self.find(x, y)
        self.cur.execute("SELECT count(*) FROM post_parts")
        self.assertEqual(self.cur.fetchone()[0], before)
        self.assertEqual(self.pairs("burst"), set())


class Debounce(unittest.TestCase):
    def test_posts_wait_for_one_run_and_a_failed_run_keeps_them(self):
        runs = []

        class Tx:
            def __enter__(self):
                return "cursor"

            def __exit__(self, *exc):
                return False

        pending = C.Pending(delay=None, transaction=Tx)
        original = C.run
        self.addCleanup(setattr, C, "run", original)
        C.run = lambda cur, ids, since=None: runs.append((cur, set(ids), since)) or {"embedding": len(ids)}
        pending.note(["p1", "p2"])
        pending.note(["p2", "p3"])
        self.assertEqual(runs, [])
        self.assertEqual(pending.flush(), {"embedding": 3})
        self.assertEqual(runs[0][1], {"p1", "p2", "p3"})
        self.assertIsNotNone(pending.last_run)

        def boom(cur, ids, since=None):
            raise RuntimeError("database gone")
        C.run = boom
        pending.note(["p4"])
        with self.assertLogs(C.log, "ERROR"):
            self.assertIsNone(pending.flush())
        self.assertEqual(pending.posts, {"p4"})

    def test_a_timer_runs_it_after_the_last_note(self):
        pending = C.Pending(delay=0.05, transaction=None)
        done = []
        pending.flush = lambda: done.append(set(pending.posts))
        pending.note(["p1"])
        pending.note(["p2"])
        pending.timer.join(2)
        self.assertEqual(done, [{"p1", "p2"}])


if __name__ == "__main__":
    unittest.main()
