"""GET /api/search (issue 0040): real services on the scratch database, over ASGI.

Word forms in English and Russian, phrases, -word, the source's name, each narrowing (scope,
Later, Kept, days), both orders, the snippet and paging. Rows are committed, so the class
only runs against a `_test` database. Every post's title ends in the test's own marker word
and every query names it, so no other row can match.
"""
import random
import string
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.db.repo_search import SearchQuery, snippet_parts
from insight_core.services import registry
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db

FOLDER_PREFIX = "mark-ix-test-folder-"


class SnippetPartsTests(unittest.TestCase):
    def test_marked_words_become_parts(self):
        self.assertEqual(snippet_parts("the \x01servers\x02  fell \x01over\x02\n&amp; out"), [
            {"text": "the ", "mark": False}, {"text": "servers", "mark": True},
            {"text": " fell ", "mark": False}, {"text": "over", "mark": True}, {"text": " & out", "mark": False},
        ])

    def test_next_marks_join(self):
        self.assertEqual(snippet_parts("\x01a\x02\x01b\x02"), [{"text": "ab", "mark": True}])

    def test_no_mark_is_no_snippet(self):
        self.assertIsNone(snippet_parts("the start of the text"))
        self.assertIsNone(snippet_parts(None))


class SearchQueryParseTests(unittest.TestCase):
    def test_bad_values_are_value_errors(self):
        for kwargs in ({"q": "  "}, {"q": "x" * 501}, {"q": "x", "filter": "unread"}, {"q": "x", "order": "oldest"},
                       {"q": "x", "limit": 0}, {"q": "x", "days": 0}, {"q": "x", "scope": "tag:x"},
                       {"q": "x", "cursor": "garbage!!"}, {"q": "x", "order": "best", "cursor": "-3"}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                SearchQuery.parse(**kwargs)

    def test_no_scope_is_every_post(self):
        self.assertIsNone(SearchQuery.parse(q="x").scope)
        self.assertEqual(SearchQuery.parse(q="x", order="best", cursor="60").offset, 60)


@requires_test_db
class SearchRouteTests(unittest.TestCase):
    def setUp(self):
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)
        self.addCleanup(self._clean)
        self._clean()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        # A word no other row holds, in every post of the test and in every query.
        self.marker = "qz" + "".join(random.choices(string.ascii_lowercase, k=10))

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM folders WHERE name LIKE %s", (FOLDER_PREFIX + "%",))
            delete_scratch_sources(cur)

    def _source(self, *, name: str | None = None, in_main_digest: bool = False) -> str:
        settings = '{"display_name": "%s"}' % name if name else "{}"
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            return insert_scratch_source(cur, settings_json=settings, in_main_digest=in_main_digest)

    def _post(self, source_id: str, title: str, content: str = "", *, hours_ago: float = 1) -> str:
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO posts (source_id, url, published_at, title, content) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (source_id, f"https://test.invalid/mark-ix/post/{uuid.uuid4().hex}",
                 self.now - timedelta(hours=hours_ago), f"{title} {self.marker}", content),
            )
            return str(cur.fetchone()[0])

    def search(self, q: str, **query):
        status, _, body = call(main.app, "GET", "/api/search", query={"q": f"{self.marker} {q}", **query})
        self.assertEqual(status, 200, body)
        return body

    def ids(self, q: str, **query) -> list[str]:
        return [item["id"] for item in self.search(q, **query)["items"]]

    # ---- what matches -------------------------------------------------------------------

    def test_english_word_forms(self):
        source = self._source()
        watching = self._post(source, "Watching the logs", "We kept watching.")
        self._post(source, "Something else", "Nothing here.")

        self.assertEqual(self.ids("watch"), [watching])
        self.assertEqual(self.ids("watches"), [watching])

    def test_russian_word_forms(self):
        source = self._source()
        server = self._post(source, "Авария", "Вчера ночью сервер упал на два часа.")
        self._post(source, "Погода", "Сегодня тепло.")

        self.assertEqual(self.ids("серверы"), [server])
        self.assertEqual(self.ids("сервера"), [server])

    def test_another_language_is_found_as_plain_words(self):
        source = self._source()
        post = self._post(source, "Le café", "Les éléphants dansent.")
        self.assertEqual(self.ids("éléphants"), [post])

    def test_a_quoted_phrase_matches_in_order(self):
        source = self._source()
        phrase = self._post(source, "Outage", "The servers fell over at noon.", hours_ago=2)
        apart = self._post(source, "Outage", "Over the weekend the servers were fine until one fell.")

        self.assertEqual(self.ids('"servers fell"'), [phrase])
        self.assertEqual(self.ids("servers fell"), [apart, phrase])

    def test_minus_word_excludes(self):
        source = self._source()
        keep = self._post(source, "Tailscale on the server", "", hours_ago=2)
        self._post(source, "Tailscale on the phone", "")

        self.assertEqual(self.ids("tailscale -phone"), [keep])

    def test_the_source_name_matches(self):
        simon = self._source(name="Simon Willison")
        other = self._source(name="Someone Else")
        by_simon = self._post(simon, "Notes on MCP", "", hours_ago=2)
        self._post(other, "Notes on MCP", "")

        self.assertEqual(self.ids("simon mcp"), [by_simon])

    def test_renaming_a_source_renames_it_in_search(self):
        source = self._source(name="Old Name")
        post = self._post(source, "A post")
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("UPDATE sources SET settings = '{\"display_name\": \"Fresh Title\"}'::jsonb WHERE id = %s", (source,))

        self.assertEqual(self.ids("fresh"), [post])
        self.assertEqual(self.ids("old"), [])

    def test_posts_stored_before_search_are_filled_in_batches(self):
        source = self._source()
        posts = [self._post(source, "Robots") for _ in range(3)]
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("UPDATE posts SET search_vector = NULL WHERE id = ANY(%s::uuid[])", (posts,))
        self.assertEqual(self.ids("robots"), [])

        reader = registry.services().reader
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(reader.search_repo.fill_missing_vectors(cur, batch=2), 2)
        self.assertGreaterEqual(reader.fill_search_vectors(), 1)

        self.assertEqual(sorted(self.ids("robots")), sorted(posts))
        self.assertEqual(reader.fill_search_vectors(), 0)

    def test_read_or_unread_does_not_matter(self):
        source = self._source()
        post = self._post(source, "A read post")
        call(main.app, "PUT", "/api/feed/read", json_body={"ids": [post], "read": True})
        self.assertEqual(self.ids("read"), [post])

    def test_only_stop_words_match_nothing(self):
        self._post(self._source(), "The and of")
        status, _, body = call(main.app, "GET", "/api/search", query={"q": "the and"})
        self.assertEqual((status, body["items"], body["next_cursor"]), (200, [], None))

    def test_bad_values_are_400(self):
        for query in ({"q": ""}, {"q": "x", "filter": "unread"}, {"q": "x", "scope": "folder:nope"},
                      {"q": "x", "order": "best", "cursor": "abc"}):
            with self.subTest(**query):
                status, _, body = call(main.app, "GET", "/api/search", query=query)
                self.assertEqual(status, 400, body)

    # ---- narrowing ----------------------------------------------------------------------

    def test_scope_source_track_main_and_everything(self):
        inside = self._source(in_main_digest=True)
        outside = self._source(in_main_digest=False)
        a = self._post(inside, "Robots", hours_ago=2)
        b = self._post(outside, "Robots")
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO folders (name) VALUES (%s) RETURNING id", (FOLDER_PREFIX + uuid.uuid4().hex,))
            track = str(cur.fetchone()[0])
            cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (track, outside))

        self.assertEqual(self.ids("robots"), [b, a], "no scope: every post")
        self.assertEqual(self.ids("robots", scope="all"), [a], "all: the Main feed")
        self.assertEqual(self.ids("robots", scope=f"source:{inside}"), [a])
        self.assertEqual(self.ids("robots", scope=f"folder:{track}"), [b])

    def test_later_and_kept(self):
        source = self._source()
        later, kept, _plain = (self._post(source, "Robots", hours_ago=h) for h in (3, 2, 1))
        call(main.app, "PUT", "/api/feed/later", json_body={"ids": [later], "later": True})
        call(main.app, "POST", f"/api/posts/item/{kept}/favorite", json_body={"favorited": True})

        self.assertEqual(self.ids("robots", filter="later"), [later])
        self.assertEqual(self.ids("robots", filter="starred"), [kept])

    def test_days(self):
        source = self._source()
        recent = self._post(source, "Robots", hours_ago=24 * 3)
        self._post(source, "Robots", hours_ago=24 * 10)

        self.assertEqual(self.ids("robots", days=7), [recent])
        self.assertEqual(len(self.ids("robots", days=30)), 2)

    # ---- order, snippet, paging ---------------------------------------------------------

    def test_newest_first_and_best_match_puts_the_title_first(self):
        source = self._source()
        in_title = self._post(source, "Kubernetes upgrade notes", "How it went.", hours_ago=5)
        in_text = self._post(source, "Weekly links", "One link was about kubernetes.", hours_ago=1)

        self.assertEqual(self.ids("kubernetes"), [in_text, in_title])
        self.assertEqual(self.ids("kubernetes", order="best"), [in_title, in_text])

    def test_snippet_marks_the_words_in_the_matching_line(self):
        source = self._source()
        filler = " ".join(["Lorem ipsum dolor sit amet."] * 40)
        self._post(source, "A long post", f"{filler} Then the servers fell over at noon. {filler}")

        (item,) = self.search("server")["items"]
        marked = [part["text"] for part in item["snippet"] if part["mark"]]
        line = "".join(part["text"] for part in item["snippet"])

        self.assertEqual(marked, ["servers"])
        self.assertIn("Then the servers fell over at noon.", line)
        self.assertLess(len(line), 400)

    def test_a_title_only_hit_has_no_snippet(self):
        source = self._source()
        self._post(source, "Kubernetes", "Nothing about it here.")
        (item,) = self.search("kubernetes")["items"]
        self.assertIsNone(item["snippet"])
        self.assertEqual(item["title"], f"Kubernetes {self.marker}")

    def test_pages_without_overlap_in_both_orders(self):
        source = self._source()
        posts = [self._post(source, "Robots", "robots " * n, hours_ago=n) for n in range(1, 6)]

        for order in ("newest", "best"):
            with self.subTest(order=order):
                seen, cursor = [], None
                while True:
                    query = {"order": order, "limit": 2, **({"cursor": cursor} if cursor else {})}
                    page = self.search("robots", **query)
                    seen += [item["id"] for item in page["items"]]
                    cursor = page["next_cursor"]
                    if not cursor:
                        break
                self.assertEqual(sorted(seen), sorted(posts))
                self.assertEqual(len(seen), 5)
                if order == "newest":
                    self.assertEqual(seen, posts)


if __name__ == "__main__":
    unittest.main()
