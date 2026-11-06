"""The fields computed for every post on save (content hash, URLs, host and language), and the
title the reader shows."""

from __future__ import annotations

import html as html_lib
import re
import unicodedata
import urllib.parse
from typing import Any, Dict, List, Tuple

from .addresses import tweet_author
from .content_fingerprints import clean_text, hash_post_content, strip_html
from .language_detection import detect_language
from .post_links import quoted_tweet
from .url_normalization import canonicalize_url, extract_url_host, normalize_url

TITLE_MAX_CHARS = 120             # not measured
TITLE_MIN_SENTENCE_CHARS = 20     # not measured
# A sentence ends at . ! ? or …, not at the period of a letter's abbreviation: an initial or "U.S." (issue 0070;
# "I" ends sentences: "Part I.").
SENTENCE_END_RE = re.compile(r"(?:[!?…]|(?<!\b[^\W\dI_])\.)(?=\s|$)")
# "…", "..." or, from the Telegram RSS bridge, "[...]" / "[…]".
TRAILING_ELLIPSIS_RE = re.compile(r"(?:…|\.\.\.|\[(?:…|\.\.\.)\])\s*$")


# Nitter's titles say what a tweet is (issue 0066): "RT by @user: …" a repost by user, "R to @user: …"
# a reply to user. The text after them is the tweet's.
# metadata key of where a post's page moved (issue 0108): the normalized address its page's
# redirect stub named, where its article was read. The story job makes the two one page.
MOVED_KEY = "moved_to"
# metadata key of a page you saved (issue 0122): when you saved it. A page of a source you follow is
# saved as that source's post with it; a feed that brings the page later keeps it (one post).
SAVED_KEY = "saved_by_owner"
REPOST_BY_RE = re.compile(r"^RT by @(\w+): ")
REPLY_TO_RE = re.compile(r"^R to @(\w+): ")
_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.U)   # a word: two letters or more


def _starts_line(title: str, i: int) -> bool:
    """Whether title[i] can open a line glued on: not punctuation that ends or continues a phrase
    (a body's "@user !" or "ИИ , знают" has a space from a tag, not a line break), not right after
    an opening bracket or quote ("«Смит" is one word), and not an emoji the title ends with: before
    "…жива💀." a custom emoji's tag left a space, not a line break (issue 0070)."""
    ends_in_emoji = unicodedata.category(title[i]) in ("So", "Sk") and not any(ch.isalnum() for ch in title[i:])
    return (title[i] not in ".,;:!?…)]}»”’\"'" and not ends_in_emoji
            and not (unicodedata.category(title[i - 1]) in ("Ps", "Pi") or title[i - 1] in "\"'"))


def _glued_first_line(cut: str, content: str | None, whole: bool = False) -> str | None:
    """A cut title that is the body's start with its line breaks dropped (the Telegram bridge joins
    "…у SpaceX" and "Датацентр…" into "SpaceXДатацентр"): the body up to the first space the title
    lacks, which is where the post's first line ended. None when the title keeps every space.

    A `whole` title (not cut, issue 0069: "$500Изменения уже действуют.") ends only where the title
    runs on into the next line's first character; a space a tag left in the body ("@user !",
    "ИИ , знают", "« Смит") is not a line's end. Its own spacing is kept. Neither is it in a cut
    title, nor a space before a lowercase letter (issue 0072: "Model Z , а" was "<b>Model Z</b>, а")."""
    title, body = clean_text(cut), clean_text(content)
    i = j = 0
    while i < len(title) and j < len(body):
        if title[i] == body[j]:
            i, j = i + 1, j + 1
        elif body[j].isspace() and not title[i].isspace():
            if len(_WORD_RE.findall(body[:j])) >= 2 and _starts_line(title, i) and (
                    body[j + 1:j + 2] == title[i] if whole else not title[i].islower()):
                return (title[:i] if whole else body[:j]).rstrip()
            j += 1   # a space after a leading emoji or one word ("🌸 Релизим"), or a tag's
        else:
            return None
    return None


