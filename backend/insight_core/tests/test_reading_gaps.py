"""What reading v9.9 would show (issue 0068): a thread's replies read as posts, the roundups that
mention a story, a repost by one of your sources as its voice, an outside origin's title by
evidence, and the stored bodies' link labels taken out once.

The rules are tested as pure functions; the job, the reader, the post page and the repair on the
database in one transaction per test, rolled back.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_posts import PostsRepository
from insight_core.db.repo_reader import FeedQuery, ReaderRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.posts_service import STORED_BODIES_KEY, PostsService, stored_bodies_stamp
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils.content_fingerprints import strip_html
from insight_core.utils.news_rules import news, tally
from insight_core.utils.post_links import site_of
from insight_core.utils.story_rules import StoryPost, group, roles
from insight_core.utils.tree_rules import origin_title

NOON = datetime(2026, 10, 27, 12, 0, 7, tzinfo=timezone.utc)
ID = 2114444636303364349


def tweet(pid, source, user, *, reposters=(), minutes=0.0):
    return StoryPost(id=pid, source_id=source, kind="x", own_site="x.com", home_site="x.com",
                     t=NOON + timedelta(minutes=minutes), url=f"https://x.com/{user}/status/{ID}", author=user,
                     reposters=tuple(reposters))


def linker(pid, source, url, text, *, hours=0.0, text_hash=None, kind="telegram"):
    return StoryPost(id=pid, source_id=source, kind=kind, own_site=f"{source}.test", t=NOON + timedelta(hours=hours),
                     url=f"https://{source}.test/{pid}", links=[(url, None)], link_texts={url: text} if text else {},
                     content_hash=text_hash, text_chars=200 if text_hash else 0)


class RepostVoiceRulesTests(unittest.TestCase):
    def test_a_reposter_is_a_share_voice_and_makes_a_story(self):
        [story] = group([tweet("t", "badlogic", "badlogicgames", reposters=["steipete"])])
        self.assertEqual((story.voices, [p.id for p in story.posts]), (2, ["t"]),
                         "one tweet your two sources pushed is a story of 2 voices")
        self.assertEqual(group([tweet("t", "badlogic", "badlogicgames")]), [], "no reposter: no story")

    def test_a_reposter_with_its_own_post_in_the_story_is_one_voice(self):
        quote = StoryPost(id="q", source_id="steipete", kind="x", own_site="x.com", home_site="x.com",
                          t=NOON + timedelta(minutes=5), url=f"https://x.com/steipete/status/{ID + 1}", author="steipete",
                          quoted=f"https://x.com/badlogicgames/status/{ID}",
                          links=[(f"https://x.com/badlogicgames/status/{ID}", "t")])
        [story] = group([tweet("t", "badlogic", "badlogicgames", reposters=["steipete"]), quote])
        self.assertEqual(story.voices, 2)

    def test_news_counts_a_reposter_as_a_share_each_voice_once(self):
        t = tweet("t", "badlogic", "badlogicgames", reposters=["steipete", "akhaliq"])
        self.assertEqual(tally([t], roles([t]), []), (1, 2, 0), "1 report, 2 shares")
        [found] = news([t], group([t]), [])
        self.assertEqual((found.reports, found.shares, found.score), (1, 2, 2.0), "a share is 1/2")


class OriginTitleTests(unittest.TestCase):
    URL = "https://anthropic.com/news/claude-fable-5-mythos-5"

    def title(self, *linkers, url=None):
        return origin_title(url or self.URL, list(linkers))

    def test_1_words_two_voices_agree_on_that_read_as_a_title(self):
        self.assertEqual(self.title(linker("a", "a", self.URL, "Claude Fable 5 and Mythos 5"),
                                    linker("b", "b", self.URL, "claude fable 5 and  mythos 5", hours=1),
                                    linker("c", "c", self.URL, "Introducing Fable", hours=2)),
                         "Claude Fable 5 and Mythos 5")

    def test_1_a_bare_word_two_voices_agree_on_is_no_title_and_copies_are_one_voice(self):
        bare = [linker("a", "a", self.URL, "Блогпост"), linker("b", "b", self.URL, "Блогпост", hours=1)]
        self.assertEqual(self.title(*bare), "Claude fable 5 mythos 5", "the slug, not a bare word")
        copies = [linker("a", "a", self.URL, "Read the whole post", text_hash="h"),
                  linker("b", "b", self.URL, "Read the whole post", hours=1, text_hash="h")]
        self.assertEqual(self.title(*copies), "Claude fable 5 mythos 5", "a forward does not agree with itself")

    def test_2_words_the_slug_confirms_keep_their_case(self):
        url = "https://openai.com/index/introducing-chatgpt-images-2-5"
        self.assertEqual(self.title(linker("a", "a", url, "Introducing ChatGPT Images 2.5"),
                                    linker("b", "b", url, "here", hours=1), url=url), "Introducing ChatGPT Images 2.5")
        url = "https://github.com/coddy-project/coddy-agent"
        self.assertEqual(self.title(linker("a", "a", url, "Coddy Agent"), url=url), "Coddy Agent")

    def test_3_the_slug_needs_three_words_of_letters(self):
        self.assertEqual(self.title(linker("a", "a", self.URL, "тут")), "Claude fable 5 mythos 5")
        for url in ("https://ft.com/content/7cab4ec7-4712-4137-b602-119a44f771de",   # an id
                    "https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro",          # two words
                    "https://arxiv.org/abs/2510.27055"):
            self.assertIsNone(self.title(linker("a", "a", url, "статья"), url=url), url)

    def test_4_one_voices_words_that_read_as_a_title(self):
        url = "https://arxiv.org/abs/2510.27055"
        self.assertEqual(self.title(linker("a", "a", url, "Scaling Laws for Agents"), linker("b", "b", url, "paper", hours=1),
                                    url=url), "Scaling Laws for Agents")

    def test_5_else_the_address(self):
        url = "https://shvm.xyz/webinar/ai-evals"
        self.assertIsNone(self.title(linker("a", "a", url, "here"), linker("b", "b", url, None, hours=1), url=url))

    def test_a_stored_page_is_the_root_with_its_own_title(self):
        stored = StoryPost(id="own", source_id="oa", kind="site", own_site="anthropic.com", t=NOON, url=self.URL,
                           title="Claude Fable 5 and Mythos 5")
        cite = StoryPost(id="a", source_id="a", kind="telegram", own_site="a.test", t=NOON + timedelta(hours=1),
                         url="https://a.test/a", links=[(self.URL, "own")], link_texts={self.URL: "Блогпост"})
        [story] = group([stored, cite])
        self.assertEqual((story.origin_url, story.parents["own"]), (None, (None, None, None)),
                         "the stored post is the root; the reader shows its title")


class ReadingGapsJobTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mark = uuid.uuid4().hex[:8]
        self.service = StoriesService(db_url(), clock=lambda: self.now)
        self.repo = PostsRepository(db_url())

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _source(self, name, handle=None):
        return insert_source(self.cur, name, handle=handle, in_main_digest=True)

    def _x(self, user):
        return self._source(user, f"https://nitter.local/{user}/rss")

    def _post(self, source, url, title, *, hours, html):
        return str(insert_post(self.cur, source, url, at=self.now - timedelta(hours=hours), title=title,
                               content="Body", html=html, content_hash=uuid.uuid4().hex))

    def _tweet(self, source, user, n, title, *, minutes=0, html=None):
        text = title.split(": ", 1)[-1] if title.startswith(("RT by @", "R to @")) else title
        post = {"url": f"https://nitter.local/{user}/status/{n}#m", "title": title, "content": text,
                "content_html": html or f"<p>{text}</p>", "date": self.now - timedelta(hours=3) + timedelta(minutes=minutes),
                "external_id": str(n)}
        return self.repo.upsert_post(self.cur, post, source)[0]

    def _regroup(self):
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        return self.service.regroup(self.cur, cutoff=None)

    def _row(self, post_id):
        """The feed row that is the post, or that its story folds it under."""
        items, _ = ReaderRepository(unread_window_days=None).list_posts(self.cur, FeedQuery(limit=100), now=self.now)
        return next(i for i in items if i["id"] == post_id
                    or any(p["id"] == post_id for p in ((i.get("story") or {}).get("posts") or [])))

    # ---- 2. the roundups that mention a story ---------------------------------------------------

    def _story_and_roundups(self):
        page = f"https://openai-{self.mark}.test/index/introducing-terra"
        link = f'<p><a href="{page}">Introducing GPT-6.1 Terra</a></p>'
        a, b = self._source("data_secrets"), self._source("Simon Willison")
        self.a = self._post(a, f"https://a-{self.mark}.test/1", "Вышла Terra", hours=6, html=link)
        self.b = self._post(b, f"https://b-{self.mark}.test/1", "Terra notes", hours=5, html=link)
        lw, smol = self._source("LessWrong"), self._source("Smol")

        def roundup(n):   # Terra is not its first link: it mentions the story, joins another
            return "".join(f'<p><a href="https://elsewhere-{self.mark}-{n}-{i}.test/x/y-z">x</a></p>' for i in range(3)) + link
        self.lw = [self._post(lw, f"https://lw-{self.mark}.test/{n}", f"AI #{n}", hours=4 - n, html=roundup(n)) for n in (1, 2)]
        self.smol = self._post(smol, f"https://smol-{self.mark}.test/1", "not much happened today", hours=1, html=roundup(9))
        return self._regroup()

    def test_the_roundups_that_mention_a_story_each_source_once_out_of_the_tree(self):
        self._story_and_roundups()
        story = self._row(self.a)["story"]
        self.assertEqual([(r["source_display_name"], r["id"], r["title"]) for r in story["roundups"]],
                         [("LessWrong", self.lw[0], "AI #1"), ("Smol", self.smol, "not much happened today")],
                         "LessWrong's two roundups, once, at its first; in the order they came")
        self.assertEqual({p["id"] for p in story["posts"]} | {self._row(self.a)["id"]}, {self.a, self.b},
                         "the roundups are not in the tree")
        self.assertEqual(story["voices"], 2, "they change no voice count")
        self.assertEqual(PostDetailService.story(self.cur, self.b)["roundups"], story["roundups"], "the post page has it too")

    def test_a_roundup_in_the_tree_is_not_repeated(self):
        self._story_and_roundups()
        page = f"https://openai-{self.mark}.test/index/introducing-terra"
        member = self._post(self._source("Zvi"), f"https://zvi-{self.mark}.test/1", "On Terra", hours=0.5,
                            html=f'<p><a href="{page}">Terra</a></p>' + "".join(
                                f'<p><a href="https://zvi-{self.mark}-{i}.test/x/y-z">x</a></p>' for i in range(3)))
        self._regroup()
        story = self._row(self.a)["story"]
        self.assertIn(member, {p["id"] for p in story["posts"]}, "a roundup whose first link is the story is in it")
        self.assertNotIn(member, {r["id"] for r in story["roundups"]})

    def test_a_sources_name_opens_its_roundup_most_about_the_story(self):
        # Issue 0069: the one that links the story's page earliest in it, then the first.
        self._story_and_roundups()
        page = f"https://openai-{self.mark}.test/index/introducing-terra"
        lw = self.cur.execute("SELECT source_id FROM posts WHERE id = %s", (self.lw[0],)).fetchone()[0]
        about = self._post(lw, f"https://lw-{self.mark}.test/3", "AI Village reacts to Terra", hours=0.5,
                           html=f'<p><a href="https://village-{self.mark}.test/x/y-z">x</a></p><p><a href="{page}">Terra</a></p>'
                           + "".join(f'<p><a href="https://village-{self.mark}-{i}.test/x/y-z">x</a></p>' for i in range(2)))
        self._regroup()
        story = self._row(self.a)["story"]
        self.assertEqual([(r["source_display_name"], r["id"]) for r in story["roundups"]],
                         [("Smol", self.smol), ("LessWrong", about)],
                         "LessWrong's roundup linking Terra second, not its earlier ones linking it fourth; then in"
                         " the order the roundups opened came")

    def test_a_source_in_the_story_is_not_named_in_roundups(self):
        self._story_and_roundups()
        lw = self.cur.execute("SELECT source_id FROM posts WHERE id = %s", (self.lw[0],)).fetchone()[0]
        self._post(lw, f"https://lw-{self.mark}.test/own", "LessWrong on Terra", hours=5.5,
                   html=f'<p><a href="https://openai-{self.mark}.test/index/introducing-terra">Terra</a></p>')
        self._regroup()
        story = self._row(self.a)["story"]
        self.assertIn("LessWrong", [s["name"] for s in story["sources"]], "LessWrong covers it")
        self.assertEqual([r["source_display_name"] for r in story["roundups"]], ["Smol"],
                         "so it isn't named again as a roundup")

    # ---- 3. a repost by one of your sources is its voice ----------------------------------------

    def test_a_tweet_your_other_source_reposted_is_a_story_and_the_reader_names_who(self):
        author, by = f"badlogic{self.mark}", f"steipete{self.mark}"
        own, steipete = self._x(author), self._x(by)
        t = self._tweet(own, author, ID, "how i work with agents in 2026")
        again = self._tweet(steipete, author, ID, f"RT by @{by}: how i work with agents in 2026")
        self.assertEqual(t, again)
        self._regroup()
        self.cur.execute("SELECT st.voices FROM story_posts sp JOIN stories st ON st.id = sp.story_id WHERE sp.post_id = %s", (t,))
        self.assertEqual(self.cur.fetchone(), (2,), "the author and the reposter: 2 voices")
        story = self._row(t)["story"]
        self.assertEqual(([s["id"] for s in story["sources"]], story["reposted_by"], story["posts"]),
                         ([own, steipete], [by], []), "covered by 2, and who reposted it")
        self.assertEqual(self.service.regroup(self.cur, cutoff=None)["changed"], 0, "a second run changes nothing")
        self.assertEqual(PostDetailService.story(self.cur, t)["voices"], 2, "the post page shows it")

    def test_an_author_reposting_itself_adds_no_voice(self):
        author = f"badlogic{self.mark}"
        own = self._x(author)
        t = self._tweet(own, author, ID, f"RT by @{author}: my own tweet again")
        self._regroup()
        self.cur.execute("SELECT 1 FROM story_posts WHERE post_id = %s", (t,))
        self.assertIsNone(self.cur.fetchone(), "no story: one voice")
        # Read by the job: the author's own source is never a reposter, whatever reposted_by holds.
        other, third = self._x(f"akhaliq{self.mark}"), self._x(f"third{self.mark}")
        row = {"id": t, "source_id": third, "t": self.now, "title": "x", "content_hash": None, "text_chars": 0,
               "html": None, "url": f"https://x.com/{author}/status/{ID}", "updated": False, "author": author,
               "links": [], "link_texts": {}, "reposted_by": [author, f"akhaliq{self.mark}", f"third{self.mark}"]}
        self.assertEqual(StoriesService._story_post(row, SourceFacts(self.cur)).reposters, (other,))

    def test_a_reposter_of_a_tweet_its_own_source_stored_adds_no_voice(self):
        author, by = f"badlogic{self.mark}", f"steipete{self.mark}"
        steipete = self._x(by)
        t = self._tweet(steipete, author, ID, f"RT by @{by}: how i work with agents in 2026")
        self._regroup()
        self.cur.execute("SELECT 1 FROM story_posts WHERE post_id = %s", (t,))
        self.assertIsNone(self.cur.fetchone(), "steipete's own repost is its post's voice, no second one")

    def test_a_repost_of_an_author_you_follow_is_the_authors_report_and_the_reposters_share(self):
        """x-repost-followed-author on the lab: one row, held by steipete's source (it saved it first)."""
        author, by = f"badlogic{self.mark}", f"steipete{self.mark}"
        steipete, own = self._x(by), self._x(author)
        t = self._tweet(steipete, author, ID, f"RT by @{by}: how i work with agents in 2026")
        self._regroup()
        self.cur.execute("SELECT st.voices, ns.reports, ns.shares, ns.score FROM story_posts sp JOIN stories st ON st.id = sp.story_id"
                         " LEFT JOIN news_posts np ON np.post_id = sp.post_id LEFT JOIN news_stories ns ON ns.id = np.news_id"
                         " WHERE sp.post_id = %s", (t,))
        self.assertEqual(self.cur.fetchone(), (2, 1, 1, 1.5), "badlogicgames' report, steipete's share: 1 + 1/2")
        self.assertEqual([s["id"] for s in self._row(t)["story"]["sources"]], [steipete, own])

    # ---- 1. a thread's replies read as posts ---------------------------------------------------

    def test_a_thread_reply_carries_its_html_and_its_links_to_stored_posts(self):
        user = f"badlogic{self.mark}"
        source = self._x(user)
        cited = self._post(self._source("Blog"), f"https://blog-{self.mark}.test/post", "A post", hours=9, html="<p>x</p>")
        root = self._tweet(source, user, ID, "software is dead. sad.")
        html = (f'<p>see <a href="https://blog-{self.mark}.test/post">this</a></p>'
                f'<img src="https://nitter.local/pic/media%2Fgiraffe.jpg" />')
        reply = self._tweet(source, user, ID + 1, f"R to @{user}: see this", minutes=2, html=html)
        self._regroup()
        [line] = [p for p in PostDetailService.story(self.cur, root)["posts"] if p["parent_reason"] == "thread"]
        self.assertEqual((line["id"], line["html"], line["internal_links"]),
                         (reply, html, {f"https://blog-{self.mark}.test/post": cited}))
        self.assertFalse(any("html" in p for p in self._row(root)["story"]["posts"]), "the feed row carries no reply's HTML")


