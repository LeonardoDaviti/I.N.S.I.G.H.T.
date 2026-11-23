"""Units: a round-up's items, each one unit, attached to the stored posts and stories they carry (0181).

A round-up (a digest, a link list, a long newsletter) is tagged (`tag`: its reading says so, or it has a digest's
shape in a digest source), split into items (`split`, pure: the finest of the `list`, `sections`, `lines` adapters,
else the reading's own items; never the post's own page or its source's signature links) and each item is attached
(Pairing's `attach` relation) to the stored post it links. Entry points: `note`, `tag`, `backfill` (the candidates
job's step), `plan_types` / `after_types` (the worker's `unit_types` question), `also_in` / `also_in_story`,
`digest` and `issues_step`. A unit is NEVER a voice: nothing here writes a table a voice, a News count or a
corroboration is read from (tests/test_markx_units.py checks every consumer). Writes mx_roundups, mx_units (appended)
and mx_attach (never deleted); nothing here rewrites a post or deletes a row.
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


def reading_guides(cur: Any) -> List[str]:
    """The readings a split reads, preferred first (reading5.guides)."""
    from insight_core.markx import reading5
    return reading5.guides(cur, READING_GUIDE)
MIN_ITEMS = 2
STRUCTURE_ITEMS = 5            # a digest's shape: this many linked items, to this many pages,
STRUCTURE_PAGES = 4
ITEMS_SHARE = 0.5              # holding this share of the post's words
READ_SEEN = 1500               # tasks.TEXT_CHARS: within it the reading saw the whole post and decides alone
TEXT_MAX = 1200                # characters of an item's words kept
LINKS_MAX = 20
BACKFILL_PAGE = 1000
RECHECK = timedelta(days=3)    # the round-ups of the last days are attached again each run (cited posts arrive late)
RECHECK_PAGE = 500
DIGEST_SHARE = 0.5             # a digest source: more than this share of its split posts of DIGEST_WORDS+ words,
DIGEST_WORDS = 150
DIGEST_POSTS = 4               # at least this many, have a digest's shape
SIGNATURE = 4                  # the digest: a page one source's round-ups link in this many issues is its signature
# unattached single-curator items a round-up source adds to a digest at most
SOLO_PER_SOURCE = 5

# ---- the splitter (pure) -------------------------------------------------------------------------------------------

_BREAKS = {"p", "div", "blockquote", "section", "article", "tr", "pre", "table", "figure", "dd", "dt", "header",
           "footer", "aside", "main", "hr", "figcaption", "summary", "details", "center"}
_HEADS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_LISTS = {"ul", "ol"}
_SKIP = {"script", "style", "noscript", "template", "svg"}
_BOLD = {"b", "strong"}
BULLET = re.compile(r"^\s*(?:[-–—•·*▪►➤▸◦○●■□✓✔✅☑🔹🔸🔥👉📌⚡️]|\d{1,2}[.)]|\(\d{1,2}\))\s*\S")
MEDIA = re.compile(r"\.(jpe?g|png|gif|webp|svg|mp4|webm|mp3|m4a|avif|ico)$", re.I)
SCHEMELESS = re.compile(r"^(?:t\.me|x\.com|twitter\.com|github\.com|huggingface\.co|arxiv\.org|youtu\.be)/", re.I)
WORD = re.compile(r"\w+", re.U)
NUMBERING = re.compile(r"^\s*(?:\d{1,2}[.):]?|[-–—•·*])\s+")
LABEL_WORDS = 12               # a bold paragraph of at most this many words and no link is a heading (a label)
HEADLINE_MIN_WORDS = 3         # a lead's bold words shorter than this are no headline ("Update:", a name)


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
    block: int = 0                     # the block (paragraph, list item, heading) it is in: a <br> ends a line only
    lead: Optional[str] = None         # what its first words are in: 'a' (a link), 'b' (bold), 'text'
    bold: List[str] = field(default_factory=list)
    plain: bool = False                # it has words outside bold

    @property
    def bold_words(self) -> str:
        return " ".join("".join(self.bold).split())

    @property
    def words(self) -> str:
        return " ".join("".join(self.text).split())


class _Lines(HTMLParser):
    """A post's HTML as a stream of lines: a block, list item, heading or <br> ends one."""

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
        self.block = 0
        self.in_a = 0
        self.in_b = 0

    def _pos(self) -> int:
        line, col = self.getpos()
        return self.starts[line - 1] + col

    def _break(self, br: bool = False) -> None:
        pos = self._pos()
        if self.cur is not None and (self.cur.words or self.cur.links):
            self.cur.end = pos
            self.lines.append(self.cur)
            self.gap = False
        elif self.cur is not None or not self.lines:
            self.gap = True
        self.cur = None
        if not br:
            self.block += 1                   # a block ends here; a <br> only ends a line of it

    def _line(self) -> _Line:
        if self.cur is None:
            self.cur = _Line(start=self._pos(), head=self.head, li=self.open_lis[-1].id if self.open_lis else None,
                             gap=self.gap, block=self.block)
        return self.cur

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in _SKIP:
            self.skip += 1
            return
        if tag in _HEADS:
            self._break()
            self.head = _HEADS[tag]
            self.open_lis.clear()         # a heading ends every list left open: digests leave <li>/<ul> unclosed
            self.depth = 0
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
            self._break(br=tag == "br")
        elif tag == "a" and not self.skip:
            self.in_a += 1
            href = dict(attrs).get("href")
            if href:
                self._line().links.append(href.strip())
        elif tag in _BOLD:
            self.in_b += 1

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "br" or tag in _BREAKS:
            if tag == "br" and self.cur is None:
                self.gap = True
            self._break(br=tag == "br")
        elif tag == "a" and not self.skip:
            href = dict(attrs).get("href")
            if href:
                self._line().links.append(href.strip())

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
        elif tag == "a":
            self.in_a = max(0, self.in_a - 1)
        elif tag in _BOLD:
            self.in_b = max(0, self.in_b - 1)

    def handle_data(self, data: str) -> None:
        if self.skip or not data:
            return
        if not data.strip():
            if self.cur is not None:
                self.cur.text.append(" ")
            return
        ln = self._line()
        if ln.lead is None:
            ln.lead = "a" if self.in_a else "b" if self.in_b else "text"
        if self.in_b:
            ln.bold.append(data)
        else:
            ln.plain = True
        ln.text.append(data)

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
    """A link as a normalized page, or None: no web page, a media file, a search."""
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
    adapter: Optional[str]
    items: Tuple[Item, ...]
    words: int
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
    """`list`: each list item with a link of its own; one without belongs to the item around it or before it."""
    own_links: Dict[int, bool] = defaultdict(bool)
    for ln in lines:
        if ln.li is not None and any(page(h, base) not in own for h in ln.links):
            own_links[ln.li] = True

    def root(li: Optional[int]) -> Optional[int]:
        chain = []
        while li is not None:
            chain.append(li)
            li = lis[li].parent
        for x in chain:             # the nearest, not the outermost: malformed lists nest each topic under the last
            if own_links[x]:
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


