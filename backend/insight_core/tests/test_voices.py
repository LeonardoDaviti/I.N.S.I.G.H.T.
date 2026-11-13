"""Voices (issue 0132 A): the suggestion rules, the role rule's "official", the owner's decisions, stories counting a
confirmed voice once (and nothing regrouping until one is confirmed), "Also on <channel>", the voice page's scope.

Every name, address and post here is invented."""
from __future__ import annotations

import contextlib
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._stories import insert_post, insert_source, story_post
from insight_core.utils import source_roles as roles
from insight_core.utils.source_roles import Focus, Mention, Official
from insight_core.utils import voice
from insight_core.utils.story_rules import group
from insight_core.utils.voice_rules import (Channel, PairCounts, address_key, groups, judge, platform_of, shingles,
                                            site_label)

DAY = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
post = partial(story_post, at=DAY)


def channel(i, kind="site", name=None, handle=None, keys=(), posts=20, own=None, **kw):
    return Channel(id=i, kind=kind, name=name or i, handle=handle or f"{i}.example", keys=set(keys), posts=posts,
                   own=posts if own is None else own, **kw)


def counts(**kw):
    e = PairCounts()
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def verdict(found, a, b):
    return next((v for v in found if {v.a, v.b} == {a, b}), None)


class AddressTests(unittest.TestCase):
    def test_platform_shapes_and_sites(self):
        self.assertEqual(address_key("https://x.com/somewriter"), ("x:somewriter", True))
        self.assertEqual(address_key("https://twitter.com/SomeWriter/status/1900000000000000001"), ("x:somewriter", False))
        self.assertEqual(address_key("https://t.me/s/somechannel"), ("tg:somechannel", True))
        self.assertEqual(address_key("https://www.youtube.com/@SomeTalks/videos"), ("yt:sometalks", True))
        self.assertEqual(address_key("https://youtube.com/channel/UCabcDEF"), ("ytc:ucabcdef", True))
        self.assertEqual(address_key("https://www.reddit.com/r/somesub/"), ("r:somesub", True))
        self.assertEqual(address_key("https://gist.github.com/somewriter.atom"), ("github.com/somewriter", True))
        self.assertEqual(address_key("https://blog.example.org/2026/a-post"), ("site:blog.example.org", False))
        self.assertEqual(address_key("https://x.com/search?q=a"), (None, False))

    def test_site_label(self):
        self.assertEqual(site_label("writer.github.io"), "writer")
        self.assertEqual(site_label("www.institute.gov.uk"), "institute")
        self.assertEqual(site_label("blog.alpha.example"), "alpha")

    def test_shingles_need_words_and_drop_addresses(self):
        self.assertIsNone(shingles("short", "a few words only"))
        text = " ".join(f"word{i}" for i in range(20))
        self.assertEqual(shingles(None, text), shingles("RT by @someone:", text + " https://a.example/x"))


class RoleTests(unittest.TestCase):
    """The role rule's step 3 (official) and 4 (focused), shared with the source analysis page (0132 B)."""

    def reads(self, n, hits, name="Orbit Labs", maker=None, role="subject"):
        out = {f"p{i}": [Mention(name=name, role=role, maker=maker, type="org")] for i in range(hits)}
        out.update({f"q{i}": [Mention(name="Someone Else", role="subject", type="org")] for i in range(n - hits)})
        return out

    def test_official_at_30_percent_of_5_read_posts(self):
        tokens, squashed = roles.self_names(["Orbit Labs News"], ["orbitlabs"])
        self.assertIsNotNone(roles.official(self.reads(10, 3), tokens, squashed), "3 of 10: in at the value")
        self.assertIsNone(roles.official(self.reads(10, 2), tokens, squashed), "2 of 10: out")
        self.assertIsNone(roles.official(self.reads(4, 4), tokens, squashed), "4 read posts: too few to tell")
        found = roles.official(self.reads(5, 5), tokens, squashed)
        self.assertEqual((found.maker, found.n, found.hits), ("orbit", 5, 5))

    def test_a_mention_as_a_mere_mention_is_not_self(self):
        tokens, squashed = roles.self_names(["Orbit Labs News"], ["orbitlabs"])
        self.assertIsNone(roles.official(self.reads(5, 5, role="mentioned"), tokens, squashed))

    def test_matched_by_acronym_and_by_handle(self):
        tokens, squashed = roles.self_names(["The Model Safety Desk"], ["msd"])
        self.assertIsNotNone(roles.official(self.reads(5, 2, name="Model Safety Desk"), tokens, squashed), "by name")
        tokens, squashed = roles.self_names(["Desk"], ["msd"])
        self.assertIsNotNone(roles.official(self.reads(5, 2, name="Model Safety Desk"), tokens, squashed), "by acronym")

    def test_focus_is_the_maker_most_posts_are_about(self):
        reads = self.reads(10, 6, name="Orbit Model 3", maker="Orbit Labs Inc.")
        self.assertEqual(roles.focus(reads), Focus("orbit", 0.6, 10))
        self.assertIsNone(roles.focus({}))


