"""Media proxy (issue 0006): only a post's own images, only from public hosts or the LAN bridges."""
from __future__ import annotations

import asyncio
import io
import json
import sys
import unittest
import urllib.error
import uuid
from email.message import Message
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.services.media_proxy_service import (
    MAX_BYTES,
    MediaFetchFailed,
    MediaNotAllowed,
    MediaProxyService,
    body_image_urls,
    is_public_address,
    post_image_urls,
)
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db

PUBLIC = ["93.184.216.34"]


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type: str):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


class FakeOrigin:
    """url -> FakeResponse | (status, location); records (url, insecure_tls)."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.requests: list[tuple[str, bool]] = []

    def __call__(self, request, timeout, insecure_tls):
        url = request.full_url
        self.requests.append((url, insecure_tls))
        answer = self.answers.get(url)
        if answer is None:
            raise urllib.error.URLError("unreachable")
        if isinstance(answer, tuple):
            status, location = answer
            headers = Message()
            if location:
                headers["Location"] = location
            raise urllib.error.HTTPError(url, status, "", headers, None)
        return answer


def service(allowed: set[str], origin: FakeOrigin, resolve=None) -> MediaProxyService:
    proxy = MediaProxyService("postgresql://unused", private_hosts={"telegram.local"},
                              resolve=resolve or (lambda host: PUBLIC), opener=origin)
    proxy._allowed = lambda post_id: allowed  # the DB lookup has its own test below
    return proxy


class AllowedImagesTests(unittest.TestCase):
    def test_a_post_may_show_its_media_its_thumbnail_and_its_body_images(self):
        allowed = post_image_urls(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ["https://telegram.local/media/chan/1/a.jpg", "https://example.com/clip.mp4"],
            '<p><img src="https://cdn.test/x.png?a=1&amp;b=2"></p>',
            "![chart](https://cdn.test/chart.webp)",
        )
        self.assertEqual(allowed, {
            "https://telegram.local/media/chan/1/a.jpg",
            "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            "https://cdn.test/x.png?a=1&b=2",
            "https://cdn.test/chart.webp",
        })

    def test_body_images_read_both_quote_styles(self):
        self.assertEqual(body_image_urls("<img alt='' src='https://a.test/1.gif'><IMG SRC=\"https://a.test/2.gif\">"),
                         ["https://a.test/1.gif", "https://a.test/2.gif"])

    def test_public_addresses(self):
        self.assertTrue(is_public_address("8.8.8.8"))
        for private in ["10.0.0.1", "127.0.0.1", "172.18.0.3", "192.168.0.25", "169.254.169.254",
                        "100.86.230.4", "::1", "fd00::1"]:
            with self.subTest(address=private):
                self.assertFalse(is_public_address(private))


class FetchTests(unittest.TestCase):
    URL = "https://cdn.test/a.jpg"

    def test_an_image_of_the_post_is_fetched(self):
        origin = FakeOrigin({self.URL: FakeResponse(b"jpeg-bytes", "image/jpeg; charset=binary")})
        image = service({self.URL}, origin).fetch("p", self.URL)
        self.assertEqual((image.body, image.content_type), (b"jpeg-bytes", "image/jpeg"))
        self.assertEqual(origin.requests, [(self.URL, False)])

    def test_an_entity_escaped_url_matches_its_decoded_form(self):
        url = "https://cdn.test/a.jpg?a=1&b=2"
        origin = FakeOrigin({url: FakeResponse(b"x", "image/png")})
        self.assertEqual(service({url}, origin).fetch("p", "https://cdn.test/a.jpg?a=1&amp;b=2").body, b"x")

    def test_a_url_that_is_not_an_image_of_the_post_is_refused_without_a_request(self):
        origin = FakeOrigin({})
        with self.assertRaises(MediaNotAllowed):
            service({self.URL}, origin).fetch("p", "https://evil.test/other.jpg")
        self.assertEqual(origin.requests, [])

    def test_a_host_on_a_private_address_is_refused(self):
        origin = FakeOrigin({})
        url = "http://postgres:5432/x.jpg"
        with self.assertRaises(MediaNotAllowed):
            service({url}, origin, resolve=lambda host: ["172.18.0.2"]).fetch("p", url)
        self.assertEqual(origin.requests, [])

    def test_a_lan_bridge_is_fetched_with_its_self_signed_certificate(self):
        url = "https://telegram.local/media/chan/1/a.jpg"
        origin = FakeOrigin({url: FakeResponse(b"x", "image/jpeg")})
        resolve = lambda host: (_ for _ in ()).throw(AssertionError("a bridge is not resolved"))  # noqa: E731
        service({url}, origin, resolve=resolve).fetch("p", url)
        self.assertEqual(origin.requests, [(url, True)])

    def test_a_redirect_to_a_private_address_is_refused(self):
        origin = FakeOrigin({self.URL: (302, "http://169.254.169.254/latest/meta-data")})
        resolve = lambda host: ["169.254.169.254"] if host == "169.254.169.254" else PUBLIC  # noqa: E731
        with self.assertRaises(MediaNotAllowed):
            service({self.URL}, origin, resolve=resolve).fetch("p", self.URL)
        self.assertEqual(len(origin.requests), 1)

    def test_a_public_redirect_is_followed(self):
        final = "https://cdn2.test/a.jpg"
        origin = FakeOrigin({self.URL: (301, final), final: FakeResponse(b"x", "image/gif")})
        self.assertEqual(service({self.URL}, origin).fetch("p", self.URL).content_type, "image/gif")

    def test_something_that_is_not_an_image_fails(self):
        origin = FakeOrigin({self.URL: FakeResponse(b"<html>", "text/html")})
        with self.assertRaises(MediaFetchFailed):
            service({self.URL}, origin).fetch("p", self.URL)

    def test_more_than_10_mb_fails(self):
        origin = FakeOrigin({self.URL: FakeResponse(b"x" * (MAX_BYTES + 1), "image/png")})
        with self.assertRaises(MediaFetchFailed):
            service({self.URL}, origin).fetch("p", self.URL)

    def test_an_origin_error_fails(self):
        for answer in [(404, None), None]:
            with self.subTest(answer=answer):
                origin = FakeOrigin({self.URL: answer} if answer else {})
                with self.assertRaises(MediaFetchFailed):
                    service({self.URL}, origin).fetch("p", self.URL)


@requires_test_db
class AllowedFromTheDatabaseTests(unittest.TestCase):
    """_allowed reads the post on its own connection, so this commits scratch rows and removes them."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        source = insert_scratch_source(self.cur)
        self.cur.execute(
            "INSERT INTO posts (source_id, url, content_html, media_urls) VALUES (%s, %s, %s, %s::jsonb) RETURNING id",
            (source, f"https://test.invalid/media/{uuid.uuid4().hex}", '<img src="https://cdn.test/body.png">',
             json.dumps(["https://cdn.test/media.jpg"])),
        )
        self.post_id = str(self.cur.fetchone()[0])
        self.conn.commit()

    def tearDown(self):
        delete_scratch_sources(self.cur)
        self.conn.commit()
        self.cur.close()
        self.conn.close()

    def test_the_post_row_decides(self):
        proxy = MediaProxyService(db_url())
        self.assertEqual(proxy._allowed(self.post_id), {"https://cdn.test/body.png", "https://cdn.test/media.jpg"})
        with self.assertRaises(MediaNotAllowed):
            proxy._allowed(str(uuid.uuid4()))
        with self.assertRaises(MediaNotAllowed):
            proxy._allowed("not-a-uuid")


class RouteTests(unittest.TestCase):
    def setUp(self):
        import main
        from insight_core.services import registry
        self.main = main
        self.registry = registry
        self.addCleanup(registry.use, registry.use(None))

    def _get(self, fetch):
        from types import SimpleNamespace
        self.registry.use(SimpleNamespace(media_proxy=SimpleNamespace(fetch=fetch)))
        return asyncio.run(self.main.get_media(post="p", url="https://cdn.test/a.jpg"))

    def test_an_image_is_cached_for_a_day_with_safe_headers(self):
        from insight_core.services.media_proxy_service import MediaResponse
        response = self._get(lambda post, url: MediaResponse(b"x", "image/svg+xml"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "public, max-age=86400")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("sandbox", response.headers["content-security-policy"])

    def test_refused_is_404_and_a_failed_origin_is_502(self):
        def refused(post, url):
            raise MediaNotAllowed("no")

        def failed(post, url):
            raise MediaFetchFailed("down")

        self.assertEqual(self._get(refused).status_code, 404)
        self.assertEqual(self._get(failed).status_code, 502)
        self.assertEqual(self._get(failed).headers["cache-control"], "public, max-age=600")


if __name__ == "__main__":
    unittest.main()
