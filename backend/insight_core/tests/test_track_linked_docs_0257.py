"""A track post's questions also show the stored pages it links on its own site (0257), so a terse release note's
fields may be quoted from the page it links; the value names the page. Covers `maker_page`, `page_window`, the post's
own questions unchanged with or without pages (at most LINKED_DOCS more within MAX_WINDOWS), salvage (a quote must
be in what the question showed; the post's own address is never offered), and the switch off (tracks.linked_docs).
Invented names; DB tests on a _test database."""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from insight_core.markx import identity, tasks, track_things as TT
from insight_core.tests.test_track_briefer_0245 import TRACKS, _Briefer, things_input, v

SCHEMA = TRACKS["setups"][1]
DOCS = "https://docs.zq-maker.example/features#fast-decode"
PAGE_TEXT = ("Features. Quiet mode: fans stay below 30 dB. " * 40
             + "Fast decode: on two used 24 GB cards it reaches 40 tok/s with llama.cpp. " + "More features follow. " * 40)


def post(title, text, links=()):
    return tasks.Post(id=str(uuid.uuid4()), kind="site", source="Zq", source_id="s", at=datetime.now(timezone.utc),
                      title=title, text=text, links=list(links))


TRACK = {"folder_id": "t", "name": "T", "description": "b", "excludes": None}


class Pure(unittest.TestCase):
    def test_the_makers_page(self):
        own = "https://zq-maker.example/releases#2026"
        self.assertTrue(TT.maker_page(own, "https://docs.zq-maker.example/features#a"), "a subdomain of its site")
        self.assertTrue(TT.maker_page(own, "https://www.zq-maker.example/faq"))
        self.assertFalse(TT.maker_page(own, "https://zq-other.example/features"))
        self.assertFalse(TT.maker_page("", "https://zq-maker.example/faq"), "no own address: none")
        code = "https://github.com/zqacme/zqtool/releases/tag/v2"
        self.assertTrue(TT.maker_page(code, "https://github.com/zqacme/zqtool/blob/main/docs/usage.md"))
        self.assertFalse(TT.maker_page(code, "https://github.com/zqother/lib"), "another account on a code host")
        self.assertFalse(TT.maker_page("https://reddit.com/r/zqa/comments/1", "https://reddit.com/r/zqb/comments/2"))

    def test_the_part_of_the_page_its_anchor_names(self):
        start, end = TT.page_window(PAGE_TEXT, DOCS)
        self.assertIn("Fast decode: on two used 24 GB cards", PAGE_TEXT[start:end])
        self.assertLessEqual(end - start, TT.WINDOW_CHARS)
        self.assertEqual(TT.page_window(PAGE_TEXT, "https://zq-maker.example/features")[0], 0)
        self.assertEqual(TT.page_window(PAGE_TEXT, "https://zq-maker.example/features#comments")[0], 0)
        self.assertEqual(TT.page_window(PAGE_TEXT, "https://zq-maker.example/features#nowhere-here")[0], 0)

    def test_the_posts_own_questions_are_unchanged(self):
        own = ["https://zq-maker.example/releases#2026"]
        page = post("Features", PAGE_TEXT + " Back to https://zq-maker.example/releases#2026")
        for text in ("Adds fast decode. https://zq-maker.example/releases#2026 " + DOCS,
                     "A long release. " * 700 + DOCS):
            p = post("Release 2026", text, links=[("https://zq-files.example/f", "files")])
            plain = TT.things_inputs(TRACK, SCHEMA, 1, p, own)
            got = TT.things_inputs(TRACK, SCHEMA, 1, p, own, [(DOCS, page), (DOCS, page), (DOCS, page)])
            self.assertEqual(got[:len(plain)], plain, "the post's own questions, byte for byte")
            self.assertEqual(len(got) - len(plain), min(TT.LINKED_DOCS, TT.MAX_WINDOWS - len(plain)))
            self.assertLessEqual(len(got), TT.MAX_WINDOWS)
            for q in got:
                self.assertNotIn(own[0], q, "the post's own address is never offered")
        short = TT.things_inputs(TRACK, SCHEMA, 1, post("R", "Adds fast decode. " + DOCS), own, [(DOCS, page)])
        self.assertEqual(len(short), 2)
        self.assertIn("\nWindow: 2 of 2 ", short[1])
        self.assertEqual(tasks.window_of(short[1]), 1)
        self.assertIn("\nLinked page on the post's own site: " + DOCS + "\nPage title: Features\nPage text: […] ",
                      short[1])
        self.assertIn("Fast decode: on two used 24 GB cards", short[1])

    def test_a_value_quoted_from_the_page_names_it(self):
        page = post("Features", PAGE_TEXT)
        q = TT.things_inputs(TRACK, SCHEMA, 1, post("Release 2", "Adds fast decode."), [], [(DOCS, page)])[1]
        answer = {"id": "x", "things": [{"kind": "setup", "fields": {
            "hardware": v("two used 24 GB cards", "on two used 24 GB cards"),
            "speed": v({"number": 40, "unit": "tok/s"}, "it reaches 40 tok/s"),
            "engine": v("llama.cpp", "40 tok/s with llama.cpp"),
            "cost": v({"number": 900, "currency": "USD"}, "about $900"),
            "page": v(DOCS, DOCS)}}]}
        got = TT.salvage(answer, q)
        fields = got["things"][0]["fields"]
        self.assertEqual(set(fields), {"hardware", "speed", "engine", "page"})
        self.assertEqual({k: f.get("page") for k, f in fields.items()},
                         {"hardware": DOCS, "speed": DOCS, "engine": DOCS, "page": DOCS})
        self.assertEqual([d["why"] for d in got["dropped"]], ["things[0].cost: quote not in the post"])
        self.assertEqual(TT.salvage(got, q)["things"], got["things"], "idempotent")
        # a quote the post itself holds names no page; a question with no page is checked as before
        fields = TT.salvage({"things": [{"kind": "setup", "fields": {"hardware": v("fast decode", "Adds fast decode")}}]},
                            q)["things"][0]["fields"]
        self.assertNotIn("page", fields["hardware"])
        plain = things_input(SCHEMA, "Two used 24 GB cards.")
        self.assertNotIn("page", TT.salvage({"things": [{"kind": "setup", "fields": {
            "hardware": v("two cards", "Two used 24 GB cards")}}]}, plain)["things"][0]["fields"]["hardware"])


