"""A post's references (issue 0125): every http(s) link of its text, each address once, with the reason line the
author gave for it. What the post page's Connected block is read from (db/repo_post_refs.py): Earlier (the stored
posts a post links), Later (the stored posts that link it) and Outside INSIGHT (the pages it links that are not
stored). No model: the author's own links, read by rules.

**The links** are `body_hrefs` (issue 0057, what the reader links), made absolute against the post's address and
normalized as posts are (0049), the first link to an address kept. The post's own address, a media file, its own
site: all kept here; the reader leaves out what no row shows (a link to itself), and Outside reads `post_links`
(extract_links' rules).

**The reason line** is the lab's measured rule (plan/research, links_v1_supp.reason; 0125 "What was measured"),
ported and nothing added. The first of:
1. the words the post quotes from the page (post_links.quoted_words: a quoted tweet, a link preview), cut at 300;
2. the sentence around the link (`anchor`), when it has 6+ words besides the link words and addresses and is not a
   footnote or reference line (starting with ^, [n] or n.);
3. Earlier and Later only, the stored post's title (read with the row: the target may be stored later);
4. the link words, when `titled_link_text` says they name a page;
5. nothing.
Outside rows show 1 and 2 only (`shown_reason`): the full rule measured 86% usable there, under its 80% lower bound.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from insight_core.utils.post_links import body_hrefs, decoded_html, quoted_words, titled_link_text
from insight_core.utils.url_normalization import normalize_url

# The kinds of reason a row's line comes from, in the rule's order.
QUOTE, SENTENCE, TITLE, LINK_WORDS = "quote", "sentence", "title", "link_words"
STORED_KINDS = (QUOTE, SENTENCE, LINK_WORDS)   # read from the post; TITLE is the target's, read with the row
OUTSIDE_KINDS = (QUOTE, SENTENCE)

QUOTE_MAX = 300
ANCHOR_MAX = 320
TITLE_MAX = 200
MIN_OWN_WORDS = 4         # a sentence that is the link and fewer words borrows the line before it
MIN_REASON_WORDS = 6      # a sentence is a reason with this many words besides the link words and addresses

# Each link of the text is marked \ue000 k \ue001 words \ue002 (k: its href's index), so a sentence is never cut inside one.
_OPEN, _MID, _END = "\ue000", "\ue001", "\ue002"
A_OPEN = re.compile(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a\s*>', re.I | re.S)
BREAK = re.compile(r'<br\s*/?>|</br>|</p\s*>|</li\s*>|</div\s*>|</h\d\s*>|</blockquote\s*>|<hr\s*/?>|</tr\s*>', re.I)
TAG = re.compile(r'<[^>]+>')
BARE = re.compile(r'https?://[^\s<>"\'`\]\[(){}]+', re.I)
SENT = re.compile(r'(?<=[.!?…])\s+(?=["«“(\[]?[A-ZА-ЯЁ0-9])')
WORD = re.compile(r'\w+', re.U)
MARK = re.compile(_OPEN + r'(\d+)' + _MID + '(.*?)' + _END, re.S)
ABBREV = re.compile(r'(\b[A-ZА-ЯЁ]|\bal|\be\.g|\bi\.e|\betc|\bvs|\bcf|\bDr|\bMr|\bMrs|\bMs|\bSt|\bNo|\bFig|\bapprox'
                    r'|\bт\.е|\bт\.д|\bт\.п|\bг)\.$')
URL = re.compile(r'(https?://|www\.)\S+|\b[\w.-]+\.[a-z]{2,6}/\S*', re.I)
FOOT = re.compile(r'^\s*(\^|\[\d+\]|\d+\.\s)')


@dataclass(frozen=True)
class PostRef:
    address: str                  # normalized, as posts.normalized_url
    href: str                     # as the text has it
    position: int                 # 0: the post's first linked address
    reason: Optional[str] = None
    reason_kind: Optional[str] = None   # quote | sentence | link_words


def marked_text(content_html: Optional[str], content: Optional[str]) -> Tuple[str, List[str]]:
    """The post's plain text, each link wrapped as \\ue000k\\ue001words\\ue002, and the links' hrefs in order (k)."""
    hrefs: List[str] = []
    if content_html:
        content_html = decoded_html(content_html) or ""

        def tag(m: re.Match) -> str:
            hrefs.append(html.unescape(m.group(1)).strip())
            words = " ".join(html.unescape(TAG.sub(" ", m.group(2))).split())
            return f"{_OPEN}{len(hrefs) - 1}{_MID}{words}{_END}"
        text = A_OPEN.sub(tag, content_html)
        return html.unescape(TAG.sub(" ", BREAK.sub("\n", text))), hrefs

    def bare(m: re.Match) -> str:   # plain text: its bare addresses are its links
        url = m.group(0).rstrip(".,;:!?'\"")
        hrefs.append(url)
        return f"{_OPEN}{len(hrefs) - 1}{_MID}{url}{_END}" + m.group(0)[len(url):]
    return BARE.sub(bare, content or ""), hrefs


def _clean(s: str) -> str:
    return " ".join(MARK.sub(lambda m: m.group(2), s).split())


def _own_words(sentence: str, k: int) -> int:
    """The sentence's words outside link k (another link's words count, unless they are an address)."""
    rest = re.sub(_OPEN + str(k) + _MID + '.*?' + _END, " ", sentence, flags=re.S)
    rest = MARK.sub(lambda m: m.group(2) if not re.match(r'https?://', m.group(2)) else " ", rest)
    return len(WORD.findall(rest))


def sentences(line: str) -> List[Tuple[int, int]]:
    """A line's sentences as (start, end): split after . ! ? … before a capital, a digit or a quote, never inside
    a link's words, never after an initial or a common abbreviation (al., e.g., Dr., т.е.)."""
    spans, start = [], 0
    for m in SENT.finditer(line):
        before = line[:m.start()]
        if before.count(_OPEN) > before.count(_END) or ABBREV.search(before):
            continue
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(line)))
    return spans