def _headline(text: str) -> Optional[str]:
    """A lead's words as an item's headline (its numbering dropped), or None when too short to say anything."""
    h = NUMBERING.sub("", " ".join(text.split())).strip(" :.–—-")
    return h if len(h.split()) >= HEADLINE_MIN_WORDS else None


def _blocks(lines: Sequence[_Line]) -> List[List[_Line]]:
    """Lines grouped by block (a paragraph and its <br> lines); a list item is a block of its own."""
    out: List[List[_Line]] = []
    for ln in lines:
        if out and out[-1][0].block == ln.block and (out[-1][0].li is None) == (ln.li is None):
            out[-1].append(ln)
        else:
            out.append([ln])
    return out


def _block_kind(b: Sequence[_Line], linked: bool) -> str:
    """'list', 'head', 'label' (a short bold paragraph with no link), 'link' or 'bold' (a lead), else 'plain'."""
    first = b[0]
    if first.li is not None:
        return "list"
    if first.head:
        return "head"
    words = sum(len(ln.words.split()) for ln in b)
    if not linked and not any(ln.plain for ln in b) and words <= LABEL_WORDS:
        return "label"
    return {"a": "link", "b": "bold"}.get(first.lead or "", "plain")


def _paragraph_items(lines: Sequence[_Line], base: Optional[str], own: Any) -> Optional[List[Item]]:
    """Paragraph items: an item starts at a lead (first words a link or bold), at a heading over plain paragraphs,
    or at a plain paragraph with a link after an item that has one; plain paragraphs and <br> lines continue it.
    Whether a later linked paragraph only continues an item is meaning, left to the type question (`continues`).
    None when leads open fewer than half the linking paragraphs (an essay)."""
    blocks = _blocks(lines)
    linked = [bool(_pages(b, base, own)) for b in blocks]
    kinds = [_block_kind(b, k) for b, k in zip(blocks, linked)]
    leads = sum(1 for k, x in zip(kinds, linked) if x and k in ("link", "bold"))
    if leads < MIN_ITEMS or 2 * leads < sum(1 for k, x in zip(kinds, linked) if x and k != "list"):
        return None
    groups: List[Tuple[List[_Line], Optional[str]]] = []
    item: Optional[List[_Line]] = None
    has_link = False
    pending: Optional[List[_Line]] = None
    for b, kind, x in zip(blocks, kinds, linked):
        if kind in ("list", "head", "label"):
            item, pending = None, (b if kind != "list" else None)
            continue
        if kind == "link" and item is not None and not has_link:
            item.extend(b)                                   # a section's link after its words
            has_link = x
        elif kind in ("link", "bold"):
            item, has_link, pending = list(b), x, None
            groups.append((item, _headline(b[0].bold_words) if kind == "bold" else None))
        elif item is not None and not (x and has_link):
            item.extend(b)                                   # a plain paragraph continues the item
            has_link = has_link or x
        elif pending is not None:
            item, has_link = list(pending) + list(b), x      # a heading over its plain paragraphs
            groups.append((item, _headline(" ".join(ln.words for ln in pending))))
            pending = None
        elif x:
            item, has_link = list(b), True                   # a plain paragraph with a link of its own: an item
            groups.append((item, None))
    out = []
    for g, head in groups:
        it = _item(len(out) + 1, g, base, own, head)
        if it.links and it.text:
            out.append(it)
    return out


