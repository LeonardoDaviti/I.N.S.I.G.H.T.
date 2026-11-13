"""Voice (issue 0189): who a post counts as, and how many voices a set of posts is. The one place that says so.

A voice is an independent source of a post (GLOSSARY.md). Two engines count them, by rules that still differ, so
the module names each rule as a policy and every caller says which one it counts by:

  - `Policy.MARKX` (Mark X; Pairing's rule): a post's voice is its source, or, for a repost a source of yours carries
    of an account another source of yours follows, that source (`counts_as`: Byline says who wrote it,
    `counted_source` which source that is). A saved post is no voice. Posts of one voice are one; nothing else
    merges them.
  - `Policy.STORIES_IX` (Mark IX's stories): a post's voice is its publication for a website (two website sources
    of one publication are one voice), its poster on Reddit (a person, not the subreddit), else its source; a
    confirmed voice's channels (0132 A) are one voice. A post's copies of one text (120+ characters) are one voice
    whatever their sources, and the sources that reposted a tweet, or wrote the tweet another source holds, are
    voices besides the post's own (0068). A saved post is no voice.
  - `Policy.NEWS_IX` (Mark IX's News, 0111): STORIES_IX with every owner's channels one voice, not only the
    confirmed ones.

The interface:
  - `voice_of(post, policy)`: the key a post counts as (a string; equal keys are one voice);
  - `count(posts, policy)`: how many voices the posts are;
  - `others_of(post, policy)`: Mark IX's other voices of a post (its tweet's author's source, its reposters);
  - `groups(items)`: Mark IX's voices among (key, text key, voice) items (copies of one text one voice), for the
    names a count reads as (story_rules.named_voices);
  - `is_voice(kind)`, `independent(...)`, `counted_source(...)`, `followed_accounts(cur)`: Mark X's basics.

The keys are this module's: no caller builds or reads one by hand. Mark IX's are stored (story_posts.voice,
news_posts.voice, the News owners in system settings, Discover's addresses), so their forms never change; the
constructors (`key`, `source_key`, `site_key`, `poster_key`, `confirmed_key`, `channel_key`) and readers (`poster`,
`source_of`, `is_site`, `is_confirmed`, `owner_of`, `channel_of`) are the only way in or out, and `key_sql` /
`source_key_sql` / `site_key_sql` / `POSTER_LIKE` say the same in a query.

Who wrote a post (a repost's author, a forward's channel) is Byline's (utils/byline.py); this module only says
which voice that makes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class Policy(Enum):
    MARKX = "markx"
    STORIES_IX = "stories_ix"
    NEWS_IX = "news_ix"


NOT_VOICE = frozenset({"saved"})      # a post the owner saved is no independent voice (both engines)

# ---- the keys (private forms; Mark IX's are stored, never change them) ---------------------------------------

_SITE, _POSTER, _SOURCE, _CONFIRMED = "site:", "reddit:", "source:", "voice:"
_CHANNEL_VOICE, _CHANNEL = "v:", "s:"        # source_stats' per-channel keys (in memory only)


def key(kind: Optional[str], source_id: str, site: str = "", author: Optional[str] = None) -> str:
    """A post's own voice in Mark IX's form (StoryPost.voice, stored as story_posts.voice): its publication for a
    website, its poster on Reddit, else its source."""
    if kind == "site":
        return _SITE + site
    if kind == "reddit" and author:
        return _POSTER + author
    return _SOURCE + source_id


def source_key(source_id: str, kind: Optional[str] = None, site: str = "") -> str:
    """A source's own voice (no poster): its publication for a website, else the source. A reposting source's
    voice, as StoryPost tells an X account's (0068), is `source_key(id)`."""
    return _SITE + site if kind == "site" else _SOURCE + source_id


def site_key(publication: str) -> str:
    """A publication's voice (a website's)."""
    return _SITE + publication


def poster_key(name: str) -> str:
    """A Reddit poster's voice, by name as given (SourceFacts lowercases the names it keys owners by)."""
    return _POSTER + name


