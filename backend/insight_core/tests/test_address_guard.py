"""Issue 0187: where INSIGHT's outgoing requests may go (AddressGuard, under KindHttp and the media proxy), and
how much of an answer they read (MAX_BODY_BYTES). Against a local server named by a fake DNS: nothing leaves
the machine."""
from __future__ import annotations

import asyncio
import io
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion import http as http_module
from insight_core.ingestion.http import (
    MAX_BODY_BYTES,
    AddressGuard,
    AddressNotAllowed,
    BodyTooLarge,
    HttpError,
    KindHttp,
    bridge_hosts,
    is_public_address,
)
from insight_core.tests._local_web import BIG, DNS, FakeDns, LocalWeb, guard

PRIVATE = {
    "loopback": "127.0.0.1", "loopback, other": "127.8.9.10", "private 10/8": "10.1.2.3",
    "private 172.16/12 (Docker's networks)": "172.17.0.1", "private 192.168/16": "192.168.1.20",
    "link-local (cloud metadata)": "169.254.169.254", "CGNAT / Tailscale 100.64/10": "100.64.0.1",
    "unspecified": "0.0.0.0", "multicast": "224.0.0.1", "reserved": "240.0.0.1", "IPv6 loopback": "::1",
    "IPv6 link-local": "fe80::1", "IPv6 unique local": "fd00::1", "IPv4-mapped loopback": "::ffff:127.0.0.1",
    "IPv4-mapped metadata": "::ffff:169.254.169.254",
}


def run(coro):
    return asyncio.run(coro)


class AddressClassTests(unittest.TestCase):
    def test_public_addresses_pass(self):
        for address in ("93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"):
            self.assertTrue(is_public_address(address), address)

    def test_every_non_global_class_is_refused_before_any_connection(self):
        no_bridges = AddressGuard(bridges=set(), insecure_tls_hosts=set())
        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("connected")):
            for name, address in PRIVATE.items():
                with self.subTest(name):
                    self.assertFalse(is_public_address(address))
                    host = f"[{address}]" if ":" in address else address
                    with self.assertRaises(AddressNotAllowed):
                        run(KindHttp(guard=no_bridges).get_text(f"http://{host}/"))
            with self.subTest("a decimal IPv4 (2130706433 = 127.0.0.1)"):
                with self.assertRaises(AddressNotAllowed):
                    run(KindHttp(guard=no_bridges).get_text("http://2130706433/"))

    def test_a_name_with_any_private_address_is_refused(self):
        for host in ("metadata.test", "docker.test", "cgnat.test", "mixed.test"):
            with self.subTest(host):
                with self.assertRaises(AddressNotAllowed):
                    guard().addresses(host, 80)

    def test_the_bridges_are_the_lan_defaults_and_the_configured_ones(self):
        hosts = bridge_hosts({"NITTER_HOSTS": "https://nitter.home:8443", "TELEGRAM_RSS_HOSTS": "tg.home",
                              "INSIGHT_MEDIA_PRIVATE_HOSTS": "img.home, ", "RSS_SKIP_TLS_VERIFY_HOSTS": "feeds.home"})
        self.assertEqual(hosts, {"telegram.local", "nitter.local", "nitter.home", "tg.home", "img.home", "feeds.home"})
        self.assertNotIn("127.0.0.1", bridge_hosts({}), "loopback is never a bridge by default")

    def test_a_bridge_on_the_lan_is_allowed_and_its_tls_unverified_only_there(self):
        lan = AddressGuard(bridges={"telegram.local"}, insecure_tls_hosts=set(),
                           resolve=FakeDns({"telegram.local": ["192.168.1.5"], "printer.local": ["192.168.1.9"]}))
        self.assertEqual(lan.addresses("telegram.local", 443), (["192.168.1.5"], True))
        self.assertTrue(lan.insecure_tls("telegram.local", True))
        self.assertFalse(lan.insecure_tls("telegram.local", False), "a bridge on a public address is verified")
        with self.assertRaises(AddressNotAllowed):   # *.local alone is no longer a pass
            lan.addresses("printer.local", 443)


