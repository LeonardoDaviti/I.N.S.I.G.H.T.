"""0236 (Stealth v10.25): one release, one News row. Two Mark X stories a current same_release chain edge joins (0219,
rule chain_stops) are one row when `chains.one_row` is on: its posts in date order (the leaks first), named by the
launch (the maker's own story, else the newest story of a news type, never a leak story); a story that only mentions
the thing has no edge and stays out; joins never chain across two things. A row still untitled whose lead is a leak
takes the maker's own post's title. Invented names ("Orbit 4 Nova" by Acme); the DB tests run on a database whose
name ends in _test, each in one transaction rolled back."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import psycopg

from insight_core.markx import graph as G
from insight_core.markx import news as N
from insight_core.markx import repo, schemas
from insight_core.tests._db import clear_tables, db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

T = datetime(2100, 3, 1, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)
ON = {"on": True, "shown": (), "one_row": True}
OFF = {"on": True, "shown": (), "one_row": False}


class Rules(unittest.TestCase):
    """No database."""

    def test_same_release_edges_make_groups_of_one_thing(self):
        edges = [("b", "a", "nova"), ("c", "b", "nova"), ("e", "d", "other")]
        self.assertEqual(G.release_components(edges), [["a", "b", "c"], ["d", "e"]])

    def test_a_story_of_two_things_never_chains_them(self):
        # b is a stop of nova (two edges) and of a family (one edge): it keeps nova's; the family's edge joins nothing
        edges = [("b", "a", "nova"), ("c", "b", "nova"), ("x", "b", "family")]
        self.assertEqual(G.release_components(edges), [["a", "b", "c"]])
        # a tie: the lowest thing id, so the result never depends on the edges' order
        self.assertEqual(G.release_components([("b", "a", "t2"), ("c", "b", "t1")]),
                         G.release_components([("c", "b", "t1"), ("b", "a", "t2")]))

    def test_release_keys_name_each_group_by_its_lowest_story(self):
        self.assertEqual(N.release_keys([["s2", "s1", "s9"]], ["s1", "s2", "s3"]), {"s1": "s1", "s2": "s1"})
        self.assertEqual(N.release_keys([["s1", "s9"]], ["s1", "s2"]), {})   # one of the group here: no join

    def test_the_launch_names_the_row_never_a_leak(self):
        f = {"leak": {"maker": False, "type": "leak_rumour", "at": T},
             "launch": {"maker": True, "type": "model_release", "at": T + 5 * H},
             "bench": {"maker": False, "type": "model_release", "at": T + 9 * H}}
        self.assertEqual(N.launch_order(f), ["launch", "bench"])
        del f["launch"]                                     # no maker's story: the newest of a news type
        f["avail"] = {"maker": False, "type": "model_release", "at": T + 7 * H}
        self.assertEqual(N.launch_order(f), ["bench", "avail"])
        self.assertEqual(N.launch_order({"leak": {"maker": True, "type": "leak_rumour", "at": T}}), [])

    def test_a_result_the_maker_announced_alongside_never_names_the_release(self):
        # 0268: the maker's release, then the same day its result on a hard problem (its own post, a newer maker story
        # of a news type) and a day later its Q&A: the release names the row, however new the others are
        f = {"launch": {"maker": True, "type": "model_release", "at": T},
             "result": {"maker": True, "type": "research_result", "at": T + 1 * H},
             "qa": {"maker": True, "type": "public_statement", "at": T + 30 * H},
             "bench": {"maker": False, "type": "research_result", "at": T + 9 * H}}
        self.assertEqual(N.launch_order(f), ["launch", "qa", "result", "bench"])
        self.assertEqual(N.launch_order(f, {"result": 9, "launch": 40})[:2], ["launch", "result"])
        # two maker stories of a release (a preview, then the launch): the one holding most of the row's voices,
        # then the newest
        f = {"preview": {"maker": True, "type": "product_release", "at": T},
             "launch": {"maker": True, "type": "model_release", "at": T + 48 * H}}
        self.assertEqual(N.launch_order(f), ["launch", "preview"])
        self.assertEqual(N.launch_order(f, {"preview": 12, "launch": 30}), ["launch", "preview"])
        self.assertEqual(N.launch_order(f, {"preview": 30, "launch": 12}), ["preview", "launch"])

    def test_story_voices_count_each_voice_once(self):
        row = {"posts": [{"post_id": "p1", "voice": "a", "story": "s1"}, {"post_id": "p2", "voice": "a", "story": "s1"},
                         {"post_id": "p3", "voice": "b", "story": "s1"}, {"post_id": "p4", "voice": "c", "story": "s2"},
                         {"post_id": "p5", "voice": "d", "story": None}]}
        self.assertEqual(N.story_voices(row), {"s1": 2, "s2": 1})


@requires_test_db
class Row(unittest.TestCase):

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, MX_TABLES)
        schemas.load_guides(self.cur)
        self.run_id = repo.start_run(self.cur, code_version="t", config={})
        self.switch = dict(ON)
        patch = mock.patch.object(G, "chain_config", side_effect=lambda: dict(self.switch))
        patch.start()
        self.addCleanup(patch.stop)

    def post(self, hours, title):
        source = insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "Ex"}))
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        body = title + ". " + " ".join(f"word{k}{url[-6:]}" for k in range(30))
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (source, url, url, title, body, T + hours * H))
        pid = str(self.cur.fetchone()[0])
        from insight_core.db.repo_post_parts import PostPartsRepository
        PostPartsRepository.write(self.cur, [pid])
        return pid

    def story(self, headline=None):
        return str(repo.add_story(self.cur, first_at=T, run_id=self.run_id, headline=headline))

    def edge(self, later, earlier, relation="same_release", thing="nova"):
        self.cur.execute("""INSERT INTO mx_connections (a_kind, a, b_kind, b, relation, p, rule, evidence)
                            VALUES ('story', %s, 'story', %s, %s, 1.0, %s, %s::jsonb)""",
                         (later, earlier, relation, G.CHAIN_RULE, json.dumps({"reason": "r", "thing": thing})))

    def case(self):
        """A rumour account's teasers (the leak story, first), the maker's launch hours later with its coverage and a
        third party's benchmark, and a rival's launch story that names Nova once (no edge: it only mentions it)."""
        leak = [self.post(0, "Orbit 4 Nova leaks: coming today"), self.post(1, "Nova spotted in the app ahead of launch"),
                self.post(2, "Orbit 4 Nova teaser: benchmarks leaked"), self.post(3, "Nova is coming, says a tipster")]
        launch = [self.post(4, "Acme launches Orbit 4 Nova"), self.post(5, "Orbit 4 Nova is rolling out now"),
                  self.post(9, "Orbit 4 Nova tops the benchmark index")]
        rival = [self.post(6, "Beta ships Comet 2, faster than Nova"), self.post(7, "Comet 2 hands-on")]
        sl, sm, sr = self.story("Orbit 4 Nova leaks ahead of launch"), self.story("Acme launches Orbit 4 Nova"), self.story()
        self.edge(sm, sl)
        stories = {sl: (leak, set()), sm: (launch, set()), sr: (rival, set())}
        return stories, (sl, sm, sr), (leak, launch, rival)

    def rows(self, stories):
        return N.rows_of(self.cur, stories, T - 24 * H, window=set())

    def test_a_leak_story_and_its_launch_story_are_one_row_in_date_order(self):
        stories, (sl, sm, sr), (leak, launch, rival) = self.case()
        rows = self.rows(stories)
        self.assertEqual(len(rows), 2)
        one = next(r for r in rows if r["id"] == leak[0])
        self.assertEqual([p["post_id"] for p in one["posts"]], leak + launch)       # oldest first: the leaks, the launch
        self.assertEqual([p["story"] for p in one["posts"]], [sl] * 4 + [sm] * 3)  # each post names its own story
        other = next(r for r in rows if r["id"] != leak[0])
        self.assertEqual([p["post_id"] for p in other["posts"]], rival)             # the rival's story stays out
        # off: two rows, as before
        self.switch = dict(OFF)
        self.assertEqual(len(self.rows(stories)), 3)

    def test_the_joined_row_is_named_by_the_launch(self):
        stories, (sl, sm, sr), (leak, launch, rival) = self.case()
        row = next(r for r in self.rows(stories) if r["id"] == leak[0])
        # the leak story holds the most voices (its main story); built's facts (read-v3 types, the maker by identity) say which is which
        facts = {sl: {"maker": False, "post": None, "type": "leak_rumour", "at": T},
                 sm: {"maker": True, "post": launch[0], "type": "model_release", "at": T + 4 * H}}
        with mock.patch.object(N, "_story_facts", return_value=facts):
            self.assertEqual(N.headlines(self.cur, [row])[leak[0]], {"text": "Acme launches Orbit 4 Nova", "from": "haiku"})
        self.assertEqual(N.main_story(row), sl)
        self.switch = dict(OFF)   # off: no release row; its main story (the leaks) names it, as before
        with mock.patch.object(N, "_story_facts", return_value=facts):
            self.assertEqual(N.headlines(self.cur, [row])[leak[0]]["text"], "Orbit 4 Nova leaks ahead of launch")

    def test_a_release_row_is_never_named_by_a_result_merged_into_it(self):
        # 0268: the maker's launch story and its result announced the same day (the maker's own post, newer, of a
        # news type), joined into one row by a same_release edge: the launch's headline names it
        launch = [self.post(4, "Acme launches Orbit 4 Nova"), self.post(5, "Orbit 4 Nova is rolling out now"),
                  self.post(6, "Orbit 4 Nova, first look"), self.post(7, "Orbit 4 Nova pricing")]
        result = [self.post(5.5, "Orbit 4 Nova settles an open question in number theory"),
                  self.post(8, "Nova's number theory proof, explained")]
        sm = self.story("Acme launches Orbit 4 Nova")
        sx = self.story("Acme says Orbit 4 Nova settled an open question in number theory")
        self.edge(sx, sm)
        row = next(r for r in self.rows({sm: (launch, set()), sx: (result, set())}) if r["id"] == launch[0])
        self.assertEqual({p["story"] for p in row["posts"]}, {sm, sx})
        facts = {sm: {"maker": True, "post": launch[0], "type": "model_release", "at": T + 4 * H},
                 sx: {"maker": True, "post": result[0], "type": "research_result", "at": T + 5.5 * H}}
        with mock.patch.object(N, "_story_facts", return_value=facts):
            self.assertEqual(N.headlines(self.cur, [row])[launch[0]], {"text": "Acme launches Orbit 4 Nova", "from": "haiku"})

    def test_an_edge_that_is_not_same_release_joins_nothing(self):
        stories, (sl, sm, sr), (leak, launch, rival) = self.case()
        self.edge(sr, sm, relation="reaction")
        self.cur.execute("UPDATE mx_connections SET valid_to = now() WHERE relation = 'same_release'")
        self.assertEqual(len(self.rows(stories)), 3)

    def test_an_untitled_row_led_by_a_leak_takes_the_makers_post_title(self):
        leak, launch = self.post(0, "Nova leaks: coming today"), self.post(4, "Acme launches Orbit 4 Nova")
        sl, sm = self.story(), self.story()
        row = {"id": leak, "posts": [{"post_id": leak, "voice": "v0", "story": sl},
                                     {"post_id": launch, "voice": "v1", "story": sm}]}
        facts = {sl: {"maker": False, "post": None, "type": "leak_rumour", "at": T},
                 sm: {"maker": True, "post": launch, "type": "model_release", "at": T + 4 * H}}
        from insight_core.markx import event_types
        types = {leak: ("leak_rumour", None)}
        with mock.patch.object(N, "_story_facts", side_effect=lambda cur, ids: {s: facts[s] for s in ids if s in facts}), \
                mock.patch.object(event_types, "types_of", side_effect=lambda cur, ids: {i: types.get(i, (None, None)) for i in ids}):
            self.assertEqual(N.headlines(self.cur, [row])[leak], {"text": "Acme launches Orbit 4 Nova", "from": "maker title"})
            types[leak] = ("model_release", None)          # a lead that is no leak keeps its own title
            self.assertEqual(N.headlines(self.cur, [row])[leak], {"text": "Nova leaks: coming today", "from": "lead title"})
            types[leak] = ("leak_rumour", None)
            facts[sm] = dict(facts[sm], maker=False, post=None)   # no maker's post in the row: the lead's title
            self.assertEqual(N.headlines(self.cur, [row])[leak]["from"], "lead title")

    def test_an_edge_that_opens_joins_the_rows_in_an_incremental_run(self):
        stories, (sl, sm, sr), (leak, launch, rival) = self.case()
        self.switch = dict(OFF)
        since = T - 24 * H
        first = {}
        rows = N.rows_of(self.cur, stories, since, window=set(), first=first, joins=[])
        self.assertEqual(len(rows), 3)
        last = {"since": since, "window": set(), "first": first, "rows": rows, "joins": [],
                "stories": {s: (frozenset(ms), frozenset(m)) for s, (ms, m) in stories.items()}}
        self.switch = dict(ON)
        joins = G.release_groups(self.cur, list(stories))
        self.assertEqual(joins, [sorted([sl, sm])])
        again, group, _ = N._changed_rows(self.cur, stories, since, last, set(), joins=joins)
        self.assertEqual(sorted(len(r["posts"]) for r in again), [2, 7])
        self.assertEqual(group, set(leak) | set(launch))     # only the joined stories' posts were made again
        # and the full run makes the same rows
        self.assertEqual([[p["post_id"] for p in r["posts"]] for r in again],
                         [[p["post_id"] for p in r["posts"]] for r in N.rows_of(self.cur, stories, since, window=set())])


if __name__ == "__main__":
    unittest.main()