class SuggestionTests(unittest.TestCase):
    """Each rule on fixed sources; platforms never joined; a name alone never suggested."""

    def test_the_same_address_is_the_same_channel_twice(self):
        chans = {"a": channel("a", "telegram", "Quiet Channel", "quietchan", {"tg:quietchan"}),
                 "b": channel("b", "telegram", "Quiet Channel", "quietchan", {"tg:quietchan"}, posts=0)}
        [v] = judge(chans, {}, {}, {})
        self.assertEqual(v.verdict, "same_channel")
        self.assertIn("disable one?", v.evidence[0]["line"])
        self.assertEqual(groups([v]), [["a", "b"]])

    def test_a_links_section_linking_the_profile_joins(self):
        chans = {"yt": channel("yt", "youtube", "@talkshow", "talkshow", {"yt:talkshow"}, posts=10),
                 "x": channel("x", "x", "zed_q", "zed_q", {"x:zed_q"})}
        found = judge(chans, {("yt", "x"): counts(link_posts=9, link_posts_own=9, profile_posts=9)}, {}, {})
        self.assertEqual(verdict(found, "yt", "x").verdict, "join", "a bare profile link in 9/10: standing")
        self.assertEqual(verdict(found, "yt", "x").evidence[0]["rule"], "standing_link")
        found = judge(chans, {("yt", "x"): counts(link_posts=2, link_posts_own=2, profile_posts=2)}, {}, {})
        self.assertIsNone(verdict(found, "yt", "x"), "2/10 profile links, no name: nothing")

    def test_a_few_citations_of_a_profile_are_no_links_section(self):
        # v10.6.1 (the owner, 2026-11-08): a small blog linking an organisation's site in 2 of its 6 posts cites it;
        # it is not that organisation's channel. Alone, a profile link joins only as a links section would: in most
        # posts, of enough posts. With a link back or a shared name, the 30% standing link still joins.
        chans = {"blog": channel("blog", name="Ann Lee", posts=6), "org": channel("org", name="Gauge Lab", posts=140)}
        cites = {("blog", "org"): counts(link_posts=2, link_posts_own=2, profile_posts=2)}
        self.assertIsNone(verdict(judge(chans, cites, {}, {}), "blog", "org"), "2/6 profile links, nothing back")
        back = {**cites, ("org", "blog"): counts(link_posts=10, link_posts_own=10)}
        self.assertEqual(verdict(judge(chans, back, {}, {}), "blog", "org").verdict, "join", "with a link back")
        chans["blog"] = channel("blog", name="Ann Lee", posts=12)
        section = {("blog", "org"): counts(link_posts=8, link_posts_own=8, profile_posts=8)}
        self.assertEqual(verdict(judge(chans, section, {}, {}), "blog", "org").verdict, "join", "8/12: a links section")

    def test_a_standing_link_needs_some_link_back_unless_a_section(self):
        chans = {"a": channel("a", posts=10), "b": channel("b", posts=40)}
        one_way = {("a", "b"): counts(link_posts=5, link_posts_own=5)}
        self.assertIsNone(verdict(judge(chans, one_way, {}, {}), "a", "b"), "5/10 own posts link it, no link back")
        both = {**one_way, ("b", "a"): counts(link_posts=3, link_posts_own=3)}
        self.assertEqual(verdict(judge(chans, both, {}, {}), "a", "b").verdict, "join")

    def test_a_hub_is_no_standing_link(self):
        chans = {i: channel(i) for i in ("a", "hub", *(f"s{k}" for k in range(8)))}
        linked = {(i, "hub"): counts(link_posts=12, link_posts_own=12) for i in chans if i != "hub"}
        linked[("hub", "a")] = counts(link_posts=2, link_posts_own=2)
        self.assertIsNone(verdict(judge(chans, linked, {}, {}), "a", "hub"),
                          "9 of 10 sources link it: a hub; linking it says nothing of who you are")

    def test_some_link_with_a_shared_name_joins_and_alone_does_not(self):
        named = {"a": channel("a", "site", "Quillon Notes", "quillon.example"),
                 "b": channel("b", "x", "quillon", "quillon", {"x:quillon"})}
        some = {("b", "a"): counts(link_posts=2, link_posts_own=2)}
        self.assertEqual(verdict(judge(named, some, {}, {}), "a", "b").verdict, "join")
        unnamed = {"a": channel("a", "site", "Desk Notes"), "b": channel("b", "x", "zed_q", "zed_q", {"x:zed_q"})}
        self.assertIsNone(verdict(judge(unnamed, some, {}, {}), "a", "b"))

    def test_near_identical_own_posts_join_only_with_a_shared_name(self):
        named = {"a": channel("a", "site", "Quillon Notes", "quillon.example"),
                 "b": channel("b", "x", "quillon", "quillon", {"x:quillon"})}
        copies = {("a", "b"): counts(copies_own=3), ("b", "a"): counts(copies_own=3)}
        v = verdict(judge(named, copies, {}, {}), "a", "b")
        self.assertEqual(v.verdict, "join")
        self.assertIn("copies", [e["rule"] for e in v.evidence])
        unnamed = {"a": channel("a", "site", "Desk Notes"), "b": channel("b", "x", "zed_q", "zed_q", {"x:zed_q"})}
        self.assertIsNone(verdict(judge(unnamed, copies, {}, {}), "a", "b"), "copies alone: a forward, not one voice")

    def test_both_official_for_the_same_maker_join(self):
        chans = {"a": channel("a", "site", "Orbit Newsroom"), "b": channel("b", "site", "Zenith Papers")}
        official = {s: Official("orbit", 0.8, 10, 8, "80% of 10") for s in chans}
        self.assertEqual(verdict(judge(chans, {}, official, {}), "a", "b").verdict, "join")
        official["b"] = Official("other", 0.8, 10, 8, "80% of 10")
        self.assertIsNone(verdict(judge(chans, {}, official, {}), "a", "b"), "two makers' officials: two voices")

    def test_a_name_alone_is_possible_never_suggested(self):
        chans = {"a": channel("a", "site", "Quillon Notes", "quillon.example"),
                 "b": channel("b", "x", "quillon", "quillon", {"x:quillon"})}
        found = judge(chans, {}, {}, {})
        self.assertEqual(verdict(found, "a", "b").verdict, "possible")
        self.assertEqual(groups(found), [], "a possible pair is never a suggested voice")

    def test_platforms_are_never_joined(self):
        named = dict(name="Quillon Board", handle="quillon")
        for platform in (channel("p", "reddit", keys={"r:quillon"}, **named),
                         channel("p", "site", authors=12, **named),
                         channel("p", "site", posts=30, own_key_share=0.1, other_keys=25, **named)):
            self.assertTrue(platform_of(platform))
            chans = {"p": platform, "b": channel("b", "x", "quillon", "quillon", {"x:quillon"})}
            evidence = {("p", "b"): counts(link_posts=20, link_posts_own=20, profile_posts=20),
                        ("b", "p"): counts(link_posts=20, link_posts_own=20, copies_own=4), ("p", "b2"): counts()}
            self.assertIsNone(verdict(judge(chans, evidence, {}, {}), "p", "b"), platform_of(platform))

    def test_related_voices_from_staff_and_reposts(self):
        chans = {"co": channel("co", "site", "Orbit Newsroom"), "staff": channel("staff", "x", "zed_q", "zed_q", {"x:zed_q"}),
                 "fan": channel("fan", "x", "fan_k", "fan_k", {"x:fan_k"})}
        official = {"co": Official("orbit", 0.8, 10, 8, "80% of 10")}
        focus = {"staff": Focus("orbit", 0.55, 20), "co": Focus("orbit", 0.8, 10)}
        reposts = {("fan", "staff"): counts(reposts=10)}
        found = judge(chans, reposts, official, focus)
        staff = verdict(found, "co", "staff")
        self.assertEqual(staff.verdict, "related")
        self.assertIn("needs a bio", staff.evidence[-1]["line"])
        self.assertEqual(verdict(found, "fan", "staff").verdict, "related", "10 reposts of one handle")
        self.assertIsNone(verdict(judge(chans, {("fan", "staff"): counts(reposts=9)}, {}, {}), "fan", "staff"))
        self.assertEqual(groups(found), [], "related is never one voice")

    def test_groups_keep_what_the_owner_said(self):
        chans = {i: channel(i, "telegram", "Same", "same", {"tg:same"}) for i in ("a", "b", "c")}
        found = judge(chans, {}, {}, {})
        self.assertEqual(groups(found), [["a", "b", "c"]])
        self.assertEqual(groups(found, rejected=[("a", "b"), ("a", "c")]), [["b", "c"]], "a pair not the same never joins")
        self.assertEqual(groups(found, joined={"a": "v", "b": "v", "c": "v"}), [], "already one voice")
        self.assertEqual(groups(found, joined={"a": "v", "b": "v"}), [["a", "b", "c"]], "c is not in it yet")


