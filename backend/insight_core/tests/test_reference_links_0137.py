"""Issue 0137 B8 (N13): a full text's reference list is kept as references, not as ordinary links.

- `extract_links`: the links inside a references or bibliography section (a heading so named, or an
  <ol>/<section>/<div> whose class or id says so) are `kind='reference'`; search-engine links are dropped;
- on the database: they are stored with kind 'reference' and as boilerplate (no story, News or Discover rule
  reads them), the signature pass keeps them so, and Connected lists them folded under `references`.
Invented hosts only.
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

from insight_core.db.repo_post_refs import PostRefsRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.tests._db import db_url, insert_scratch_source, requires_db
from insight_core.utils.post_links import extract_links, is_search_link, reference_spans
from insight_core.utils.url_normalization import normalize_url

POST = "https://journal.example/articles/s41-sleep-and-memory"


def kinds(html, url=POST):
    return [(link.url, link.kind) for link in extract_links(html, url, "site")]


ARTICLE = (
    '<p>Sleep matters, as <a href="https://news.example/2026/11/sleep-study">a report</a> said.</p>'
    '<h2>Methods</h2><p>See <a href="https://data.example/sets/sleep-2026">the data</a>.</p>'
    '<h2>References</h2><ol>'
    '<li>A. Author. Sleep. <a href="https://doi.example/10.1000/sleep.1">doi</a> '
    '<a href="https://scholar.google.example/scholar_lookup?title=Sleep">Google Scholar</a></li>'
    '<li>B. Author. Memory. <a href="https://pubmed.example/?term=memory+sleep">PubMed</a> '
    '<a href="https://papers.example/memory-and-sleep-2025">paper</a></li></ol>'
    '<h2>Acknowledgements</h2><p>Thanks to <a href="https://lab.example/people">the lab</a>.</p>')


class ReferenceSectionTests(unittest.TestCase):
    def test_links_under_a_references_heading_are_references_until_the_next_heading(self):
        self.assertEqual(kinds(ARTICLE), [
            ("https://news.example/2026/11/sleep-study", "link"),
            ("https://data.example/sets/sleep-2026", "link"),
            ("https://doi.example/10.1000/sleep.1", "reference"),
            ("https://papers.example/memory-and-sleep-2025", "reference"),
            ("https://lab.example/people", "link"),
        ])

    def test_positions_stay_in_text_order(self):
        self.assertEqual([link.position for link in extract_links(ARTICLE, POST, "site")], [0, 1, 2, 3, 4])

    def test_heading_words_numbered_or_in_russian_or_bibliography(self):
        for heading in ("7. References", "Bibliography", "Works cited", "Literature", "Notes and references:",
                        "Список литературы", "REFERENCES"):
            html = f'<h3>{heading}</h3><p><a href="https://cited.example/a-paper-on-sleep">x</a></p>'
            self.assertEqual(kinds(html), [("https://cited.example/a-paper-on-sleep", "reference")], heading)

    def test_a_list_or_section_whose_class_or_id_says_references(self):
        html = ('<p><a href="https://before.example/x-y-z-w">before</a></p>'
                '<section class="c-article-references" id="Bib1"><div><ol>'
                '<li><a href="https://cited.example/one">one</a></li></ol></div>'
                '<p><a href="https://cited.example/two">two</a></p></section>'
                '<p><a href="https://after.example/x-y-z-w">after</a></p>'
                '<ol id="citations"><li><a href="https://cited.example/three">three</a></li></ol>')
        self.assertEqual(kinds(html), [("https://before.example/x-y-z-w", "link"), ("https://cited.example/one", "reference"),
                                       ("https://cited.example/two", "reference"), ("https://after.example/x-y-z-w", "link"),
                                       ("https://cited.example/three", "reference")])

    def test_a_heading_that_only_mentions_references_is_not_one(self):
        html = '<h2>References to sleep in the press</h2><p><a href="https://press.example/a-b-c-d">x</a></p>'
        self.assertEqual(kinds(html), [("https://press.example/a-b-c-d", "link")])
        self.assertEqual(reference_spans("<p>no sections</p>"), [])

    def test_a_link_in_a_reference_and_in_the_text_is_a_link(self):
        html = ('<p>As <a href="https://papers.example/memory-and-sleep-2025">this paper</a> shows.</p>'
                '<h2>References</h2><p><a href="https://papers.example/memory-and-sleep-2025">paper</a></p>')
        self.assertEqual(kinds(html), [("https://papers.example/memory-and-sleep-2025", "link")])


class SearchLinkTests(unittest.TestCase):
    def test_search_engine_and_search_page_links_are_dropped_anywhere(self):
        for url in ("https://scholar.google.example/scholar?q=sleep", "https://scholar.example/citations?user=x",
                    "https://www.google.example/search?q=sleep+memory", "https://pubmed.example/?term=sleep",
                    "https://site.example/search?q=sleep", "https://site.example/search/results?query=sleep"):
            self.assertTrue(is_search_link(url), url)
            self.assertEqual(kinds(f'<p><a href="{url}">x</a></p>'), [], url)

    def test_ordinary_links_with_a_query_are_kept(self):
        for url in ("https://site.example/article?id=12", "https://video.example/watch?v=abc",
                    "https://site.example/search-for-meaning-essay", "https://site.example/research/sleep"):
            self.assertFalse(is_search_link(url), url)


@requires_db
class StoredReferencesTests(unittest.TestCase):
    """Saved, a reference is a post_links row of kind 'reference', boilerplate: no story reads it; Connected folds them."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.mark = uuid.uuid4().hex[:8]
        self.source = insert_scratch_source(self.cur)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _post(self, html, url=None):
        url = url or f"https://{self.mark}.test/{uuid.uuid4().hex}"
        self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, title, content, content_html, published_at)
                            VALUES (%s, %s, %s, 'A paper', 'words', %s, %s) RETURNING id""",
                         (self.source, url, normalize_url(url), html, datetime.now(timezone.utc) - timedelta(days=1)))
        post = str(self.cur.fetchone()[0])
        StoriesRepository().save_post_links(self.cur, post)
        return post

    def _rows(self, post):
        self.cur.execute("SELECT target_url, kind, boilerplate FROM post_links WHERE post_id = %s ORDER BY position", (post,))
        return self.cur.fetchall()

    def test_stored_with_their_kind_and_never_read_as_ordinary_links(self):
        post = self._post(ARTICLE)
        rows = self._rows(post)
        self.assertEqual([(url, kind, boiler) for url, kind, boiler in rows if kind == "reference"],
                         [("https://doi.example/10.1000/sleep.1", "reference", True),
                          ("https://papers.example/memory-and-sleep-2025", "reference", True)])
        self.assertEqual({boiler for _, kind, boiler in rows if kind == "link"}, {False})
        # The signature pass leaves a reference boilerplate.
        StoriesRepository.mark_boilerplate(self.cur, SourceFacts(self.cur), [self.source])
        self.assertEqual({boiler for _, kind, boiler in self._rows(post) if kind == "reference"}, {True})

    def test_connected_lists_references_folded_not_as_outside_rows(self):
        post = self._post(ARTICLE)
        found = PostRefsRepository.connected(self.cur, post)
        self.assertNotIn("https://doi.example/10.1000/sleep.1", [r.get("address") for r in found["outside"]])
        self.assertEqual([(r["url"], r["host"]) for r in found["references"]],
                         [("https://doi.example/10.1000/sleep.1", "doi.example"),
                          ("https://papers.example/memory-and-sleep-2025", "papers.example")])

    def test_a_post_with_no_references_has_none(self):
        post = self._post('<p><a href="https://news.example/2026/11/a-b-c">x</a></p>')
        self.assertEqual(PostRefsRepository.connected(self.cur, post)["references"], [])


if __name__ == "__main__":
    unittest.main()