def anchor(text: str, k: int) -> str:
    """The sentence around link k: the sentence of its line holding it; when that is the link and fewer than
    MIN_OWN_WORDS words, the previous non-empty line's last sentence first. Cut at ANCHOR_MAX."""
    pos = text.find(f"{_OPEN}{k}{_MID}")
    if pos < 0:
        return ""
    lines = text.split("\n")
    off, li = 0, 0
    for li, line in enumerate(lines):
        if off + len(line) >= pos:
            break
        off += len(line) + 1
    line, rel = lines[li], pos - off
    chosen = line
    for a, b in sentences(line):
        if a <= rel <= b:
            chosen = line[a:b]
            break
    out = chosen
    if _own_words(chosen, k) < MIN_OWN_WORDS:
        j = li - 1
        while j >= 0 and not _clean(lines[j]):
            j -= 1
        if j >= 0:
            prev = lines[j].strip()
            a, b = sentences(prev)[-1]
            out = prev[a:b] + " " + chosen
    s = " ".join(re.sub(f"[{_OPEN}-{_END}]", "", _clean(out)).split())
    if len(s) > ANCHOR_MAX:
        s = s[:ANCHOR_MAX].rsplit(" ", 1)[0] + " …"
    return s


def _words_besides(s: str, link_words: Optional[str]) -> int:
    if link_words:
        s = s.replace(link_words, " ")
    return len(re.findall(r"\w+", URL.sub(" ", s)))


def stored_reason(address: str, text: str, k: Optional[int], link_words: Optional[str],
                  quoted: dict) -> Tuple[Optional[str], Optional[str]]:
    """Steps 1, 2 and 4 of the rule (3, the stored post's title, is read with the row): (reason, kind) or (None, None)."""
    if address in quoted:
        return " ".join(quoted[address].split())[:QUOTE_MAX], QUOTE
    sentence = anchor(text, k) if k is not None else ""
    if sentence and _words_besides(sentence, link_words) >= MIN_REASON_WORDS and not FOOT.match(sentence):
        return sentence, SENTENCE
    if titled_link_text(link_words):
        return link_words, LINK_WORDS
    return None, None


def shown_reason(reason: Optional[str], kind: Optional[str], title: Optional[str] = None, *,
                 outside: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """The line under a row: the stored reason in the rule's order, with the stored post's title (step 3) before the
    link words on an Earlier or Later row; on an Outside row only a quote or a sentence."""
    if reason and kind in (QUOTE, SENTENCE):
        return reason, kind
    if outside:
        return None, None
    title = " ".join((title or "").split())
    if title:
        return title[:TITLE_MAX], TITLE
    if reason and kind == LINK_WORDS:
        return reason, kind
    return None, None


def refs_of(content_html: Optional[str], content: Optional[str], post_url: Optional[str]) -> List[PostRef]:
    """Every http(s) address the post's text links (body_hrefs), first seen first, each once, with its reason."""
    hrefs = body_hrefs(content_html, content)
    if not hrefs:
        return []
    text, marked = marked_text(content_html, content)
    first: dict = {}
    for k, href in enumerate(marked):
        first.setdefault(href, k)
    quoted = quoted_words(decoded_html(content_html))
    out: List[PostRef] = []
    seen = set()
    for href in hrefs:
        try:   # a malformed address (a "port" that is a sentence) is skipped, as internal_links skips it
            absolute = urljoin(post_url or "", href)
            if not absolute.lower().startswith(("http://", "https://")):
                continue
            address = normalize_url(absolute)
        except ValueError:
            continue
        if not address or address in seen:
            continue
        seen.add(address)
        k = first.get(href)
        words = None
        if k is not None:
            m = re.search(_OPEN + str(k) + _MID + '(.*?)' + _END, text, re.S)
            words = " ".join(m.group(1).split()) if m else None
        reason, kind = stored_reason(address, text, k, words, quoted)
        out.append(PostRef(address, href, len(out), reason, kind))
    return out
