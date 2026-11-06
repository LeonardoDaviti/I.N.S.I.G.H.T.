"""X: reposts, quotes and threads become connections (issue 0066).

One address per tweet whatever the host; a repost names its original author and is a share; a
quote hangs from the tweet it quotes; an author's replies to itself within 24 hours are one
thread, one row in the feed, read together. The rules are tested as pure functions; the saver,
the job, the feed and migration 0047 on the database in one transaction per test, rolled back.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import PostsRepository
from insight_core.db.repo_reader import FeedQuery, ReaderRepository, repost_of
from insight_core.db.repo_stories import StoriesRepository
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.utils.post_fields import build_post_fields, display_title
from insight_core.utils.post_links import extract_links, quoted_tweet
from insight_core.utils.story_rules import StoryPost, group, threads
from insight_core.utils.url_normalization import normalize_url

MIGRATION = BACKEND_DIR / "insight_core" / "db" / "migrations" / "0047_x_connections.sql"
NOON = datetime(2026, 10, 27, 12, 0, 7, tzinfo=timezone.utc)
ID = 2115002476311241104


def tweet(pid, source, user, *, n, minutes=0.0, reposted=False, reply_to=None, quoted=None, links=()):
    """A post of an X source; `user` is the tweet's account, `n` its status id."""
    return StoryPost(id=pid, source_id=source, kind="x", own_site="x.com", home_site="x.com",
                     t=NOON + timedelta(minutes=minutes), url=f"https://x.com/{user}/status/{n}", author=user,
                     reposted=reposted, reply_to=reply_to, quoted=quoted, links=list(links))


def parents(story):
    """post -> (parent post or page, reason)"""
    return {pid: (p or u, r) for pid, (p, u, r) in story.parents.items()}


def cite(user, n):
    return f'<blockquote><b>{user}</b><p>quoted</p><footer>— <cite><a href="https://nitter.local/{user}/status/{n}#m">' \
           f'https://nitter.local/{user}/status/{n}#m</a></footer></blockquote>'