# Words that stand in for a post's text (issue 0069), told by shape: a bracketed word ("[Photo]",
# the Telegram bridge's album pieces), the name of a media kind alone ("Image", Nitter's tweet with no
# words), or a bare address. Such a title says nothing of the post, so the text says it instead.
_ADDRESS = r"(?:https?://|[\w-]+(?:\.[\w-]+)+/)\S*"
_PLACEHOLDER_RE = re.compile(
    r"^(?:\[[^\W\d_]+\]|(?i:photo|video|gif|image|media|audio|sticker|document|file)"
    rf"|{_ADDRESS})$")
_LEADING_ADDRESS_RE = re.compile(rf"^(?:{_ADDRESS}\s+)+")   # a link's preview: its address, then its words
_FINISHED_RE = re.compile(r"[.!?…][\"'»”’)\]]*$")
# A list's or a quote's mark at a line's start ("- ", "• ", "> "): markup, not a title's words (issue 0070).
_MARK_RE = re.compile(r"^[>•*\-–—]\s+")
# A Telegram link preview's lines (issue 0070): the bridge writes it as <cite>site</cite>, then the
# page's title and description, each ended by a break; the stored text has lost those breaks.
_PREVIEW_SITE_RE = re.compile(r"<cite>.*?</cite>", re.I | re.S)
# A preview of a tweet is titled by its author, "Percy Liang (@percyliang)": who, not what; its text says it.
# A quoted tweet's words open on it too (issue 0072): who is quoted, not what.
_BYLINE_RE = re.compile(r"^[^()\n]{1,60}\(@\w+\)(?:\s+|$)")
_LINE_END_RE = re.compile(r"<(?:br\s*/?|/br|/p|/b|/blockquote|/li|/h[1-6])>", re.I)
# A line's end in a body's HTML (issue 0072): a break or a block's end; a bold word ends no line.
_BLOCK_END_RE = re.compile(r"<(?:br\s*/?|/br|/p|/div|/blockquote|/li|/h[1-6])>", re.I)


# Nitter's quote of a tweet (issue 0072): a card that opens on its author in bold, "Name (@user)", and
# ends on a footer citing it, "— https://nitter.local/user/status/1#m"; the post links the quoted tweet
# above it by a bare address. Who and where, never the post's words: they leave its text and HTML.
_QUOTE_CARD_RE = re.compile(r"<blockquote>\s*<b>([^<]*\(@(\w+)\))</b>", re.I)
_QUOTE_FOOTER_RE = re.compile(r"\s*— https?://\S+/status/\d+\S*\s*$")
_QUOTE_FOOTER_HTML_RE = re.compile(r"\s*<footer>\s*—\s*<cite>\s*<a\b[^>]*/status/\d+[^>]*>[^<]*</a>\s*(?:</cite>\s*)?</footer>", re.I)


def _quoted_address_re(user: str) -> re.Pattern:
    """The bare link to a tweet of `user` (its text an address, no spaces) that Nitter writes before a quote card."""
    return re.compile(rf'<a\b[^>]*href="[^"]*/{re.escape(user)}/status/\d+[^"]*"[^>]*>([^<\s]*)</a>', re.I)


def without_quote_marks(content: str | None, html: str | None) -> Tuple[str | None, str | None]:
    """A tweet's text and HTML without its quote card's byline and footer and the quoted tweet's bare
    address (issue 0072); the quoted words stay, in the card. Anything else as it is. `html` may be only
    the HTML's start: a card that starts after it is left alone."""
    card = _QUOTE_CARD_RE.search(html or "")
    if not card:
        return content, html
    address = _quoted_address_re(card.group(2))
    link = address.search(html[:card.start()])
    if content:
        content = _QUOTE_FOOTER_RE.sub("", content)
        # The byline becomes a line's end: the post's own words end where the quote begins.
        for mark, gap in ((html_lib.unescape(link.group(1)) if link else None, " "), (html_lib.unescape(card.group(1)), "\n")):
            at = content.find(mark) if mark else -1
            if at >= 0:
                content = (content[:at].rstrip() + gap + content[at + len(mark):].lstrip()).strip()
    html = _QUOTE_FOOTER_HTML_RE.sub("", html)
    if link:
        html = html[:link.start()] + html[link.end():]
    return content, _EMPTY_P_RE.sub("", html).strip()


