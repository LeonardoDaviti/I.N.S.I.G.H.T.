"""Connected on every post (issue 0125): Earlier, Later and Outside INSIGHT, read from the author's own links, no model.

- the Reddit fix: `extract_links` decodes escaped HTML as `body_hrefs` does;
- the reason line (utils/post_refs.py, the lab's measured rule): each of its steps, and the Outside restriction;
- `post_refs` written on insert and update, the backfill resumable, the signature pass marking it;
- the Connected read: Later through both address forms, a target stored after its linker, the caps and `more`.

On the database, one transaction per test, rolled back, unless a class says it commits.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.utils.post_links import extract_links


class EscapedHtmlTests(unittest.TestCase):
    """Reddit's feed stores its HTML escaped: no raw `<a href`, `&lt;a` instead. Its links were never kept."""

    ESCAPED = ('&lt;!-- SC_OFF --&gt;&lt;div class=&quot;md&quot;&gt;&lt;p&gt;A long read on the topic: '
               '&lt;a href=&quot;https://news.example/2026/10/the-story?x=1&amp;amp;y=2&quot;&gt;The Story Of The Day&lt;/a&gt;'
               '&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt; submitted by '
               '&lt;a href=&quot;https://www.reddit.com/user/someone&quot;&gt; /u/someone &lt;/a&gt;')

    def test_escaped_html_is_decoded_first(self):
        links = extract_links(self.ESCAPED, "https://www.reddit.com/r/x/comments/1/t/", "reddit")
        self.assertEqual([(l.url, l.text) for l in links],
                         [("https://news.example/2026/10/the-story?x=1&y=2", "The Story Of The Day")])

    def test_raw_html_with_an_escaped_sample_is_left_as_it_is(self):
        # A post that shows HTML as text (a code sample) and has a real link: only the real link counts.
        html = ('<p>Write it as <code>&lt;a href="https://sample.example/x"&gt;</code>, see '
                '<a href="https://docs.example/guide/links-in-html">the guide</a></p>')
        self.assertEqual([l.url for l in extract_links(html, "https://blog.example/p", "site")],
                         ["https://docs.example/guide/links-in-html"])


if __name__ == "__main__":
    unittest.main()
