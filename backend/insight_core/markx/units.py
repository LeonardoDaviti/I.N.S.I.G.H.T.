"""Units (issue 0181): a round-up's items, each one unit, attached to the stored posts and stories they carry.

A round-up (a daily digest, a link list, a long newsletter) carries many items. As a whole it is never compared
(Pairing's unit rule) and never a voice; before this module its items were invisible to stories. Here a round-up is
tagged, split into its items, and each item is attached (Pairing's `attach` relation) to the stored post it links:
the post, and the story holding it, show "also in round-ups"; the digest (`digest`) ranks what round-ups carry by
how many separate round-up sources carry it. A unit is NEVER a voice: nothing here writes a table a voice, a News
count or a corroboration is read from (tests/test_markx_units.py checks every consumer).

The interface (what a caller must know):
  - `Unit` = (post, n, span, links, text, at): the n-th item of a round-up post (1-based), its span in the text the
    splitter read (character offsets), the pages it links (normalized, in order), its words, its time (the stored
    post it attaches to, else the issue's time).
  - `split(html, text, url, reading, skip)` -> `Split` (pure): what the reading says, the digest shape, the items.
  - `note(cur, post_ids)`: split the posts now and store what changed (a reading landed: tasks.record; a new post).
  - `tag(cur, sources)`: the round-up tags of these sources' posts made current (a digest source's shaped posts).
  - `backfill(cur)`: one resumable step of the candidates job: posts never split by this code, newest first, bounded;
    then the attach of the recent round-ups again (a cited post stored after its digest).
  - `also_in(cur, post_ids)` / `also_in_story(cur, story_id)`: the round-ups carrying these posts (a story's line).
  - `digest(cur, span, until)`: INSIGHT's own round-up of a day or a week (read on request; no job writes it).

The splitter adapters (each reads the post's HTML as the reader renders it; the finest split is used). No item links
the post's own page (a table of contents) or its source's signature (post_links.boilerplate):
  - `list`: each list item (<li>) carrying a link of its own is an item; a list item with no link is in the nearest
    item around it, or right after an item, its detail. A heading ends every list left open (digests leave <li> and
    <ul> unclosed: each next topic would else nest under the last).
  - `sections`: headed sections (<h1>-<h6>) carrying a link.
  - `lines`: paragraphs or lines (<p>, <br>): when bullets ("-", "—", "•", "1.") open half the lines that link, a
    bulleted line starts an item and the lines after it continue it; else each line carrying a link is an item.
  - `reading`: a round-up the reading names (read-v2 kind `roundup`) whose HTML gives too few items: the reading's own
    items (headline and link), each placed on the line that links it when one does.

The tag. A post is a round-up when its reading says so (and it splits into MIN_ITEMS+ items); or when it has a digest's
shape (STRUCTURE_ITEMS+ list items, sections or bulleted lines carrying links to STRUCTURE_PAGES+ pages, holding
ITEMS_SHARE of its words), its reading did not see it whole (a read task shows READ_SEEN characters: a daily digest's
reading saw only its first story) and its source is a digest source (more than DIGEST_SHARE of its posts have the
shape: an essayist's post with a list of links has it too). Paragraphs that link are never a shape. Measured in
plan/research/roundups-1016 (private).

Stored (migration 0123): `mx_roundups` (a post's tag and issue time, one row a post this code looked at, kept
current), `mx_units` (the items of each split, appended when a split's inputs change: a new reading, a new text, new
code; the post's current basis is mx_roundups.basis) and `mx_attach` (unit -> stored post, once per source; never
deleted). Nothing here rewrites a post or deletes a row.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

UNITS_VERSION = "units-v1"     # bump with a change to what a split is made of outside this module
READING_GUIDE = "read-v2"
MIN_ITEMS = 2                  # a split of fewer items is no split (a reading's round-up of one item is a post)
STRUCTURE_ITEMS = 5            # a round-up by its structure: this many linked items ...
STRUCTURE_PAGES = 4            # ... linking this many distinct pages ...
ITEMS_SHARE = 0.5              # ... holding this share of the post's words
READ_SEEN = 1500               # a read task shows a post's first 1,500 characters (tasks.TEXT_CHARS): within it the
                               # reading saw the whole post and decides alone
TEXT_MAX = 1200                # an item's words kept (characters)
LINKS_MAX = 20                 # an item's links kept
BACKFILL_PAGE = 1000           # posts never split by this code, a candidates run, newest first
RECHECK = timedelta(days=3)    # the round-ups of the last days are attached again each run (cited posts arrive late)
RECHECK_PAGE = 500
DIGEST_SHARE = 0.5             # a digest source: more than half of its split posts ...
DIGEST_WORDS = 150             # ... of this many words ...
DIGEST_POSTS = 4               # ... at least this many of them, have a digest's shape
SIGNATURE = 4                  # the digest: a page one source's round-ups link in this many issues is its signature

# ---- the splitter (pure) -------------------------------------------------------------------------------------------

_BREAKS = {"p", "div", "blockquote", "section", "article", "tr", "pre", "table", "figure", "dd", "dt", "header",
           "footer", "aside", "main", "hr", "figcaption", "summary", "details", "center"}
_HEADS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_LISTS = {"ul", "ol"}
_SKIP = {"script", "style", "noscript", "template", "svg"}
BULLET = re.compile(r"^\s*(?:[-–—•·*▪►➤▸◦○●■□✓✔✅☑🔹🔸🔥👉📌⚡️]|\d{1,2}[.)]|\(\d{1,2}\))\s*\S")
MEDIA = re.compile(r"\.(jpe?g|png|gif|webp|svg|mp4|webm|mp3|m4a|avif|ico)$", re.I)
SCHEMELESS = re.compile(r"^(?:t\.me|x\.com|twitter\.com|github\.com|huggingface\.co|arxiv\.org|youtu\.be)/", re.I)
WORD = re.compile(r"\w+", re.U)


@dataclass
class _Li:
    id: int
    depth: int
    parent: Optional[int]


@dataclass
class _Line:
    start: int
    end: int = -1
    text: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    head: int = 0                      # inside a heading of this level
    li: Optional[int] = None           # the innermost open list item
    gap: bool = False                  # an empty line (a paragraph's end, <br><br>) came before it

    @property
    def words(self) -> str:
        return " ".join("".join(self.text).split())


class _Lines(HTMLParser):
    """A post's HTML as a stream of lines: a block, a list item, a heading or a <br> ends one. Each line keeps its
    character span, its words, its links (raw hrefs), the heading it is in and the list item it is in."""

    def __init__(self, src: str) -> None:
        super().__init__(convert_charrefs=True)
        self.src = src
        self.starts = [0]
        for m in re.finditer("\n", src):
            self.starts.append(m.end())
        self.lines: List[_Line] = []
        self.lis: Dict[int, _Li] = {}
        self.open_lis: List[_Li] = []
        self.depth = 0
        self.head = 0
        self.skip = 0
        self.cur: Optional[_Line] = None
        self.gap = False

    def _pos(self) -> int:
        line, col = self.getpos()
        return self.starts[line - 1] + col

    def _break(self) -> None:
        pos = self._pos()
        if self.cur is not None and (self.cur.words or self.cur.links):
            self.cur.end = pos
            self.lines.append(self.cur)
            self.gap = False
        elif self.cur is not None or not self.lines:
            self.gap = True
        self.cur = None

    def _line(self) -> _Line:
        if self.cur is None:
            self.cur = _Line(start=self._pos(), head=self.head, li=self.open_lis[-1].id if self.open_lis else None,
                             gap=self.gap)
        return self.cur

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in _SKIP:
            self.skip += 1
            return
        if tag in _HEADS:
            self._break()
            self.head = _HEADS[tag]
            self.open_lis.clear()         # a heading ends every list left open (unclosed <li> and <ul>: a digest's
            self.depth = 0                # sections would else nest under its last item)
        elif tag in _LISTS:
            self._break()
            self.depth += 1
        elif tag == "li":
            self._break()
            while self.open_lis and self.open_lis[-1].depth >= max(self.depth, 1):
                self.open_lis.pop()
            li = _Li(len(self.lis), max(self.depth, 1), self.open_lis[-1].id if self.open_lis else None)
            self.lis[li.id] = li
            self.open_lis.append(li)
        elif tag == "br" or tag in _BREAKS:
            if tag == "br" and self.cur is None:
                self.gap = True
            self._break()
        elif tag == "a" and not self.skip:
            href = dict(attrs).get("href")
            if href:
                self._line().links.append(href.strip())

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "br" or tag in _BREAKS:
            if tag == "br" and self.cur is None:
                self.gap = True
            self._break()
        elif tag == "a":
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag in _HEADS:
            self._break()
            self.head = 0
        elif tag in _LISTS:
            self._break()
            while self.open_lis and self.open_lis[-1].depth >= max(self.depth, 1):
                self.open_lis.pop()
            self.depth = max(0, self.depth - 1)
        elif tag == "li":
            self._break()
            if self.open_lis and self.open_lis[-1].depth == max(self.depth, 1):
                self.open_lis.pop()
        elif tag in _BREAKS:
            self._break()

    def handle_data(self, data: str) -> None:
        if self.skip or not data:
            return
        if not data.strip():
            if self.cur is not None:
                self.cur.text.append(" ")
            return
        self._line().text.append(data)

    def close(self) -> None:
        super().close()
        self._break()


def lines_of(src: str) -> Tuple[List[_Line], Dict[int, _Li]]:
    p = _Lines(src)
    try:
        p.feed(src)
        p.close()
    except Exception:   # a broken page: what was read so far
        log.debug("units: the HTML parser stopped early", exc_info=True)
    return p.lines, p.lis


def _text_as_html(text: str) -> str:
    """Plain text (a post with no HTML) as HTML lines, its bare addresses as links."""
    from insight_core.utils.post_links import BARE_URL
    out = []
    for line in (text or "").split("\n"):
        esc, last = [], 0
        for m in BARE_URL.finditer(line):
            url = m.group(0).rstrip(".,;:!?'\"")
            esc.append(html_lib.escape(line[last:m.start()]))
            esc.append(f'<a href="{html_lib.escape(url)}">{html_lib.escape(url)}</a>')
            last = m.start() + len(url)
        esc.append(html_lib.escape(line[last:]))
        out.append("".join(esc))
    return "<br>\n".join(out)


def page(href: str, base: Optional[str]) -> Optional[str]:
    """A link as a page (normalized as posts are, 0049), or None: no web page, a media file, a search."""
    from insight_core.utils.post_links import is_search_link
    from insight_core.utils.url_normalization import normalize_url
    href = html_lib.unescape(href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    if SCHEMELESS.match(href):
        href = "https://" + href
    try:
        absolute = urljoin(base or "", href)
        parsed = urlparse(absolute)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname or MEDIA.search(parsed.path or ""):
        return None
    if is_search_link(absolute):
        return None
    return normalize_url(absolute)


@dataclass(frozen=True)
class Item:
    n: int
    start: int
    stop: int
    links: Tuple[str, ...]
    text: str
    headline: Optional[str] = None


@dataclass(frozen=True)
class Split:
    said: bool                    # the reading names it a round-up (and it splits)
    why: str                      # 'reading' | 'structure' | 'none': where the items came from
    adapter: Optional[str]        # 'list' | 'sections' | 'lines' | 'reading'
    items: Tuple[Item, ...]
    words: int                    # the post's words
    structured: bool = False      # the shape of a digest (alone no tag: see `tag`)
    read_whole: bool = False      # a reading saw all of it: the reading decides alone


def _pages(lines: Sequence[_Line], base: Optional[str], own: Any) -> List[str]:
    out: List[str] = []
    for ln in lines:
        for href in ln.links:
            u = page(href, base)
            if u and u not in out and u not in own:
                out.append(u)
    return out[:LINKS_MAX]


def _item(n: int, lines: Sequence[_Line], base: Optional[str], own: Any, headline: Optional[str] = None) -> Item:
    text = " ".join(ln.words for ln in lines if ln.words)
    return Item(n, lines[0].start, lines[-1].end, tuple(_pages(lines, base, own)), text[:TEXT_MAX], headline)


def _numbered(groups: Sequence[Sequence[_Line]], base: Optional[str], own: Any) -> List[Item]:
    out = []
    for g in groups:
        it = _item(len(out) + 1, g, base, own)
        if it.links and it.text:
            out.append(it)
    return out


def split_list(lines: Sequence[_Line], lis: Mapping[int, _Li], base: Optional[str], own: Any) -> List[Item]:
    """`list`: each list item carrying a link of its own words is an item; a list item with no link of its own is in
    the nearest item around it, or, right after an item, is its detail (a digest's bullet under its topic)."""
    own_links: Dict[int, bool] = defaultdict(bool)
    for ln in lines:
        if ln.li is not None and any(page(h, base) not in own for h in ln.links):
            own_links[ln.li] = True

    def root(li: Optional[int]) -> Optional[int]:
        chain = []
        while li is not None:
            chain.append(li)
            li = lis[li].parent
        for x in chain:             # the nearest item with a link of its own (a digest's malformed lists nest each
            if own_links[x]:        # next topic under the last: the outermost would swallow them all)
                return x
        return None

    groups: Dict[int, List[_Line]] = {}
    last: Optional[int] = None
    for ln in lines:
        if ln.li is None or ln.head:
            last = None                         # a paragraph or a heading between items ends the last one
            continue
        r = root(ln.li)
        if r is None:
            r = last                            # a list item with no link after an item: its detail, in it
        if r is not None:
            groups.setdefault(r, []).append(ln)
            last = r
    return _numbered([groups[k] for k in sorted(groups, key=lambda k: groups[k][0].start)], base, own)


def split_sections(lines: Sequence[_Line], base: Optional[str], own: Any) -> List[Item]:
    """`sections`: a heading and the lines up to the next heading, carrying a link."""
    groups: List[List[_Line]] = []
    for ln in lines:
        if ln.head:
            if groups and groups[-1][-1].head:      # a heading run (a title over its subtitle): one heading
                groups[-1].append(ln)
            else:
                groups.append([ln])
        elif groups:
            groups[-1].append(ln)
    return _numbered(groups, base, own)


def split_lines(lines: Sequence[_Line], base: Optional[str], own: Any) -> Tuple[List[Item], bool]:
    """`lines`: bulleted lines (and the lines continuing them) when bullets open at least half the lines that link;
    else each line carrying a link. (items, bulleted)."""
    plain = [ln for ln in lines if ln.li is None and not ln.head]
    bullets = [ln for ln in plain if BULLET.match(ln.words)]
    groups: List[List[_Line]] = []
    if len(bullets) >= MIN_ITEMS and 2 * len(bullets) >= sum(1 for ln in plain if ln.links):   # bullets lead most
        for ln in lines:
            if ln.head or ln.li is not None:
                if groups and groups[-1]:
                    groups.append([])               # a heading or a list closes an item
                continue
            if BULLET.match(ln.words):
                groups.append([ln])
            elif groups and groups[-1] and not ln.gap:
                groups[-1].append(ln)
            elif groups and groups[-1]:
                groups.append([])
        return _numbered([g for g in groups if g], base, own), True
    return _numbered([[ln] for ln in plain], base, own), False


def _located(lines: Sequence[_Line], link: Optional[str], base: Optional[str]) -> Optional[_Line]:
    want = page(link or "", base) if link else None
    if not want:
        return None
    for ln in lines:
        if any(page(h, base) == want for h in ln.links):
            return ln
    return None


def split_reading(lines: Sequence[_Line], items: Sequence[Mapping[str, Any]], base: Optional[str],
                  own: Any) -> List[Item]:
    """`reading`: the reading's items (headline, link), each on the line linking it when one does."""
    out: List[Item] = []
    for it in items or ():
        head = " ".join(str(it.get("headline_en") or "").split())
        if not head:
            continue
        ln = _located(lines, it.get("link"), base)
        link = page(str(it.get("link") or ""), base) if it.get("link") else None
        links = tuple(_pages([ln], base, own)) if ln else ()
        if link and link not in own and link not in links:
            links = (link, *links)
        out.append(Item(len(out) + 1, ln.start if ln else -1, ln.end if ln else -1, links[:LINKS_MAX],
                        ((ln.words if ln else "") or head)[:TEXT_MAX], head))
    return out


def _words(s: str) -> int:
    return len(WORD.findall(s))


def _structured(items: Sequence[Item], total: int) -> bool:
    covered = sum(_words(i.text) for i in items)
    pages = {p for i in items for p in i.links}
    return (len(items) >= STRUCTURE_ITEMS and len(pages) >= STRUCTURE_PAGES and total > 0
            and covered >= ITEMS_SHARE * total)


class _Own:
    """The pages that are no item's: the post's own page (any of its addresses' forms: a table of contents links its
    own sections) and its source's signature links (post_links.boilerplate: a newsletter's sign-up page)."""

    def __init__(self, url: Optional[str], skip: Iterable[str] = ()) -> None:
        from insight_core.markx.pairing import page_address
        from insight_core.utils.url_normalization import normalize_url
        self.urls = {u for u in (normalize_url(url), *skip) if u}
        self.addr = page_address(url)

    def __contains__(self, u: Optional[str]) -> bool:
        from insight_core.markx.pairing import page_address
        return u is None or u in self.urls or (self.addr is not None and page_address(u) == self.addr)


def split(content_html: Optional[str], content: Optional[str], url: Optional[str],
          reading: Optional[Mapping[str, Any]] = None, skip: Iterable[str] = ()) -> Split:
    """A post's split and what it says on its own (pure: the post's HTML, else its text; its address; its reading).

    - `said`: the reading names it a round-up and it splits into MIN_ITEMS+ items (its HTML's finest split, else the
      reading's own items): a round-up.
    - `structured`: its finest split of list items, headed sections or bulleted lines (never plain paragraphs that
      link: an essay's as often as a digest's) has STRUCTURE_ITEMS+ items, to STRUCTURE_PAGES+ pages, holding
      ITEMS_SHARE of its words. Alone it is no tag: an essay with a list of links has the shape; a source whose posts
      mostly have it is a digest (`tag`, over the source's posts).
    - `read_whole`: a reading saw the whole post (its text within READ_SEEN characters), so the reading decides alone."""
    from insight_core.utils.post_links import decoded_html
    src = decoded_html(content_html) if content_html else _text_as_html(content or "")
    lines, lis = lines_of(src or "")
    own = _Own(url, skip)
    total = sum(_words(ln.words) for ln in lines)
    by_line, bulleted = split_lines(lines, url, own)
    options = [("list", split_list(lines, lis, url, own)), ("sections", split_sections(lines, url, own)),
               ("lines", by_line)]
    adapter, items = max(options, key=lambda o: len(o[1]))     # the finest split (the first on a tie)
    shaped = [o for o in options if o[0] != "lines" or bulleted]
    s_adapter, s_items = max(shaped, key=lambda o: len(o[1]))
    structured = _structured(s_items, total)
    read_whole = bool(reading) and sum(len(ln.words) + 1 for ln in lines) <= READ_SEEN
    if bool(reading) and reading.get("kind") == "roundup":
        if len(items) >= MIN_ITEMS:
            return Split(True, "reading", adapter, tuple(items), total, structured, read_whole)
        r_items = split_reading(lines, (reading or {}).get("items") or [], url, own)
        if len(r_items) >= MIN_ITEMS:
            return Split(True, "reading", "reading", tuple(r_items), total, structured, read_whole)
    if structured:
        return Split(False, "structure", s_adapter, tuple(s_items), total, True, read_whole)
    return Split(False, "none", None, (), total, False, read_whole)


# ---- stored ----------------------------------------------------------------------------------------------------------

_version: Optional[str] = None


def version() -> str:
    """UNITS_VERSION and the sha256 of this module's code: a change splits every post again."""
    global _version
    if _version is None:
        h = hashlib.sha256(UNITS_VERSION.encode())
        with open(__file__, "rb") as f:
            h.update(f.read())
        _version = UNITS_VERSION + ":" + h.hexdigest()[:16]
    return _version


@dataclass(frozen=True)
class Unit:
    """A round-up's n-th item as stored: its post, number, span, links, words and time."""
    id: int
    post: str
    n: int
    span: Optional[Tuple[int, int]]
    links: Tuple[str, ...]
    text: str
    at: Optional[datetime]
    headline: Optional[str] = None


def _basis(call: Optional[str], content_hash: str) -> str:
    return hashlib.sha256(json.dumps([version(), READING_GUIDE, call, content_hash]).encode()).hexdigest()


def _inputs(cur: Any, ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    cur.execute("""SELECT p.id::text, p.source_id::text, p.content_html, p.content, p.url, r.call_id::text, r.reading,
                          ARRAY(SELECT l.target_url FROM post_links l WHERE l.post_id = p.id AND l.boilerplate
                                 ORDER BY l.target_url)
                     FROM posts p LEFT JOIN mx_readings r ON r.post_id = p.id AND r.guide = %s
                    WHERE p.id = ANY(%s::uuid[])""", (READING_GUIDE, list(ids)))
    out = {}
    for pid, sid, h, t, url, call, reading, skip in cur.fetchall():
        if isinstance(reading, str):
            reading = json.loads(reading)
        digest = hashlib.sha256("\x00".join([h or "", t or "", *skip]).encode()).hexdigest()
        out[pid] = {"source": sid, "html": h, "text": t, "url": url, "call": call, "reading": reading,
                    "skip": list(skip), "basis": _basis(call, digest)}
    return out


def note(cur: Any, ids: Iterable[str]) -> Dict[str, int]:
    """Split these posts now: a post whose inputs (code, reading, text) moved is split again; its items are stored
    (appended) when it is said or shaped a round-up; then its source's tags (`tag`) and the attach of the posts
    tagged. {split, roundups, units}."""
    ids = sorted({str(i) for i in ids})
    if not ids:
        return {"split": 0, "roundups": 0, "units": 0}
    inputs = _inputs(cur, ids)
    cur.execute("SELECT post_id::text, basis FROM mx_roundups WHERE post_id = ANY(%s::uuid[])", (ids,))
    have = dict(cur.fetchall())
    now: List[str] = []
    sources: Set[str] = set()
    for pid, x in inputs.items():
        if have.get(pid) == x["basis"]:
            continue
        now.append(pid)
        sources.add(x["source"])
        s = split(x["html"], x["text"], x["url"], x["reading"], x["skip"])
        cur.execute("""INSERT INTO mx_roundups (post_id, source_id, version, basis, roundup, said, structured, read_whole,
                                                why, adapter, units, words)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (post_id) DO UPDATE SET source_id = EXCLUDED.source_id, version = EXCLUDED.version,
                              basis = EXCLUDED.basis, roundup = EXCLUDED.roundup, said = EXCLUDED.said,
                              structured = EXCLUDED.structured, read_whole = EXCLUDED.read_whole, why = EXCLUDED.why,
                              adapter = EXCLUDED.adapter, units = EXCLUDED.units, words = EXCLUDED.words,
                              issue_at = NULL, split_at = clock_timestamp(), checked_at = clock_timestamp()""",
                    (pid, x["source"], version(), x["basis"], s.said, s.said, s.structured, s.read_whole, s.why,
                     s.adapter, len(s.items), s.words))
        for it in s.items:
            cur.execute("""INSERT INTO mx_units (post_id, basis, n, adapter, span_start, span_stop, links, text, headline)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (post_id, basis, n) DO NOTHING""",
                        (pid, x["basis"], it.n, s.adapter, it.start if it.start >= 0 else None,
                         it.stop if it.stop >= 0 else None, list(it.links), it.text, it.headline))
    tagged = tag(cur, sources)
    cur.execute("SELECT post_id::text FROM mx_roundups WHERE post_id = ANY(%s::uuid[]) AND roundup", (now,))
    fresh = {r[0] for r in cur.fetchall()} | tagged
    if fresh:
        attach(cur, sorted(fresh))
    cur.execute("""SELECT count(*), COALESCE(sum(units), 0) FROM mx_roundups
                    WHERE post_id = ANY(%s::uuid[]) AND roundup""", (ids,))
    n, u = cur.fetchone()
    return {"split": len(now), "roundups": n, "units": int(u)}


def digest_sources(cur: Any, source_ids: Iterable[str]) -> Set[str]:
    """The sources whose posts are mostly shaped as round-ups: more than DIGEST_SHARE of their split posts of
    DIGEST_WORDS+ words, DIGEST_POSTS+ of them (a daily digest; an essayist's post with a list of links is not)."""
    cur.execute("""SELECT source_id::text FROM mx_roundups
                    WHERE source_id = ANY(%s::uuid[]) AND version = %s AND words >= %s
                    GROUP BY source_id HAVING count(*) >= %s AND avg(structured::int) > %s""",
                (sorted({str(s) for s in source_ids}), version(), DIGEST_WORDS, DIGEST_POSTS, DIGEST_SHARE))
    return {r[0] for r in cur.fetchall()}


def tag(cur: Any, source_ids: Iterable[str]) -> Set[str]:
    """The round-up tag of these sources' split posts, made current: the reading says so (`said`), or the post has
    a digest's shape, its reading (if any) saw only its head, and its source is a digest source (`digest_sources`).
    A post no longer tagged loses its issue time. Returns the posts tagged now that were not before."""
    sources = sorted({str(s) for s in source_ids if s})
    if not sources:
        return set()
    digest = sorted(digest_sources(cur, sources))
    cur.execute("""UPDATE mx_roundups r SET roundup = x.now,
                          issue_at = CASE WHEN x.now THEN r.issue_at END, checked_at = clock_timestamp()
                     FROM (SELECT post_id, said OR (structured AND NOT read_whole AND source_id = ANY(%s::uuid[])) AS now
                             FROM mx_roundups WHERE source_id = ANY(%s::uuid[])) x
                    WHERE r.post_id = x.post_id AND r.roundup IS DISTINCT FROM x.now
                RETURNING r.post_id::text, x.now""", (digest, sources))
    return {pid for pid, now in cur.fetchall() if now}


def units_of(cur: Any, post_ids: Iterable[str]) -> Dict[str, List[Unit]]:
    """{round-up post: its current units, in order}."""
    cur.execute("""SELECT u.id, u.post_id::text, u.n, u.span_start, u.span_stop, u.links, u.text, u.at, u.headline
                     FROM mx_units u JOIN mx_roundups r ON r.post_id = u.post_id AND r.basis = u.basis AND r.roundup
                    WHERE u.post_id = ANY(%s::uuid[]) ORDER BY u.post_id, u.n""", (sorted({str(p) for p in post_ids}),))
    out: Dict[str, List[Unit]] = defaultdict(list)
    for uid, pid, n, a, b, links, text, at, head in cur.fetchall():
        out[pid].append(Unit(uid, pid, n, (a, b) if a is not None else None, tuple(links or ()), text, at, head))
    return out


def attach(cur: Any, roundup_ids: Iterable[str]) -> Dict[str, int]:
    """Pairing's `attach` relation for these round-ups' current units: each unit's targets (pairing.attach_targets,
    stored once per unit, target and source), then each unit's time and the issue's time. {attached: rows added}."""
    from insight_core.markx import pairing
    ids = sorted({str(p) for p in roundup_ids})
    units = units_of(cur, ids)
    flat = [u for us in units.values() for u in us]
    if not flat:
        return {"attached": 0}
    added = 0
    for unit_id, target, source in pairing.attach_targets(cur, flat):
        cur.execute("""INSERT INTO mx_attach (unit_id, roundup_id, target_id, source)
                       SELECT %s, post_id, %s, %s FROM mx_units WHERE id = %s
                       ON CONFLICT (unit_id, target_id, source) DO NOTHING""", (unit_id, target, source, unit_id))
        added += cur.rowcount or 0
    _times(cur, ids)
    return {"attached": added}


def _times(cur: Any, ids: Sequence[str]) -> None:
    """A unit's time: its earliest attached post's own date; the issue's time: its latest unit time within the attach
    row's `issue_reach` of the round-up's own date (either side: a digest dated at the start of the day it covers);
    none: NULL (the post's own date stands). Never a rewrite of the post."""
    from insight_core.markx import pairing
    reach = pairing.POLICIES[pairing.ATTACH].issue_reach
    cur.execute(f"""UPDATE mx_units u SET at = t.at
                      FROM (SELECT a.unit_id, min({pairing.ordinary_date('p')}) AS at
                              FROM mx_attach a JOIN posts p ON p.id = a.target_id
                             WHERE a.roundup_id = ANY(%s::uuid[]) GROUP BY a.unit_id) t
                     WHERE u.id = t.unit_id AND u.at IS DISTINCT FROM t.at""", (list(ids),))
    cur.execute(f"""UPDATE mx_roundups r SET issue_at = x.at, checked_at = clock_timestamp()
                      FROM (SELECT r.post_id,
                                   max(u.at) FILTER (WHERE u.at BETWEEN {pairing.ordinary_date('p')} - %s
                                                                   AND {pairing.ordinary_date('p')} + %s) AS at
                              FROM mx_roundups r JOIN posts p ON p.id = r.post_id
                              LEFT JOIN mx_units u ON u.post_id = r.post_id AND u.basis = r.basis
                             WHERE r.post_id = ANY(%s::uuid[]) AND r.roundup
                             GROUP BY r.post_id, p.surfaced_at, p.published_at, p.fetched_at) x
                     WHERE r.post_id = x.post_id AND r.issue_at IS DISTINCT FROM x.at""", (reach, reach, list(ids)))


def backfill(cur: Any, *, limit: int = BACKFILL_PAGE, recheck: int = RECHECK_PAGE,
             now: Optional[datetime] = None) -> Dict[str, int]:
    """One resumable step (the candidates job's, each run): `limit` posts never split by this code, newest first
    (Pairing's post date), split; then the round-ups of the last RECHECK days attached again (`recheck` of them,
    newest first). {split, roundups, units, rechecked, left}."""
    from insight_core.markx import pairing
    missing = """FROM posts p LEFT JOIN mx_roundups r ON r.post_id = p.id
                WHERE r.version IS DISTINCT FROM %(v)s"""
    params = {"v": version()}
    got = {"split": 0, "roundups": 0, "units": 0}
    if limit:
        cur.execute(f"SELECT p.id::text {missing} ORDER BY {pairing.ordinary_date('p')} DESC, p.id LIMIT %(n)s",
                    {**params, "n": limit})
        got = note(cur, [r[0] for r in cur.fetchall()])
    rechecked = 0
    if recheck:
        cur.execute(f"""SELECT r.post_id::text FROM mx_roundups r JOIN posts p ON p.id = r.post_id
                         WHERE r.roundup AND {pairing.ordinary_date('p')} >= COALESCE(%s::timestamptz, now()) - %s
                         ORDER BY {pairing.ordinary_date('p')} DESC LIMIT %s""", (now, RECHECK, recheck))
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            attach(cur, ids)
            rechecked = len(ids)
    cur.execute(f"SELECT count(*) {missing}", params)
    return {**got, "rechecked": rechecked, "left": cur.fetchone()[0]}


# ---- reads: "also in round-ups" and the digest ----------------------------------------------------------------------

def _source_names(cur: Any, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    cur.execute("""SELECT p.id::text, p.source_id::text,
                          COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url), p.title, p.url
                     FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ANY(%s::uuid[])""",
                (sorted({str(i) for i in ids}),))
    return {pid: {"source_id": sid, "source": name, "title": title, "url": url} for pid, sid, name, title, url
            in cur.fetchall()}


def also_in(cur: Any, post_ids: Iterable[str], *, exclude: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """The round-ups carrying these posts as an item (current units, attached), each round-up once, earliest first:
    [{post, source, title, url, at, n, item, carries}]. `exclude`: round-ups not to list (a story's own members).
    Display only: never a voice, a member or a mention."""
    from insight_core.markx import pairing
    ids = sorted({str(p) for p in post_ids})
    if not ids:
        return []
    cur.execute(f"""SELECT a.roundup_id::text, u.n, u.text, u.headline, a.target_id::text, {pairing.post_date('p')}
                      FROM mx_attach a JOIN mx_units u ON u.id = a.unit_id
                      JOIN mx_roundups r ON r.post_id = u.post_id AND r.basis = u.basis AND r.roundup
                      JOIN posts p ON p.id = a.roundup_id
                     WHERE a.target_id = ANY(%s::uuid[]) AND NOT a.roundup_id = ANY(%s::uuid[])
                     ORDER BY 6, 1, 2""", (ids, sorted({str(e) for e in exclude} | set(ids))))
    rows: Dict[str, Dict[str, Any]] = {}
    for rid, n, text, head, target, at in cur.fetchall():
        r = rows.setdefault(rid, {"post": rid, "at": at.isoformat() if at else None, "n": n,
                                  "item": (head or text or "")[:240], "carries": []})
        if target not in r["carries"]:
            r["carries"].append(target)
    names = _source_names(cur, rows)
    return [{**r, **{k: (names.get(r["post"]) or {}).get(k) for k in ("source_id", "source", "title", "url")}}
            for r in rows.values()]


def also_in_story(cur: Any, story_id: str) -> List[Dict[str, Any]]:
    """A Mark X story's "also in round-ups": the round-ups carrying one of its current members."""
    cur.execute("SELECT post_id::text FROM mx_story_posts WHERE story_id = %s AND valid_to IS NULL", (story_id,))
    members = [r[0] for r in cur.fetchall()]
    return also_in(cur, members, exclude=members)


SPANS = {"day": timedelta(days=1), "week": timedelta(days=7)}


def _neg_time(iso: str) -> float:
    return -datetime.fromisoformat(iso).timestamp()


def digest(cur: Any, span: str = "day", until: Optional[datetime] = None, limit: int = 60) -> Dict[str, Any]:
    """INSIGHT's own round-up of a day or a week (no job writes it: read on request). The items of the round-ups whose
    unit time is in the span, grouped by what they carry: the Mark X story holding the attached post, else its Mark IX
    story, else the post; an item attached to nothing by its first page that is no reference page. Ranked by curators
    (separate round-up sources carrying it: not the source of the post it carries), then what INSIGHT holds, the
    issues carrying it, the latest. `only_roundups`: no stored post outside round-ups carries it (nothing attached,
    and no post that is not a round-up links its page in the span). Display only: nothing here is a voice."""
    from insight_core.markx import pairing
    from insight_core.utils.post_links import is_reference
    if span not in SPANS:
        raise ValueError(f"span must be one of {', '.join(SPANS)}")
    cur.execute("SELECT COALESCE(%s::timestamptz, now())", (until,))
    hi = cur.fetchone()[0]
    lo = hi - SPANS[span]
    cur.execute(f"""SELECT u.id, u.post_id::text, u.n, u.links, u.text, u.headline,
                           COALESCE(u.at, {pairing.post_date('p')}) AS at, p.source_id::text
                      FROM mx_units u JOIN mx_roundups r ON r.post_id = u.post_id AND r.basis = u.basis AND r.roundup
                      JOIN posts p ON p.id = u.post_id
                     WHERE COALESCE(u.at, {pairing.post_date('p')}) > %s AND COALESCE(u.at, {pairing.post_date('p')}) <= %s
                     ORDER BY 7, 2, 3""", (lo, hi))
    rows = cur.fetchall()
    unit_ids = [r[0] for r in rows]
    cur.execute("SELECT unit_id, target_id::text FROM mx_attach WHERE unit_id = ANY(%s)", (unit_ids,))
    targets: Dict[int, List[str]] = defaultdict(list)
    for uid, t in cur.fetchall():
        targets[uid].append(t)
    all_targets = sorted({t for ts in targets.values() for t in ts})
    cur.execute("""SELECT sp.post_id::text, sp.story_id::text, s.headline FROM mx_story_posts sp
                     JOIN mx_stories s ON s.id = sp.story_id
                    WHERE sp.post_id = ANY(%s::uuid[]) AND sp.valid_to IS NULL AND sp.role = 'member'
                      AND s.merged_into IS NULL ORDER BY sp.valid_from, sp.story_id""", (all_targets,))
    mx: Dict[str, Tuple[str, Optional[str]]] = {}
    for pid, sid, head in cur.fetchall():
        mx.setdefault(pid, (sid, head))
    cur.execute("SELECT post_id::text, story_id::text FROM story_posts WHERE post_id = ANY(%s::uuid[])", (all_targets,))
    ix = dict(cur.fetchall())
    groups: Dict[str, Dict[str, Any]] = {}
    for uid, rid, n, links, text, head, at, source in rows:
        ts = targets.get(uid) or []
        if ts:
            t = sorted(ts)[0]
            key, kind, ref = ((f"mx:{mx[t][0]}", "mx_story", mx[t][0]) if t in mx else
                              (f"ix:{ix[t]}", "ix_story", ix[t]) if t in ix else (f"post:{t}", "post", t))
        else:
            link = next((x for x in links or () if pairing.page_key(x) and not is_reference(x)), None)
            key, kind, ref = (f"page:{pairing.page_key(link)}", "page", link) if link else (f"unit:{uid}", "unit", None)
        g = groups.setdefault(key, {"key": key, "kind": kind, "ref": ref, "targets": set(),
                                    "headline": mx[sorted(ts)[0]][1] if kind == "mx_story" else None,
                                    "curators": set(), "units": [], "at": at, "pages": set()})
        g["targets"].update(ts)
        g["curators"].add(source)
        g["pages"].update(pairing.page_key(x) for x in links or () if pairing.page_key(x))
        g["at"] = max(g["at"], at)
        g["units"].append({"unit": uid, "post": rid, "n": n, "item": (head or text or "")[:240]})
    # only in round-ups: nothing attached, and no post that is not a round-up links its page in the span
    loose = sorted({p for g in groups.values() if not g["targets"] for p in g["pages"] if p})
    linked: Set[str] = set()
    if loose:
        cur.execute(f"""SELECT DISTINCT pl.target_url FROM post_links pl JOIN posts p ON p.id = pl.post_id
                          LEFT JOIN mx_roundups r ON r.post_id = p.id
                         WHERE NOT pl.boilerplate AND {pairing.post_date('p')} > %s - %s AND {pairing.post_date('p')} <= %s
                           AND NOT COALESCE(r.roundup, false)""", (lo, SPANS[span], hi))
        linked = {k for k in (pairing.page_key(u) for (u,) in cur.fetchall()) if k}
    # a source's signature (its profile, its licence, its sign-up page): a page its round-ups link in SIGNATURE+
    # issues, ever: no item (post_links.boilerplate marks it only once the story job has seen enough of its posts)
    refs = sorted({g["ref"] for g in groups.values() if g["kind"] == "page" and g["ref"]})
    signature: Set[Tuple[str, str]] = set()
    if refs:
        cur.execute("""SELECT l, r.source_id::text FROM mx_units u
                         JOIN mx_roundups r ON r.post_id = u.post_id AND r.basis = u.basis AND r.roundup,
                              unnest(u.links) AS l
                        WHERE u.links && %s::text[] AND l = ANY(%s::text[])
                        GROUP BY 1, 2 HAVING count(DISTINCT u.post_id) >= %s""", (refs, refs, SIGNATURE))
        signature = {(l, s) for l, s in cur.fetchall()}
    for k in [k for k, g in groups.items() if g["kind"] == "page" and any((g["ref"], s) in signature
                                                                           for s in g["curators"])]:
        del groups[k]
    titles = _source_names(cur, {t for g in groups.values() for t in g["targets"]}
                           | {u["post"] for g in groups.values() for u in g["units"]})
    items = []
    for g in groups.values():
        only = not g["targets"] and not (g["pages"] & linked)
        first_target = sorted(g["targets"])[0] if g["targets"] else None
        headline = g["headline"] or ((titles.get(first_target) or {}).get("title") if first_target else None) \
            or g["units"][0]["item"]
        # a separate curator: a round-up source that is not the source of what it carries (a site's own newsletter
        # listing its own article curates nothing)
        theirs = {(titles.get(t) or {}).get("source_id") for t in g["targets"]}
        items.append({"key": g["key"], "kind": g["kind"], "ref": g["ref"], "headline": headline,
                      "curators": len(g["curators"] - theirs), "issues": len({u["post"] for u in g["units"]}),
                      "only_roundups": only, "at": g["at"].isoformat(),
                      "posts": sorted(g["targets"]),
                      "units": [{**u, "source": (titles.get(u["post"]) or {}).get("source"),
                                 "title": (titles.get(u["post"]) or {}).get("title")} for u in g["units"]]})
    # curators first; then what INSIGHT holds (an attached post), the issues carrying it (one issue's deep dive
    # counts once), the latest. An item grouped by a reference page (a profile, a licence, docs) is its own row.
    items.sort(key=lambda i: (-i["curators"], not i["posts"], -i["issues"], _neg_time(i["at"]), i["key"]))
    return {"span": span, "from": lo.isoformat(), "until": hi.isoformat(), "roundups": len({r[1] for r in rows}),
            "units": len(rows), "items": items[:limit], "count": len(items)}


# ---- the stored issues: a daily and a weekly own round-up (owner 2026-11-12) -------------------------------------------
#
# Each closed day and each closed week gets an issue: `digest` over the period, written once as a row of
# mx_roundup_issues and never rewritten. A rebuild (`build_issue(..., rebuild=True)`, by hand) adds a new version row
# of the same period; readers read the newest version. The periods are the owner's: local midnight and local Monday
# at a fixed offset from UTC (mx_settings TZ_KEY, minutes; default UTC+4). A period is built ISSUE_SETTLE after it
# closes (a digest of a day arrives the next morning; its items' times put it in its day). Built by the candidates
# job's step in that job's own process (jobs._issues_step), never in the API.

TZ_KEY = "roundup_tz_offset_minutes"
TZ_DEFAULT = 240                        # UTC+4, the owner's
ISSUE_SETTLE = timedelta(hours=6)       # a period is built this long after it closes
ISSUE_CATCHUP = {"day": 7, "week": 4}   # closed periods a run builds at most, newest first (a job that was off)
ISSUE_ITEMS = 100                       # items kept in an issue


def tz_offset(cur: Any) -> timedelta:
    """The owner's offset from UTC that the issues' days and weeks begin at (mx_settings TZ_KEY, minutes)."""
    from insight_core.markx import repo
    v = repo.get_setting(cur, TZ_KEY, default=TZ_DEFAULT)
    try:
        minutes = int(v)
    except (TypeError, ValueError):
        minutes = TZ_DEFAULT
    return timedelta(minutes=max(-14 * 60, min(14 * 60, minutes)))


def period(span: str, at: datetime, offset: timedelta) -> Tuple[datetime, datetime]:
    """The day (local midnight to midnight) or the week (local Monday to Monday) holding `at`, in UTC. `at` is read
    in UTC first (a database time comes in the session's zone; a naive time is UTC)."""
    if span not in SPANS:
        raise ValueError(f"span must be one of {', '.join(SPANS)}")
    at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)
    local = at + offset
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if span == "week":
        start -= timedelta(days=start.weekday())
    return start - offset, start - offset + SPANS[span]


def closed_periods(span: str, now: datetime, offset: timedelta, n: int) -> List[Tuple[datetime, datetime]]:
    """The last `n` periods closed at least ISSUE_SETTLE before `now`, newest first."""
    start, _ = period(span, now - ISSUE_SETTLE, offset)
    out = []
    for _ in range(n):
        start, end = period(span, start - timedelta(seconds=1), offset)
        out.append((start, end))
    return out


def build_issue(cur: Any, span: str, start: datetime, *, rebuild: bool = False) -> Optional[int]:
    """The issue of the period starting at `start`: written when the period has none (or as a new version with
    `rebuild`); a past issue is never changed. Its id, or None (one exists and no rebuild)."""
    cur.execute("SELECT max(version) FROM mx_roundup_issues WHERE span = %s AND period_start = %s", (span, start))
    have = cur.fetchone()[0]
    if have is not None and not rebuild:
        return None
    end = start + SPANS[span]
    d = digest(cur, span, end, limit=ISSUE_ITEMS)
    cur.execute("""INSERT INTO mx_roundup_issues (span, period_start, period_end, version, code_version, roundups,
                                                  units, count, items)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id""",
                (span, start, end, (have or 0) + 1, version(), d["roundups"], d["units"], d["count"],
                 json.dumps(d["items"], default=str)))
    return cur.fetchone()[0]


def _split_from(cur: Any, since: datetime) -> Optional[datetime]:
    """The newest own date of a post dated from `since` on that this code never split (no mx_roundups row), or None:
    the backfill (newest first) has split every post from there on."""
    from insight_core.markx import pairing
    cur.execute(f"""SELECT max({pairing.ordinary_date('p')}) FROM posts p
                     WHERE {pairing.ordinary_date('p')} >= %s
                       AND NOT EXISTS (SELECT 1 FROM mx_roundups r WHERE r.post_id = p.id)""", (since,))
    return cur.fetchone()[0]


def issues_step(cur: Any, now: datetime) -> Dict[str, List[int]]:
    """The candidates job's step: the closed days and weeks (ISSUE_CATCHUP of each, newest first) with no issue yet,
    built. A period waits while a post that may carry its items was never split (a first backfill still under way: a
    round-up from ATTACH_AFTER before the period on may list them), as an issue is never changed once written.
    {span: [issue ids written]}."""
    from insight_core.markx import pairing
    offset = tz_offset(cur)
    after = pairing.POLICIES[pairing.ATTACH].after
    periods = {span: closed_periods(span, now, offset, n) for span, n in ISSUE_CATCHUP.items()}
    unsplit = _split_from(cur, min(s for ps in periods.values() for s, _ in ps) - after)
    out: Dict[str, List[int]] = {}
    for span, ps in periods.items():
        built = [i for i in (build_issue(cur, span, s) for s, _ in ps if unsplit is None or unsplit < s - after) if i]
        if built:
            out[span] = built
    return out


_ISSUE_COLS = "id, span, period_start, period_end, version, built_at, roundups, units, count, items"


def _issue_row(r: Sequence[Any], items: bool) -> Dict[str, Any]:
    out = {"id": r[0], "span": r[1], "from": r[2].isoformat(), "until": r[3].isoformat(), "version": r[4],
           "built_at": r[5].isoformat(), "roundups": r[6], "units": r[7], "count": r[8]}
    if items:
        out["items"] = r[9]
    return out


def issues(cur: Any, limit: int = 30) -> Dict[str, Any]:
    """The newest version of each issue: {daily: the latest day's (with its items), weekly: the latest week's, past:
    [the others, newest first, without items], tz_offset_minutes}."""
    cur.execute(f"""SELECT {_ISSUE_COLS} FROM (SELECT DISTINCT ON (span, period_start) * FROM mx_roundup_issues
                                                ORDER BY span, period_start, version DESC) x
                     ORDER BY period_start DESC, span LIMIT %s""", (limit,))
    rows = cur.fetchall()
    latest = {span: next((r for r in rows if r[1] == span), None) for span in SPANS}
    shown = {r[0] for r in latest.values() if r}
    return {"daily": _issue_row(latest["day"], True) if latest["day"] else None,
            "weekly": _issue_row(latest["week"], True) if latest["week"] else None,
            "past": [_issue_row(r, False) for r in rows if r[0] not in shown],
            "tz_offset_minutes": int(tz_offset(cur).total_seconds() // 60)}


def issue(cur: Any, issue_id: int) -> Optional[Dict[str, Any]]:
    """One stored issue (any version), with its items, or None."""
    cur.execute(f"SELECT {_ISSUE_COLS} FROM mx_roundup_issues WHERE id = %s", (issue_id,))
    r = cur.fetchone()
    return _issue_row(r, True) if r else None