def quote_only(html: str | None) -> str | None:
    """The tweet a post only quotes, normalized (issue 0072): before the quote card it has nothing of its
    own (no words, emoji or pictures), only the quoted tweet's bare address. Else None."""
    card = _QUOTE_CARD_RE.search(html or "")
    if not card:
        return None
    own = _quoted_address_re(card.group(2)).sub("", html[:card.start()])
    if re.search(r"<(?:img|video)\b", own, re.I) or html_lib.unescape(_TAG_RE.sub("", own)).strip():
        return None
    return quoted_tweet(html)


def _words(line: str, preview: bool = False) -> str:
    """A line as a title's words, a placeholder nothing. `preview`: the text under a placeholder
    title, where a leading address is the link the post shares, its words after it."""
    line = _BYLINE_RE.sub("", _LEADING_ADDRESS_RE.sub("", line)) if preview else line
    return "" if _PLACEHOLDER_RE.match(line) else line


def _html_lines(html: str, ends: re.Pattern = _LINE_END_RE) -> str:
    """HTML's text, one line per break or block (`ends`), a link preview's site name left out."""
    return html_lib.unescape(_TAG_RE.sub("", ends.sub("\n", _PREVIEW_SITE_RE.sub("", html))))


def _squashed(text: str | None) -> str:
    """Text without its whitespace, to tell whether one text starts another (issue 0072: "X *" and
    "X*" are one start)."""
    return re.sub(r"\s+", "", clean_text(text))


def _false_end(title: str) -> bool:
    """A title the source ended where no sentence ends (issue 0072): inside an open bracket ("(?"),
    or at an abbreviation's period ("т.к.", "U.S.") that SENTENCE_END_RE doesn't take as an end."""
    return title.count("(") > title.count(")") or (title.endswith(".") and not SENTENCE_END_RE.search(title, len(title) - 1))


def display_title(title: str | None, content: str | None, html: str | None = None) -> str:
    """The title the feed and the post page show; the stored title is never changed.

    The text is the title, or the body when the title is empty, a placeholder ("[Photo]", "Image",
    a bare address: issue 0069) or the body's start cut with "…" or "[...]" (a tweet, a Telegram
    post, a GitHub commit). Nitter's "RT by @…: " and "R to @…: " are dropped (who reposted or
    whom it answers is said beside it). Only the first line with words counts. A title's first
    line under 20 characters that ends unfinished ("Day 25/", "BREAKING:": a tweet's title is its
    whole text) runs on into its next lines; a body's short first line is its heading. A title
    the Telegram bridge glued from two lines ("$500Изменения") ends where the body's first line
    did. Title and body are stored plain text, so nothing in them is read as a tag. When the text
    has no words, the stored title stands.

    Issue 0070: a line's list or quote mark ("- ", "> ") is no word; a list right under the address
    a post shares is titled by that address ("agentville.world"). Under a placeholder, a Telegram
    link preview's `html` gives the page's title as its own line, not run on with the site's name.
    """
    stored = REPLY_TO_RE.sub("", REPOST_BY_RE.sub("", (title or "").strip()))   # issue 0066
    # A quote card's byline and footer aren't the post's words (issue 0072).
    content = _QUOTE_FOOTER_RE.sub("", without_quote_marks(content, html)[0] or "")
    cut = TRAILING_ELLIPSIS_RE.sub("", stored).strip()
    cut = re.sub(r"&#?\w*$", "", cut).rstrip() if cut != stored else cut   # the bridge cut inside "&quot;" (0072)
    placeholder = bool(stored) and not _words(clean_text(stored))
    # Issue 0072: a title ended where no sentence ends is cut too, and a cut title starts the text
    # whatever its spaces; its line comes from the HTML's breaks when the text has lost them.
    false_end = cut == stored and _false_end(stored)
    starts = _squashed(content).startswith(_squashed(cut)) and (not false_end or len(_squashed(content)) > len(_squashed(cut)))
    from_body = not stored or placeholder or ((cut != stored or false_end) and bool(cut) and starts)
    lines_html = _html_lines(html, _BLOCK_END_RE) if html and from_body and not placeholder else None
    first = next((clean_text(line) for line in (lines_html or "").splitlines() if _WORD_RE.search(line)), "")
    if not (first and (_squashed(first).startswith(_squashed(cut)) or _squashed(cut).startswith(_squashed(first)))):
        lines_html = None   # the HTML opens on something else: the text says it
    glued = _glued_first_line(cut, content, whole=cut == stored) if cut and not placeholder and not lines_html else None
    # Issue 0076: a whole title ends where the body's first line did only if its HTML ends a line there too
    # (the bridge glued two lines); "145GB" against the text's "145 GB" is one word written two ways.
    if glued and cut == stored and html and not _ends_a_line(html, glued):
        glued = _html_line_head(html, clean_text(stored))   # where the HTML ends the line, if it's a start of it
    text = (lines_html or (_html_lines(html) if html and placeholder and _PREVIEW_SITE_RE.search(html) else content)) if from_body else stored
    raws, after_blank, blank = [], set(), False   # a line that opens a paragraph (issue 0072)
    for raw in (text or "").splitlines():
        if clean_text(raw):
            after_blank |= {len(raws)} if blank else set()
            raws.append(clean_text(raw))
        blank = not clean_text(raw)
    lines = [words for raw in raws if (words := _words(raw, placeholder))]
    if glued or not lines:
        whole = clean_text(stored)
        return _titled(glued or whole, [], False, [whole[len(glued):]] if glued and whole.startswith(glued) else [])
    if raws[0] != lines[0] and _MARK_RE.match(lines[0]) and re.fullmatch(_ADDRESS, raws[0]):
        return _cut(_bare(raws[0]), False)   # a link, then a list of what it is
    line = lines[0] = _MARK_RE.sub("", lines[0])
    run_on = (not from_body and len(lines) > 1 and len(line) < TITLE_MIN_SENTENCE_CHARS
              and not _FINISHED_RE.search(line))
    if run_on and len(lines) == len(raws):
        line = _run_on(lines, after_blank)
    elif run_on:
        line = " ".join(lines)
    after = raws[next(i for i, raw in enumerate(raws) if _words(raw, placeholder)) + 1:]
    # A tweet's words after its quote card's byline are the quoted tweet's (without_quote_marks).
    quoted = [w for raw in (content or "").splitlines()[1:] if (w := clean_text(raw))] if _QUOTE_CARD_RE.search(html or "") else []
    return _titled(line, after, run_on, quoted)