class AddressTests(unittest.TestCase):
    def test_every_form_of_a_tweet_is_one_address(self):
        forms = [f"https://nitter.local/Extraltodeus/status/{ID}#m", f"https://x.com/extraltodeus/status/{ID}?s=20&t=abc",
                 f"https://twitter.com/Extraltodeus/status/{ID}", f"https://mobile.twitter.com/Extraltodeus/status/{ID}",
                 f"https://xcancel.com/Extraltodeus/status/{ID}?s=46", f"https://fxtwitter.com/Extraltodeus/status/{ID}/photo/1",
                 f"http://nitter.net/Extraltodeus/status/{ID}/history", f"https://vxtwitter.com/Extraltodeus/status/{ID}"]
        self.assertEqual({normalize_url(url) for url in forms}, {f"https://x.com/extraltodeus/status/{ID}"})

    def test_only_the_shape_is_a_tweet(self):
        self.assertEqual(normalize_url("https://twitter.com/op/status/176767"), "https://x.com/op/status/176767",
                         "an id under 15 digits is no tweet's address by shape (the host alias still applies)")
        self.assertEqual(normalize_url("https://nitter.local/karpathy"), "https://nitter.local/karpathy")
        self.assertEqual(normalize_url(f"https://example.com/status/{ID}"), f"https://example.com/status/{ID}")

    def test_a_tweets_links_to_other_tweets_are_kept_through_your_own_nitter(self):
        html = (f'<p>see <a href="https://nitter.local/karpathy/status/{ID + 1}#m">this</a>'
                f' and <a href="https://nitter.local/karpathy">karpathy</a>'
                f' and <a href="https://nitter.local/badlogicgames/status/{ID}#m">me</a></p>{cite("hvent90", ID + 2)}')
        links = extract_links(html, f"https://nitter.local/badlogicgames/status/{ID}#m", "x")
        self.assertEqual([link.url for link in links],
                         [f"https://x.com/karpathy/status/{ID + 1}", f"https://x.com/hvent90/status/{ID + 2}"],
                         "a profile is still the platform, and a tweet never links itself")
        self.assertEqual(quoted_tweet(html), f"https://x.com/hvent90/status/{ID + 2}")
        on_a_blog = extract_links(f'<a href="https://xcancel.com/sama/status/{ID}?s=46">x</a>', "https://blog.test/a", "site")
        self.assertEqual([link.url for link in on_a_blog], [f"https://x.com/sama/status/{ID}"])

    def test_a_repost_names_its_author_and_who_reposted_it(self):
        fields = build_post_fields({"url": f"https://nitter.local/badlogicgames/status/{ID}#m",
                                    "title": "RT by @steipete: how i work with agents in 2026."})
        self.assertEqual((fields["author"], fields["reposted_by"], fields["url_host"]), ("badlogicgames", ["steipete"], "x.com"))
        own = build_post_fields({"url": f"https://nitter.local/sama/status/{ID}#m", "title": "RT by @sama: mine"})
        self.assertEqual((own["author"], own["reposted_by"]), ("sama", []), "an author reposting itself is no one else")
        self.assertEqual(build_post_fields({"url": "https://blog.test/a", "title": "A"})["author"], None)
        self.assertEqual(display_title("RT by @steipete: how i work with agents in 2026.", "how i work"),
                         "how i work with agents in 2026.", "who reposted it is said beside the title")

    def test_a_repost_line_names_its_source_once(self):
        # Issue 0070: "badlogicgames ↻ from @thsottiaux", not "badlogicgames · ↻ @badlogicgames, from @thsottiaux".
        nitter = "https://nitter.local/badlogicgames/rss"
        self.assertEqual(repost_of("rss", nitter, "thsottiaux", ["badlogicgames"]), {"by": [], "author": "thsottiaux"})
        self.assertEqual(repost_of("rss", nitter, "thsottiaux", ["BadlogicGames", "steipete"]),
                         {"by": ["steipete"], "author": "thsottiaux"})
        self.assertIsNone(repost_of("rss", "https://nitter.local/thsottiaux/rss", "thsottiaux", ["steipete"]),
                          "the author's own row: the reposters are said in its story")
        self.assertIsNone(repost_of("rss", nitter, None, None))