class ConnectionTests(unittest.TestCase):
    def test_an_allowed_host_is_fetched(self):
        with LocalWeb() as web:
            body, headers = run(KindHttp(guard=guard()).get_text(web.url("origin.test", "/ok")))
        self.assertEqual(body, "hello")
        self.assertEqual(headers["content-type"], "text/plain")

    def test_the_connection_goes_to_the_address_checked_no_second_answer(self):
        # DNS rebinding: the first answer is public, every later one loopback. The guard asks once per
        # connection and connects to that answer, so the second never matters.
        dns = FakeDns({"rebind.test": [["93.184.216.34"], ["127.0.0.1"]]})
        connected = []

        def create_connection(address, *args, **kwargs):
            connected.append(address)
            raise OSError("stop here")

        with mock.patch.object(socket, "create_connection", create_connection):
            with self.assertRaises(HttpError):
                run(KindHttp(guard=AddressGuard(bridges=set(), resolve=dns)).get_text("http://rebind.test/"))
        self.assertEqual(connected, [("93.184.216.34", 80)])
        self.assertEqual(dns.asked, ["rebind.test"])

    def test_a_redirect_to_an_internal_address_is_refused(self):
        with LocalWeb() as web:
            for call in (lambda h, u: h.get_text(u), lambda h, u: h.get_start(u, 100),
                         lambda h, u: h.get_conditional(u)):
                with self.subTest(call=call):
                    dns = FakeDns(DNS)
                    with self.assertRaises(AddressNotAllowed):
                        run(call(KindHttp(guard=guard(dns)), web.url("origin.test", "/to-internal")))
                    self.assertEqual(dns.asked, ["origin.test", "metadata.test"], "each hop is checked")

    def test_a_redirect_to_a_non_web_address_is_refused(self):
        with LocalWeb() as web:
            with self.assertRaises(HttpError):
                run(KindHttp(guard=guard()).get_text(web.url("origin.test", "/to-file")))

    def test_at_most_three_redirects(self):
        with LocalWeb() as web:
            body, final = run(KindHttp(guard=guard()).get_start(web.url("origin.test", "/chain/3"), 100))
            self.assertEqual((body, final), (b"end", web.url("origin.test", "/chain/0")))
            with self.assertRaises(HttpError):
                run(KindHttp(guard=guard()).get_text(web.url("origin.test", "/chain/4")))

    def test_a_cookie_follows_a_redirect_only_on_the_same_host(self):
        cookie = {"Cookie": "substack.sid=secret"}
        with LocalWeb() as web:
            same, _ = run(KindHttp(guard=guard()).get_text(web.url("origin.test", "/to-same"), headers=cookie))
            other, _ = run(KindHttp(guard=guard()).get_text(web.url("origin.test", "/to-other"), headers=cookie))
        self.assertEqual(same, "substack.sid=secret")
        self.assertEqual(other, "none")

    def test_no_environment_proxy_is_used(self):
        with LocalWeb() as web, mock.patch.dict("os.environ", {"http_proxy": "http://169.254.169.254:1",
                                                               "HTTP_PROXY": "http://169.254.169.254:1"}):
            body, _ = run(KindHttp(guard=guard()).get_text(web.url("origin.test", "/ok")))
        self.assertEqual(body, "hello")


class BodyCapTests(unittest.TestCase):
    def test_a_gzip_bomb_stops_at_the_cap(self):
        with LocalWeb() as web:
            url = web.url("origin.test", "/bomb")
            with self.assertRaises(BodyTooLarge):
                run(KindHttp(guard=guard()).get_text(url))
            with self.assertRaises(BodyTooLarge):
                run(KindHttp(guard=guard()).get_conditional(url))
            start = run(KindHttp(guard=guard()).get_start(url, 1000))[0]
            self.assertEqual(start, b"\0" * 1000, "a short read still unpacks only what it asked for")

    def test_a_raw_body_over_the_cap_fails_and_a_caller_may_raise_it(self):
        with LocalWeb() as web:
            url = web.url("origin.test", "/big")
            with self.assertRaises(BodyTooLarge):
                run(KindHttp(guard=guard()).get_text(url))
            body, _ = run(KindHttp(guard=guard()).get_text(url, max_bytes=2 * MAX_BODY_BYTES))
            self.assertEqual(len(body), BIG)
            with self.assertRaises(BodyTooLarge):   # a smaller cap is not a way around the default
                run(KindHttp(guard=guard()).get_text(url, max_bytes=10))

    def test_a_small_compressed_body_still_reads(self):
        with LocalWeb() as web:
            body, _ = run(KindHttp(guard=guard()).get_text(web.url("origin.test", "/small-gzip")))
        self.assertEqual(body, "<rss/>")

    def test_a_json_answer_is_capped_too(self):
        class Huge(io.BytesIO):
            headers: dict = {}

        with mock.patch.object(KindHttp, "_open", return_value=Huge(b"1" * (MAX_BODY_BYTES + 1))):
            with self.assertRaises(BodyTooLarge):
                run(KindHttp().post_json("https://x.example/", {}))

    def test_an_error_answer_body_is_read_only_in_part(self):
        import urllib.error

        class Endless(io.BytesIO):
            def read(self, n=-1):
                if n is None or n < 0:
                    raise AssertionError("read the whole error body")
                return b"x" * n

        error = urllib.error.HTTPError("https://x.example/", 500, "Oops", {}, Endless())
        with mock.patch.object(KindHttp, "_open", side_effect=error):
            with self.assertRaises(HttpError) as raised:
                run(KindHttp().get_text("https://x.example/"))
        self.assertEqual(raised.exception.status, 500)
        self.assertLess(len(str(raised.exception)), 400)


class DefaultsTests(unittest.TestCase):
    def test_every_kind_http_and_the_media_proxy_are_guarded_by_default(self):
        from insight_core.services.media_proxy_service import MediaProxyService
        self.assertIsInstance(KindHttp().guard, AddressGuard)
        self.assertIsInstance(MediaProxyService("postgresql://unused").guard, AddressGuard)
        self.assertNotIn("urlopen(", Path(http_module.__file__).read_text(),
                         "no request leaves through urllib's unguarded urlopen")


if __name__ == "__main__":
    unittest.main()