def split_lines(lines: Sequence[_Line], base: Optional[str], own: Any) -> Tuple[List[Item], bool]:
    """`lines`: bulleted items when bullets open half the linking lines, else `_paragraph_items`, else each linking
    line. (items, bulleted)."""
    plain = [ln for ln in lines if ln.li is None and not ln.head]
    bullets = [ln for ln in plain if BULLET.match(ln.words)]
    groups: List[List[_Line]] = []
    if len(bullets) >= MIN_ITEMS and 2 * len(bullets) >= sum(1 for ln in plain if ln.links):
        for ln in lines:
            if ln.head or ln.li is not None:
                if groups and groups[-1]:
                    groups.append([])
                continue
            if BULLET.match(ln.words):
                groups.append([ln])
            elif groups and groups[-1] and not ln.gap:
                groups[-1].append(ln)
            elif groups and groups[-1]:
                groups.append([])
        return _numbered([g for g in groups if g], base, own), True
    paragraphs = _paragraph_items(lines, base, own)
    if paragraphs is not None:
        return paragraphs, False
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
    """The pages that are no item's: the post's own page (any address form) and its source's signature links."""

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
    """A post's split (pure). `said`: the reading names it a round-up and it splits into MIN_ITEMS+ items.
    `structured`: a digest's shape (never from plain linking paragraphs); alone no tag, see `tag`. `read_whole`: the
    reading saw the whole post, so it decides alone."""
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
    """UNITS_VERSION plus this module's code hash: a code change splits every post again."""
    global _version
    if _version is None:
        h = hashlib.sha256(UNITS_VERSION.encode())
        with open(__file__, "rb") as f:
            h.update(f.read())
        _version = UNITS_VERSION + ":" + h.hexdigest()[:16]
    return _version


