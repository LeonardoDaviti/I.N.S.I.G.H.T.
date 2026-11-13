"""Byline: who wrote a post, and via whom (issue 0185). The one place every view asks; display only.

A post's feed is not always its writer. An X feed carries reposts and quotes of other accounts (the stored address is
nitter.local/<author>/status/..., the feed another account's); a Telegram channel forwards other channels' messages
(`metadata.forwarded_from`). The byline, from stored fields only:

  - `author`  : the original writer when the feed did not write it ("@acme" on X, the forward's channel title on
                Telegram), else None (the feed's own post);
  - `via`     : the feed (its source name) that carried it, always;
  - `quoting` : the account whose post it quotes ("@other", post_parts.quoted), else None.

`original_author` is the rule (0168 E): on X a row whose author is not the feed's own account; a Telegram forward's
channel as its header names it. Mark X's renders (`tasks.Post.who`) and the reader's repost field (`repost_of`) read
it here.

Who wrote a post, as the other modules ask it (issue 0189), is here too:
  - `author_account` (Mark X): the account of a repost's original author (x.com/<user>; t.me/<channel> for a forward
    whose header names it), what Voice counts a followed author's repost as (voice.counted_source);
  - `tweet_account` (Mark IX's story job): the account of a tweet's stored author, whoever it is (the feed's own
    account too): its author's source and the reposters' sources are read through it;
  - `repost_of`: a row its source reposted, {by, author}, for the reader, the post page and Mark X's folds;
  - `is_repost` (source stats; Telegram's adapter's note) and `retold` (the Voices suggestions' older test): whether
    a row is not its source's own post, with the SQL they read (`retweet_sql`, `forwarded_sql`, `reposted_sql`;
    `not_retold_sql`: the stance count's filter);
  - `RT_BY` / `RT_BY_PREFIX`: Nitter's "RT by @user: " title, the one pattern for it.

Display only: who a post COUNTS as (a voice) is Voice's rule (utils/voice.py: `voice.counted_source` over
`author_account`: a repost counts as its author's voice only when a source follows that author). Nothing here
changes it.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

# The stored fields a byline reads, for a query joining posts p, sources s and (LEFT) post_parts pp, in `of_row`'s
# order after the source name: platform, handle, author, forward's name, quoted tweet.
COLUMNS = ("s.platform, s.handle_or_url, p.author, NULLIF(btrim(p.metadata->'forwarded_from'->>'name'), ''), "
           "pp.quoted")
# Nitter's title of a repost: "RT by @user: <text>" (issue 0066). RT_BY_PREFIX is the pattern's text, for a pattern
# that adds to it (x_articles' prefixes, post_parser's cut).
# RT_BY_TAG is the tag alone, for a reader that cuts it with whatever space follows (voice_rules' shingles, series'
# titles: `\s*`, where Nitter writes one space).
RT_BY_TAG = r"RT by @(\w+):"
RT_BY_PREFIX = RT_BY_TAG + " "
RT_BY = re.compile("^" + RT_BY_PREFIX)
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


# ---- who wrote it, as the other modules ask (issue 0189) -------------------------------------------------------

def author_account(kind: str, by: Optional[str], forwarded_user: Optional[str] = None) -> Optional[str]:
    """The account (Mark IX's form, repo_stories.source_account's) of a repost's original author (`by`:
    original_author's "@acme"): x.com/<user> for an X repost, t.me/<channel> for a Telegram forward whose header names
    the channel; None otherwise (a forward by name alone names no account)."""
    from insight_core.utils.addresses import x_account
    if kind == "x" and by:
        return x_account(by.lstrip("@"))
    if kind == "telegram" and by and forwarded_user:
        return "t.me/" + forwarded_user.lstrip("@").lower()
    return None


def tweet_account(author: Optional[str]) -> Optional[str]:
    """Mark IX's account of a tweet's stored author (x.com/<author> as stored, whoever wrote it: the feed's own account
    too), else None. The story job reads a tweet's author's source and its reposters' sources through it; unlike
    `author_account` it reads X only (a Telegram forward's channel is no author here) and never asks whether the
    feed wrote it."""
    from insight_core.utils.addresses import x_account
    return x_account(author) if author is not None else None


def repost_of(platform: Optional[str], handle: Optional[str], author: Optional[str],
              reposted_by: Optional[Sequence[str]]) -> Optional[Dict[str, Any]]:
    """A row its source reposted (issue 0066): {by, author}, `by` the other accounts of yours that
    reposted it, never the row's own source (issue 0070: "badlogicgames ↻ from @thsottiaux"). None
    when the row's source didn't repost it (its author's own tweet, the others said in its story).
    Who wrote it is `original_author`; `by` is who else reposted it."""
    own = own_account(platform, handle)
    if not original_author("x", platform, handle, author, None) or own not in [a.lower() for a in reposted_by or ()]:
        return None
    return {"by": [a for a in reposted_by or () if a.lower() != own], "author": author}


def is_retweet(title: Optional[str]) -> bool:
    """Nitter's "RT by @" title."""
    return (title or "").startswith("RT by @")


def is_repost(kind: Optional[str], platform: Optional[str], handle: Optional[str], own: Optional[str],
              title: Optional[str], author: Optional[str], reposted_by: Any, forwarded: Any = False) -> bool:
    """Not the source's own post (source stats): a Telegram forward (Part C3's "forwarded from"), a retweet ("RT by
    @", or a row its source reposted, issue 0066), or on X a post another account wrote. `own`: the source's account
    (repo_stories.source_account's form, "x.com/<user>")."""
    if forwarded or is_retweet(title):
        return True
    if repost_of(platform, handle, author, reposted_by) is not None:
        return True
    if kind == "x" and author and own:
        return author.lower().lstrip("@") != own.split("/", 1)[-1]
    return False


def retold(kind: Optional[str], own_handle: Optional[str], author: Optional[str], reposted: bool,
           retweet: bool) -> bool:
    """The Voices suggestions' test (repo_voices.channels) of a row that is not its source's own post: any account
    of yours reposted it (`reposted`: reposted_sql), a retweet (`retweet`: retweet_sql), or on X another account
    wrote it. Unlike `is_repost` it never reads a Telegram forward, and a row anyone reposted is one whoever wrote
    it (issue 0189 keeps both as they were)."""
    return bool(reposted or retweet or (kind == "x" and author and author.lower().lstrip("@") != own_handle))


def retweet_sql(alias: str = "p") -> str:
    """A row whose title is Nitter's "RT by @" (SQL; for a query with parameters)."""
    return f"COALESCE({alias}.title, '') LIKE 'RT by @%%'"


def forwarded_sql(alias: str = "p") -> str:
    """A Telegram forward (SQL)."""
    return f"({alias}.metadata ? 'forwarded_from')"


def reposted_sql(alias: str = "p") -> str:
    """A row an account of yours reposted (posts.reposted_by not empty; SQL)."""
    return f"COALESCE(cardinality({alias}.reposted_by), 0) > 0"


def not_retold_sql(alias: str = "p") -> str:
    """Neither a retweet nor a Telegram forward (SQL): the stance count's filter, which reads no author."""
    return f"NOT {retweet_sql(alias)} AND NOT {forwarded_sql(alias)}"