def _ends_a_line(html: str, head: str) -> bool:
    """Whether the HTML's text ends a line (a break, a block's or a bold run's end) right after `head`, its
    start (whitespace aside). Only text that says the head can tell: HTML that says something else first,
    or doesn't reach that far (a window of pictures), doesn't."""
    want, seen = _squashed(head), ""
    for line in _html_lines(html).splitlines():
        seen += _squashed(line)
        if seen == want:
            return True
        if not want.startswith(seen):
            return not seen.startswith(want)   # past the head inside one line: no line end there
    return True


def _html_line_head(html: str, title: str) -> str | None:
    """The start of `title` that the HTML's first line with text is (two words at least), when the title
    runs on past it: where the bridge glued the next line on. None when the HTML's line is no start of it."""
    want = _squashed(title)
    line = next((line for line in _html_lines(html).splitlines() if _squashed(line)), "")
    seen = _squashed(line)
    if not seen or len(seen) >= len(want) or not want.startswith(seen) or len(_WORD_RE.findall(line)) < 2:
        return None
    count = 0
    for i, ch in enumerate(title):
        count += not ch.isspace()
        if count == len(seen):
            return title[:i + 1]
    return None


# A quote tweet whose own words are a short reaction ("no! really?!", an emoji alone) is about what it
# quotes (issue 0076, the v9.15 reader review): News leads its row by the quoted tweet's title, said by
# its author (post_parts.subject); its row and its page keep its own words ("the rows are right").
# Measured on the lab (2026-11-04): of the quote tweets with words of their own, those of 4 words or
# fewer read as reactions to the quote ("repent, you meat proxies", "Bourbaki strikes again"); at 5 and
# more most say something of their own. Neither number is tuned past that read.
REACTION_MAX_WORDS = 4
REACTION_MAX_CHARS = 30
_QUOTED_TEXT_RE = re.compile(r'<blockquote>\s*<b>[^<]*</b>(.*?)<footer>', re.I | re.S)