class PossibleShapeTests(unittest.TestCase):
    def test_a_channel_possible_with_a_confirmed_voice_shows_once(self):
        # v10.6.1 (the owner, 2026-11-08): after a voice is confirmed, a channel sharing its name was listed once per
        # channel of the voice; it is one question, "this channel and that voice", asked once.
        from insight_core.services.voices_service import one_question_per_voice
        src = lambda i, v=None: {"id": i, "name": i, "voice_id": v}   # noqa: E731
        pairs = [{"a": src("gh", "V"), "b": src("medium")}, {"a": src("x", "V"), "b": src("medium")},
                 {"a": src("medium"), "b": src("blog", "V")}, {"a": src("x", "V"), "b": src("gh", "V")},
                 {"a": src("ncase1"), "b": src("ncase2")}]
        got = one_question_per_voice(pairs)
        self.assertEqual([(p["a"]["id"], p["b"]["id"]) for p in got], [("gh", "medium"), ("ncase1", "ncase2")])


class CountingTests(unittest.TestCase):
    """Stories count a confirmed voice once (story_rules); nothing else changes."""

    def test_a_confirmed_voice_is_one_voice_in_a_story_and_in_news(self):
        page = [("https://outside.example/2026/10/a-model-ships-today", None)]
        blog = post("blog", "s-blog", links=page)
        tweet = post("tweet", "s-x", kind="x", site="x.com", hours=1, links=page)
        [story] = group([blog, tweet])
        self.assertEqual(story.voices, 2)
        joined = [post("blog", "s-blog", links=page, owner="voice:v1"),
                  post("tweet", "s-x", kind="x", site="x.com", hours=1, links=page, owner="voice:v1")]
        [story] = group(joined)
        self.assertEqual(story.voices, 1, "one confirmed voice")
        self.assertEqual(voice.count(joined, voice.Policy.NEWS_IX), 1, "News too")

    def test_an_owner_told_by_the_data_still_counts_only_in_news(self):
        page = [("https://outside.example/2026/10/a-model-ships-today", None)]
        owned = [post("blog", "s-blog", links=page, owner="source:s-x"),
                 post("tweet", "s-x", kind="x", site="x.com", hours=1, links=page)]
        self.assertEqual(voice.count(owned, voice.Policy.STORIES_IX), 2, "issue 0111's owners are News's only")
        self.assertEqual(voice.count(owned, voice.Policy.NEWS_IX), 1)

    def test_a_reddit_poster_stays_its_own_voice_in_a_story(self):
        page = [("https://outside.example/2026/10/a-model-ships-today", None)]
        posts = [post("x1", "s-x", kind="x", site="x.com", links=page, owner="voice:v1"),
                 post("r1", "s-red", kind="reddit", site="reddit.com", author="zed_q", links=page, owner="voice:v1")]
        self.assertEqual(voice.count(posts, voice.Policy.STORIES_IX), 2)

    def test_the_rules_stamp_reads_no_voice(self):
        """The deploy regroups nothing: the sample has no confirmed voice, so its owners, prints and stamp are the
        ones before voices (a source with no voice keeps its facts' print)."""
        from insight_core.db.repo_stories import SourceFacts
        from insight_core.services.stories_service import StoriesService
        from insight_core.utils import stamps
        plain = SourceFacts.of((s[:4] for s in stamps.SOURCES), stamps.HOSTS, stamps.LINKED)
        joined = SourceFacts.of((s[:4] for s in stamps.SOURCES), stamps.HOSTS, stamps.LINKED,
                                voices={"s-alpha": "v1", "s-x1": "v1"})
        self.assertEqual(plain.voice_of, {})
        before, after = StoriesService._facts(plain)["sources"], StoriesService._facts(joined)["sources"]
        self.assertEqual({s for s in before if before[s] != after[s]}, {"s-alpha", "s-x1"}, "only the joined sources")
        del plain.voice_of
        self.assertEqual(StoriesService._facts(plain)["sources"], before, "no voice: the print before voices")
        self.assertEqual(joined.owners["site:blog.alpha.example"], "voice:v1")
        self.assertEqual(joined.owners["source:s-x1"], "voice:v1")