class XRulesTests(unittest.TestCase):
    # ---- reposts --------------------------------------------------------------------------------

    def test_a_repost_stored_apart_hangs_from_its_original_and_is_a_share(self):
        original = tweet("bg", "bg-src", "badlogicgames", n=ID)
        repost = tweet("sp", "sp-src", "badlogicgames", n=ID, minutes=40, reposted=True)
        [story] = group([original, repost])
        self.assertEqual(parents(story), {"bg": (None, None), "sp": ("bg", "repost")})
        self.assertEqual(story.roles, {"bg": "report", "sp": "share"})
        self.assertFalse(repost.on_own_site, "another account's tweet is never its source's own page")

    # ---- quotes ---------------------------------------------------------------------------------

    def test_a_quote_hangs_from_the_stored_tweet_it_quotes_whatever_the_source(self):
        quoted_url = f"https://x.com/hvent90/status/{ID}"
        shared = tweet("rt", "bg-src", "hvent90", n=ID, reposted=True)   # badlogicgames' repost of hvent90
        quote = tweet("q", "bg-src", "badlogicgames", n=ID + 9, minutes=131, quoted=quoted_url, links=[(quoted_url, "rt")])
        [story] = group([shared, quote])
        self.assertEqual(parents(story), {"rt": (None, None), "q": ("rt", "quote")})
        self.assertIn("quote", story.reasons["q"])

    def test_a_quote_of_a_tweet_not_stored_hangs_from_it_as_the_outside_origin(self):
        quoted_url = f"https://x.com/elonmusk/status/{ID}"
        a = tweet("a", "a-src", "sama", n=ID + 1, quoted=quoted_url, links=[(quoted_url, None)])
        b = tweet("b", "b-src", "karpathy", n=ID + 2, minutes=30, quoted=quoted_url, links=[(quoted_url, None)])
        [story] = group([a, b])
        self.assertEqual(story.origin_url, quoted_url)
        self.assertEqual(parents(story), {"a": (quoted_url, "quote"), "b": (quoted_url, "quote")})

    def test_a_quote_does_not_make_a_tweet_a_roundup(self):
        page, docs, quoted_url = "https://hf.test/unsloth/glm-gguf", "https://unsloth.test/docs/glm", f"https://x.com/u/status/{ID}"
        quote = tweet("q", "dh", "danielhanchen", n=ID + 1, quoted=quoted_url,
                      links=[(docs, None), (page, None), (quoted_url, None)])
        blog = StoryPost(id="kc", source_id="kc-src", kind="site", own_site="kaitchup.test", t=NOON + timedelta(hours=30),
                         url="https://kaitchup.test/glm", links=[(page, None)])
        [story] = group([quote, blog])
        self.assertEqual({p.id for p in story.posts}, {"q", "kc"}, "both links of the quote stay what it is about")

    # ---- threads --------------------------------------------------------------------------------

    def test_three_replies_to_itself_are_a_thread(self):
        posts = [tweet("t0", "bg", "badlogicgames", n=ID),
                 tweet("t1", "bg", "badlogicgames", n=ID + 1, minutes=5, reply_to="badlogicgames"),
                 tweet("t2", "bg", "badlogicgames", n=ID + 2, minutes=10, reply_to="badlogicgames"),
                 tweet("t3", "bg", "badlogicgames", n=ID + 3, minutes=15, reply_to="BadLogicGames")]
        [story] = group(posts)
        self.assertEqual(parents(story), {"t0": (None, None), "t1": ("t0", "thread"), "t2": ("t1", "thread"),
                                          "t3": ("t2", "thread")})
        self.assertEqual(story.voices, 1, "one source's thread is a story of one voice")

    def test_a_page_saved_days_after_a_thread_about_it_is_in_the_thread(self):
        """0113: one account's thread links the page you saved later, dated by its first link (the save path): one
        place, no link join, but its date joins it to the thread (the lab's case: a saved essay under its author's thread)."""
        page = "https://essays.example/blog/matmul"
        saved = StoryPost(id="s", source_id="saved-src", kind="saved", own_site="", home_site="",
                          t=NOON, url=page, title="Inside the GPU")   # no date of its own: its first link's
        posts = [saved, tweet("t0", "ag", "author_a", n=ID, links=[(page, "s")]),
                 tweet("t1", "ag", "author_a", n=ID + 1, minutes=5, reply_to="author_a", links=[(page, "s")]),
                 tweet("t2", "ag", "author_a", n=ID + 2, minutes=10, reply_to="author_a")]
        [story] = group(posts)
        self.assertEqual({p.id for p in story.posts}, {"s", "t0", "t1", "t2"})
        self.assertEqual(story.voices, 1)

    def test_tweets_of_one_second_follow_their_ids(self):
        posts = [tweet("z0", "pa", "predict_addict", n=ID),
                 tweet("a2", "pa", "predict_addict", n=ID + 2, reply_to="predict_addict"),
                 tweet("a1", "pa", "predict_addict", n=ID + 1, reply_to="predict_addict")]
        self.assertEqual(threads(posts), {"a1": "z0", "a2": "a1"})
        [story] = group(posts)
        self.assertEqual((story.id, parents(story)["z0"]), ("z0", (None, None)), "the first tweet is the thread's root")

    def test_a_reply_to_someone_else_makes_no_thread(self):
        posts = [tweet("t0", "bg", "badlogicgames", n=ID),
                 tweet("r", "bg", "badlogicgames", n=ID + 1, minutes=5, reply_to="hvent90"),
                 tweet("t2", "bg", "badlogicgames", n=ID + 2, minutes=10, reply_to="badlogicgames")]
        self.assertEqual(threads(posts), {}, "nor does a reply to itself that follows it")
        self.assertEqual(group(posts), [])

    def test_a_reply_more_than_24_hours_after_the_post_before_starts_nothing(self):
        posts = [tweet("t0", "bg", "badlogicgames", n=ID),
                 tweet("t1", "bg", "badlogicgames", n=ID + 1, minutes=24 * 60 + 1, reply_to="badlogicgames"),
                 tweet("t2", "bg", "badlogicgames", n=ID + 2, minutes=24 * 60 + 5, reply_to="badlogicgames")]
        self.assertEqual(threads(posts), {"t2": "t1"}, "24 hours of the previous post in the chain, not of its first")

    def test_a_thread_never_starts_at_a_repost_of_another_account(self):
        posts = [tweet("own", "pk", "pankajkumar_dev", n=ID),
                 tweet("rt", "pk", "someone", n=ID - 5, minutes=10, reposted=True),
                 tweet("r1", "pk", "pankajkumar_dev", n=ID + 1, minutes=11, reply_to="pankajkumar_dev")]
        self.assertEqual(threads(posts), {}, "its parent is not known: not the repost, not the post before it")
        self_repost = [tweet("rt", "pk", "pankajkumar_dev", n=ID), tweet("r1", "pk", "pankajkumar_dev", n=ID + 1,
                                                                          minutes=1, reply_to="pankajkumar_dev")]
        self.assertEqual(threads(self_repost), {"r1": "rt"}, "an author reposting its own tweet: its own post")

    # ---- a thread follows the tweet it quotes (issue 0103) ----------------------------------------

    def _two_subjects(self, *, stored=True):
        """An account's tweet on one subject, then a thread on another, then a reply quoting the first."""
        first = f"https://x.com/ann/status/{ID}"
        second = f"https://x.com/ann/status/{ID + 10}"
        return [tweet("a", "ann", "ann", n=ID)] * stored + [                                # subject A
                tweet("b", "ann", "ann", n=ID + 10, minutes=60),                           # subject B
                tweet("b1", "ann", "ann", n=ID + 11, minutes=61, reply_to="ann", quoted=second,
                      links=[(second, "b")]),
                tweet("b2", "ann", "ann", n=ID + 12, minutes=62, reply_to="ann", quoted=second,
                      links=[(second, "b")]),
                tweet("a1", "ann", "ann", n=ID + 13, minutes=80, reply_to="ann", quoted=first,
                      links=[(first, "a" if stored else None)])]   # not stored: its link resolves to none

    def test_a_self_reply_hangs_under_the_own_tweet_it_quotes_not_the_one_before_it(self):
        posts = self._two_subjects()
        self.assertEqual(threads(posts), {"b1": "b", "b2": "b", "a1": "a"})
        stories = group(posts)
        self.assertEqual(sorted(sorted(p.id for p in s.posts) for s in stories), [["a", "a1"], ["b", "b1", "b2"]],
                         "the two subjects stay apart")
        [b] = [s for s in stories if s.id == "b"]
        self.assertEqual(parents(b), {"b": (None, None), "b1": ("b", "thread"), "b2": ("b", "thread")})

    def test_a_self_reply_quoting_an_own_tweet_not_stored_follows_the_timeline(self):
        posts = self._two_subjects(stored=False)
        self.assertEqual(threads(posts)["a1"], "b2", "its target isn't stored: the post before it")

    def test_a_self_reply_quoting_its_stored_tweet_from_two_days_ago_continues_the_tweet_before_it(self):
        # Measured on the lab (0103): "Related tweet from earlier…", "oh yeah i should have linked…" quote
        # an older tweet as a reference, inside the thread right before them.
        old = f"https://x.com/ann/status/{ID}"
        posts = [tweet("a", "ann", "ann", n=ID),
                 tweet("b", "ann", "ann", n=ID + 10, minutes=47 * 60),
                 tweet("a1", "ann", "ann", n=ID + 11, minutes=48 * 60, reply_to="ann", quoted=old, links=[(old, "a")])]
        self.assertEqual(threads(posts), {"a1": "b"}, "past a thread's 24 hours, its quote is no reply target")
        [story] = group(posts)
        self.assertEqual(sorted(p.id for p in story.posts), ["a", "a1", "b"], "its quote still joins the tweet it quotes")

    def test_a_self_reply_quoting_its_tweet_held_as_another_rows_link_finds_its_own_row(self):
        first = f"https://x.com/ann/status/{ID}"
        posts = [tweet("a", "ann", "ann", n=ID),
                 tweet("b", "ann", "ann", n=ID + 10, minutes=5),
                 tweet("a1", "ann", "ann", n=ID + 11, minutes=6, reply_to="ann", quoted=first,
                       links=[(first, "elsewhere")])]   # the address's first row is another source's
        self.assertEqual(threads(posts), {"a1": "a"})

    def test_a_self_reply_quoting_someone_elses_tweet_follows_the_timeline(self):
        other = f"https://x.com/bob/status/{ID + 5}"
        posts = [tweet("a", "ann", "ann", n=ID),
                 tweet("a1", "ann", "ann", n=ID + 11, minutes=6, reply_to="ann", quoted=other, links=[(other, "x")])]
        self.assertEqual(threads(posts), {"a1": "a"})

    def test_a_reply_across_a_repost_hangs_under_the_own_tweet_it_quotes(self):
        first = f"https://x.com/pk/status/{ID}"
        posts = [tweet("own", "pk", "pk", n=ID),
                 tweet("rt", "pk", "someone", n=ID - 5, minutes=10, reposted=True),
                 tweet("r1", "pk", "pk", n=ID + 1, minutes=11, reply_to="pk", quoted=first, links=[(first, "own")])]
        self.assertEqual(threads(posts), {"r1": "own"}, "its target is known: the repost before it is no matter")