def confirmed_key(voice_id: str) -> str:
    """A voice the owner confirmed (0132 A: its channels are one voice in stories and News)."""
    return _CONFIRMED + voice_id


def is_confirmed(k: Optional[str]) -> bool:
    return bool(k) and k.startswith(_CONFIRMED)


def poster(k: Optional[str]) -> Optional[str]:
    """A Reddit poster's name, when the key is one."""
    return k.split(":", 1)[1] if k and k.startswith(_POSTER) else None


def is_poster(k: Optional[str]) -> bool:
    return bool(k) and k.startswith(_POSTER)


def source_of(k: Optional[str]) -> Optional[str]:
    """The source a source's key names (None for a publication, a poster or a confirmed voice)."""
    return k[len(_SOURCE):] if k and k.startswith(_SOURCE) else None


def is_site(k: Optional[str]) -> bool:
    return bool(k) and k.startswith(_SITE)


def site_of_key(k: str) -> str:
    """A publication's key's publication."""
    return k[len(_SITE):]


def owner_of(owners: Mapping[str, str], k: str) -> Optional[str]:
    """A voice's owner's voice in `owners` (SourceFacts.owners, as the story job keeps them), when another: a Reddit
    poster by its lowercased name."""
    return owners.get(k.lower() if k.startswith(_POSTER) else k)


def channel_key(source_id: str, voice_id: Optional[str] = None) -> str:
    """source_stats' voice of a channel: its confirmed voice's (0132 A), else its own."""
    return f"{_CHANNEL_VOICE}{voice_id}" if voice_id else f"{_CHANNEL}{source_id}"


def channel_of(k: str) -> Tuple[str, str]:
    """("voice", voice id) or ("source", source id) of a channel key; ("", the rest) of any other (a Mark IX key)."""
    kind, _, rest = k.partition(":")
    return {"v": "voice", "s": "source"}.get(kind, ""), rest


def story_channel_key(stored: Optional[str], source_id: str, voice_id: Optional[str] = None) -> str:
    """source_stats' voice of a story member: its channel's (channel_key) when Mark IX keyed it by its source (or not
    at all), else Mark IX's stored key (a Reddit poster, a publication)."""
    if not stored or stored.startswith(_SOURCE):
        return channel_key(source_id, voice_id)
    return stored


def key_sql(kind: str, site: str, author: str, source_id: str) -> str:
    """`key` as SQL over these column expressions."""
    return (f"(CASE WHEN {kind} = 'site' THEN '{_SITE}' || {site} "
            f"WHEN {kind} = 'reddit' AND {author} IS NOT NULL THEN '{_POSTER}' || {author} "
            f"ELSE '{_SOURCE}' || {source_id}::text END)")


def source_key_sql(kind: str, site: str, source_id: str) -> str:
    """`source_key` as SQL over these column expressions."""
    return f"CASE WHEN {kind} = 'site' THEN '{_SITE}' || {site} ELSE '{_SOURCE}' || {source_id}::text END"


def site_key_sql(site: str) -> str:
    return f"'{_SITE}' || {site}"


POSTER_LIKE = _POSTER + "%%"        # a LIKE pattern (a query with parameters) for a poster's key


# ---- what a post counts as -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Said:
    """What Mark X counts a post by: its source, its kind, and the source its original author is when one of your
    sources follows that author (`counts_as`, from `counted_source`)."""
    source_id: Any
    kind: Optional[str] = None
    counts_as: Optional[str] = None


def is_voice(kind: Optional[str]) -> bool:
    return kind not in NOT_VOICE


def independent(source_a: Any, kind_a: Optional[str], source_b: Any, kind_b: Optional[str]) -> bool:
    """Two posts are independent voices (Mark X): both voices, of different sources."""
    return is_voice(kind_a) and is_voice(kind_b) and source_a != source_b


