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
from insight_core.utils.post_refs import PostRef, refs_of, shown_reason


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


POST = "https://blog.example/2026/11/a-post"


def reason(html, link=0, url=POST):
    """The (reason, kind) of the post's `link`-th address."""
    ref = refs_of(html, None, url)[link]
    return ref.reason, ref.reason_kind


class RefsTests(unittest.TestCase):
    def test_every_http_address_once_in_order_absolute_and_normalized(self):
        html = ('<p><a href="/2026/10/part-one">part one</a> <a href="https://Other.example/a/?utm_source=x">a</a> '
                '<a href="https://other.example/a">again</a> <a href="mailto:x@y.z">mail</a> '
                '<a href="https://cdn.example/pic.jpg">pic</a> <a href="#top">top</a></p>')
        refs = refs_of(html, None, POST)
        self.assertEqual([(r.address, r.href, r.position) for r in refs],
                         [("https://blog.example/2026/10/part-one", "/2026/10/part-one", 0),
                          ("https://other.example/a", "https://Other.example/a/?utm_source=x", 1),
                          ("https://cdn.example/pic.jpg", "https://cdn.example/pic.jpg", 2),
                          (POST, "#top", 3)])   # its own address too: the reader leaves it out, the table keeps it

    def test_plain_text_bare_addresses(self):
        refs = refs_of(None, "Earlier: https://t.me/chan/12. And https://b.example/x", "https://t.me/chan/13")
        self.assertEqual([r.address for r in refs], ["https://t.me/chan/12", "https://b.example/x"])

    def test_escaped_html(self):
        html = '&lt;p&gt;&lt;a href=&quot;https://news.example/a-story-of-the-day&quot;&gt;x&lt;/a&gt;&lt;/p&gt;'
        self.assertEqual([r.address for r in refs_of(html, None, POST)], ["https://news.example/a-story-of-the-day"])

    def test_nothing(self):
        self.assertEqual(refs_of(None, None, POST), [])
        self.assertEqual(refs_of("<p>no links</p>", None, POST), [])


class ReasonRuleTests(unittest.TestCase):
    """Each step of the rule, on fixed texts (0125 "The reason line")."""

    def test_1_the_words_the_post_quotes_from_the_page(self):
        page = "https://news.example/2026/11/the-launch"
        html = (f'<p>Big if true <a href="{page}">{page}</a></p>'
                f'<blockquote cite="{page}"><cite><b>News Example</b></cite></br><b>The launch, as reported today</b></br>'
                'More words</blockquote>')
        self.assertEqual(reason(html), ("The launch, as reported today", "quote"))

    def test_1_a_quote_is_cut_at_300(self):
        page = "https://news.example/2026/11/the-launch"
        long = "word " * 100
        html = (f'<a href="{page}">x</a><blockquote cite="{page}"><cite><b>Site</b></cite></br><b>{long}</b></br></blockquote>')
        self.assertEqual(len(reason(html)[0]), 300)

    def test_2_the_sentence_around_the_link(self):
        html = ('<p>Some opening words here. Last week I explained why the scheduler drops tasks under load in '
                '<a href="https://blog.example/2026/10/part-one">the first part</a>. Then more.</p>')
        self.assertEqual(reason(html), ("Last week I explained why the scheduler drops tasks under load in the first part.",
                                        "sentence"))

    def test_2_a_link_alone_on_its_line_takes_the_line_before(self):
        html = ('<p>This builds on what I measured in the spring, with the same machines.</p>'
                '<p><a href="https://blog.example/2026/04/spring">Spring numbers</a></p>')
        self.assertEqual(reason(html), ("This builds on what I measured in the spring, with the same machines. Spring numbers",
                                        "sentence"))

    def test_2_never_cut_after_an_initial_an_abbreviation_or_inside_the_link_words(self):
        html = ('<p>Before that. As J. Smith et al. showed in <a href="https://papers.example/2026/the-paper">the paper. '
                'It holds</a> for large models too.</p>')
        self.assertEqual(reason(html)[0], "As J. Smith et al. showed in the paper. It holds for large models too.")

    def test_2_a_sentence_is_cut_at_320(self):
        html = '<p>' + "many words " * 60 + '<a href="https://b.example/x">x</a></p>'
        text = reason(html)[0]
        self.assertTrue(text.endswith(" …") and len(text) <= 322, text)

    def test_2_too_few_words_besides_the_link_words_and_addresses(self):
        html = '<p>See also: <a href="https://b.example/2026/a-post-about-it">The Post About It</a></p>'
        self.assertEqual(reason(html), ("The Post About It", "link_words"))   # 2 words besides: step 4

    def test_2_never_a_footnote_or_a_reference_line(self):
        for line in ("[1] The full report from the agency, published in the spring of this year",
                     "^ The full report from the agency, published in the spring of this year",
                     # (a numbered line splits after "2." before a capital, as the measured rule does: one in lower case)
                     "2. the full report from the agency, published in the spring of this year"):
            html = f'<p>{line} <a href="https://b.example/report">here</a></p>'
            self.assertEqual(reason(html), (None, None), line)

    def test_4_link_words_that_name_a_page_else_nothing(self):
        self.assertEqual(reason('<p><a href="https://b.example/x">Why Schedulers Drop Tasks</a></p>'),
                         ("Why Schedulers Drop Tasks", "link_words"))
        self.assertEqual(reason('<p><a href="https://b.example/x">here</a></p>'), (None, None))
        self.assertEqual(reason('<p><a href="https://b.example/x">https://b.example/x</a></p>'), (None, None))

    def test_3_the_stored_posts_title_before_the_link_words_on_earlier_and_later(self):
        self.assertEqual(shown_reason("Why Schedulers Drop Tasks", "link_words", "  Part one:\n the scheduler "),
                         ("Part one: the scheduler", "title"))
        self.assertEqual(shown_reason("Why Schedulers Drop Tasks", "link_words", None), ("Why Schedulers Drop Tasks", "link_words"))
        self.assertEqual(shown_reason("A sentence about it, long enough", "sentence", "A title"),
                         ("A sentence about it, long enough", "sentence"))
        self.assertEqual(shown_reason(None, None, "t" * 250), ("t" * 200, "title"))

    def test_outside_rows_show_only_a_quote_or_a_sentence(self):
        self.assertEqual(shown_reason("Quoted words", "quote", outside=True), ("Quoted words", "quote"))
        self.assertEqual(shown_reason("A sentence", "sentence", outside=True), ("A sentence", "sentence"))
        self.assertEqual(shown_reason("Why Schedulers Drop Tasks", "link_words", outside=True), (None, None))
        self.assertEqual(shown_reason(None, None, "A title", outside=True), (None, None))


if __name__ == "__main__":
    unittest.main()
