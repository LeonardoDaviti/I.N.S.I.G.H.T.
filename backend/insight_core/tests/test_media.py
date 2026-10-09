"""Pure media helpers: clean stored URLs, tell images apart, derive YouTube thumbnails."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.kinds import parsing
from insight_core.utils import media

SIGNED = ("https://external-preview.redd.it/abc.png?width=640&crop=smart&auto=webp"
          "&s=0a0b0a86e772bac1ab597770541d706305a218b9")


class CleanUrlTests(unittest.TestCase):
    def test_unescapes_entities(self):
        escaped = SIGNED.replace("&", "&amp;")
        self.assertEqual(media.clean_url(escaped), SIGNED)
        self.assertEqual(media.clean_url(SIGNED.replace("&", "&#038;")), SIGNED)
        self.assertEqual(media.clean_url(SIGNED.replace("&", "&amp;#038;")), SIGNED, "double-escaped")
        self.assertEqual(media.clean_url("  " + SIGNED + " "), SIGNED)

    def test_non_strings_and_blanks(self):
        self.assertIsNone(media.clean_url(None))
        self.assertIsNone(media.clean_url(""))
        self.assertIsNone(media.clean_url(42))


class YoutubeIdTests(unittest.TestCase):
    def test_url_shapes(self):
        for url in (
            "https://www.youtube.com/watch?v=rHCpgtc5nzs",
            "https://youtube.com/watch?feature=share&v=rHCpgtc5nzs",
            "https://m.youtube.com/watch?v=rHCpgtc5nzs&t=10",
            "https://youtu.be/rHCpgtc5nzs?si=x",
            "https://www.youtube.com/shorts/rHCpgtc5nzs",
            "https://www.youtube.com/embed/rHCpgtc5nzs",
            "https://www.youtube-nocookie.com/embed/rHCpgtc5nzs",
            "https://www.youtube.com/live/rHCpgtc5nzs",
        ):
            self.assertEqual(media.youtube_video_id(url), "rHCpgtc5nzs", url)

    def test_not_a_video(self):
        for url in (None, "", "https://www.youtube.com/@channel", "https://example.com/watch?v=rHCpgtc5nzs",
                    "https://i.ytimg.com/vi/rHCpgtc5nzs/3.jpg", "https://www.youtube.com/watch?v=bad"):
            self.assertIsNone(media.youtube_video_id(url), url)

    def test_thumbnail(self):
        self.assertEqual(media.youtube_thumbnail("rHCpgtc5nzs"), "https://i.ytimg.com/vi/rHCpgtc5nzs/hqdefault.jpg")


class IsImageTests(unittest.TestCase):
    def test_images(self):
        for url in (
            "https://cdn.example.com/a.JPG", "https://x.com/a.jpeg?w=1", "https://x.com/a.png", "https://x.com/a.webp",
            "https://x.com/a.gif", "https://x.com/a.avif",
            "https://i.redd.it/abc", "https://preview.redd.it/abc?width=640", SIGNED,
            "https://i.ytimg.com/vi/x/3.jpg", "https://i0.wp.com/site/img?resize=1", "https://static.simonwillison.net/x",
            "https://tg.i-c-a.su/media/chan/1/photo", "https://substackcdn.com/image/fetch/w_1456/https%3A%2F%2Fa",
        ):
            self.assertTrue(media.is_image_url(url), url)

    def test_not_images(self):
        for url in (
            None, "https://www.youtube.com/watch?v=rHCpgtc5nzs", "https://tg.i-c-a.su/media/chan/1/clip.mp4",
            "https://example.com/article", "https://t.me/chan/1?single", "https://v.redd.it/abc",
            "https://x.com/a.webm", "https://i.redd.it/clip.mp4", "ftp://x.com/a.jpg",
        ):
            self.assertFalse(media.is_image_url(url), url)


class PostMediaTests(unittest.TestCase):
    def test_youtube_post(self):
        urls = ["https://www.youtube.com/watch?v=rHCpgtc5nzs", "https://i.ytimg.com/vi/rHCpgtc5nzs/3.jpg"]
        self.assertEqual(media.feed_thumb(urls, "https://www.youtube.com/watch?v=rHCpgtc5nzs"),
                         "https://i.ytimg.com/vi/rHCpgtc5nzs/hqdefault.jpg")
        result = media.post_media(urls, "https://www.youtube.com/watch?v=rHCpgtc5nzs")
        self.assertEqual(result["video"], {"provider": "youtube", "id": "rHCpgtc5nzs"})
        self.assertEqual(result["images"], [], "the video's own frame is not a separate image")

    def test_video_id_from_post_url_alone(self):
        self.assertEqual(media.feed_thumb([], "https://youtu.be/rHCpgtc5nzs"),
                         "https://i.ytimg.com/vi/rHCpgtc5nzs/hqdefault.jpg")

    def test_first_image_skipping_videos_and_cleaning(self):
        urls = ["https://tg.i-c-a.su/media/c/3730/clip.mp4", SIGNED.replace("&", "&amp;"),
                "https://x.com/b.jpg", SIGNED, None, 7, "https://example.com/page"]
        self.assertEqual(media.feed_thumb(urls, "https://example.com/post"), SIGNED)
        result = media.post_media(urls, "https://example.com/post")
        self.assertEqual(result["images"], [{"url": SIGNED}, {"url": "https://x.com/b.jpg"}], "ordered, deduped")
        self.assertIsNone(result["video"])

    def test_nothing(self):
        self.assertIsNone(media.feed_thumb(None, None))
        self.assertEqual(media.post_media(None, None), {"images": [], "video": None})
        self.assertIsNone(media.feed_thumb("not a list", None))


class ParsingUnescapeTests(unittest.TestCase):
    def test_feed_img_src_is_unescaped(self):
        escaped = SIGNED.replace("&", "&amp;amp;")  # &amp; inside an escaped description
        feed = f"""<?xml version="1.0"?><rss version="2.0"><channel><item>
          <title>t</title><link>https://example.com/p</link>
          <description>&lt;img src="{escaped}" /&gt;</description>
        </item></channel></rss>"""
        (post,) = parsing.parse_feed_posts(feed, "https://example.com/feed")
        self.assertEqual(post["media_urls"], [SIGNED])

    def test_extract_html_image_urls_unescapes(self):
        html_text = f'<img src="{SIGNED.replace("&", "&#038;")}"><img src="{SIGNED.replace("&", "&amp;")}">'
        self.assertEqual(parsing.extract_html_image_urls(html_text), [SIGNED])


if __name__ == "__main__":
    unittest.main()
