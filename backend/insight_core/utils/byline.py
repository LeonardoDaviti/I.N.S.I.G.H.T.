"""Byline: who wrote a post, and via whom (issue 0185). The one place every view asks; display only.

A post's feed is not always its writer. An X feed carries reposts and quotes of other accounts (the stored address is
nitter.local/<author>/status/..., the feed another account's); a Telegram channel forwards other channels' messages
(`metadata.forwarded_from`). The byline, from stored fields only:

  - `author`  : the original writer when the feed did not write it ("@acme" on X, the forward's channel title on
                Telegram), else None (the feed's own post);
  - `via`     : the feed (its source name) that carried it, always;
  - `quoting` : the account whose post it quotes ("@other", post_parts.quoted), else None.

`original_author` is the rule (0168 E): on X a row whose author is not the feed's own account; a Telegram forward's
channel as its header names it. Mark X's renders (`tasks.Post.who`) and the reader's repost field
(`repo_reader.repost_of`) read it here.

Display only: who a post COUNTS as (a voice) is Pairing's rule (`pairing.counted_voice` over `tasks.author_account`:
a repost counts as its author's voice only when a source follows that author). Nothing here changes it.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Iterable, Optional, Tuple

# The stored fields a byline reads, for a query joining posts p, sources s and (LEFT) post_parts pp, in `of_row`'s
# order after the source name: platform, handle, author, forward's name, quoted tweet.
COLUMNS = ("s.platform, s.handle_or_url, p.author, NULLIF(btrim(p.metadata->'forwarded_from'->>'name'), ''), "
           "pp.quoted")
SOURCE_NAME = ("COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''), "
               "s.handle_or_url)")


@lru_cache(maxsize=1024)
def own_account(platform: Optional[str], handle: Optional[str]) -> str:
    """The X account a source follows ("badlogicgames"), else ""."""
    from insight_core.db.repo_stories import source_account
    account = source_account(platform, handle) or ""
    return account[len("x.com/"):] if account.startswith("x.com/") else ""


def original_author(kind: str, platform: Optional[str], handle: Optional[str], author: Optional[str],
                    forwarded: Optional[str], owns: Optional[Dict[Tuple[Any, Any], str]] = None) -> Optional[str]:
    """0168 E: the original author of a post its feed carries but did not write: on X a row whose author is not the
    feed's own account ("@acme", a repost); a Telegram forward's channel as its header names it. None: the feed's
    own post (or unknown)."""
    if kind == "x" and author:
        key = (platform, handle)
        own = owns.get(key) if owns is not None and key in owns else own_account(platform, handle)
        if owns is not None:
            owns[key] = own
        a = author.strip().lstrip("@")
        return "@" + a if own and a and a.casefold() != own.casefold() else None
    if kind == "telegram" and forwarded:
        return forwarded.strip() or None
    return None


def quoting(quoted: Optional[str], *, besides: Iterable[Optional[str]] = ()) -> Optional[str]:
    """"@other": the account whose tweet a post quotes (post_parts.quoted, a tweet's address), None when it quotes
    none or quotes the writer itself (a thread's self-quote is no credit)."""
    from insight_core.utils.addresses import tweet_author
    address = quoted if not quoted or "://" in quoted else "https://" + quoted   # stored normalized; a bare one too
    who = tweet_author(address) if address else None
    if not who:
        return None
    mine = {(b or "").strip().lstrip("@").casefold() for b in besides}
    return None if who.casefold() in mine else "@" + who


def byline(source: Optional[str], platform: Optional[str], handle: Optional[str], author: Optional[str] = None,
           forwarded: Optional[str] = None, quoted: Optional[str] = None, *, kind: Optional[str] = None,
           owns: Optional[Dict[Tuple[Any, Any], str]] = None) -> Dict[str, Optional[str]]:
    """{author, via, quoting} of a post from its stored fields (see the module)."""
    from insight_core.utils.post_links import source_kind
    kind = kind or source_kind(platform, handle)
    by = original_author(kind, platform, handle, author, forwarded, owns)
    own = own_account(platform, handle) if kind == "x" else ""
    return {"author": by, "via": source or "", "quoting": quoting(quoted, besides=(by, own, author if not by else None))}


def of_row(source: Optional[str], platform: Optional[str], handle: Optional[str], author: Optional[str],
           forwarded: Optional[str], quoted: Optional[str],
           owns: Optional[Dict[Tuple[Any, Any], str]] = None) -> Dict[str, Optional[str]]:
    """The byline of a row read with SOURCE_NAME, COLUMNS."""
    return byline(source, platform, handle, author, forwarded, quoted, owns=owns)


def who(b: Dict[str, Optional[str]]) -> str:
    """A render's one line (0168 E's words): the feed, or "a post by @X shared by <feed>"."""
    return f"a post by {b['author']} shared by {b['via']}" if b.get("author") else (b.get("via") or "")


def bylines(cur: Any, ids: Iterable[Any]) -> Dict[str, Dict[str, Optional[str]]]:
    """{post id: byline} for the posts that exist: one query over stored fields."""
    ids = sorted({str(i) for i in ids})
    if not ids:
        return {}
    cur.execute(f"""SELECT p.id::text, {SOURCE_NAME}, {COLUMNS}
                      FROM posts p JOIN sources s ON s.id = p.source_id LEFT JOIN post_parts pp ON pp.post_id = p.id
                     WHERE p.id = ANY(%s::uuid[])""", (ids,))
    owns: Dict[Tuple[Any, Any], str] = {}
    return {pid: of_row(*row, owns=owns) for pid, *row in cur.fetchall()}
