"""GET /api/search (issues 0040, 0056): real services on the scratch database, over ASGI.

Word forms in English and Russian, phrases, -word, the source's name, each narrowing (scope,
Later, Kept, days), both orders, the snippet and paging. Issue 0056: version names on the index
and the query sides (and the refill of older vectors), stories folded at their best-matching
post, the News and Classics scopes, and their paging. Rows are committed, so the class
only runs against a `_test` database. Every post's title ends in the test's own marker word
and every query names it, so no other row can match.
"""
import json
import random
import string
import sys
import unittest
from unittest import mock
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
from insight_core.tests._db import SCRATCH_PREFIX, db_url, delete_scratch_sources, insert_scratch_source, requires_test_db

FOLDER_PREFIX = "mark-ix-test-folder-"
CLASSIC_PREFIX = "https://test.invalid/mark-ix/classic/"


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

    def test_classics_page_by_offset_and_what_folds(self):
        self.assertEqual(SearchQuery.parse(q="x", filter="classics", cursor="40").offset, 40)
        with self.assertRaises(ValueError):
            SearchQuery.parse(q="x", filter="classics", cursor="garbage")
        folds = {f"{scope}/{filter}": SearchQuery.parse(q="x", scope=scope, filter=filter).folds
                 for scope in (None, "all", f"source:{uuid.uuid4()}") for filter in ("all", "later", "news")}
        self.assertEqual(folds, {
            "None/all": "story", "None/later": None, "None/news": "news",
            "all/all": "story", "all/later": None, "all/news": "news",
            **{k: v for k, v in folds.items() if k.startswith("source:")},
        })
        self.assertEqual([v for k, v in folds.items() if k.startswith("source:")], [None, None, "news"])


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
            cur.execute("DELETE FROM classic_hidden WHERE target_url LIKE %s", (CLASSIC_PREFIX + "%",))
            cur.execute("DELETE FROM classics WHERE target_url LIKE %s", (CLASSIC_PREFIX + "%",))
            delete_scratch_sources(cur)

    def _source(self, *, name: str = "Scratch Source", in_main_digest: bool = False) -> str:
        # A name of its own, never its random scratch address: the name is in each post's vector, and
        # an address's hex can read as more words than another's, so ties would break by it (0129).
        settings = '{"display_name": "%s"}' % name
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
        # The marker makes every query 2+ words, which orders by best match unless asked (issue 0139): newest here.
        status, _, body = call(main.app, "GET", "/api/search", query={"q": f"{self.marker} {q}", "order": "newest", **query})
        self.assertEqual(status, 200, body)
        return body

    def ids(self, q: str, **query) -> list[str]:
        return [item["id"] for item in self.search(q, **query)["items"]]

    # ---- v10.13.6: a pasted address, a slug, a title phrase first ----------------------------------------

    def _addressed(self, source_id: str, url: str, title: str) -> str:
        from insight_core.utils.url_normalization import normalize_url
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO posts (source_id, url, normalized_url, published_at, title, content)"
                        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                        (source_id, url, normalize_url(url), self.now - timedelta(hours=2), f"{title} {self.marker}", "Body."))
            return str(cur.fetchone()[0])

    def raw(self, q: str, **query) -> list[str]:
        status, _, body = call(main.app, "GET", "/api/search", query={"q": q, **query})
        self.assertEqual(status, 200, body)
        return [item["id"] for item in body["items"]]

    def test_a_pasted_address_finds_its_post(self):
        source = self._source()
        slug = f"the-{self.marker}-playbook-guide"
        post = self._addressed(source, f"https://example.test/resources/articles/{slug}", "A playbook")
        self._post(source, "Another post")
        self.assertEqual(self.raw(f"https://example.test/resources/articles/{slug}"), [post])
        self.assertEqual(self.raw(f"https://www.example.test/resources/articles/{slug}/?utm_source=x"), [post])
        self.assertEqual(self.raw(f"example.test/resources/articles/{slug}"), [post])
        self.assertEqual(self.raw(slug), [post])                                  # its slug alone
        self.assertEqual(self.raw("https://example.test/nothing-stored-here-at-all"), [])

    def test_an_address_outside_the_scope_is_not_found(self):
        a, b = self._source(name="Scratch A"), self._source(name="Scratch B")
        url = f"https://example.test/a/{self.marker}-x-y"
        self._addressed(a, url, "A page")
        self.assertEqual(self.raw(url, scope=f"source:{b}"), [])

    def test_best_match_puts_a_title_holding_the_whole_query_first(self):
        source = self._source()
        exact = self._post(source, "The zeta-native widget playbook", "Short.")
        self._post(source, "Notes", "zeta native widget playbook " * 30, hours_ago=0.5)   # more matches, newer
        status, _, body = call(main.app, "GET", "/api/search",
                               query={"q": f"zeta-native widget playbook {self.marker}", "order": "best"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["items"][0]["id"], exact)

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

    # ---- version names (issue 0056) -----------------------------------------------------

    def test_a_version_name_is_found_by_its_parts(self):
        source = self._source()
        kimi = self._post(source, "Introducing Kimi K3.1 Pro", "Moonshot released it today.")
        self._post(source, "Kimi K2 notes", "An older model, 3.0 of something else.")

        for q in ("kimi 3.1", "kimi k3.1", "K3.1", '"kimi 3.1"', '"k3.1 pro"', '"kimi k3.1 pro"'):
            with self.subTest(q=q):
                self.assertEqual(self.ids(q), [kimi])

    def test_a_hyphenated_spaced_or_joined_version_is_found_every_way(self):
        source = self._source()
        hyphen = self._post(source, "GPT-6.1 is out", hours_ago=3)
        spaced = self._post(source, "GPT 6.1 benchmarks", hours_ago=2)
        joined = self._post(source, "Notes on gpt6.1", hours_ago=1)
        self._post(source, "GPT-6 and 1.1 of something")

        for q in ("gpt 6.1", "GPT-6.1", "gpt6.1"):
            with self.subTest(q=q):
                self.assertEqual(self.ids(q), [joined, spaced, hyphen])

    def test_a_suffix_and_a_stop_word_part(self):
        source = self._source()
        qwen = self._post(source, "Qwen3.8-Max lands", hours_ago=2)
        moe = self._post(source, "Running Qwen3.6-35B-A3B at home")

        self.assertEqual(self.ids("qwen 3.8"), [qwen])
        self.assertEqual(self.ids("qwen3.8"), [qwen])
        self.assertEqual(self.ids("qwen 3.6"), [moe])
        self.assertEqual(self.ids("qwen3.6-35b-a3b"), [moe])

    def test_hashes_and_ids_are_not_split(self):
        source = self._source()
        post = self._post(source, "Commit 26b5c67b fixed it", "Build a3f9c2e7 passed.")
        self.assertEqual(self.ids("26b5c67b"), [post])
        self.assertEqual(self.ids("b 5"), [])
        self.assertEqual(self.ids("f 9"), [])

    def test_the_rule_on_the_index_and_the_query(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT w, search_version_parts(w) FROM unnest(%s::text[]) w",
                        (["k3.1", "qwen3.8-max", "-6.1", "claude3", "a100", "26b5c67b", "kimi", "3.1", "x.com/a1"],))
            parts = dict(cur.fetchall())
            cur.execute("SELECT search_query(q)::text FROM unnest(%s::text[]) WITH ORDINALITY u(q, n) ORDER BY n",
                        (["kimi 3.1", "K3.1", '"kimi k3.1 pro"', "GPT-6.1 -qwen3.8"],))
            queries = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT post_search_vector('Kimi K3.1 Pro', '', '')::text")
            vector = cur.fetchone()[0]
        self.assertEqual(parts, {"k3.1": ["k", "3.1"], "qwen3.8-max": ["qwen", "3.8", "max"], "-6.1": ["6.1"],
                                 "claude3": ["claud", "3"], "a100": None, "26b5c67b": None, "kimi": None, "3.1": None,
                                 "x.com/a1": None})
        self.assertEqual(queries, [
            "'kimi' <-> '3.1' | 'kimi' <2> '3.1'",   # a name and its version stand together (v10.13.1, 0095)
            "'k3.1' | 'k' <-> '3.1'",
            "'kimi' <-> 'k3.1' <-> 'pro'",   # a phrase keeps its word: an OR there takes its longest width
            "'gpt' <-> ( '-6.1' | '6.1' ) & !( 'qwen3.8' | 'qwen' <-> '3.8' )",
        ])
        # The parts at the word's place: the last at its position, the first before it.
        self.assertEqual(vector, "'3.1':2A 'k':1A 'k3.1':2A 'kimi':1A 'pro':3A")

    def test_older_vectors_are_refilled_in_the_background(self):
        source = self._source()
        posts = [self._post(source, "Kimi K3.1 Pro") for _ in range(3)]
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            # As 0033 made them: the words alone, no version, no parts.
            cur.execute("UPDATE posts SET search_vector = to_tsvector('russian', title), search_version = NULL"
                        " WHERE id = ANY(%s::uuid[])", (posts,))
        self.assertEqual(self.ids("kimi 3.1"), [])
        self.assertEqual(sorted(self.ids("k3.1")), sorted(posts), "an older vector matches what it did")

        reader = registry.services().reader
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(reader.search_repo.fill_missing_vectors(cur, batch=2), 2)
        self.assertGreaterEqual(reader.fill_search_vectors(), 1)

        self.assertEqual(sorted(self.ids("kimi 3.1")), sorted(posts))
        self.assertEqual(reader.fill_search_vectors(), 0)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT search_version = search_vector_version() FROM posts WHERE id = ANY(%s::uuid[])",
                        (posts,))
            self.assertEqual(cur.fetchall(), [(True,)])

    # ---- stories (issue 0056) -----------------------------------------------------------

    def _story(self, *posts: tuple[str, str]) -> str:
        """A story of (post id, role), keyed by its first post (as 0050 keys it)."""
        story = posts[0][0]
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, now(), %s)", (story, len(posts)))
            for i, (post, role) in enumerate(posts):
                cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice) VALUES (%s, %s, %s, %s)",
                            (post, story, role, f"voice-{i}"))
        return story

    def test_a_story_shows_once_at_its_best_matching_post(self):
        anthropic = self._source(name="Anthropic News", in_main_digest=True)
        simon = self._source(name="Simon Willison", in_main_digest=True)
        channel = self._source(name="data_secrets", in_main_digest=True)
        # The word in the title counts most: the story's best match is Simon's post.
        report = self._post(anthropic, "A new model today", "Today we release Claude Fable 5.2.", hours_ago=5)
        best = self._post(simon, "Claude Fable 5.2", "My notes.", hours_ago=3)
        share = self._post(channel, "Вышла новая модель", "Claude Fable 5.2 от Anthropic.", hours_ago=1)
        alone = self._post(simon, "Another Fable post", "Fable again.", hours_ago=2)
        story = self._story((report, "report"), (best, "report"), (share, "share"))

        for query in ({}, {"scope": "all"}):
            with self.subTest(**query):
                items = self.search("fable", **query)["items"]
                self.assertEqual([i["id"] for i in items], [alone, best])
                lead = items[1]
                self.assertEqual(lead["story"]["id"], story)
                self.assertEqual([p["id"] for p in lead["story"]["posts"]], [report, share])
                self.assertEqual([s["name"] for s in lead["story"]["sources"]],
                                 ["Anthropic News", "Simon Willison", "data_secrets"])
                self.assertIsNone(items[0]["story"])
        self.assertEqual(sorted(self.ids("fable", order="best")), sorted([best, alone]))

    def test_a_tie_goes_to_the_report_then_the_first_posted(self):
        source = self._source()
        share = self._post(source, "Same words here", hours_ago=3)
        first = self._post(source, "Same words here", hours_ago=2)
        second = self._post(source, "Same words here", hours_ago=1)
        self._story((share, "share"), (first, "report"), (second, "report"))
        self.assertEqual(self.ids("same words"), [first])

    def test_only_matching_posts_in_the_scope_and_dates_compete(self):
        inside = self._source(in_main_digest=True)
        outside = self._source(in_main_digest=False)
        # In the title, the word counts most; the two title hits tie, and the first posted leads.
        old_best = self._post(inside, "Robots", "Robots.", hours_ago=24 * 10)
        best_outside = self._post(outside, "Robots", "Robots.", hours_ago=2)
        inside_post = self._post(inside, "A note", "Robots.", hours_ago=1)
        unmatched = self._post(inside, "Unrelated", "Nothing.", hours_ago=24 * 9)
        self._story((old_best, "report"), (best_outside, "report"), (inside_post, "report"), (unmatched, "report"))

        self.assertEqual(self.ids("robots"), [old_best])
        self.assertEqual(self.ids("robots", days=7), [best_outside])
        self.assertEqual(self.ids("robots", scope="all"), [old_best])
        self.assertEqual(self.ids("robots", scope="all", days=7), [inside_post])

    def test_dates_compete_whatever_the_scratch_addresses(self):
        """Issue 0129: the test above failed about 1 run in 15. A scratch address's random hex read
        like `3e4f…` is two lexemes (a number in scientific notation and a word), so that source's
        posts were one lexeme longer and ranked lower: the tie broke by the address, not the date."""
        addresses = iter([f"{SCRATCH_PREFIX}3e4f{uuid.uuid4().hex}", f"{SCRATCH_PREFIX}{uuid.uuid4().hex}"])
        with mock.patch("insight_core.tests._db.scratch_handle", lambda: next(addresses)):
            self.test_only_matching_posts_in_the_scope_and_dates_compete()

    def test_one_source_later_and_kept_show_every_post(self):
        source = self._source()
        a = self._post(source, "Robots", hours_ago=2)
        b = self._post(source, "Robots")
        self._story((a, "report"), (b, "report"))
        call(main.app, "PUT", "/api/feed/later", json_body={"ids": [a, b], "later": True})

        self.assertEqual(self.ids("robots"), [a])
        self.assertEqual(self.ids("robots", scope=f"source:{source}"), [b, a])
        self.assertEqual(self.ids("robots", filter="later"), [b, a])
        self.assertTrue(all(item.get("story") is None for item in self.search("robots", filter="later")["items"]))

    def test_folded_results_page_without_overlap(self):
        source = self._source()
        # The word in a title outranks the word only in the text.
        posts = [self._post(source, "Robots" if n in (0, 2, 3, 6, 7) else "Notes", "robots", hours_ago=n + 1)
                 for n in range(8)]
        self._story((posts[1], "report"), (posts[2], "report"))
        self._story((posts[4], "report"), (posts[5], "share"), (posts[6], "share"))

        for order in ("newest", "best"):
            with self.subTest(order=order):
                seen, cursor = [], None
                while True:
                    page = self.search("robots", order=order, limit=2, **({"cursor": cursor} if cursor else {}))
                    seen += [item["id"] for item in page["items"]]
                    cursor = page["next_cursor"]
                    if not cursor:
                        break
                self.assertEqual(len(seen), len(set(seen)))
                self.assertEqual(sorted(seen), sorted([posts[0], posts[2], posts[3], posts[6], posts[7]]),
                                 "8 posts, two stories of 2 and 3, each at its best match (a title hit)")

    # ---- News and Classics (issue 0056) -------------------------------------------------

    def _news(self, *posts: tuple[str, str], first_at: datetime) -> str:
        news = posts[0][0]
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO news_stories (id, first_at, voices, reports, shares, mentions, score)"
                        " VALUES (%s, %s, %s, %s, %s, 0, 2.5)",
                        (news, first_at, len(posts), sum(r == "report" for _, r in posts),
                         sum(r == "share" for _, r in posts)))
            for i, (post, role) in enumerate(posts):
                cur.execute("INSERT INTO news_posts (post_id, news_id, role, voice) VALUES (%s, %s, %s, %s)",
                            (post, news, role, f"voice-{i}"))
        return news

    def test_news_searches_news_stories_of_any_date(self):
        main_source = self._source(name="Main", in_main_digest=True)
        other = self._source(name="Other", in_main_digest=False)
        old_report = self._post(main_source, "Snap launches glasses", "The Specs.", hours_ago=24 * 60)
        old_best = self._post(other, "Snap Specs: hands on", "Glasses.", hours_ago=24 * 59)
        recent = self._post(main_source, "Specs again", "", hours_ago=2)
        self._post(main_source, "Specs not in News", "", hours_ago=1)
        old_news = self._news((old_report, "report"), (old_best, "report"), first_at=self.now - timedelta(days=60))
        recent_news = self._news((recent, "report"), first_at=self.now - timedelta(hours=2))

        body = self.search("specs", filter="news")
        self.assertEqual([i["id"] for i in body["items"]], [recent, old_best])
        lead = body["items"][1]
        self.assertEqual(lead["story"]["id"], old_news)
        self.assertEqual([p["id"] for p in lead["story"]["posts"]], [old_report])
        self.assertEqual([s["name"] for s in lead["story"]["sources"]], ["Main", "Other"])
        self.assertEqual((lead["news"]["part"], lead["news"]["reports"], lead["news"]["score"]), ("earlier", 2, 2.5))
        self.assertEqual((body["items"][0]["news"]["part"], body["items"][0]["story"]["id"]), ("recent", recent_news))
        # A story with a post in the scope, whichever of its posts matched best.
        self.assertEqual(self.ids("specs", filter="news", scope="all"), [recent, old_best])
        self.assertEqual(self.ids("specs", filter="news", scope=f"source:{other}"), [old_best])
        self.assertEqual(self.ids("specs", filter="news", days=7), [recent])

    def _classic(self, slug: str, title: str | None, *, citers: list[str], days_ago: float = 1,
                 post: str | None = None) -> str:
        url = f"{CLASSIC_PREFIX}{self.marker}/{slug}"
        last_at = self.now - timedelta(days=days_ago)
        cited = [{"voice": f"v{i}", "name": f"Voice {i}", "at": last_at.isoformat(), "source_ids": [sid]}
                 for i, sid in enumerate(citers)]
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            if post:
                cur.execute("UPDATE posts SET normalized_url = %s WHERE id = %s", (url, post))
            cur.execute("INSERT INTO classics (target_url, post_id, voices, first_at, last_at, title, citers)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
                        (url, post, len(citers), last_at - timedelta(days=400), last_at, title, json.dumps(cited)))
        return url

    def classics(self, q: str, **query) -> list[str]:
        body = self.search(q, filter="classics", **query)
        self.assertNotIn("items", body)
        return [c["url"] for c in body["classics"]]

    def test_classics_match_their_title_or_address(self):
        main_source = self._source(in_main_digest=True)
        other = self._source(in_main_digest=False)
        lesson = self._classic("bitter-lesson", "The Bitter Lesson", citers=[main_source, other], days_ago=4)
        by_address = self._classic("leaky-abstractions", "Joel on software", citers=[other], days_ago=2)
        stored_post = self._post(other, "Scaling laws for neural language models")
        stored = self._classic("kaplan", "Kaplan et al.", citers=[main_source], days_ago=1, post=stored_post)
        hidden = self._classic("bitter-again", "The bitter lesson, again", citers=[main_source])
        status, _, _ = call(main.app, "POST", "/api/classics/hide", json_body={"url": hidden})
        self.assertEqual(status, 200)

        self.assertEqual(self.classics("bitter lesson"), [lesson])
        self.assertEqual(self.classics("leaky"), [by_address])
        self.assertEqual(self.classics("scaling"), [stored], "a stored post's title is the classic's")
        self.assertEqual(self.classics("kaplan"), [stored], "and its address")
        self.assertEqual(self.classics(""), [stored, by_address, lesson], "newest: the most recently cited first")
        self.assertEqual(self.classics("", scope="all"), [stored, lesson])
        self.assertEqual(self.classics("", days=3), [stored, by_address])
        (classic,) = self.search("scaling", filter="classics")["classics"]
        self.assertEqual((classic["post_id"], classic["title"], classic["voices"], classic["citers"][0]["name"],
                          classic["days"]),
                         (stored_post, f"Scaling laws for neural language models {self.marker}", 1, "Voice 0", 400))

    def test_a_classic_address_keeps_its_versions(self):
        source = self._source()
        model = self._classic("Qwen/Qwen3.6-35B-A3B", None, citers=[source])
        self._classic("Qwen/Qwen3-6B", None, citers=[source])
        self.assertEqual(self.classics("qwen 3.6"), [model])
        self.assertEqual(self.classics("qwen3.6"), [model])

    def test_classics_page_by_offset_in_both_orders(self):
        source = self._source()
        made = [self._classic(f"page-{n}", f"Page {n}", citers=[source], days_ago=n) for n in range(1, 6)]
        for order in ("newest", "best"):
            with self.subTest(order=order):
                seen, cursor = [], None
                while True:
                    body = self.search("page", filter="classics", order=order, limit=2,
                                       **({"cursor": cursor} if cursor else {}))
                    seen += [c["url"] for c in body["classics"]]
                    cursor = body["next_cursor"]
                    if not cursor:
                        break
                self.assertEqual(sorted(seen), sorted(made))
                if order == "newest":
                    self.assertEqual(seen, made)


if __name__ == "__main__":
    unittest.main()
