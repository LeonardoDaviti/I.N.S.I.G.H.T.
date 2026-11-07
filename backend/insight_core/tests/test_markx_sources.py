"""0132 B (Stealth v10.6): the source analysis page. The role rule's order and "official"; the stance answer's quotes
checked by code; each card's formula and threshold on synthetic sources (posting rate, own share, first to report,
solo share, News yield, cited by, too few to tell); voices when the table exists, per source when it doesn't; the
page's routes (rows only, no overall score, 404s); the stance planner (monthly, own posts of 250+ characters) and its
labels; Part C1 (the last 20 posts read) and C3 (Telegram forwards) off by default; the stats job's schedule.
Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import json
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg

from insight_core.markx import schemas, source_role as R, source_stats as S, tasks, validate
from insight_core.tests.test_markx_api import _Api, call, reading

NOW = datetime.now(timezone.utc)
D = timedelta(days=1)


# ---- the role rule (no database) --------------------------------------------------------------------

class TheRoleRule(unittest.TestCase):
    def test_the_order(self):
        base = dict(kind="x", posts=40, read=12, own_share=0.9, kinds={"report": 0.6, "commentary": 0.4})
        cases = [
            (dict(kind="reddit"), "platform"),
            (dict(kind="site", authors=12), "platform"),
            (dict(kind="site", own_pages_share=0.1), "curator"),
            (dict(official=True, self_share=0.5, maker="Other", maker_share=0.9, own_share=0.2), "official"),
            (dict(maker="Other Co", maker_share=0.6, own_share=0.2), "staff_or_beat"),
            (dict(own_share=0.4, kinds={"roundup": 0.9}), "reposter"),
            (dict(kinds={"roundup": 0.35, "commentary": 0.65}), "curator"),
            (dict(link_post_share=0.5, kinds={"commentary": 0.9}), "curator"),
            (dict(kinds={"commentary": 0.45, "report": 0.55}), "commentator"),
            (dict(kinds={"report": 0.5, "tool": 0.5}), "reporter"),
            (dict(kinds={"tool": 0.6, "other": 0.4}), "independent"),
            (dict(read=4, posts=4, kinds={"report": 1.0}), "too_few"),
        ]
        for over, want in cases:
            with self.subTest(want=want, over=over):
                role, line = R.role(R.Facts(**{**base, **over}))
                self.assertEqual(role, want, line)
                self.assertTrue(line)

    def test_staff_or_beat_needs_five_read_posts_and_says_needs_a_bio(self):
        self.assertEqual(R.role(R.Facts(read=4, maker="Other", maker_share=1.0))[0], "too_few")
        role, line = R.role(R.Facts(read=5, maker="Other", maker_share=0.5))
        self.assertEqual(role, "staff_or_beat")
        self.assertIn("needs a bio", line)

    def test_link_posts_make_a_curator_only_on_x_or_telegram(self):
        f = dict(posts=20, read=10, link_post_share=0.8, kinds={"commentary": 0.8})
        self.assertEqual(R.role(R.Facts(kind="telegram", **f))[0], "curator")
        self.assertEqual(R.role(R.Facts(kind="site", **f))[0], "commentator")

    def test_official_by_name_handle_label_or_acronym(self):
        def read(*names):
            return {f"p{i}": [R.Mention(n, None, "subject", "org")] for i, n in enumerate(names)}
        names = R.Names.of(["Acme Labs"], ["acmelabs"], ["blog.acme-labs.example"])
        ok, share, n, hits = R.official(read("Acme Labs", "Acme", "Widget", "Widget", "Gadget"), names)
        self.assertEqual((ok, n, len(hits)), (True, 5, 2))
        self.assertAlmostEqual(share, 0.4)
        self.assertFalse(R.official(read("Acme Labs", "Acme"), names)[0])             # fewer than 5 read posts
        self.assertFalse(R.official(read("Acme Labs", "W", "W", "W", "W"), names)[0])   # 20%: under 30%
        institute = R.Names.of(["ESI News"], [], ["esi.gov.zz"])
        ok, *_ = R.official(read(*["Example Safety Institute"] * 2, "W", "W", "W"), institute)
        self.assertTrue(ok)                                                             # by acronym
        # a mention as a mere mention never counts
        ms = {f"p{i}": [R.Mention("Acme Labs", None, "mention", "org")] for i in range(6)}
        self.assertFalse(R.official(ms, names)[0])

    def test_the_top_maker_is_never_the_source_itself(self):
        names = R.Names.of(["Acme Labs"], ["acmelabs"])
        rd = {"a": [R.Mention("Acme Labs", None, "subject", "org"), R.Mention("Bolt 2", "Other Co", "subject", "model")],
              "b": [R.Mention("Bolt 3", "Other Co Inc", "actor", "model")], "c": [R.Mention("Acme", None, "subject", "org")]}
        maker, share, posts = R.top_maker(rd, names)
        self.assertEqual((maker, round(share, 2), sorted(posts)), ("Other Co", 0.67, ["a", "b"]))


# ---- the stance answer's quotes (no database) ---------------------------------------------------------

STANCE_INPUT = tasks.stance_input("Example Wire", "site", [
    "First post. We simply cannot trust the vendor again after this week.",
    "Second post. Once more the vendor promised and we cannot trust it.",
    "Third post. A neutral report about a chip with 3 nm and 40 W.",
])


class TheStanceQuotes(unittest.TestCase):
    def answer(self, *patterns):
        return {"patterns": list(patterns), "voice": "commentator", "interest": None, "too_few": False}

    def test_a_pattern_needs_two_exact_quotes_from_two_posts(self):
        good = {"pattern": "distrusts the vendor", "kind": "stance", "strength": "clear",
                "evidence": [{"post": 1, "quote": "we simply cannot trust the vendor"},
                             {"post": 2, "quote": "we cannot trust it"}]}
        one_post = {"pattern": "x", "evidence": [{"post": 1, "quote": "First post"}, {"post": 1, "quote": "this week"}]}
        reworded = {"pattern": "y", "evidence": [{"post": 1, "quote": "the vendor can't be trusted"},
                                                 {"post": 3, "quote": "A neutral report"}]}
        got = validate.stance_grounded(self.answer(good, one_post, reworded), STANCE_INPUT)
        self.assertEqual([p["pattern"] for p in got], ["distrusts the vendor"])
        self.assertEqual([q["post"] for q in got[0]["quotes"]], [1, 2])
        # folded: case, typographic quotes and runs of space don't matter
        loose = dict(good, evidence=[{"post": 1, "quote": "WE  SIMPLY cannot trust"}, {"post": 2, "quote": "we cannot"}])
        self.assertEqual(len(validate.stance_grounded(self.answer(loose), STANCE_INPUT)), 1)

    def test_the_answer_check(self):
        good = {"pattern": "p", "evidence": [{"post": 1, "quote": "First post"}, {"post": 2, "quote": "Second"}]}
        self.assertIsNone(validate.check("stance", self.answer(good), STANCE_INPUT)[1])
        bad = {"pattern": "p", "evidence": [{"post": 9, "quote": "First post"}]}
        self.assertIn("post 9", validate.check("stance", self.answer(bad), STANCE_INPUT)[1])
        self.assertIn("patterns", validate.check("stance", {"patterns": [good] * 5}, STANCE_INPUT)[1])
        self.assertEqual(schemas.KINDS["stance"].guide, "stance-v1")
        body = schemas.guide_body("stance-v1")
        self.assertIn("at least 2 quotes from 2 different posts", body)


# ---- Part C3: Telegram forwards (no database) ---------------------------------------------------------

class TelegramForwards(unittest.TestCase):
    def test_kept_only_with_the_switch(self):
        from insight_core.ingestion.kinds.telegram_mtproto import synthesize_posts
        fwd = SimpleNamespace(from_id=SimpleNamespace(channel_id=42), from_name=None, channel_post=7,
                              date=datetime(2026, 10, 1, tzinfo=timezone.utc))
        msgs = [SimpleNamespace(id=2, grouped_id=None, text="forwarded", media=None, date=NOW, fwd_from=fwd),
                SimpleNamespace(id=1, grouped_id=None, text="own", media=None, date=NOW, fwd_from=None)]
        old = os.environ.pop("INSIGHT_TELEGRAM_FORWARDS", None)
        self.addCleanup(lambda: os.environ.__setitem__("INSIGHT_TELEGRAM_FORWARDS", old) if old is not None
                        else os.environ.pop("INSIGHT_TELEGRAM_FORWARDS", None))
        self.assertEqual([p["metadata"] for p in synthesize_posts(msgs, "chan")], [{}, {}])     # off by default
        os.environ["INSIGHT_TELEGRAM_FORWARDS"] = "on"
        got = synthesize_posts(msgs, "chan")
        self.assertEqual(got[0]["metadata"], {"forwarded_from": {"channel_id": 42, "post": 7,
                                                                 "date": "2026-10-01T00:00:00+00:00"}})
        self.assertEqual(got[1]["metadata"], {})


# ---- the stats job's schedule (no database) -----------------------------------------------------------

class TheSchedule(unittest.TestCase):
    def test_due(self):
        night = datetime(2026, 11, 8, 3, tzinfo=timezone.utc)
        day = datetime(2026, 11, 8, 14, tzinfo=timezone.utc)
        last = {"last_at": (night - timedelta(hours=22)).isoformat()}
        self.assertEqual(S.due({}, {}, day), "never ran")
        self.assertEqual(S.due(last, {}, night), "nightly")
        self.assertIsNone(S.due(last, {}, day))                                  # not at night
        self.assertIsNone(S.due(last, {}, night, busy="Mark IX's story job is running"))
        regroup = {"full_at": (day - timedelta(hours=1)).isoformat()}
        self.assertEqual(S.due({"last_at": (day - timedelta(hours=3)).isoformat()}, regroup, day), "after a regroup")
        self.assertIsNone(S.due({"last_at": (day - timedelta(hours=3)).isoformat()}, dict(regroup, rebuild={"phase": "keys"}), day))
        self.assertEqual(S.due({"last_at": (day - timedelta(hours=37)).isoformat()}, {}, day), "overdue")


# ---- the signals on synthetic sources -----------------------------------------------------------------

class _World(_Api):
    def setUp(self):
        super().setUp()
        self.made = []
        self.addCleanup(self._drop)
        self.x = self.source_row("rss", "https://nitter.local/acmelabs/rss", "Acme Labs")
        self.site = self.source_row("rss", "https://wire.example-news.invalid/feed", "Example Wire")
        self.other = self.source_row("rss", "https://other.example-blog.invalid/rss", "Other Blog")
        self.thin = self.source_row("rss", "https://thin.example-thin.invalid/rss", "Thin Feed")

    def _drop(self):
        self.cur.execute("DELETE FROM news_posts WHERE post_id IN (SELECT id FROM posts WHERE source_id = ANY(%s::uuid[]))",
                         (self.made,))
        self.cur.execute("DELETE FROM story_posts WHERE post_id IN (SELECT id FROM posts WHERE source_id = ANY(%s::uuid[]))",
                         (self.made,))
        self.cur.execute("DELETE FROM source_stats WHERE subject_id = ANY(%s::uuid[])", (self.made,))
        self.cur.execute("DELETE FROM sources WHERE id = ANY(%s::uuid[])", (self.made,))

    def source_row(self, platform, handle, name, *, created=NOW - 100 * D):
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest, settings, created_at) "
                         "VALUES (%s, %s, false, false, %s::jsonb, %s) RETURNING id",
                         (platform, handle, json.dumps({"display_name": name}), created))
        sid = str(self.cur.fetchone()[0])
        self.made.append(sid)
        return sid

    def add(self, source, *, url, at=None, title="A post", text=None, author=None, reposted_by=None, links=()):
        text = text or f"Some words about a thing that happened, written once ({uuid.uuid4().hex[:8]})."
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at, author, reposted_by) "
                         "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                         (source, url, url, title, text, at or NOW - D, author, reposted_by))
        pid = str(self.cur.fetchone()[0])
        for n, target in enumerate(links):
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, boilerplate) "
                             "VALUES (%s, %s, 'example.invalid', %s, false)", (pid, target, n))
        return pid

    def story(self, *members):
        """A Mark IX story of (post, source, parent?) members."""
        sid = members[0][0]   # a story is named by its first post
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, %s)", (sid, NOW - 5 * D, len(members)))
        for i, (post, source) in enumerate(members):
            self.cur.execute("INSERT INTO story_posts (story_id, post_id, role, voice, parent_id, position) "
                             "VALUES (%s, %s, 'report', %s, %s, %s)",
                             (sid, post, f"source:{source}", None if i == 0 else members[0][0], i))
        self.addCleanup(self.cur.execute, "DELETE FROM stories WHERE id = %s", (sid,))
        return sid

    def stats(self):
        d = S.load(self.cur)
        rows = S.compute(d, only=self.made)
        S.write(self.cur, rows, d.now)
        return {(r.id, r.signal): r for r in rows}

    def world(self):
        x = [self.add(self.x, url=f"https://x.com/acmelabs/status/{i}", author="acmelabs", reposted_by=None,
                      at=NOW - (i + 1) * D) for i in range(8)]
        for i in range(4):
            self.add(self.x, url=f"https://x.com/someone/status/{100 + i}", title="RT by @acmelabs: hi", author="someone",
                     reposted_by=["acmelabs"], at=NOW - (i + 1) * D)
        site = [self.add(self.site, url=f"https://wire.example-news.invalid/{i}", at=NOW - (i + 2) * D) for i in range(15)]
        other = []
        for i in range(10):
            o = self.add(self.other, url=f"https://other.example-blog.invalid/{i}", at=NOW - (i + 2) * D + timedelta(hours=2),
                         links=[f"https://wire.example-news.invalid/{i}"] if i < 2 else (["https://x.com/acmelabs"] if i == 2 else []))
            other.append(o)
            self.story((site[i], self.site), (o, self.other))
        self.add(self.thin, url="https://thin.example-thin.invalid/1")
        news = site[0]   # a News row is named by its first post
        self.cur.execute("INSERT INTO news_stories (id, first_at, voices, reports, shares, mentions, score) VALUES (%s, %s, 2, 2, 0, 0, 1)", (news, NOW - 30 * D))
        self.addCleanup(self.cur.execute, "DELETE FROM news_stories WHERE id = %s", (news,))
        for i, p in enumerate(site[:3]):
            self.cur.execute("INSERT INTO news_posts (news_id, post_id, role, voice, name, position) VALUES (%s, %s, 'report', 'v', 'n', %s)",
                             (news, p, i))
        return x, site, other


class Signals(_World):
    def test_the_cards(self):
        x, site, other = self.world()
        got = self.stats()
        v = lambda s, sig: got[(s, sig)].value
        n = lambda s, sig: got[(s, sig)].n
        # rhythm: posts in 90 days over 90/7 weeks
        self.assertEqual((v(self.site, "per_week"), n(self.site, "per_week")), (round(15 / (90 / 7), 2), 15))
        # own share: 8 of 12 on X; the reposts are the evidence
        self.assertEqual((v(self.x, "own_share"), n(self.x, "own_share")), (round(8 / 12, 3), 12))
        self.assertEqual(got[(self.x, "own_share")].evidence["reposted"], [{"author": "someone", "posts": 4}])
        # first to report: the site was first in its 10 stories, the blog in none (2 hours later)
        self.assertEqual((v(self.site, "first_to_report"), n(self.site, "first_to_report")), (1.0, 10))
        self.assertEqual((v(self.other, "first_to_report"), n(self.other, "first_to_report")), (0.0, 10))
        late = got[(self.other, "first_to_report")].evidence["stories"][0]
        self.assertEqual((late["first"], late["first_voice"], late["hours"]), (False, "Example Wire", 2.0))
        # covered by others: 5 of the site's 15 posts are in no story of 2+ voices
        self.assertEqual(v(self.site, "solo_share"), round(5 / 15, 3))
        # News yield: 3 of its 15 posts in the News window
        self.assertEqual((v(self.site, "news_yield"), n(self.site, "news_yield")), (0.2, 15))
        self.assertEqual(got[(self.site, "news_yield")].evidence["news"], "markix")
        # cited by: the blog links two of the site's posts, and the X profile once; with the bias note
        self.assertEqual((v(self.site, "cited_by"), n(self.site, "cited_by")), (1, 2))
        self.assertEqual((v(self.x, "cited_by"), n(self.x, "cited_by")), (1, 1))
        self.assertEqual(got[(self.site, "cited_by")].evidence["voices"][0]["voice"], "Other Blog")
        self.assertIn("Telegram", got[(self.site, "cited_by")].evidence["bias"])
        self.assertEqual(v(self.other, "cited_by"), 0)
        # root share: every site post leads its story
        self.assertEqual((v(self.site, "root_share"), v(self.other, "root_share")), (1.0, 0.0))
        # who it is: nothing read yet
        self.assertEqual(v(self.site, "role"), "too_few")
        # rows: one per signal and subject, every signal
        self.assertEqual({sig for (s, sig) in got if s == self.site}, set(S.SIGNALS))

    def test_the_page(self):
        self.world()
        self.stats()
        status, page = call("GET", "/api/markx/sources")
        self.assertEqual(status, 200)
        rows = {r["id"]: r for r in page["rows"] if r["id"] in self.made}
        self.assertEqual(set(rows), set(self.made))
        self.assertEqual(page["columns"], list(S.LIST_COLUMNS))
        self.assertNotIn("score", json.dumps(page))                       # no overall score
        self.assertEqual(rows[self.site]["stats"]["first_to_report"], {"value": 1.0, "n": 10, "too_few": False})
        self.assertTrue(rows[self.thin]["stats"]["solo_share"]["too_few"])     # 1 post: too few to tell
        status, one = call("GET", f"/api/markx/sources/{self.site}")
        self.assertEqual(status, 200)
        self.assertEqual(one["subject"]["name"], "Example Wire")
        cards = one["tabs"][0]["cards"]
        self.assertEqual([c["card"] for c in cards], [c for c, _ in S.CARDS])
        sig = {s["signal"]: s for c in cards for s in c["signals"]}
        self.assertEqual(sig["first_to_report"]["min"], 10)
        self.assertTrue(sig["first_to_report"]["formula"])
        self.assertTrue(sig["role"]["too_few"])
        self.assertTrue(sig["stance"]["too_few"])
        self.assertTrue([c for c in cards if c["card"] == "stance"][0]["experimental"])
        self.assertEqual(call("GET", f"/api/markx/sources/{uuid.uuid4()}")[0], 404)
        self.assertEqual(call("GET", "/api/markx/sources/not-an-id")[0], 404)
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertEqual(call("GET", "/api/markx/sources")[0], 404)

    def test_the_same_channel_twice_and_telegram_forwards(self):
        twice = self.source_row("rss", "https://telegram.local/rss/examplechan?limit=50", "Example Chan (bridge)")
        native = self.source_row("telegram", "examplechan", "Example Chan")
        for i in range(10):
            self.add(native, url=f"https://t.me/examplechan/{i}")
        self.cur.execute("UPDATE posts SET metadata = jsonb_build_object('forwarded_from', jsonb_build_object('channel_id', 7)) "
                         "WHERE id IN (SELECT id FROM posts WHERE source_id = %s LIMIT 3)", (native,))
        got = self.stats()
        flagged = got[(twice, "channels")].evidence["same_channel_twice"]
        self.assertEqual([(f["other"], f["address"]) for f in flagged], [(native, "t.me/examplechan")])
        self.assertEqual(got[(self.site, "channels")].evidence["same_channel_twice"], [])
        self.assertEqual(got[(native, "own_share")].value, 0.7)            # C3: a kept forward is a repost

    def test_a_source_never_computed_shows_too_few_everywhere(self):
        status, one = call("GET", f"/api/markx/sources/{self.thin}")
        self.assertEqual(status, 200)
        self.assertFalse(one["tabs"][0]["computed"])
        for c in one["tabs"][0]["cards"]:
            for s in c["signals"]:
                self.assertEqual(s["too_few"], s["min"] > 0, s["signal"])

    def test_official_end_to_end(self):
        posts = [self.add(self.x, url=f"https://x.com/acmelabs/status/{i}", author="acmelabs",
                          text=f"Acme Labs released Widget {i}.1 today for everyone, with a long note number {i}.")
                 for i in range(6)]
        for p in posts:
            with self.conn.transaction():
                rt, _ = tasks.read_task(self.cur, p)
                et, _ = tasks.entities_task(self.cur, p)
            ok = self.answer((rt, reading()), (et, {"entities": [
                {"span": "Acme Labs", "name": "Acme Labs", "type": "org", "role": "actor"}]}))[1]
            self.assertEqual(ok["valid"], 2, ok)
        got = self.stats()
        role = got[(self.x, "role")]
        self.assertEqual((role.value, role.n), ("official", 6))
        self.assertIn("subject, actor or venue", role.evidence["line"])
        self.assertEqual(len(role.evidence["posts"]), 3)
        self.assertEqual(got[(self.x, "kinds")].value, {"report": 1.0})

    def test_voices_when_the_table_exists(self):
        a = self.source_row("rss", "https://nitter.local/acmelabs2/rss", "Acme Labs (2)")
        for i in range(3):
            self.add(a, url=f"https://x.com/acmelabs2/status/{i}", author="acmelabs2")
            self.add(self.x, url=f"https://x.com/acmelabs/status/{i}", author="acmelabs")
        existed = S.voices_exist(self.cur)
        # 0132 A's tables, in a transaction rolled back (another slice's migration 0080 makes them)
        with self.conn.transaction():
            self.cur.execute("CREATE TABLE IF NOT EXISTS voices (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
                             "name text, kind text)")
            self.cur.execute("ALTER TABLE sources ADD COLUMN IF NOT EXISTS voice_id uuid")
            self.cur.execute("INSERT INTO voices (name, kind) VALUES ('Acme', 'company') RETURNING id")
            voice = str(self.cur.fetchone()[0])
            self.cur.execute("UPDATE sources SET voice_id = %s WHERE id = ANY(%s::uuid[])", (voice, [a, self.x]))
            got = self.stats()
            self.assertEqual(got[(voice, "per_week")].n, 6)
            self.assertEqual(got[(voice, "channels")].value, 2)
            self.assertEqual(got[(a, "per_week")].n, 3)                                         # each channel too
            rows = S.list_view(self.cur)["rows"]
            mine = [r for r in rows if r["id"] in (voice, a, self.x)]
            self.assertEqual([(r["kind"], r["channels"]) for r in mine], [("voice", 2)])   # one row per voice
            page = S.subject_view(self.cur, voice)
            self.assertEqual([t["kind"] for t in page["tabs"]], ["voice", "source", "source"])   # a tab per channel
            self.assertEqual(S.subject_view(self.cur, a)["subject"]["voice"], {"id": voice, "name": "Acme"})
            raise psycopg.Rollback()
        self.assertEqual(S.voices_exist(self.cur), existed)


# ---- the stance planner, its answer on the card, the labels; Part C1 -----------------------------------

class Stance(_World):
    def long(self, i):
        return (f"Post number {i}. We simply cannot trust the vendor, says the writer, and here is why at length: "
                + "the reasons pile up one after another and each is worth reading slowly. " * 3 + f"(end {i})")

    def test_plan_answer_card_and_labels(self):
        for i in range(15):
            self.add(self.site, url=f"https://wire.example-news.invalid/s{i}", text=self.long(i), title="")
        for i in range(14):
            self.add(self.other, url=f"https://other.example-blog.invalid/s{i}", text=self.long(i), title="")
        with self.conn.transaction():
            self.assertEqual(tasks.plan_stance(self.cur), 1)          # the blog has 14: not asked
            self.assertEqual(tasks.plan_stance(self.cur), 0)          # once a month
        self.cur.execute("SELECT id, a::text, input, subject_kind FROM mx_tasks WHERE kind = 'stance'")
        task, a, text, subject = self.cur.fetchone()
        self.assertEqual((a, subject), (self.site, "source"))
        self.assertEqual(len(validate.stance_posts(text)), 15)
        posts = validate.stance_posts(text)
        q1 = posts[1].strip()[:30]
        q2 = posts[2].strip()[:30]
        answer = {"patterns": [{"pattern": "distrusts the vendor", "kind": "stance", "strength": "clear",
                                "evidence": [{"post": 1, "quote": q1}, {"post": 2, "quote": q2}]},
                               {"pattern": "made up", "kind": "tone",
                                "evidence": [{"post": 1, "quote": q1}, {"post": 3, "quote": "words it never wrote"}]}],
                   "voice": "commentator", "interest": None, "too_few": False}
        self.assertEqual(self.answer((task, answer))[1]["valid"], 1)
        got = self.stats()
        st = got[(self.site, "stance")]
        self.assertEqual((st.value, st.n), (1, 15))
        quotes = st.evidence["patterns"][0]["quotes"]
        self.assertTrue(all(q["post_id"] for q in quotes), quotes)    # each quote opens its post
        status, out = call("POST", "/api/markx/sources/stance/label", body={"task": str(task), "pattern": 0, "answer": "right"})
        self.assertEqual((status, out["labels"]), (200, {"0": "right"}))
        page = call("GET", f"/api/markx/sources/{self.site}")[1]
        stance = [s for c in page["tabs"][0]["cards"] for s in c["signals"] if s["signal"] == "stance"][0]
        self.assertEqual(stance["evidence"]["labels"], {"0": "right"})
        self.assertFalse(stance["too_few"])
        out = call("POST", "/api/markx/sources/stance/label", body={"task": str(task), "pattern": 0, "answer": "undo"})[1]
        self.assertEqual(out["labels"], {})
        self.assertEqual(call("POST", "/api/markx/sources/stance/label",
                              body={"task": str(task), "pattern": 0, "answer": "maybe"})[0], 400)
        self.assertEqual(call("POST", "/api/markx/sources/stance/label",
                              body={"task": str(uuid.uuid4()), "pattern": 0, "answer": "right"})[0], 404)

    def test_reposts_are_never_sampled(self):
        for i in range(15):
            self.add(self.x, url=f"https://x.com/someone/status/{i}", title="RT by @acmelabs: hi", text=self.long(i),
                     author="someone", reposted_by=["acmelabs"])
        with self.conn.transaction():
            self.assertEqual(tasks.plan_stance(self.cur), 0)

    def test_last_posts_off_by_default_then_twenty_a_source(self):
        for i in range(25):
            self.add(self.thin, url=f"https://thin.example-thin.invalid/l{i}", at=NOW - (400 + i) * D)
        old = os.environ.pop(tasks.LAST_POSTS_SWITCH, None)
        self.addCleanup(lambda: os.environ.__setitem__(tasks.LAST_POSTS_SWITCH, old) if old is not None
                        else os.environ.pop(tasks.LAST_POSTS_SWITCH, None))
        with self.conn.transaction():
            self.assertEqual(tasks.plan_last_posts(self.cur, "read"), 0)
        os.environ[tasks.LAST_POSTS_SWITCH] = "on"
        with self.conn.transaction():
            tasks.plan_last_posts(self.cur, "read")
        self.cur.execute("SELECT count(*) FROM mx_tasks t JOIN posts p ON p.id = t.a WHERE t.kind = 'read' AND p.source_id = %s",
                         (self.thin,))
        self.assertEqual(self.cur.fetchone()[0], 20)      # its last 20, though they are over a year old
        with self.conn.transaction():
            tasks.plan_last_posts(self.cur, "read")
        self.cur.execute("SELECT count(*) FROM mx_tasks t JOIN posts p ON p.id = t.a WHERE t.kind = 'read' AND p.source_id = %s",
                         (self.thin,))
        self.assertEqual(self.cur.fetchone()[0], 20)      # never more


if __name__ == "__main__":
    unittest.main()