class HostingPlatformTests(unittest.TestCase):
    """Item 8: a hosting platform's subdomain is its own site, as the Public Suffix List's private
    section says; an ordinary subdomain is its site's."""

    def test_a_platform_subdomain_is_its_own_site_an_ordinary_one_is_not(self):
        self.assertEqual([site_of(h) for h in ("karpathy.github.io", "www.lilianweng.github.io", "herman.bearblog.dev",
                                               "blog.x.com", "blog.ncase.me", "news.bbc.co.uk", "github.io")],
                         ["karpathy.github.io", "lilianweng.github.io", "herman.bearblog.dev",
                          "x.com", "ncase.me", "bbc.co.uk", "github.io"])
        self.assertEqual(site_of("gwern.substack.com"), "substack.com", "Substack is not in the list (measured; see the issue)")

    def test_two_writers_on_one_platform_are_two_voices(self):
        page = "https://example.org/papers/attention"

        def blog(pid, host, hours):
            return StoryPost(id=pid, source_id=pid, kind="site", own_site=site_of(host), t=NOON + timedelta(hours=hours),
                             url=f"https://{host}/{pid}", links=[(page, None)])
        [story] = group([blog("k", "karpathy.github.io", 0), blog("l", "lilianweng.github.io", 1)])
        self.assertEqual(story.voices, 2)
        self.assertEqual(group([blog("a", "blog.ncase.me", 0), blog("b", "ncase.me", 1)]), [], "one writer: one voice, no story")


class StoredBodiesTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_the_link_labels_leave_the_stored_bodies_and_nothing_else(self):
        source = insert_scratch_source(self.cur)
        labelled = ('<p>We worked with <a href="https://x.test/a">partners<span class="sr-only">(opens in a new window)</span>'
                    '</a> and <span class="visually-hidden">a chart: 66 %</span>.</p>')
        rows = {}
        for name, html in (("labelled", labelled), ("plain", "<p>We worked with <a href=\"https://x.test/a\">partners</a>.</p>")):
            self.cur.execute(
                """INSERT INTO posts (source_id, url, title, content, content_html, content_hash, links_scanned_at)
                   VALUES (%s, %s, %s, %s, %s, 'h', now()) RETURNING id""",
                (source, f"https://x.test/{uuid.uuid4().hex}", name, strip_html(html), html))
            rows[name] = str(self.cur.fetchone()[0])
        self.assertGreaterEqual(PostsRepository.drop_hidden_link_labels(self.cur), 1)
        self.cur.execute("SELECT id, content_html, content, content_hash <> 'h', links_scanned_at IS NULL FROM posts"
                         " WHERE id = ANY(%s::uuid[])", (list(rows.values()),))
        got = {str(r[0]): r[1:] for r in self.cur.fetchall()}
        self.assertEqual(got[rows["labelled"]][0], '<p>We worked with <a href="https://x.test/a">partners</a> and '
                                                   '<span class="visually-hidden">a chart: 66 %</span>.</p>',
                         "the label inside the link goes; hidden text outside a link stays")
        self.assertEqual(got[rows["labelled"]][1], "We worked with partners and a chart: 66 % .")
        self.assertEqual(got[rows["labelled"]][2:], (True, True), "its hash follows; the job reads its links again")
        self.assertEqual(got[rows["plain"]][2:], (False, False), "a body without labels is untouched")
        self.assertEqual(PostsRepository.drop_hidden_link_labels(self.cur), 0, "twice over: nothing more")


@requires_test_db
class StoredBodiesCatchUpTests(unittest.TestCase):
    """The repair runs once, in the background, as a version the stored bodies are brought up to."""

    def setUp(self):
        self.service = PostsService(db_url())
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.saved = SystemSettingsRepository.get(cur, STORED_BODIES_KEY)
            cur.execute("DELETE FROM system_settings WHERE key = %s", (STORED_BODIES_KEY,))

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM system_settings WHERE key = %s", (STORED_BODIES_KEY,))
            if self.saved:
                SystemSettingsRepository.upsert(cur, STORED_BODIES_KEY, self.saved[0])

    def test_once_then_never_again(self):
        self.service.catch_up_stored_bodies()
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(SystemSettingsRepository.get(cur, STORED_BODIES_KEY)[0]["rules"], stored_bodies_stamp())
        self.assertEqual(self.service.catch_up_stored_bodies(), 0, "at the same rules: nothing is read again")


if __name__ == "__main__":
    unittest.main()