@requires_test_db
class XJobTests(unittest.TestCase):
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

    def _x(self, user):
        """An X source following `user` (through your Nitter), in the Main feed."""
        source = insert_scratch_source(self.cur, in_main_digest=True)
        self.cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s",
                         (f"https://nitter.local/{user}/rss", source))
        return source

    def _save(self, source, user, n, title, *, minutes=0, html=None):
        text = title.split(": ", 1)[-1] if title.startswith(("RT by @", "R to @")) else title   # Nitter's body
        post = {"url": f"https://nitter.local/{user}/status/{n}#m", "title": title, "content": text,
                "content_html": html or f"<p>{title}</p>", "date": self.now - timedelta(hours=3) + timedelta(minutes=minutes),
                "external_id": str(n)}
        return self.repo.upsert_post(self.cur, post, source)[0]

    def _regroup(self):
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        return self.service.regroup(self.cur)

    def test_a_tweet_two_of_your_sources_repost_is_one_row_that_keeps_both(self):
        steipete, akhaliq = self._x(f"steipete{self.mark}"), self._x(f"akhaliq{self.mark}")
        author = f"Badlogic{self.mark}"
        first = self._save(steipete, author, ID, f"RT by @steipete{self.mark}: how i work with agents in 2026.")
        again = self._save(akhaliq, author, ID, f"RT by @akhaliq{self.mark}: how i work with agents in 2026.")
        self.assertEqual(first, again)
        self.cur.execute("SELECT normalized_url, author, reposted_by FROM posts WHERE id = %s", (first,))
        self.assertEqual(self.cur.fetchone(), (f"https://x.com/{author.lower()}/status/{ID}", author,
                                               sorted([f"akhaliq{self.mark}", f"steipete{self.mark}"])))
        items, _ = ReaderRepository(unread_window_days=None).list_posts(self.cur, FeedQuery(limit=100), now=self.now)
        [row] = [i for i in items if i["id"] == first]
        # The row is steipete's: it names the other reposter, never its own source again (issue 0070).
        self.assertEqual(row["repost"], {"by": [f"akhaliq{self.mark}"], "author": author})
        self.assertEqual(row["title"], "how i work with agents in 2026.")

    def test_two_copies_of_one_tweet_join_by_their_address(self):
        user = f"sama{self.mark}"
        own = self._save(self._x(user), user, ID, "who is running the bigger scam")
        df = insert_scratch_source(self.cur, in_main_digest=True)
        for page in ("a", "b"):   # Daring Fireball publishes on its own site, and links a tweet now and then
            self.repo.upsert_post(self.cur, {"url": f"https://df-{self.mark}.test/{page}", "title": page, "content": page}, df)
        link = self.repo.upsert_post(self.cur, {"url": f"https://x.com/{user}/status/{ID}", "title": "Altman and Musk Argue",
                                                "content": "Altman and Musk", "date": self.now - timedelta(hours=1)}, df)[0]
        self.assertNotEqual(own, link, "two titles: two posts (0049)")
        self._regroup()
        self.cur.execute("SELECT post_id, parent_id, parent_reason FROM story_posts WHERE post_id = ANY(%s::uuid[])", ([own, link],))
        self.assertEqual({str(r[0]): (str(r[1]) if r[1] else None, r[2]) for r in self.cur.fetchall()},
                         {own: (None, None), link: (own, "address")})

    def test_a_thread_is_one_row_read_in_order_and_read_together(self):
        user = f"badlogic{self.mark}"
        source = self._x(user)
        root = self._save(source, user, ID, "software is dead. sad.")
        replies = [self._save(source, user, ID + i, f"R to @{user}: reply {i}", minutes=5 * i) for i in (1, 2, 3)]
        other = self._save(source, user, ID + 9, "R to @someone: not mine", minutes=20)
        self._regroup()
        items, _ = ReaderRepository(unread_window_days=None).list_posts(self.cur, FeedQuery(limit=100), now=self.now)
        mine = [i for i in items if i["id"] in (root, *replies, other)]
        self.assertEqual([i["id"] for i in mine], [other, root], "the thread is one row, at its first post")
        story = mine[1]["story"]
        self.assertTrue(story["thread"])
        self.assertEqual([(p["parent_reason"], p["title"], p["text"]) for p in story["posts"]],
                         [("thread", f"reply {i}", f"reply {i}") for i in (1, 2, 3)], "the replies' own words, in order")
        self.assertTrue(PostDetailService.story(self.cur, root)["thread"], "the post page reads the thread too")
        marked = ReaderRepository(unread_window_days=None).set_read(self.cur, [root], True)
        self.assertEqual(set(marked), {root, *replies}, "opening the thread marks its posts read")

    def test_a_replys_quote_of_its_own_thread_is_no_card(self):
        # Issue 0070: pankajkumar_dev's replies each quote the thread's first tweet; it is read once.
        user = f"ann{self.mark}"
        source = self._x(user)
        root = self._save(source, user, ID, "Model Y leaks: codenamed Q")
        quote = (f'<p>Its out guys.<br>\n</p><p><a href="https://nitter.net/{user}/status/{ID}?s=20">nitter.net/{user}/status…</a></p>\n'
                 f'<hr/>\n<blockquote>\n<b>Pankaj</b>\n<p>Model Y leaks</p>\n<footer>\n— <cite>'
                 f'<a href="https://nitter.local/{user}/status/{ID}#m">https://nitter.local/{user}/status/{ID}#m</a>\n</footer>\n</blockquote>')
        reply = self._save(source, user, ID + 1, f"R to @{user}: Its out guys.", minutes=5, html=quote)
        self._regroup()
        [line] = [p for p in PostDetailService.story(self.cur, root)["posts"] if p["id"] == reply]
        self.assertEqual((line["quotes_above"], line["html"]), (True, "<p>Its out guys.<br>\n</p>"))

    def test_a_reply_that_only_quotes_its_thread_is_no_line(self):
        # Issue 0072: a reply with nothing of its own, only a quote of the thread's first tweet, is no
        # line in the tree or the thread page; the reply after it hangs from the post before.
        user = f"ann{self.mark}"
        source = self._x(user)
        root = self._save(source, user, ID, "Model Z one more output.")
        card = (f'<p><a href="https://nitter.net/{user}/status/{ID}?s=20">nitter.net/{user}/status…</a></p>\n<hr/>\n'
                f'<blockquote>\n<b>Ann Lee (@{user})</b>\n<p>Model Z one more output.</p>\n<footer>\n— <cite>'
                f'<a href="https://nitter.local/{user}/status/{ID}#m">https://nitter.local/{user}/status/{ID}#m</a>\n</footer>\n</blockquote>')
        only = self._save(source, user, ID + 1, f"R to @{user}: x.com/{user}/status…", minutes=5, html=card)
        after = self._save(source, user, ID + 2, f"R to @{user}: Benchmarks are out", minutes=10)
        self._regroup()
        story = PostDetailService.story(self.cur, root)
        self.assertEqual([(p["id"], p["parent_id"], p["parent_reason"]) for p in story["posts"]], [(after, root, "thread")])
        item = {"id": only}
        ReaderRepository.attach_stories(self.cur, [item])
        self.assertEqual(item["story"]["parent_id"], root, "opened at itself, the post still has its place")
        both = [{"id": root}, {"id": only}]   # one page holding both (issue 0072 D1: this raised KeyError)
        ReaderRepository.attach_stories(self.cur, both)
        self.assertEqual([p["id"] for p in both[0]["story"]["posts"]], [after])
        self.assertEqual(both[1]["story"]["parent_id"], root)

    def test_a_thread_posts_quote_of_its_first_tweet_is_no_card_on_its_page(self):
        # Issue 0072 D4: the opened reply's card repeats the thread's first tweet, which the thread lists below.
        user = f"ann{self.mark}"
        source = self._x(user)
        self._save(source, user, ID, "Model Z benchmarks are out")
        card = (f'<p>Benchmarks</p>\n<p><a href="https://nitter.net/{user}/status/{ID}?s=20">nitter.net/{user}/status…</a></p>\n<hr/>\n'
                f'<blockquote>\n<b>Ann Lee (@{user})</b>\n<p>Model Z benchmarks are out</p>\n<footer>\n— <cite>'
                f'<a href="https://nitter.local/{user}/status/{ID}#m">https://nitter.local/{user}/status/{ID}#m</a>\n</footer>\n</blockquote>')
        reply = self._save(source, user, ID + 1, f"R to @{user}: Benchmarks", minutes=5, html=card)
        self._regroup()

        @contextmanager
        def here(_url):
            yield self.conn
        with mock.patch("insight_core.services.post_detail_service.db.connection", here):
            post = PostDetailService(db_url()).get_post_by_id(reply)
        self.assertTrue(post["story"]["thread"])
        self.assertNotIn("<blockquote>", post["content_html"] or "")
        self.assertEqual(post["title"], "Benchmarks")
        self.assertEqual(post["content"], "Benchmarks", "its text without the quoted words: the page reads its title once")

    def test_a_reply_quoting_an_earlier_tweet_of_its_own_joins_that_tweets_story_only(self):
        # Issue 0103: a reply quoting the account's tweet of an hour ago hangs under it, not under the
        # account's thread on another subject posted in between.
        user = f"ann{self.mark}"
        source = self._x(user)

        def card(n, words):
            return (f'<p>{words}</p>\n<p><a href="https://nitter.net/{user}/status/{n}?s=20">nitter.net/{user}/status…</a></p>\n'
                    f'<hr/>\n<blockquote>\n<b>Ann Lee (@{user})</b>\n<p>quoted</p>\n<footer>\n— <cite>'
                    f'<a href="https://nitter.local/{user}/status/{n}#m">https://nitter.local/{user}/status/{n}#m</a>\n'
                    f'</footer>\n</blockquote>')
        first = self._save(source, user, ID, "Another output from Model A.")
        launch = self._save(source, user, ID + 10, "Model B is now live", minutes=60)
        out = self._save(source, user, ID + 11, f"R to @{user}: its out", minutes=61, html=card(ID + 10, "its out"))
        back = self._save(source, user, ID + 12, f"R to @{user}: one more from Model A", minutes=80,
                          html=card(ID, "one more from Model A"))
        self._regroup()
        self.cur.execute("SELECT post_id::text, story_id::text, parent_id::text, parent_reason FROM story_posts "
                         "WHERE post_id = ANY(%s::uuid[])", ([first, launch, out, back],))
        rows = {r[0]: r[1:] for r in self.cur.fetchall()}
        self.assertEqual(rows[back][1:], (first, "thread"))
        self.assertEqual(rows[out][1:], (launch, "thread"))
        self.assertNotEqual(rows[first][0], rows[launch][0], "two subjects, two stories")

    def test_a_thread_of_only_quotes_of_its_first_tweet_is_no_story(self):
        user = f"ann{self.mark}"
        source = self._x(user)
        root = self._save(source, user, ID, "Model Y leaks: codenamed Q")
        card = (f'<p><a href="https://nitter.net/{user}/status/{ID}?s=20">nitter.net/{user}/status…</a></p>\n<hr/>\n'
                f'<blockquote>\n<b>Ann Lee (@{user})</b>\n<p>Model Y leaks</p>\n<footer>\n— <cite>'
                f'<a href="https://nitter.local/{user}/status/{ID}#m">https://nitter.local/{user}/status/{ID}#m</a>\n</footer>\n</blockquote>')
        for n in (1, 2):
            self._save(source, user, ID + n, f"R to @{user}: x.com/{user}/status…", minutes=5 * n, html=card)
        self._regroup()
        self.assertIsNone(PostDetailService.story(self.cur, root), "no 'Thread · 1 posts' with nothing under it")