class Flow(_Briefer):
    def linked(self, on):
        bands = identity.bands()
        was = dict(bands["tracks"])
        bands["tracks"]["linked_docs"] = on
        self.addCleanup(bands.__setitem__, "tracks", was)

    def page(self, url, title, text):
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, now()) RETURNING id::text",
                         (self.source, url, url, title, text))
        return self.cur.fetchone()[0]

    def release(self, f):
        p = self.in_track(f, "Release 2026", f"Adds fast decode. See {DOCS} and https://zq-other.example/stored")
        own = "https://zq-maker.example/releases#2026"
        self.cur.execute("UPDATE posts SET url = %s, normalized_url = %s WHERE id = %s", (own, own, p))
        for n, (addr, href) in enumerate([("https://docs.zq-maker.example/features", DOCS),
                                          ("https://zq-other.example/stored", "https://zq-other.example/stored"),
                                          ("https://zq-maker.example/unstored", "https://zq-maker.example/unstored"),
                                          ("https://zq-maker.example/releases", own)]):
            self.cur.execute("INSERT INTO post_refs (post_id, target_address, href, position) VALUES (%s, %s, %s, %s)",
                             (p, addr, href, n))
        self.page("https://docs.zq-maker.example/features", "Features", PAGE_TEXT)
        self.page("https://zq-other.example/stored", "Elsewhere", "Another site's page, 99 tok/s on one card. " * 5)
        return p

    def test_a_release_read_with_its_makers_docs(self):
        f = self.track("setups")
        self.schema(f, "setups")
        p = self.release(f)
        self.run_planner("track_things")
        rows = [r for r in self.open_tasks("track_things") if r[1] == p]
        self.assertEqual(len(rows), 2, "the post, then its maker's one stored page (not another site's, not unstored)")
        rows.sort(key=lambda r: "Linked page" in r[3])   # one transaction: same created_at, so pick each by content
        post_q, page_q = rows[0][3], rows[1][3]
        self.assertNotIn("Linked page", post_q)
        self.assertIn("Linked page on the post's own site: " + DOCS, page_q)
        self.assertNotIn("99 tok/s", page_q)
        self.assertNotIn("https://zq-maker.example/releases#2026", page_q, "the post's own address never offered")
        status, body = self.answer((rows[1][0], {"id": "x", "things": [{"kind": "setup", "fields": {
            "hardware": v("two used 24 GB cards", "on two used 24 GB cards"),
            "speed": v({"number": 40, "unit": "tok/s"}, "it reaches 40 tok/s"),
            "cost": v({"number": 99, "currency": "USD"}, "$99 on one card")}}]}))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        (row,) = TT.current(self.cur, f, "setup")
        self.assertEqual(row["fields"]["speed"]["page"], DOCS)
        self.assertEqual(row["fields"]["speed"]["post"], p)
        self.assertNotIn("cost", row["fields"], "a quote the question did not show is dropped")
        (report,) = TT.reports(self.cur, f)[row["id"]]
        self.assertEqual(report["values"]["hardware"]["page"], DOCS)
        from insight_core.markx import track_brief as TB
        kinds = {k["kind"]: k for k in TT.current_schema(self.cur, f)["schema"]["kinds"]}
        view = TB.thing_view(kinds["setup"], row, [report], {})
        self.assertEqual(view["fields"]["speed"]["page"], DOCS)

    def test_off_only_the_posts_own_questions(self):
        self.linked(False)
        f = self.track("setups")
        self.schema(f, "setups")
        p = self.release(f)
        self.run_planner("track_things")
        rows = [r for r in self.open_tasks("track_things") if r[1] == p]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("Linked page", rows[0][3])


if __name__ == "__main__":
    unittest.main()
