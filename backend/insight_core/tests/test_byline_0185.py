"""Issue 0185 (1): Byline, who wrote a post and via whom, one module every view reads (utils/byline.py). Display only:
the voice a post counts as (Pairing's rule: a repost or forward counts as its author's voice only when a source follows
that author) is unchanged, proved here on a seeded world. Synthetic names only."""
from __future__ import annotations

import json
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from insight_core.db.repo_reader import _ITEM_COLUMNS, _item, repost_of  # noqa: E402
from insight_core.db.repo_stories import source_account  # noqa: E402
from insight_core.markx import news, pairing, tasks  # noqa: E402
from insight_core.tests._db import db_url, requires_test_db  # noqa: E402
from insight_core.utils import byline as B  # noqa: E402

NITTER = "https://nitter.local/{}/rss"


class Pure(unittest.TestCase):
    def test_an_x_feeds_own_post_a_repost_and_a_quote(self):
        feed = NITTER.format("feedowner")
        self.assertEqual(B.byline("Example Feed", "rss", feed, "feedowner"),
                         {"author": None, "via": "Example Feed", "quoting": None})
        self.assertEqual(B.byline("Example Feed", "rss", feed, "Acme"),
                         {"author": "@Acme", "via": "Example Feed", "quoting": None})
        self.assertEqual(B.byline("Example Feed", "rss", feed, "feedowner", quoted="nitter.local/other/status/2014444636303364349"),
                         {"author": None, "via": "Example Feed", "quoting": "@other"})
        # a quoted repost: the original's author, and whom the original quotes
        self.assertEqual(B.byline("Example Feed", "rss", feed, "Acme", quoted="x.com/other/status/2014444636303364349"),
                         {"author": "@Acme", "via": "Example Feed", "quoting": "@other"})
        # a self-quote (a thread) credits nobody else
        self.assertIsNone(B.byline("Example Feed", "rss", feed, "feedowner", quoted="x.com/FeedOwner/status/2014444636303364348")["quoting"])

    def test_a_telegram_forward_and_other_kinds(self):
        self.assertEqual(B.byline("Example Channel", "telegram", "examplechan", None, forwarded="Acme News"),
                         {"author": "Acme News", "via": "Example Channel", "quoting": None})
        self.assertIsNone(B.byline("Example Channel", "telegram", "examplechan", None, forwarded="  ")["author"])
        self.assertEqual(B.byline("Example Blog", "rss", "https://blog.example/feed", "Ivo Kestrel"),
                         {"author": None, "via": "Example Blog", "quoting": None}, "a blog's author field is no repost")

    def test_the_render_words_are_0168s(self):
        self.assertEqual(B.who({"author": "@acme", "via": "Example Feed"}), "a post by @acme shared by Example Feed")
        self.assertEqual(B.who({"author": None, "via": "Example Feed"}), "Example Feed")
        self.assertIs(tasks.original_author, B.original_author, "one rule, re-exported, never copied")

    def test_repost_of_is_unchanged(self):
        """The reader's repost field reads Byline's author rule now: the same answer as before on every case."""
        def before(platform, handle, author, reposted_by):
            account = source_account(platform, handle) or ""
            own = account[len("x.com/"):] if account.startswith("x.com/") else ""
            if not author or not own or own not in [a.lower() for a in reposted_by or ()]:
                return None
            return {"by": [a for a in reposted_by or () if a.lower() != own], "author": author}
        feeds = [("rss", NITTER.format("feedowner")), ("rss", "https://blog.example/feed"), ("telegram", "examplechan")]
        authors = [None, "", "feedowner", "Acme", "other"]
        bys = [None, [], ["feedowner"], ["FeedOwner", "fan_a"], ["fan_a"], ["acme"]]
        for platform, handle in feeds:
            for author in authors:
                for by in bys:
                    if author and by and author.lower() in [a.lower() for a in by]:
                        continue    # never stored: reposted_by leaves the tweet's own author out (post_fields.reposted_by)
                    self.assertEqual(repost_of(platform, handle, author, by), before(platform, handle, author, by),
                                     (platform, handle, author, by))