def reaction_title(html: str | None) -> str | None:
    """"<Name>: <the quoted tweet's title>" for a quote tweet whose own words are a short reaction, else None."""
    card = _QUOTE_CARD_RE.search(html or "")
    if not card:
        return None
    own = _quoted_address_re(card.group(2)).sub("", html[:card.start()])
    if re.search(r"<(?:img|video)\b", own, re.I):
        return None
    own = clean_text(_TAG_RE.sub(" ", own))
    quoted = _QUOTED_TEXT_RE.search(html, card.start())
    if not own or len(own) > REACTION_MAX_CHARS or len(_WORD_RE.findall(own)) > REACTION_MAX_WORDS or not quoted:
        return None   # nothing of its own is a quote only (quote_only), read by the quoted words already
    title = display_title(None, _html_lines(quoted.group(1)))
    name = html_lib.unescape(card.group(1)).rsplit("(@", 1)[0].strip()
    return f"{name}: {title}" if title and name else title or None


def _titled(line: str, rest: List[str], run_on: bool, words_after: List[str]) -> str:
    """A line as a title (_without_address, _cut). Issue 0072 D2: a short line that leads to an address on
    the next one (`rest`: "Прочёл:", then the address) reads it, bare, when both fit. A title left an
    address alone (a label and its address, an address alone) reads `words_after`, the words its own text
    has after that address: a glued title's sentence after the address it opens on, the words of the
    tweet it quotes."""
    title = _without_address(line)
    joined = f"{title} {_bare(rest[0].split()[0])}" if rest and _TRAILING_ADDRESS_RE.fullmatch(rest[0]) else ""
    if len(title) < TITLE_MIN_SENTENCE_CHARS and _LEADS_RE.search(title) and not run_on and 0 < len(joined) <= TITLE_MAX_CHARS:
        return joined
    if _TRAILING_ADDRESS_RE.fullmatch(title):
        title = next((_without_address(w.lstrip(". ")) for w in words_after if _words(w)), title)
    return _cut(title, run_on)


def _run_on(lines: List[str], after_blank: set) -> str:
    """A short unfinished first line run on into the lines after it (issue 0069), up to a label's or an
    address's line ("paper: https://…", issue 0072). A name and its subtitle, each a paragraph
    ("NAME", "A Subtitle…"), read "NAME: A Subtitle…"; a title wrapped in
    lines reads as one."""
    out = lines[0]
    for i, line in enumerate(lines[1:], 1):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        label = _LABEL_LINE_RE.fullmatch(line) and (_TRAILING_ADDRESS_RE.search(line) or not nxt or _TRAILING_ADDRESS_RE.fullmatch(nxt))
        if label or _TRAILING_ADDRESS_RE.fullmatch(line):
            break
        named = i == 1 and i in after_blank and out[-1:].isalnum() and line[:1].isupper()
        out += (": " if named else " ") + line
    return out


# A label and its colon, one to three words (issue 0072: "paper:", "Download:", "📝 Blog:"), alone or
# before an address: it says what the address is, never what the post is.
_LABEL = r"\W*[^\W\d_][\w-]*(?: [\w-]+){0,2} ?:"   # "tweet :" too (issue 0072 D2)
_LABEL_LINE_RE = re.compile(rf"{_LABEL}(?:\s*(?:https?://\S+|(?:[\w-]+\.)+[a-zA-Z]{{2,}}/\S*))*\s*")
_TRAILING_ADDRESS_RE = re.compile(r"(?:\s*(?:https?://\S+|(?:[\w-]+\.)+[a-zA-Z]{2,}/\S*))+\s*$")
# Words a sentence doesn't end on, that lead to what follows (issue 0072 D2: "…are now on", "…done by",
# "Moved to", "Quoting"): English and Russian prepositions, "here", a colon or an arrow. The address after
# them is the sentence's object.
_LEADS_RE = re.compile(r"(?:(?:^|\s)(?i:on|at|by|to|in|from|of|for|with|via|into|onto|about|see|here|quoting|"
                       r"в|во|на|по|из|от|к|ко|у|с|со|о|об|для|про|через|тут|здесь)|:|->|→|—|-)$")