@dataclass(frozen=True)
class Unit:
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
                                   AND l.kind <> 'mention'   -- 0235: no href of the text (a post's split stays)
                                 ORDER BY l.target_url)
                     FROM posts p LEFT JOIN LATERAL (
                          SELECT x.call_id, x.reading FROM mx_readings x WHERE x.post_id = p.id AND x.guide = ANY(%s)
                           ORDER BY array_position(%s::text[], x.guide) LIMIT 1) r ON TRUE
                    WHERE p.id = ANY(%s::uuid[])""", (reading_guides(cur), reading_guides(cur), list(ids)))
    out = {}
    for pid, sid, h, t, url, call, reading, skip in cur.fetchall():
        if isinstance(reading, str):
            reading = json.loads(reading)
        digest = hashlib.sha256("\x00".join([h or "", t or "", *skip]).encode()).hexdigest()
        out[pid] = {"source": sid, "html": h, "text": t, "url": url, "call": call, "reading": reading,
                    "skip": list(skip), "basis": _basis(call, digest)}
    return out


def note(cur: Any, ids: Iterable[str]) -> Dict[str, int]:
    """Splits the posts whose inputs (code, reading, text) moved, appends their items, then retags their sources and
    attaches the tagged posts; a post whose tag moved is queued for the story job. {split, roundups, units}."""
    ids = sorted({str(i) for i in ids})
    if not ids:
        return {"split": 0, "roundups": 0, "units": 0}
    inputs = _inputs(cur, ids)
    cur.execute("SELECT post_id::text, basis FROM mx_roundups WHERE post_id = ANY(%s::uuid[])", (ids,))
    have = dict(cur.fetchall())
    now = [pid for pid, x in inputs.items() if have.get(pid) != x["basis"]]
    sources: Set[str] = {inputs[pid]["source"] for pid in now}
    was = _tagged_in(cur, sources)
    for pid in now:
        x = inputs[pid]
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
    moved = was ^ _tagged_in(cur, sources)
    if moved:   # the story job reads the tag (a round-up joins no story by its links)
        from insight_core.db.repo_stories import StoriesRepository
        StoriesRepository.queue_regroup(cur, sorted(moved))
    cur.execute("SELECT post_id::text FROM mx_roundups WHERE post_id = ANY(%s::uuid[]) AND roundup", (now,))
    fresh = {r[0] for r in cur.fetchall()} | tagged
    if fresh:
        attach(cur, sorted(fresh))
    cur.execute("""SELECT count(*), COALESCE(sum(units), 0) FROM mx_roundups
                    WHERE post_id = ANY(%s::uuid[]) AND roundup""", (ids,))
    n, u = cur.fetchone()
    return {"split": len(now), "roundups": n, "units": int(u)}


def _tagged_in(cur: Any, source_ids: Iterable[str]) -> Set[str]:
    """The posts of these sources tagged round-ups now."""
    sources = sorted({str(s) for s in source_ids if s})
    if not sources:
        return set()
    cur.execute("SELECT post_id::text FROM mx_roundups WHERE source_id = ANY(%s::uuid[]) AND roundup", (sources,))
    return {r[0] for r in cur.fetchall()}


def roundup_sql(post: str) -> str:
    """The round-up predicate as SQL over the column `post` (this module owns it), as `tag` keeps it current."""
    return f"EXISTS (SELECT 1 FROM mx_roundups r_ WHERE r_.post_id = {post} AND r_.roundup)"


def tags_stamp(cur: Any) -> str:
    """A short hash of the tagged posts: a reader keeping `roundup_sql` counts recounts when it moves."""
    cur.execute("""SELECT md5(COALESCE(string_agg(post_id::text, ',' ORDER BY post_id), ''))
                     FROM mx_roundups WHERE roundup""")
    return cur.fetchone()[0][:16]


def tagged(cur: Any) -> List[str]:
    """The posts tagged round-ups now, in order (what `tags_stamp` hashes)."""
    cur.execute("SELECT post_id::text FROM mx_roundups WHERE roundup ORDER BY post_id")
    return [r[0] for r in cur.fetchall()]


def digest_sources(cur: Any, source_ids: Iterable[str]) -> Set[str]:
    """The sources whose split posts mostly have a digest's shape (DIGEST_SHARE, DIGEST_WORDS, DIGEST_POSTS)."""
    cur.execute("""SELECT source_id::text FROM mx_roundups
                    WHERE source_id = ANY(%s::uuid[]) AND version = %s AND words >= %s
                    GROUP BY source_id HAVING count(*) >= %s AND avg(structured::int) > %s""",
                (sorted({str(s) for s in source_ids}), version(), DIGEST_WORDS, DIGEST_POSTS, DIGEST_SHARE))
    return {r[0] for r in cur.fetchall()}


def tag(cur: Any, source_ids: Iterable[str]) -> Set[str]:
    """Makes these sources' round-up tags current: `said`, or a digest's shape not read whole in a digest source.
    An untagged post loses its issue time. Returns the posts newly tagged."""
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
    """Stores the `attach` targets of these round-ups' units, then their times. {attached: rows added}."""
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
    """A unit's time: its earliest attached post's date; the issue's: its latest unit time within `issue_reach` of
    the round-up's date (either side), else NULL. Never rewrites the post."""
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
    """One resumable candidates-job step: split `limit` posts never split by this code (newest first), reattach
    `recheck` recent round-ups (cited posts arrive late), plan types. {split, roundups, units, rechecked, left}."""
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
    left = cur.fetchone()[0]
    asked = plan_types(cur, now=now)
    return {**got, "rechecked": rechecked, "left": left, **({"typed_asked": asked} if asked else {})}


