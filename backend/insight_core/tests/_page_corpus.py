"""The corpus of real article pages (issue 0032): what the shared reader must make of each.

fixtures/pages/<name>.html is a real page, fetched once and trimmed of <script>, <style>,
<noscript>, <svg> and inline base64 blobs (the reader drops those itself); the rest is
verbatim (gwern_spaced_repetition is also cut to some of its sections and its first ten
footnotes, 107 KB of 370). fixtures/pages/expectations.json says, per page:

  url, fetched     where and when it was fetched
  title            page_watch's page_title for the page
  first, last      text found in the first / last EDGE_CHARS characters of the kept text
                   (a title, byline or date may come before the first sentence; chrome may not)
  images           the article's own images, counted by hand on the page: its figures and
                   inline images, its cover when the cover sits inside the article element;
                   never related cards, sidebars, avatars, logos or icons
  must_not         words of the page's chrome (menus, share bars, "Related", newsletter boxes)
  contains         optional: text that must be kept (a code block)
  tables           the article's data tables, each as its number of cells (th and td); none
                   when absent (issue 0042: a table is kept as a table, not loose paragraphs)
  figures          [figures kept, of them with a caption]; [0, 0] when absent
Every page is also checked never to end on a heading (heading_last): a section title whose
content a script fills in is no part of the article.
  known_gaps       optional: {expectation: why the reader misses it}. A known gap must still
                   fail: when the reader starts meeting it, the corpus test says so, and the
                   gap is removed rather than left to hide a regression.

Used by test_page_corpus and the owner-run scripts/refresh_page_corpus.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from insight_core.ingestion.kinds import page_watch, parsing

PAGES_DIR = Path(__file__).resolve().parent / "fixtures" / "pages"
EXPECTATIONS_FILE = PAGES_DIR / "expectations.json"
EDGE_CHARS = 400
CHECKS = ("title", "first", "last", "images", "must_not", "contains", "tables", "figures", "heading_last")


TRIMMED_RE = re.compile(r"(?is)<(script|style|noscript|svg)\b.*?</\1\s*>")
BASE64_RE = re.compile(r"data:[a-z0-9.+/-]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE)


def trim(page: str) -> str:
    """A fetched page as the corpus keeps it: no scripts, styles, noscript, svg or inline
    base64 blobs (the reader drops them all); the rest verbatim."""
    return BASE64_RE.sub("data:,", TRIMMED_RE.sub("", page))


def load_expectations() -> Dict[str, Dict[str, Any]]:
    return json.loads(EXPECTATIONS_FILE.read_text(encoding="utf-8"))


def page_html(name: str) -> str:
    return (PAGES_DIR / f"{name}.html").read_text(encoding="utf-8")


def read(page: str, url: str) -> Dict[str, Any]:
    """What the reader keeps of a page: its title, normalised text, image count, tables (their
    cell counts), figures ([kept, with a caption]) and whether its last block is a heading."""
    html = parsing.extract_article_html(page, base_url=url)
    figures = re.findall(r"(?is)<figure>.*?</figure>", html)
    return {
        "title": page_watch.page_title(page, url),
        "text": " ".join(parsing.strip_html(html).split()),
        "images": len(re.findall(r"<img\b", html)),
        "tables": [len(re.findall(r"(?i)<t[dh]\b", table)) for table in re.findall(r"(?is)<table>.*?</table>", html)],
        "figures": [len(figures), sum("<figcaption>" in figure for figure in figures)],
        "heading_last": bool(re.match(r"(?i)<h[1-6]\b", html.strip().split("\n")[-1])),
    }


def problems(expected: Dict[str, Any], kept: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """{check: None when met, else what was found}, for every check the page has."""
    text = kept["text"]
    found: Dict[str, Optional[str]] = {}
    if "title" in expected:
        found["title"] = None if kept["title"] == expected["title"] else f"title is {kept['title']!r}"
    if "first" in expected:
        found["first"] = (None if expected["first"] in text[:EDGE_CHARS]
                          else f"text starts {text[:160]!r}")
    if "last" in expected:
        found["last"] = (None if expected["last"] in text[-EDGE_CHARS:]
                         else f"text ends {text[-160:]!r}")
    if "images" in expected:
        found["images"] = (None if kept["images"] == expected["images"]
                           else f"{kept['images']} images kept, {expected['images']} expected")
    if "must_not" in expected:
        present = [word for word in expected["must_not"] if word in text]
        found["must_not"] = f"chrome kept: {present}" if present else None
    if "contains" in expected:
        missing = [word for word in expected["contains"] if word not in text]
        found["contains"] = f"missing: {missing}" if missing else None
    tables = expected.get("tables", [])
    found["tables"] = None if kept["tables"] == tables else f"tables of {kept['tables']} cells kept, {tables} expected"
    figures = expected.get("figures", [0, 0])
    found["figures"] = (None if kept["figures"] == figures
                        else f"{kept['figures']} figures (kept, with a caption), {figures} expected")
    found["heading_last"] = "the article ends on a heading" if kept["heading_last"] else None
    return found