def _bare(address: str) -> str:
    """An address as a title: no scheme, no www., no trailing slash ("agentville.world")."""
    return re.sub(r"^https?://(?:www\.)?", "", address).rstrip("/")


def _without_address(line: str) -> str:
    """A title without the address it ends in, nor a label that address leaves alone (issue 0072:
    "Вышла новая модель https://…" is "Вышла новая модель"); after a finished sentence, the words that
    only led to it go too ("Thanks! Details are at"), and words that point at it (":", "->") keep it,
    bare. A title left without words is the address, bare. Issue 0072 D2: an address the words lead to
    (_LEADS_RE: "…are now on", "Moved to", "Quoting") is the sentence's object: it stays, bare."""
    address = _TRAILING_ADDRESS_RE.search(line)
    if not address:
        return line
    words, bare = line[:address.start()].rstrip(" ([{«\"'"), _bare(address.group(0).split()[0])
    if not _WORD_RE.search(words) or _LABEL_LINE_RE.fullmatch(words):
        return bare
    ends = [m.end() for m in SENTENCE_END_RE.finditer(words, TITLE_MIN_SENTENCE_CHARS - 1)]
    if ends and ends[-1] < len(words) and not re.search(r"(?::|->|→|—|-)$", words):
        return words[:ends[-1]]   # "Thanks! Details are at" is "Thanks!"; "website: tool.test" points at it
    return f"{words} {bare}" if _LEADS_RE.search(words) else words


def _cut(line: str, run_on: bool) -> str:
    """A line over 120 characters, or run on, cut at its first sentence end (after 20 characters at
    least), else at the last space within 117 characters, with "…"."""
    if len(line) <= TITLE_MAX_CHARS and not run_on:
        return line
    sentence = SENTENCE_END_RE.search(line, TITLE_MIN_SENTENCE_CHARS - 1)
    if sentence and sentence.end() <= TITLE_MAX_CHARS:
        return line[: sentence.end()]
    if len(line) <= TITLE_MAX_CHARS:
        return line
    head = line[: TITLE_MAX_CHARS - 3]
    space = head.rfind(" ")
    return (head[:space] if space > 0 else head).rstrip() + "…"


_TAG_RE = re.compile(r"(<[^>]*>)")
_EMPTY_P_RE = re.compile(r"<p>\s*</p>\s*", re.I)
_BLOCK_TAG_RE = re.compile(r"</?(?:p|br|h[1-6]|div|li|ul|ol|blockquote|hr|figure|section|header|article|table|tr|pre)\b", re.I)
# What a title taken out of a body leaves at its start: breaks, and elements left empty.
_LEFT_AT_START_RE = re.compile(r"^((?:\s*<(?!br\b)[a-z][^>]*>)*)\s*(?:<br\s*/?>\s*|<([a-z][a-z0-9]*)\b[^>]*>\s*</\2>\s*)+", re.I)


def _block_follows(parts: List[str]) -> bool:
    """Whether a line or a block ends here: a break or a block's tag comes before any more words."""
    for part in parts:
        if part.startswith("<"):
            if _BLOCK_TAG_RE.match(part):
                return True
        elif part.strip():
            return False
    return False


def body_after_title(title: str, body: str | None, *, html: bool = False, line: bool = False) -> str | None:
    """The body without the title it starts with (issue 0070: a title taken from the body isn't read
    twice: the post page's heading, then its text). Whitespace and, in HTML, tags and entities don't
    count (HTML codes are read as what they say). The title must be a whole line or sentence of the
    body: it ends a sentence, a line or a block ends with it, or (`line`) it is known to be a line.
    Unchanged when the title is cut ("…"), isn't the body's start, or is all of it."""
    want = re.sub(r"\s+", "", title or "")
    if not body or not want or TRAILING_ELLIPSIS_RE.search(title):
        return body
    parts = _TAG_RE.split(body) if html else [body]
    out, matched = [], 0
    for index, part in enumerate(parts):
        if matched == len(want) or (html and part.startswith("<")):
            out.append(part)
            continue
        text = html_lib.unescape(part)
        at = 0
        while at < len(text) and matched < len(want):
            if not text[at].isspace():
                if text[at] != want[matched]:
                    return body
                matched += 1
            at += 1
        tail = text[at:]
        # "Notes" is not the title of "Notes on X".
        if matched == len(want) and not (line or _FINISHED_RE.search(title) or "\n" in tail[:len(tail) - len(tail.lstrip())]
                                          or (not tail.strip() and _block_follows(parts[index + 1:]))):
            return body
        out.append(html_lib.escape(tail, quote=False) if html else tail)
    rest = "".join(out)
    rest = _LEFT_AT_START_RE.sub(r"\1", rest).strip() if html else rest.strip()
    words = strip_html(rest) if html else rest
    return rest if matched == len(want) and _WORD_RE.search(words or "") else body