@requires_test_db
class VoicesJobTests(unittest.TestCase):
    """The owner's decisions on the database, one transaction rolled back, and the story job after them."""

    def setUp(self):
        from insight_core.services.news_service import NewsService
        from insight_core.services.stories_service import StoriesService
        from insight_core.services.voices_service import VoicesService
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mark = uuid.uuid4().hex[:8]
        self.news = NewsService(db_url(), clock=lambda: self.now)
        self.stories = StoriesService(db_url(), clock=lambda: self.now, news=self.news)
        self.asked = []

        @contextlib.contextmanager
        def mine():
            yield self.cur
        self.voices = VoicesService(db_url(), after_change=self.asked.append, clock=lambda: self.now,
                                    background=False, cursor=mine)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _source(self, name, **kw):
        return insert_source(self.cur, f"{name} {self.mark}", in_main_digest=True, followed_days=60, **kw)

    def _post(self, source, site, *, hours_ago=1.0, title="A post", html=None, url=None, content="Body"):
        url = url or f"https://{site}-{self.mark}.test/2026/{uuid.uuid4().hex}"
        return str(insert_post(self.cur, source, url, at=self.now - timedelta(hours=hours_ago), title=title,
                               content=content, html=html, content_hash=uuid.uuid4().hex, host=f"{site}-{self.mark}.test"))

    def _fill(self):
        from insight_core.db.repo_stories import StoriesRepository
        while StoriesRepository().fill_missing_links(self.cur):
            pass

    def _story_of(self, pid):
        self.cur.execute("SELECT s.id::text, s.voices FROM story_posts sp JOIN stories s ON s.id = sp.story_id "
                         "WHERE sp.post_id = %s", (pid,))
        return self.cur.fetchone()

    def _in_news(self, pid):
        self.cur.execute("SELECT 1 FROM news_posts WHERE post_id = %s", (pid,))
        return self.cur.fetchone() is not None

    def _two_channels(self):
        """Two channels of one person, named apart (no owner told by the data), covering one outside page."""
        page = f"https://outside-{self.mark}.test/2026/10/a-model-ships-today"
        self.blog = self._source("Quillon Desk")
        self.video = self._source("Brightwater Talks")
        link = f'<p><a href="{page}">read</a></p>'
        self.p1 = self._post(self.blog, "quillon", hours_ago=5, title="On the model", html=link)
        self.p2 = self._post(self.video, "brightwater", hours_ago=4, title="A talk on the model", html=link)
        self.p3 = self._post(self.blog, "quillon", hours_ago=300, title="Earlier notes")   # the blog: its main channel
        self._fill()
        self.stories.full_on(self.cur)

    def test_confirming_counts_one_voice_queues_only_its_posts_and_undo_restores(self):
        self._two_channels()
        self.assertEqual(self._story_of(self.p1)[1], 2)
        self.assertTrue(self._in_news(self.p1), "two voices: News")
        other = self._source("Elsewhere")
        stranger = self._post(other, "elsewhere", title="Unrelated")
        self._fill()
        self.stories.update(self.cur)
        self.cur.execute("DELETE FROM story_queue")
        answer = self.voices.join([self.blog, self.video])
        self.assertEqual(answer["voice"]["name"], f"Quillon Desk {self.mark}", "named by its main channel")
        self.assertEqual(sorted(answer["queued_sources"]), sorted([self.blog, self.video]))
        self.assertEqual(len(self.asked), 1, "the story job is asked for")
        self.cur.execute("SELECT key FROM story_queue")
        queued = {k for (k,) in self.cur.fetchall()}
        self.assertEqual(queued, {"post:" + p for p in (self.p1, self.p2, self.p3)},
                         "only the voice's channels' posts: no regroup of the rest")
        self.assertNotIn("post:" + stranger, queued)
        self.stories.update(self.cur)
        self.cur.execute("SELECT value FROM system_settings WHERE key = 'stories'")
        state = self.cur.fetchone()[0]
        self.assertNotIn("rebuild", state, "no rule change: no full regroup")
        self.assertEqual(self._story_of(self.p1)[1], 1, "one confirmed voice")
        self.assertFalse(self._in_news(self.p1), "one voice is no News")
        before = dict(self.stories.full_on(self.cur))
        self.assertEqual(before["changed"], 0, "the incremental job's rows are the full regroup's")
        self.voices.remove(answer["voice"]["id"])
        self.stories.update(self.cur)
        self.assertEqual(self._story_of(self.p1)[1], 2, "undone: two voices again")
        self.assertTrue(self._in_news(self.p1))
        self.cur.execute("SELECT voice_id FROM sources WHERE id = ANY(%s::uuid[])", ([self.blog, self.video],))
        self.assertEqual({r[0] for r in self.cur.fetchall()}, {None}, "removing a voice keeps its channels")
        self.cur.execute("SELECT removed_at IS NOT NULL FROM voices WHERE id = %s", (answer["voice"]["id"],))
        self.assertEqual(self.cur.fetchone(), (True,), "the voice's row is kept")

    def test_a_story_names_one_confirmed_voice_once(self):
        self._two_channels()
        self.voices.join([self.blog, self.video])
        self.stories.update(self.cur)
        from insight_core.db.repo_reader import ReaderRepository
        items = [{"id": self.p1}]
        ReaderRepository.attach_stories(self.cur, items)
        story = items[0].get("story")
        self.assertIsNotNone(story)
        self.assertEqual(story["voices"], 1)
        self.assertEqual(sorted(s["id"] for s in story["sources"]), sorted([self.blog, self.video]),
                         "one voice: its channels as who said it")

    def test_one_voice_per_source_moves_a_channel_and_removes_an_empty_voice(self):
        a, b, c = (self._source(n) for n in ("Alder", "Birch", "Cedar"))
        first = self.voices.join([a, b])["voice"]["id"]
        second = self.voices.join([b, c], by_hand=True)["voice"]
        self.assertEqual(second["id"], first, "b's voice takes c")
        self.assertEqual(sorted(ch["id"] for ch in second["channels"]), sorted([a, b, c]))
        lone = self.voices.join([self._source("Dogwood"), self._source("Elm")])["voice"]["id"]
        moved = self.voices.join([a], voice_id=lone)["voice"]
        self.assertIn(a, [ch["id"] for ch in moved["channels"]])
        self.cur.execute("SELECT count(*) FROM sources WHERE id = %s AND voice_id = %s", (a, lone))
        self.assertEqual(self.cur.fetchone()[0], 1, "a source is in one voice")
        from insight_core.checks.invariants import _voice_one_per_source

        class R:
            cur = self.cur
        self.assertEqual(_voice_one_per_source(R)[0], [])
        self.cur.execute("UPDATE voices SET removed_at = now() WHERE id = %s", (lone,))
        self.assertIn(a, _voice_one_per_source(R)[0], "a source in a voice not kept")

    def test_not_same_related_leave_and_rename(self):
        a, b = self._source("Alder"), self._source("Birch")
        self.voices.not_same(a, b, [{"rule": "shared_name", "line": "shared name"}])
        from insight_core.db.repo_voices import VoicesRepository
        self.assertEqual(VoicesRepository.decided_pairs(self.cur)[tuple(sorted((a, b)))], "not_same")
        related = self.voices.related(a, b, [{"rule": "reposts", "line": "12 reposts"}])["voices"]
        self.assertEqual(len(related), 2, "each its own voice")
        self.assertEqual([r["id"] for r in related[0]["related"]], [related[1]["id"]])
        self.assertEqual(self.asked, [], "one-channel voices count nothing new: no story run")
        joined = self.voices.join([a, self._source("Cedar")])["voice"]
        renamed = self.voices.rename(joined["id"], "Alder and friends", "person", set_kind=True)["voice"]
        self.assertEqual((renamed["name"], renamed["kind"]), ("Alder and friends", "person"))
        with self.assertRaises(ValueError):
            self.voices.rename(joined["id"], "  ")
        left = self.voices.leave(a)
        self.assertEqual(sorted(left["queued_sources"]), sorted(ch["id"] for ch in joined["channels"]),
                         "a voice left with one channel counts as none: both requeued")
        with self.assertRaises(ValueError):
            self.voices.join([a])
        with self.assertRaises(LookupError):
            self.voices.join([a, str(uuid.uuid4())])

    def test_suggestions_from_the_database(self):
        handle = f"quietchan{''.join(ch for ch in self.mark if ch.isalpha())}"
        native = insert_source(self.cur, "Quiet", platform="telegram", handle=handle, in_main_digest=True)
        bridge = insert_source(self.cur, "Quiet", platform="telegram", handle=f"https://tg.bridge.example/rss/{handle}",
                               in_main_digest=True)
        found = self.voices.suggestions()
        mine = [g for g in found["voices"] if {s["id"] for s in g["sources"]} == {native, bridge}]
        self.assertEqual(len(mine), 1, found["voices"])
        self.assertTrue(mine[0]["same_channel"])
        self.voices.not_same(native, bridge)
        self.assertFalse([g for g in self.voices.suggestions()["voices"] if native in {s["id"] for s in g["sources"]}],
                         "not the same: never again, at once")

    def test_also_on_shows_one_post_once_on_the_voice_page(self):
        from insight_core.db.repo_voices import VoicesRepository
        blog, social = self._source("Quillon Desk"), self._source("Brightwater Talks")
        first = self._post(blog, "quillon", hours_ago=10, title="The long post")
        self.cur.execute("SELECT url FROM posts WHERE id = %s", (first,))
        url = self.cur.fetchone()[0]
        announce = self._post(social, "brightwater", hours_ago=9, title="New post", html=f'<a href="{url}">read</a>')
        far = self._post(social, "brightwater", hours_ago=200, title="Old", html=f'<a href="{url}">read</a>')
        self._fill()
        items = [{"id": announce}, {"id": first}, {"id": far}]
        self.assertEqual(VoicesRepository.also_on(self.cur, items, scope_kind="all", scope_id=None, filter="all"), items,
                         "no confirmed voice: the page as it was")
        voice = self.voices.join([blog, social])["voice"]["id"]
        shown = VoicesRepository.also_on(self.cur, items, scope_kind="voice", scope_id=voice, filter="all")
        self.assertEqual([i["id"] for i in shown], [first, far], "the later one leaves; one past 72 hours stays")
        self.assertEqual([line["id"] for line in shown[0]["also_on"]], [announce])
        self.assertEqual(shown[0]["also_on"][0]["why"], "links")
        alone = VoicesRepository.also_on(self.cur, items, scope_kind="source", scope_id=social, filter="all")
        self.assertEqual(alone, items, "one channel read alone shows every post")
        kept = VoicesRepository.also_on(self.cur, items, scope_kind="voice", scope_id=voice, filter="starred")
        self.assertEqual(kept, items)

    def test_the_voice_scope_reads_every_channel(self):
        from insight_core.db.repo_reader import FeedQuery, ReaderRepository
        blog, social, other = self._source("Quillon Desk"), self._source("Brightwater Talks"), self._source("Elsewhere")
        posts = [self._post(blog, "quillon", title="One"), self._post(social, "brightwater", title="Two"),
                 self._post(other, "elsewhere", title="Three")]
        voice = self.voices.join([blog, social])["voice"]["id"]
        rows, _ = ReaderRepository().list_posts(self.cur, FeedQuery.parse(scope=f"voice:{voice}", filter="all"), now=self.now)
        self.assertEqual({str(r["id"]) for r in rows}, set(posts[:2]))
        self.assertEqual(self.news.news_on(self.cur, f"voice:{voice}")["items"], [])
        self.assertTrue(self.news.classics_on(self.cur, f"voice:{voice}")["success"])