@requires_test_db
class SeededWorld(unittest.TestCase):
    maxDiff = None
    """An X feed carrying its own post, a repost of an account another source follows, a repost of a stranger and a
    quote; a Telegram channel forwarding a followed channel and a stranger."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        sfx = uuid.uuid4().hex[:6]
        self.owner, self.acme, self.chan, self.other = f"feedowner{sfx}", f"acme{sfx}", f"chan{sfx}", f"otherchan{sfx}"
        self.s_feed = self.source("rss", NITTER.format(self.owner), "Example Feed")
        self.s_acme = self.source("rss", NITTER.format(self.acme), "Acme")
        self.s_chan = self.source("telegram", self.chan, "Example Channel")
        self.s_other = self.source("telegram", self.other, "Other Channel")
        self.own = self.post(self.s_feed, self.owner)
        self.rt_followed = self.post(self.s_feed, self.acme, reposted_by=[self.owner])
        self.rt_stranger = self.post(self.s_feed, f"stranger{sfx}", reposted_by=[self.owner])
        self.quote = self.post(self.s_feed, self.owner, quoted=f"https://nitter.local/quoted{sfx}/status/2014444636303364347")
        self.fwd_followed = self.post(self.s_chan, None, forwarded={"username": self.other, "name": "Other Channel"})
        self.fwd_stranger = self.post(self.s_chan, None, forwarded={"username": f"stranger{sfx}", "name": "Stranger Channel"})
        self.sfx = sfx

    def source(self, platform, handle, name):
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest, settings) "
                         "VALUES (%s, %s, false, false, %s::jsonb) RETURNING id::text",
                         (platform, handle, json.dumps({"display_name": name})))
        return self.cur.fetchone()[0]

    def post(self, source, author, *, reposted_by=None, forwarded=None, quoted=None):
        n = uuid.uuid4().hex
        url = f"https://nitter.local/{author}/status/{int(n[:12], 16)}" if author else f"https://t.me/x/{n[:8]}"
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at, author, "
                         "reposted_by, metadata) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id::text",
                         (source, url, url, "A post", "A post with words of its own.", datetime.now(timezone.utc),
                          author, reposted_by, json.dumps({"forwarded_from": forwarded} if forwarded else {})))
        pid = self.cur.fetchone()[0]
        if quoted:
            self.cur.execute("INSERT INTO post_parts (post_id, title, title_from, lead, quoted, parse_stamp, digest) "
                             "VALUES (%s, 'A post', 'title', '', %s, 'test', 'test')", (pid, quoted))
        return pid

    def expected(self):
        return {
            self.own: {"author": None, "via": "Example Feed", "quoting": None},
            self.rt_followed: {"author": f"@{self.acme}", "via": "Example Feed", "quoting": None},
            self.rt_stranger: {"author": f"@stranger{self.sfx}", "via": "Example Feed", "quoting": None},
            self.quote: {"author": None, "via": "Example Feed", "quoting": f"@quoted{self.sfx}"},
            self.fwd_followed: {"author": "Other Channel", "via": "Example Channel", "quoting": None},
            self.fwd_stranger: {"author": "Stranger Channel", "via": "Example Channel", "quoting": None},
        }

    def test_every_view_reads_one_byline(self):
        want = self.expected()
        self.assertEqual(B.bylines(self.cur, want), want)
        lines = news._posts(self.cur, want)                                  # the Mark X pages' post lines
        self.assertEqual({p: lines[p]["byline"] for p in want}, want)
        for pid, b in want.items():                                          # the reader's row (feed, search, News)
            self.cur.execute(f"SELECT {_ITEM_COLUMNS} FROM posts p JOIN sources s ON s.id = p.source_id "
                             "LEFT JOIN post_reader_state rs ON rs.post_id = p.id "
                             "LEFT JOIN post_parts pp ON pp.post_id = p.id WHERE p.id = %s", (pid,))
            self.assertEqual(_item(self.cur.fetchone())["byline"], b, pid)
        loaded = tasks.load_posts(self.cur, want)                            # Mark X's renders
        for pid, b in want.items():
            self.assertEqual(loaded[pid].by, b["author"], pid)
            self.assertEqual(loaded[pid].who, B.who(b), pid)

    def test_voice_counts_are_unchanged(self):
        """Display only: a repost or forward counts as its author's voice only when a source follows that author
        (Pairing's rule); a stranger's stays the feed's voice, though its byline names the stranger."""
        loaded = tasks.load_posts(self.cur, self.expected())
        voices = {pid: p.voice for pid, p in loaded.items()}
        self.assertEqual(voices, {
            self.own: self.s_feed, self.rt_followed: self.s_acme, self.rt_stranger: self.s_feed,
            self.quote: self.s_feed, self.fwd_followed: self.s_other, self.fwd_stranger: self.s_chan})
        # the same as Pairing's rule asked directly over the stored fields, never the byline's words
        followed = pairing.followed_accounts(self.cur)
        for pid, p in loaded.items():
            account = tasks.author_account(p.kind, p.by, self.other if pid == self.fwd_followed else
                                           f"stranger{self.sfx}" if pid == self.fwd_stranger else None)
            direct = pairing.counted_voice(p.source_id, account, followed) if account else p.source_id
            self.assertEqual(voices[pid], direct, pid)
        self.assertEqual(len(set(voices.values())), 4, "4 voices over 6 posts: 2 strangers' posts stay their feeds'")


if __name__ == "__main__":
    unittest.main()