# hnrss's item body (issue 0070): four labelled lines, the article's and the discussion's addresses,
# then the points and the comments ("Points: 1675", "# Comments: 1628"). They are the row's counts,
# never its text; a body with both counts is that shape.
_HNRSS_COUNTS_RE = re.compile(r"Points: (\d+)\s*(?:</p>\s*<p>\s*)?# Comments: (\d+)")
_HNRSS_LINE_RE = re.compile(r"(?:<hr\s*/?>\s*)?<p>\s*(?:Article URL|Comments URL|Points|# Comments):.*?</p>\s*"
                            r"|(?:Article URL|Comments URL): \S+\s*|(?:Points|# Comments): \d+\s*", re.S)


# Reddit's item footer (issue 0072): "submitted by /u/x [link] [comments]", the author and the page the
# post shares; never its text. `[link]` is the shared page (its own thread for a text post).
_SPACE = r"(?:\s|&#32;)*"
_REDDIT_FOOTER_RE = re.compile(rf"{_SPACE}submitted by{_SPACE}/u/\S+{_SPACE}\[link\]{_SPACE}\[comments\]\s*$")
_REDDIT_FOOTER_HTML_RE = re.compile(
    rf'{_SPACE}submitted by{_SPACE}<a\b[^>]*>\s*/u/[^<]*</a>\s*(?:<br\s*/?>)?\s*<span>\s*<a href="([^"]*)">\[link\]</a>\s*</span>'
    rf'{_SPACE}<span>\s*<a\b[^>]*>\[comments\]</a>\s*</span>', re.I)
# A text that opens on a picture's address (a Reddit image post: "https://preview.redd.it/x.png?…"): no words.
_LEADING_PICTURE_RE = re.compile(r"^(?:https?://\S+?\.(?:png|jpe?g|gif|webp)(?:\?\S*)?\s+)+", re.I)


# What a link post shares (issue 0072 D4): a picture (an image file's address), a video on Reddit's video
# host (it plays on the post's thread), else a page.
_PICTURE_URL_RE = re.compile(r"\.(?:png|jpe?g|gif|webp|avif)(?:[?#]|$)", re.I)
VIDEO_HOSTS = ("v.redd.it",)


def link_post_target(html: str | None) -> str | None:
    """The page a Reddit link post shares (its footer's `[link]`), when it is not a Reddit thread (its own,
    or a short link to one); Reddit's picture and video hosts count. Else None."""
    match = _REDDIT_FOOTER_HTML_RE.search(html or "")
    url = html_lib.unescape(match.group(1)) if match else ""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    thread = host == "redd.it" or host == "reddit.com" or host.endswith(".reddit.com")
    return url if url.startswith(("http://", "https://")) and not thread else None


def link_kind(url: str) -> str:
    """"picture", "video" or "page": what a link post's link opens (issue 0072 D4)."""
    if _PICTURE_URL_RE.search(urllib.parse.urlparse(url).path):
        return "picture"
    return "video" if (urllib.parse.urlparse(url).hostname or "").lower() in VIDEO_HOSTS else "page"


def hnrss_counts(content: str | None) -> Dict[str, int] | None:
    """{points, comments} of a Hacker News item as hnrss writes it, else None."""
    match = _HNRSS_COUNTS_RE.search(content or "")
    return {"points": int(match.group(1)), "comments": int(match.group(2))} if match else None