# ---- the items' types: the worker's question (kind `unit_types`) ------------------------------------------------------
# Each item's type, short headline and whether it continues the item before; keyed by the sha256 of its words, so a
# new split of the same words keeps its answer.

TYPE_KIND = "unit_types"
TYPE_DAYS = timedelta(days=16)     # round-ups this recent are asked (the issues still buildable)
TYPE_PLAN_MAX = 60
TYPE_TEXT = 400
TYPE_LINKS = 2
SHA = "encode(sha256(convert_to({t}, 'UTF8')), 'hex')"


def text_sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _short(url: str) -> str:
    u = urlparse(url)
    return ((u.hostname or "").removeprefix("www.") + (u.path or ""))[:90]


def type_question(head: Mapping[str, Any], items: Sequence[Mapping[str, Any]], before: Optional[str]) -> str:
    """One question's input: the round-up's head, the item before the first, then items keyed u1..uN."""
    at = head.get("at")
    lines = [f"ROUND-UP: {head.get('source') or 'a source'} - {' '.join((head.get('title') or '').split())[:160]}"
             f" ({at.date().isoformat() if at else 'no date'})"]
    if before:
        lines.append(f"(before u1: {' '.join(before.split())[:200]})")
    lines.append("")
    for k, it in enumerate(items, 1):
        words = " ".join((it.get("text") or "").split())[:TYPE_TEXT]
        links = ", ".join(_short(x) for x in (it.get("links") or [])[:TYPE_LINKS])
        lines.append(f"[u{k}] {words}" + (f" | links: {links}" if links else ""))
    return "\n".join(lines)


def plan_types(cur: Any, *, now: Optional[datetime] = None, limit: int = TYPE_PLAN_MAX) -> int:
    """Adds type questions for recent items never typed nor asked; returns how many."""
    from insight_core.markx import pairing, schemas, tasks
    sha = SHA.format(t="u.text")
    cur.execute(f"""SELECT u.post_id::text, u.n, u.text, u.links, {sha}, v.text
                      FROM mx_units u JOIN mx_roundups r ON r.post_id = u.post_id AND r.basis = u.basis AND r.roundup
                      JOIN posts p ON p.id = u.post_id
                      LEFT JOIN mx_units v ON v.post_id = u.post_id AND v.basis = u.basis AND v.n = u.n - 1
                     WHERE {pairing.post_date('p')} >= COALESCE(%s::timestamptz, now()) - %s
                       AND NOT EXISTS (SELECT 1 FROM mx_unit_types t WHERE t.post_id = u.post_id AND t.text_sha = {sha})
                       AND NOT EXISTS (SELECT 1 FROM mx_unit_type_asks a WHERE a.post_id = u.post_id AND {sha} = ANY(a.texts))
                     ORDER BY {pairing.post_date('p')} DESC, u.post_id, u.n""", (now, TYPE_DAYS))
    by_post: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for pid, n, text, links, h, before in cur.fetchall():
        by_post[pid].append({"n": n, "text": text, "links": list(links or ()), "sha": h, "before": before})
    if not by_post:
        return 0
    heads = _source_names(cur, by_post)
    cur.execute(f"SELECT p.id::text, {pairing.post_date('p')} FROM posts p WHERE p.id = ANY(%s::uuid[])", (list(by_post),))
    dates = dict(cur.fetchall())
    added = 0
    for pid, items in by_post.items():
        for k in range(0, len(items), schemas.UNITS_PER_QUESTION):
            if added >= limit:
                return added
            chunk = items[k:k + schemas.UNITS_PER_QUESTION]
            head = {**(heads.get(pid) or {}), "at": dates.get(pid)}
            text = type_question(head, chunk, chunk[0]["before"])
            tid, new = tasks.add(cur, TYPE_KIND, text, a=pid)
            cur.execute("""INSERT INTO mx_unit_type_asks (task_id, post_id, texts) VALUES (%s, %s, %s)
                           ON CONFLICT (task_id) DO NOTHING""", (tid, pid, [x["sha"] for x in chunk]))
            added += 1 if new else 0
    return added