@requires_test_db
class VoicesRouteTests(unittest.TestCase):
    def setUp(self):
        import main
        from insight_core.routers import voices as route
        from insight_core.tests._asgi import call
        self.call, self.app, self.route = call, main.app, route

        class Fake:
            def __init__(self):
                self.calls = []

            def voices(self):
                return {"success": True, "voices": []}

            def join(self, ids, **kw):
                self.calls.append(("join", ids, kw))
                if len(ids) < 2 and not kw.get("voice_id"):
                    raise ValueError("a voice needs 2 sources at least")
                return {"success": True, "voice": {"id": "v"}, "queued_sources": ids}

            def voice(self, vid):
                raise LookupError(f"no such voice: {vid}")
        self.fake = Fake()
        route.use(self.fake)

    def tearDown(self):
        self.route.use(None)

    def test_routes_answer_and_say_why(self):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        status, _, body = self.call(self.app, "GET", "/api/voices")
        self.assertEqual((status, body["voices"]), (200, []))
        status, _, body = self.call(self.app, "POST", "/api/voices", json_body={"source_ids": [a, b], "by_hand": True})
        self.assertEqual(status, 200)
        self.assertTrue(self.fake.calls[-1][2]["by_hand"])
        status, _, body = self.call(self.app, "POST", "/api/voices", json_body={"source_ids": [a]})
        self.assertEqual(status, 400)
        status, _, body = self.call(self.app, "POST", "/api/voices", json_body={"source_ids": ["nope", b]})
        self.assertEqual((status, body["detail"]), (400, "source id must be a uuid"))
        status, _, _ = self.call(self.app, "GET", f"/api/voices/{a}")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