def body_without_feed_lines(body: str | None) -> str | None:
    """A body (text or HTML) without an aggregator's lines: hnrss's four, Reddit's footer (issue 0072:
    a body left with no words, a link post's thumbnail, is empty); any other body as it is."""
    if not body:
        return body
    if _HNRSS_COUNTS_RE.search(body):
        return _HNRSS_LINE_RE.sub("", body).strip()
    if _REDDIT_FOOTER_HTML_RE.search(body):
        rest = _REDDIT_FOOTER_HTML_RE.sub("", body).strip()
        return rest if _WORD_RE.search(strip_html(rest)) else ""
    return _REDDIT_FOOTER_RE.sub("", body).strip() if _REDDIT_FOOTER_RE.search(body) else body


# A title is read from the text's and the HTML's start (issue 0070): every place reads the same start,
# so a post reads one title everywhere (issue 0072 D1). Neither is measured.
TITLE_TEXT_CHARS = 4000
TITLE_HTML_CHARS = 2000


def title_columns(p: str = "p") -> str:
    """The columns post_title reads, in its order, of the posts table aliased `p`."""
    return f"{p}.title, left({p}.content, {TITLE_TEXT_CHARS}), left({p}.content_html, {TITLE_HTML_CHARS})"


def _reading_parts(content: str | None, html: str | None) -> Tuple[str | None, str | None]:
    """A body's text and HTML as the reader reads them: a feed's own lines and a quote card's marks out,
    a picture's leading address no text (issue 0072)."""
    content, html = without_quote_marks(body_without_feed_lines(content), body_without_feed_lines(html))
    return (_LEADING_PICTURE_RE.sub("", content) if content else content), html


def post_title(title: str | None, content: str | None, html: str | None = None) -> str:
    """The title of a stored post, the one every place shows it by (issue 0072 D1: the feed, a tree's
    lines, News, search, Classics, Discover, roundup names, a link's title, the post page). It reads
    the text's and the HTML's start only (title_columns), so the whole body or its start give one title."""
    return display_title(title, *_reading_parts(content and content[:TITLE_TEXT_CHARS], html and html[:TITLE_HTML_CHARS]))


def reading_text(title: str | None, content: str | None, html: str | None = None
                 ) -> Tuple[str, str | None, str | None]:
    """(the title the reader shows, post_title; the text and the HTML under it): a feed's own lines
    out (hnrss), and the title out of the body's start when it was taken from it (issue 0070). Where
    the stored text has lost its line breaks (a tweet's, an RSS body's), its HTML says where the first
    line ended."""
    shown = post_title(title, content, html)
    content, html = _reading_parts(content, html)
    html_after = body_after_title(shown, html, html=True)
    return shown, body_after_title(shown, content, line=html_after != html), html_after


def reposted_by(title: str | None, author: str | None) -> List[str]:
    """Who reposted a tweet, by its title: "RT by @user: …", the author reposting itself aside."""
    match = REPOST_BY_RE.match(title or "")
    return [match.group(1)] if match and author and match.group(1).lower() != author.lower() else []


def build_post_fields(post: Dict[str, Any]) -> Dict[str, Any]:
    """Build the normalised fields reading and deduplication rely on, for one post."""
    title = post.get("title") if isinstance(post, dict) else None
    content = post.get("content") if isinstance(post, dict) else None
    content_html = post.get("content_html") if isinstance(post, dict) else None
    url = post.get("url") if isinstance(post, dict) else None
    raw_lang = post.get("lang") if isinstance(post, dict) else None

    normalized_url = normalize_url(url)
    author = tweet_author(url)
    # A page that moved (issue 0108): its canonical is where it moved; the post keeps its address.
    canonical_url = canonicalize_url(post.get("canonical_url") if isinstance(post, dict) else None) or canonicalize_url(url)
    url_host = extract_url_host(url)
    language_input = "\n".join(
        part
        for part in [title or "", content or "", strip_html(content_html, entities="decode_first")]
        if part
    )
    detected = detect_language(language_input)

    return {
        "lang": raw_lang,
        "language_code": detected["language_code"],
        "language_confidence": float(detected["confidence"] or 0.0),
        "normalized_url": normalized_url,
        "canonical_url": canonical_url or normalized_url,
        "url_host": url_host,
        "content_hash": hash_post_content(title, content, content_html),
        # Attribution (issue 0066): a tweet's account, and the accounts that reposted it.
        "author": author,
        "reposted_by": reposted_by(title, author),
    }