def after_types(cur: Any, task: Mapping[str, Any], call_id: Any, answer: Mapping[str, Any]) -> int:
    """A valid answer's items as rows (mx_unit_types), keyed by their words; the first answer for an item stays."""
    cur.execute("SELECT post_id, texts FROM mx_unit_type_asks WHERE task_id = %s", (task["id"],))
    row = cur.fetchone()
    if row is None:
        return 0
    pid, texts = row
    got = 0
    for u in answer.get("units") or []:
        k = int(u["key"][1:])
        if not 1 <= k <= len(texts):
            continue
        cur.execute("""INSERT INTO mx_unit_types (post_id, text_sha, type, headline, continues, task_id, call_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (post_id, text_sha) DO NOTHING""",
                    (pid, texts[k - 1], u["type"], " ".join(u["headline"].split()).rstrip("."), bool(u["continues"]),
                     task["id"], call_id))
        got += cur.rowcount or 0
    return got


# ---- reads: "also in round-ups" and the digest ----------------------------------------------------------------------

def _source_names(cur: Any, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    cur.execute("""SELECT p.id::text, p.source_id::text,
                          COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url), p.title, p.url
                     FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ANY(%s::uuid[])""",
                (sorted({str(i) for i in ids}),))
    return {pid: {"source_id": sid, "source": name, "title": title, "url": url} for pid, sid, name, title, url
            in cur.fetchall()}


def also_in(cur: Any, post_ids: Iterable[str], *, exclude: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """The round-ups carrying these posts as an item, each once, earliest first: [{post, source, title, url, at, n,
    item, carries}]. `exclude`: round-ups not to list. Display only: never a voice, a member or a mention."""
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


def _lead_page(links: Sequence[str]) -> Optional[str]:
    """The page an unattached item is grouped by: its first page that is no reference or legal page, else its first
    page. Not post_links.is_reference: that counts a one-segment article slug as a profile."""
    from insight_core.markx import pairing
    from insight_core.utils.post_links import LEGAL, REFERENCE, bare
    pages = [x for x in links if pairing.page_key(x)]
    for x in pages:
        _, _, rest = bare(x).partition("/")
        path = "/" + rest.split("?", 1)[0].split("#", 1)[0]
        if path.strip("/") and not REFERENCE.search("/" + rest) and not LEGAL.search(path):
            return x
    return pages[0] if pages else None


def digest(cur: Any, span: str = "day", until: Optional[datetime] = None, limit: int = 60) -> Dict[str, Any]:
    """INSIGHT's own round-up of a day or a week (what an issue is built from), from the round-up items in the span.

    News only (typed items of a news type that do not just continue the one before; untyped kept and counted),
    grouped by what they carry (Mark X story, Mark IX story, post, else lead page; signature pages dropped), ranked:
    stories or 2+ independent curators first, then single-curator attached items, then unattached ones (at most
    SOLO_PER_SOURCE a source, by their place in the round-up). Display only: nothing here is a voice."""
    from insight_core.markx import event_types, pairing
    if span not in SPANS:
        raise ValueError(f"span must be one of {', '.join(SPANS)}")
    cur.execute("SELECT COALESCE(%s::timestamptz, now())", (until,))
    hi = cur.fetchone()[0]
    lo = hi - SPANS[span]
    cur.execute(f"""SELECT u.id, u.post_id::text, u.n, u.links, u.text, u.headline,
                           COALESCE(u.at, {pairing.post_date('p')}) AS at, p.source_id::text, {SHA.format(t="u.text")}
                      FROM mx_units u JOIN mx_roundups r ON r.post_id = u.post_id AND r.basis = u.basis AND r.roundup
                      JOIN posts p ON p.id = u.post_id
                     WHERE COALESCE(u.at, {pairing.post_date('p')}) > %s AND COALESCE(u.at, {pairing.post_date('p')}) <= %s
                     ORDER BY 7, 2, 3""", (lo, hi))
    all_rows = cur.fetchall()
    typed = event_types.of_units(cur, {r[1] for r in all_rows})
    left_out: Dict[str, int] = defaultdict(int)
    untyped = 0
    untyped_roundups: Set[str] = set()
    rows = []
    for r in all_rows:
        t = typed.get((r[1], r[8]))
        if t is None:
            untyped += 1
            untyped_roundups.add(r[1])
        elif t.continues and r[2] > 1:
            left_out["continues"] += 1
            continue
        elif not event_types.unit_is_news(t.type):
            left_out[t.type] += 1
            continue
        rows.append((*r, t.headline if t else None))
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
    for uid, rid, n, links, text, head, at, source, _sha, worker_head in rows:
        ts = targets.get(uid) or []
        if ts:
            t = sorted(ts)[0]
            key, kind, ref = ((f"mx:{mx[t][0]}", "mx_story", mx[t][0]) if t in mx else
                              (f"ix:{ix[t]}", "ix_story", ix[t]) if t in ix else (f"post:{t}", "post", t))
        else:
            link = _lead_page(links or ())
            key, kind, ref = (f"page:{pairing.page_key(link)}", "page", link) if link else (f"unit:{uid}", "unit", None)
        g = groups.setdefault(key, {"key": key, "kind": kind, "ref": ref, "targets": set(),
                                    "headline": mx[sorted(ts)[0]][1] if kind == "mx_story" else None,
                                    "worker": None, "lead": None, "curators": set(), "units": [], "at": at,
                                    "pages": set(), "place": n})
        g["targets"].update(ts)
        g["curators"].add(source)
        g["pages"].update(pairing.page_key(x) for x in links or () if pairing.page_key(x))
        g["at"] = max(g["at"], at)
        g["place"] = min(g["place"], n)
        g["worker"] = g["worker"] or worker_head
        g["lead"] = g["lead"] or head
        g["units"].append({"unit": uid, "post": rid, "n": n, "item": (worker_head or head or text or "")[:240]})
    # only in round-ups: nothing attached, and no non-round-up post links its page in the span
    loose = sorted({p for g in groups.values() if not g["targets"] for p in g["pages"] if p})
    linked: Set[str] = set()
    if loose:
        cur.execute(f"""SELECT DISTINCT pl.target_url FROM post_links pl JOIN posts p ON p.id = pl.post_id
                          LEFT JOIN mx_roundups r ON r.post_id = p.id
                         WHERE NOT pl.boilerplate AND {pairing.post_date('p')} > %s - %s AND {pairing.post_date('p')} <= %s
                           AND NOT COALESCE(r.roundup, false)""", (lo, SPANS[span], hi))
        linked = {k for k in (pairing.page_key(u) for (u,) in cur.fetchall()) if k}
    # a source's signature: a page its round-ups link in SIGNATURE+ issues is no item (boilerplate may not know it yet)
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
        headline = (g["headline"] or g["worker"]
                    or ((titles.get(first_target) or {}).get("title") if first_target else None)
                    or g["lead"] or g["units"][0]["item"])
        theirs = {(titles.get(t) or {}).get("source_id") for t in g["targets"]}
        curators = len(g["curators"] - theirs)
        tier = 0 if g["kind"] in ("mx_story", "ix_story") or curators >= 2 else 1 if g["targets"] else 2
        items.append({"key": g["key"], "kind": g["kind"], "ref": g["ref"], "headline": headline,
                      "curators": curators, "issues": len({u["post"] for u in g["units"]}), "tier": tier,
                      "only_roundups": only, "at": g["at"].isoformat(), "place": g["place"],
                      "posts": sorted(g["targets"]),
                      "units": [{**u, "source": (titles.get(u["post"]) or {}).get("source"),
                                 "title": (titles.get(u["post"]) or {}).get("title")} for u in g["units"]]})
    items.sort(key=lambda i: (i["tier"], -i["curators"], -i["issues"], _neg_time(i["at"]), i["key"]) if i["tier"] == 0
               else (i["tier"], i["place"], _neg_time(i["at"]), i["key"]))
    kept, per_source, capped = [], defaultdict(int), 0
    for i in items:
        if i["tier"] == 2:
            src = (titles.get(i["units"][0]["post"]) or {}).get("source_id")
            if per_source[src] >= SOLO_PER_SOURCE:
                capped += 1
                continue
            per_source[src] += 1
        kept.append(i)
    return {"span": span, "from": lo.isoformat(), "until": hi.isoformat(), "roundups": len({r[1] for r in all_rows}),
            "units": len(all_rows), "items": kept[:limit], "count": len(kept), "capped": capped,
            "left_out": dict(sorted(left_out.items())), "untyped": untyped, "untyped_roundups": sorted(untyped_roundups)}


# ---- the stored issues: a daily and a weekly own round-up -------------------------------------------------------------
# Each closed local day and week gets `digest` written once to mx_roundup_issues, never rewritten (a rebuild adds a new
# version; readers read the newest). Built by the candidates job (jobs._issues_step), never in the API.

TZ_KEY = "roundup_tz_offset_minutes"
TZ_DEFAULT = 240
ISSUE_SETTLE = timedelta(hours=6)       # a day's digest arrives the next morning
ISSUE_CATCHUP = {"day": 7, "week": 2}   # closed periods a run builds at most; within TYPE_DAYS
ISSUE_ITEMS = 100
TYPE_WAIT = timedelta(hours=18)         # a settled period waits this long more for its items' types


def tz_offset(cur: Any) -> timedelta:
    """The offset from UTC the issues' days and weeks begin at (mx_settings TZ_KEY, minutes)."""
    from insight_core.markx import repo
    v = repo.get_setting(cur, TZ_KEY, default=TZ_DEFAULT)
    try:
        minutes = int(v)
    except (TypeError, ValueError):
        minutes = TZ_DEFAULT
    return timedelta(minutes=max(-14 * 60, min(14 * 60, minutes)))


def period(span: str, at: datetime, offset: timedelta) -> Tuple[datetime, datetime]:
    """The local day or week (from Monday) holding `at`, as UTC bounds; a naive `at` is UTC."""
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


def build_issue(cur: Any, span: str, start: datetime, *, rebuild: bool = False,
                now: Optional[datetime] = None) -> Optional[int]:
    """Writes the issue of the period starting at `start` when it has none (or a new version with `rebuild`); a
    past issue is never changed. With `now`, a period with untyped items waits TYPE_WAIT. Its id, or None."""
    cur.execute("SELECT max(version) FROM mx_roundup_issues WHERE span = %s AND period_start = %s", (span, start))
    have = cur.fetchone()[0]
    if have is not None and not rebuild:
        return None
    end = start + SPANS[span]
    d = digest(cur, span, end, limit=ISSUE_ITEMS)
    if d["untyped"] and now is not None:
        cur.execute("SELECT max(asked_at) FROM mx_unit_type_asks WHERE post_id = ANY(%s::uuid[])",
                    (d["untyped_roundups"],))
        asked = cur.fetchone()[0]
        if now < max(end + ISSUE_SETTLE, asked or end + ISSUE_SETTLE) + TYPE_WAIT:
            return None
    cur.execute("""INSERT INTO mx_roundup_issues (span, period_start, period_end, version, code_version, roundups,
                                                  units, count, items, left_out, untyped, capped)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s) RETURNING id""",
                (span, start, end, (have or 0) + 1, version(), d["roundups"], d["units"], d["count"],
                 json.dumps(d["items"], default=str), json.dumps(d["left_out"]), d["untyped"], d["capped"]))
    return cur.fetchone()[0]


def _split_from(cur: Any, since: datetime) -> Optional[datetime]:
    """The newest date of a post from `since` on never split, or None: the backfill has split them all."""
    from insight_core.markx import pairing
    cur.execute(f"""SELECT max({pairing.ordinary_date('p')}) FROM posts p
                     WHERE {pairing.ordinary_date('p')} >= %s
                       AND NOT EXISTS (SELECT 1 FROM mx_roundups r WHERE r.post_id = p.id)""", (since,))
    return cur.fetchone()[0]


def issues_step(cur: Any, now: datetime) -> Dict[str, List[int]]:
    """Builds the closed days' and weeks' missing issues. A period waits while a post that may carry its items is
    unsplit, or for its items' types, since an issue is never changed once written. {span: [issue ids written]}."""
    from insight_core.markx import pairing
    offset = tz_offset(cur)
    after = pairing.POLICIES[pairing.ATTACH].after
    periods = {span: closed_periods(span, now, offset, n) for span, n in ISSUE_CATCHUP.items()}
    unsplit = _split_from(cur, min(s for ps in periods.values() for s, _ in ps) - after)
    out: Dict[str, List[int]] = {}
    for span, ps in periods.items():
        built = [i for i in (build_issue(cur, span, s, now=now) for s, _ in ps
                             if unsplit is None or unsplit < s - after) if i]
        if built:
            out[span] = built
    return out


_ISSUE_COLS = "id, span, period_start, period_end, version, built_at, roundups, units, count, left_out, untyped, capped, items"


def _issue_row(r: Sequence[Any], items: bool) -> Dict[str, Any]:
    out = {"id": r[0], "span": r[1], "from": r[2].isoformat(), "until": r[3].isoformat(), "version": r[4],
           "built_at": r[5].isoformat(), "roundups": r[6], "units": r[7], "count": r[8], "left_out": r[9] or {},
           "untyped": r[10], "capped": r[11]}
    if items:
        out["items"] = r[12]
    return out


def issues(cur: Any, limit: int = 30) -> Dict[str, Any]:
    """The newest version of each issue: {daily, weekly (with items), past (no items), tz_offset_minutes}."""
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
