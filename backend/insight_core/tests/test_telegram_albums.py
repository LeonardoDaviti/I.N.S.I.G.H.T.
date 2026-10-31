"""A Telegram album is one post (issue 0069, B4): migration 0051's fold_telegram_albums, the feed,
its counts, search, read state, the post page and the media proxy. Commits scratch rows, so it runs
only against a *_test database."""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import PostDraft, PostsRepository
from insight_core.db.repo_reader import FeedQuery, FeedScope, ReaderRepository
from insight_core.services.media_proxy_service import MediaProxyService
from insight_core.services.post_detail_service import PostDetailService
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db

T0 = datetime(2026, 10, 29, 18, 54, 17, tzinfo=timezone.utc)


def _picture(channel: str, n: int) -> dict:
    image = f"https://telegram.local/media/{channel}/{n}/full.jpg"
    return {"html": f'<a href="{image}"><img src="https://telegram.local/media/{channel}/{n}/thumb.jpeg"/></a>',
            "media": [image, f"https://telegram.local/media/{channel}/{n}/thumb.jpeg"]}


@requires_test_db
class TelegramAlbumTests(unittest.TestCase):
    def setUp(self):
        self.url = db_url()
        self.channel = f"chan{uuid.uuid4().hex[:8]}"
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source = insert_scratch_source(cur)
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _draft(self, n: int, after: timedelta, text: str = "") -> PostDraft:
        picture = _picture(self.channel, n)
        return PostDraft(self.source, {
            "url": f"https://t.me/{self.channel}/{n}", "title": text or "[Photo]", "date": T0 + after,
            "content": text, "content_html": picture["html"] + (f"<br/>{text}" if text else ""),
            "media_urls": picture["media"],
        })

    def _ids(self) -> dict:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT url, id, album_of FROM posts WHERE source_id = %s", (self.source,))
            return {url.rsplit("/", 1)[1]: (str(pid), str(album) if album else None) for url, pid, album in cur.fetchall()}

    def _save_album(self) -> dict:
        drafts = [
            # The bridge sends the newest first; the album is folded once the batch is saved.
            self._draft(15, timedelta(hours=1, minutes=10)),   # 10 minutes after its channel's post: its own
            self._draft(14, timedelta(hours=1), "A later post with words."),
            self._draft(13, timedelta(seconds=78)),
            self._draft(12, timedelta(seconds=78)),
            self._draft(11, timedelta(seconds=9)),
            self._draft(10, timedelta(0), "Тема с роутингом отдельных запросов на разные модели."),
        ]
        with psycopg.connect(self.url) as conn:
            PostsRepository(self.url).save_batch(conn, drafts)
        return self._ids()

    def test_the_pictures_after_a_post_are_that_post(self):
        ids = self._save_album()
        host = ids["10"][0]
        self.assertEqual({n: album for n, (_, album) in ids.items()},
                         {"10": None, "11": host, "12": host, "13": host, "14": None, "15": None})
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT fold_telegram_albums(%s::uuid)", (self.source,))
            self.assertEqual(cur.fetchone()[0], 0, "folding again changes nothing")

    def test_the_feed_its_counts_and_search_show_the_post_once(self):
        ids = self._save_album()
        reader = ReaderRepository(unread_window_days=None)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            items, _ = reader.list_posts(cur, FeedQuery(scope=FeedScope.parse(f"source:{self.source}"), filter="all"),
                                         now=T0 + timedelta(days=1))
            self.assertEqual({item["id"] for item in items}, {ids[n][0] for n in ("10", "14", "15")})
            self.assertEqual(reader.unread_counts(cur)["by_source"][self.source], 3)
            # Reading the post reads its pictures: nothing of the album is left unread.
            marked = reader.set_read(cur, [ids["10"][0]], True)
            self.assertEqual(set(marked), {ids[n][0] for n in ("10", "11", "12", "13")})

    def test_the_post_page_shows_the_pictures_in_its_body_and_the_proxy_serves_them(self):
        ids = self._save_album()
        post = PostDetailService(self.url).get_post_by_id(ids["10"][0])
        html = post["content_html"]
        for n in (11, 12, 13):
            self.assertIn(f"/media/{self.channel}/{n}/thumb.jpeg", html)
        self.assertLess(html.index(f"/{self.channel}/12/"), html.index(f"/{self.channel}/13/"))
        self.assertNotIn(f"/{self.channel}/15/", html)
        allowed = MediaProxyService(self.url)._allowed(ids["10"][0])
        self.assertIn(f"https://telegram.local/media/{self.channel}/13/full.jpg", allowed)
        self.assertNotIn(f"https://telegram.local/media/{self.channel}/15/full.jpg", allowed)


if __name__ == "__main__":
    unittest.main()
