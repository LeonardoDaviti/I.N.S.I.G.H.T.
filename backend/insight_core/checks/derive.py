"""What a version of the code makes of every stored post (issue 0075 B and C): its title as every page
shows it, the start of its shown text, the page it links out to, and the marks the invariants count.

One pass over the whole copy, in parallel: each worker process reads its share of the posts (by a hash
of the id) on a connection of its own and runs the app's own functions on them (compat), so a check
reads what the pages read. The text is read from the body's first TEXT_WINDOW characters: the start of
the text, and a feed's footer on the short posts that carry one, are inside it (a footer at the end of
a longer body isn't seen; none of the feeds that add one write bodies that long).
"""
from __future__ import annotations

import multiprocessing
import os
import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

TEXT_WINDOW = 8000
TEXT_START = 300
WORD_RE = re.compile(r"[^\W\d_]{2,}", re.U)
# The feeds' own lines (independent of the rules that remove them, so a rule that stops removing one is seen).
FOOTER_RES = {
    "reddit": re.compile(r"submitted by\s+/u/\S+\s+\[link\]\s+\[comments\]"),
    "hnrss": re.compile(r"(?:^|\n|\s)(?:Article URL|Comments URL|Points|# Comments):\s"),
    "nitter": re.compile(r"—\s+https?://\S+/status/\d+\S*\s*$"),
}
BYLINE_RE = re.compile(r"<blockquote>\s*<b>([^<]{1,80}\(@\w+\))</b>", re.I)


@dataclass
class Facts:
    id: str
    source_id: str
    platform: str
    title: str
    text: str                 # the shown text's start (TEXT_START characters)
    has_words: bool           # the stored post has words (title or text)
    repeats_title: bool       # the shown text opens with its title again
    footer: Optional[str]     # a feed's footer kind left in the shown text
    byline: bool              # a quote card's byline left in the shown text
    link: Optional[str]       # the page a link post opens (post_fields.link_post_target)


def squash(text: Optional[str]) -> str:
    return " ".join((text or "").split()).casefold()


def facts(row) -> Facts:
    from insight_core.checks import compat
    pid, source_id, platform, title, content, html, *stored = row
    parts = compat.stored_parts()
    if stored and parts:   # issue 0076: what the pages read, the post's stored parts (its stored title until parsed)
        shown, link_target = (stored[0] if stored[0] is not None else title or ""), stored[5]
        text = (parts[1](content, stored[1:5]) or "")[:TEXT_WINDOW]   # the window the rules read before (above)
    else:
        window = compat.title_window()
        shown = compat.title_function()(title, content and content[:window[0]], html and html[:window[1]])
        reading = compat.reading_function()
        if reading is not None:
            _, text, _ = reading(title, content, html)
        else:
            text = content
        link = compat.link_target_function()
        link_target = link(html) if link else None
    text = text or ""
    head, start = squash(shown).rstrip("…. "), squash(text[: len(shown) + 40])
    footer = next((k for k, rx in FOOTER_RES.items() if rx.search(text)), None)
    card = BYLINE_RE.search(html or "")
    return Facts(
        id=pid, source_id=source_id, platform=platform, title=shown, text=text[:TEXT_START],
        has_words=bool(WORD_RE.search(title or "") or WORD_RE.search(content or "")),
        repeats_title=len(head) >= 12 and not shown.endswith("…") and start.startswith(head),
        footer=footer, byline=bool(card and card.group(1) in text),
        link=link_target,
    )


SQL = f"""SELECT p.id::text, p.source_id::text, s.platform, p.title, left(p.content, {TEXT_WINDOW}), left(p.content_html, {TEXT_WINDOW})
          FROM posts p JOIN sources s ON s.id = p.source_id
          WHERE abs(hashtext(p.id::text)) %% %s = %s"""


# A version that stores each post's parts (issue 0076): its title, its text's cut points (the whole text,
# where they cut) and its link, read as its pages read them.
SQL_PARTS = """SELECT p.id::text, p.source_id::text, s.platform, p.title, p.content, left(p.content_html, {window}),
                      pp.title, {text_columns}, pp.link_target
               FROM posts p JOIN sources s ON s.id = p.source_id LEFT JOIN post_parts pp ON pp.post_id = p.id
               WHERE abs(hashtext(p.id::text)) %% %s = %s"""


def _sql(cur) -> str:
    from insight_core.checks import compat
    parts = compat.stored_parts()
    cur.execute("SELECT to_regclass('post_parts') IS NOT NULL")
    if not parts or not cur.fetchone()[0]:
        return SQL
    return SQL_PARTS.format(window=TEXT_WINDOW, text_columns=", ".join(parts[0].split(", ")[:4]))


def _share(args) -> List[dict]:
    db_url, workers, k = args
    import psycopg
    out = []
    with psycopg.connect(db_url, options="-c default_transaction_read_only=on -c jit=off") as conn:
        with conn.cursor() as plain:
            sql = _sql(plain)
        with conn.cursor(name="facts") as cur:
            cur.itersize = 2000
            cur.execute(sql, (workers, k))
            for row in cur:
                try:
                    out.append(asdict(facts(row)))
                except Exception as e:  # noqa: BLE001 - a post the rules can't read is a finding, not a crash
                    out.append({"id": row[0], "source_id": row[1], "platform": row[2], "title": "", "text": "",
                                "has_words": True, "repeats_title": False, "footer": None, "byline": False, "link": None,
                                "error": f"{type(e).__name__}: {e}"})
    return out


def default_workers() -> int:
    return min(12, max(1, (os.cpu_count() or 2) - 1))


def all_posts(db_url: str, workers: Optional[int] = None) -> Dict[str, dict]:
    """post id -> its Facts (as a dict), for every post of the copy. Read-only."""
    workers = workers or default_workers()
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        shares = pool.map(_share, [(db_url, workers, k) for k in range(workers)])
    return {f["id"]: f for share in shares for f in share}