def counted_source(source_id: str, author_account: Optional[str], of_account: Mapping[str, str]) -> str:
    """The source a post counts as under MARKX (Mark IX's rule, StoryPost.author_source, issue 0068): a post its feed
    carries but another account wrote (an X repost; a Telegram forward naming its channel) counts as that account's
    source when one of the sources follows that account (`of_account`: account -> the first source by id following
    it, `followed_accounts`); a stranger's post stays the feed's own voice. A quote or a reply is the feed's own post:
    its quoted or replied-to account never adds a voice."""
    return (of_account.get(author_account) if author_account else None) or source_id


def followed_accounts(cur: Any) -> Dict[str, str]:
    """Every source's account -> the source following it, as Mark IX reads it (SourceFacts.of_account: its own rule
    over every source's platform and handle, the first by id; issue 0068)."""
    from insight_core.db.repo_stories import SourceFacts
    cur.execute("SELECT id, platform, handle_or_url, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), "
                "handle_or_url) FROM sources")
    return dict(SourceFacts.of(cur.fetchall(), []).of_account)


def voice_of(post: Any, policy: Policy) -> str:
    """The key `post` counts as. MARKX reads .source_id, .counts_as (a Said, tasks.Post); the Mark IX policies read a
    StoryPost (.kind, .source_id, .own_site, .author, .owner)."""
    if policy is Policy.MARKX:
        return getattr(post, "counts_as", None) or post.source_id
    own = key(post.kind, post.source_id, post.own_site, post.author)
    if policy is Policy.NEWS_IX:
        return post.owner or own
    return post.owner if is_confirmed(post.owner) and post.kind != "reddit" else own


def others_of(post: Any, policy: Policy) -> List[str]:
    """Mark IX: the voices of a StoryPost's other sources (its tweet's author's source, the sources that reposted it),
    in other_sources' order; under NEWS_IX each as its owner's, under STORIES_IX a confirmed voice's still."""
    owners = post.other_owners
    by_owner = policy is Policy.NEWS_IX
    return [(owners[k] if k < len(owners) and owners[k] and (by_owner or is_confirmed(owners[k])) else None)
            or source_key(s) for k, s in enumerate(post.other_sources)]


def count(posts: Iterable[Any], policy: Policy) -> int:
    """How many voices `posts` are, by `policy` (see the module). A saved post is none under every policy."""
    if policy is Policy.MARKX:
        return len({voice_of(p, policy) for p in posts if is_voice(p.kind)})
    posts = [p for p in posts if is_voice(p.kind)]
    return len(groups([*((p.id, p.text_key, voice_of(p, policy)) for p in posts),
                       *((f"{p.id}>{s}", None, v) for p in posts
                         for s, v in zip(p.other_sources, others_of(p, policy)))]))


def groups(items: Iterable[Tuple[Any, Optional[str], str]]) -> List[List[Any]]:
    """Mark IX's voices among `items` ((node, text key, voice key) each: a post, or a source that wrote or reposted
    the tweet a post holds, issue 0068): items of one voice, and copies of one text, are one voice. Each voice is its
    items' nodes in the order given, the voices in the order of their first."""
    from insight_core.utils.story_rules import _UnionFind   # story_rules imports this module
    uf = _UnionFind()
    keys: Dict[str, Any] = {}
    order = []
    for node, text, voice in items:
        order.append(node)
        uf.find(node)
        for k in (("text:" + text) if text else None, "voice:" + voice):
            if k is None:
                continue
            if k in keys:
                uf.union(node, keys[k])
            else:
                keys[k] = node
    out: Dict[Any, List[Any]] = {}
    for node in order:
        out.setdefault(uf.find(node), []).append(node)
    return list(out.values())


__all__ = ["Policy", "Said", "NOT_VOICE", "voice_of", "count", "others_of", "groups", "is_voice", "independent",
           "counted_source", "followed_accounts", "key", "source_key", "site_key", "poster_key", "confirmed_key",
           "is_confirmed", "poster", "is_poster", "source_of", "is_site", "site_of_key", "owner_of", "channel_key",
           "channel_of", "story_channel_key", "key_sql", "source_key_sql", "site_key_sql", "POSTER_LIKE"]