class MigrationTests(unittest.TestCase):
    @requires_test_db
    def test_0047_re_addresses_tweets_and_keeps_their_reading_state(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        conn = psycopg.connect(db_url())
        try:
            cur = conn.cursor()
            mark = uuid.uuid4().hex[:8]
            source = insert_scratch_source(cur)
            cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s", (f"https://nitter.local/akhaliq{mark}/rss", source))
            rows = {}
            for name, url, title in [
                ("repost", f"https://nitter.local/Clement{mark}/status/{ID}#m", f"RT by @gg{mark}: We crossed $100M"),
                ("own", f"https://nitter.local/akhaliq{mark}/status/{ID + 1}#m", "a paper"),
                ("blog", f"https://blog-{mark}.test/a", "A post"),
            ]:
                cur.execute("""INSERT INTO posts (source_id, url, normalized_url, url_host, title, content, links_scanned_at, content_html)
                               VALUES (%s, %s, %s, %s, %s, 'c', now(), %s) RETURNING id""",
                            (source, url, url.split("#")[0], url.split("/")[2], title,
                             f'<a href="https://x.com/k/status/{ID}">x</a>' if name == "blog" else None))
                rows[name] = cur.fetchone()[0]
            cur.execute("INSERT INTO post_reader_state (post_id, read_at, starred_at) VALUES (%s, now(), now())", (rows["repost"],))
            for _ in range(2):   # a second run changes nothing more
                cur.execute(sql)
                cur.execute("SELECT id, normalized_url, canonical_url, url_host, author, reposted_by, links_scanned_at IS NULL"
                            " FROM posts WHERE id = ANY(%s)", (list(rows.values()),))
                got = {r[0]: r[1:] for r in cur.fetchall()}
                self.assertEqual(got[rows["repost"]], (f"https://x.com/clement{mark}/status/{ID}",) * 2
                                 + ("x.com", f"Clement{mark}", sorted([f"akhaliq{mark}", f"gg{mark}"]), False))
                self.assertEqual(got[rows["own"]][3:5], (f"akhaliq{mark}", None), "its own tweet: no one reposted it")
                self.assertEqual(got[rows["blog"]][3:], (None, None, True), "a post linking a tweet is read again")
            cur.execute("SELECT read_at IS NOT NULL, starred_at IS NOT NULL FROM post_reader_state WHERE post_id = %s",
                        (rows["repost"],))
            self.assertEqual(cur.fetchone(), (True, True), "read state stays with the post")
        finally:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    unittest.main()
