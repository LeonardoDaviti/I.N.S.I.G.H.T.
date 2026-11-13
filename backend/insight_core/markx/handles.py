"""A person's handles (issue 0168 A-D): which posts cite an account, by a deterministic rule over the post's FULL text,
and which handles are whose, learned from "Display Name (@handle)" pairs and confirmed by the owner once.

**The rule (A).** A post cites a handle when its whole title and text (not the 1.5k / 6k characters the entities guide
reads: E7 found 31% of the gain in long round-ups), its kept links, or its author fields say so, in one of these forms:

  - `repost`  : a repost of another account's post (an X feed's row whose author is not the feed's account; a Telegram
                forward's channel when the header names it)                                         -> role `by`
  - `quote`   : the tweet a post quotes (post_parts.quoted)                                         -> role `by`
  - `embed`   : an embedded tweet as a page writes it out ("— Name (@handle) May 3, 2026")          -> role `by`
  - `status`  : a link to one of the account's posts (x.com / twitter / nitter / xcancel / fx... status links, a Bluesky
                post, a Telegram channel's post). It names the cited post's AUTHOR, never its subject -> role `source`
  - `said`    : "@h said / confirmed / announced ...", "@h: ...", "according to @h"                 -> role `source`
  - `at`      : any other @mention                                                                  -> role `mention`
  - `profile` : a link to the account's profile                                                     -> role `mention`
  - `reply`   : the post replies to the account ("R to @h:")                                        -> role `reply` (hidden
                by default)

An `@h` is an X handle outside Telegram posts; in a Telegram post it is a Telegram channel or user. Never an e-mail, a
CSS / BibTeX / code at-word, a path's `/@user`, a Mastodon `@user@host`, or a bare word (E7: bare words 67% right). The
post's own account (its source's) is never cited by its own post: the person's own sources are "By" (0144 B1).
**Boilerplate**: a citation whose sentence 3+ posts of one source repeat (digits outside addresses aside), or a mention
whose nearest words (the word before, the handle, the word after) 5+ posts of one source repeat, is the source's
furniture, not a citation (E7's one error class: a round-up's section header "The <Group> @x Discord has no new
messages" in 93 issues); found at read time from the refs' line keys, nothing hard-coded.

**Handles are keyed by platform** (x, github, telegram, bluesky, hf): the same handle on two platforms is two accounts
(E7: GitHub's same handle was a different person), joined only by a declared link (0162's research).

**Pairs (C).** "Display Name (@handle)" in a post's text (a quote's header, a round-up's "Tweet from Name (@h)"): E7
measured 580 of 583 agreeing. Each pair is stored; `learn` proposes a handle for the person or org whose name the pairs
agree on (2+ posts, AGREE share), one owner question (mx_entity_queue kind `handle`); a second handle paired with the
same name is offered as that entity's other handle, with the time range its pairs span (a renamed account). Never a
handle from a name alone: only pairs, the person's own followed accounts, or the owner.

**Names from handles (D).** An entity named by a handle ("ikestrel" typed an org) whose handle's pairs agree on a display
name: when an entity of that name exists, an alias question (the owner merges); otherwise a `handle` question whose
yes keeps the handle and shows the display name (entity_repair.shown reads `learned_names`).

Stored in mx_handle_scans / mx_handle_refs / mx_handle_pairs (one row set a post's digest: a post read again under a
new rule or new text gets a new set; the old rows stay, unread) and mx_entity_handles (the owner's answers, newest
counts). Migration 0112.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from insight_core.markx import pairing

from insight_core.utils import byline

STAMP = "handles-v1"
PLATFORMS = ("x", "github", "telegram", "bluesky", "hf")
ROLE = {"repost": "by", "quote": "by", "embed": "by", "status": "source", "said": "source", "reply": "reply",
        "at": "mention", "profile": "mention"}
BY_FORMS = ("repost", "quote", "embed")
SOURCE_FORMS = ("status", "said")
BOILER_POSTS = 3          # a line holding the handle that this many posts of one source repeat is boilerplate
BOILER_WINDOW = 5         # ... and a mention's words around it (the word before, the handle, the word after)
PAIR_MIN = 2              # pairs (separate posts) that must agree before a handle is proposed
AGREE = 0.9               # ... and the share of the handle's pairs they must be
PROPOSE_LIMIT = 50        # handle questions a run may add
SCAN_BATCH = 500          # posts a run scans at a time (newest first), within its deadline
SCAN_LIMIT = 5000         # ... and at most this many a run (the backfill CLI has none)
SNIPPET = 160
LINE_MAX = 240

# ---- the pure rule ---------------------------------------------------------------------------------------------

_H = r"[A-Za-z0-9_]{1,15}"
AT = re.compile(r"(?<![\w@./\-+=:#&%~`\\])@([A-Za-z0-9_]{1,32})(?![\w@])")
BSKY_AT = re.compile(r"(?<![\w@./\-+])@((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,})(?![\w@.-])", re.I)
X_LINK = re.compile(r"(?<![\w.@-])(?:https?://)?(?:www\.|mobile\.|m\.)?(?:x|twitter)\.com/(?:#!/)?(" + _H + r")"
                    r"(?:/status(?:es)?/(\d+))?(?![A-Za-z0-9_])", re.I)
X_MIRROR = re.compile(r"https?://(?:nitter\.[a-z0-9.-]+|xcancel\.com|fxtwitter\.com|vxtwitter\.com|fixupx\.com"
                      r"|fixvx\.com)/(" + _H + r")(?:/status/(\d+))?(?![A-Za-z0-9_])", re.I)
BSKY_LINK = re.compile(r"https?://bsky\.app/profile/([A-Za-z0-9._:-]+)(?:/post/([a-z0-9]+))?", re.I)
TG_LINK = re.compile(r"(?<![\w.@-])(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})(?:/(\d+))?"
                     r"(?![A-Za-z0-9_/])", re.I)
GH_LINK = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/?(?=$|[\s\"'<>)?#])", re.I)
HF_LINK = re.compile(r"https?://(?:www\.)?huggingface\.co/([A-Za-z0-9][A-Za-z0-9_.-]{0,95})/?(?=$|[\s\"'<>)?#])", re.I)
# a platform's own pages, never an account (a vocabulary of page kinds, not a site list)
RESERVED = {
    "x": {"i", "search", "home", "hashtag", "intent", "share", "settings", "explore", "messages", "notifications",
          "login", "logout", "signup", "tos", "privacy", "compose", "status", "account", "about", "jobs", "download",
          "en", "rss", "pic", "web", "help", "who_to_follow", "lists", "communities", "premium", "following",
          "followers", "media", "likes", "x", "twitter", "verified", "topics", "moments", "articles"},
    "github": {"about", "features", "topics", "trending", "orgs", "organizations", "explore", "marketplace", "pricing",
               "login", "join", "settings", "notifications", "issues", "pulls", "sponsors", "collections", "events",
               "security", "enterprise", "team", "customer-stories", "readme", "site", "apps", "codespaces", "new",
               "search", "blog", "contact", "home", "dashboard", "github", "copilot", "solutions", "resources"},
    "hf": {"models", "datasets", "spaces", "docs", "blog", "papers", "collections", "organizations", "learn", "posts",
           "pricing", "login", "join", "settings", "enterprise", "chat", "tasks", "new", "search", "huggingface",
           "api", "terms-of-service", "privacy", "inference-endpoints", "join-community", "changelog"},
    "telegram": {"joinchat", "addstickers", "share", "proxy", "socks", "iv", "addemoji", "setlanguage", "login",
                 "contact", "boost", "addlist", "s", "c"},
    "bluesky": set(),
}
# at-words of style sheets, citation files and code (CSS at-rules, BibTeX entries, decorators and doc tags): a
# vocabulary of languages, not of accounts
CODE_WORDS = {
    "media", "import", "keyframes", "charset", "supports", "font", "page", "namespace", "layer", "container",
    "property", "apply", "tailwind", "mixin", "include", "extend", "use", "forward", "each", "if", "else", "return",
    "article", "inproceedings", "book", "misc", "techreport", "phdthesis", "mastersthesis", "incollection", "online",
    "staticmethod", "classmethod", "dataclass", "abstractmethod", "cached_property", "override", "overload",
    "param", "returns", "throws", "deprecated", "author", "since", "see", "todo", "fixme", "type", "typedef",
    "interface", "implementation", "end", "synthesize", "autoreleasepool", "objc", "pytest", "fixture",
    "component", "injectable", "input", "output", "ngmodule", "entity", "column", "controller", "autowired", "bean",
    "test", "suppresswarnings", "functionalinterface", "jsonproperty", "requestmapping", "everywhere", "here",
    "channel", "all", "everyone", "latest", "next", "types", "babel", "angular", "vue", "nestjs", "storybook",
    "testing", "emotion", "mui", "radix", "tanstack", "trpc", "remix", "sveltejs",
    "searchable", "function", "predictions", "connection", "aws_subscribe", "aws_auth", "skip", "defer", "stream",
    "client", "export", "unique", "relation", "default", "map", "index", "id", "updatedat", "createdat", "auth",
    "model", "key", "http", "aws_cognito_user_pools", "aws_iam", "aws_api_key", "aws_lambda", "aws_oidc",
}
SAID_AFTER = re.compile(r"\s*(?:\)\s*)?(?::(?!//)|,?\s+(?:has\s+|had\s+|just\s+|also\s+)?(?:said|says|confirm(?:s|ed)|"
                        r"announc(?:es|ed)|wr(?:ote|ites)|post(?:s|ed)|tweet(?:s|ed)|shar(?:es|ed)|not(?:es|ed)|"
                        r"report(?:s|ed)|explain(?:s|ed)|argu(?:es|ed)|claim(?:s|ed)|reveal(?:s|ed)|teas(?:es|ed)|"
                        r"hint(?:s|ed)|stat(?:es|ed)|declar(?:es|ed)|admit(?:s|ted)|predict(?:s|ed)|warn(?:s|ed)|"
                        r"thinks|believes|suggest(?:s|ed)|recommend(?:s|ed))\b)", re.I)
SAID_BEFORE = re.compile(r"(?:(?:according to|per|says|said|via|h/t|hat tip(?: to)?|quoting)\s*"
                         r"|(?:tweet|post) from\s[^()\n@]{1,60}\(|quoting\s[^()\n@]{1,60}\()$", re.I)
EMBED = re.compile(r"[—–-]\s*([^\n()@—–]{1,60}?)\s*\(@(" + _H + r")\)\s*"
                   r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s*\d{4}|\d{4}-\d\d-\d\d)", re.I)
PAIR = re.compile(r"([^\s()@\[\]][^()@\[\]\n]{0,80}?)\s?\(@(" + _H + r")\)")
PAIR_LEAD = {"tweet", "tweets", "quoting", "quote", "from", "by", "rt", "via", "replying", "retweeted", "reposted",
             "post", "thread", "on", "x", "twitter", "see", "follow", "and", "with", "cc"}
PAIR_CUT = re.compile(r"[.!?:;|•·—–\"“”«»#*_>\[\]]|\s-\s|\bby\b|\bfrom\b", re.I)
NOT_NAMES = {"it", "this", "that", "here", "there", "me", "him", "her", "them", "us", "you", "post", "thread", "link",
             "tweet", "source", "credit", "photo", "video", "image", "pic", "account", "profile", "below", "above"}
UNIT = re.compile(r"^\d+(?:[a-z]{1,2}|x|px|pm|am)?$", re.I)
REPLY = re.compile(r"^R to @(\w+): ")
REPOST = byline.RT_BY   # Nitter's "RT by @x: " (Byline's one pattern, issue 0189)


@dataclass(frozen=True)
class Ref:
    platform: str
    handle: str              # casefolded
    shown: str               # as written
    form: str
    status: Optional[str] = None
    line: Optional[str] = None      # the line's key (boilerplate), None for an author field or a kept link
    snippet: Optional[str] = None

    @property
    def role(self) -> str:
        return ROLE[self.form]


@dataclass(frozen=True)
class Pair:
    platform: str
    handle: str
    name: str


def role_of(forms: Iterable[str]) -> str:
    """A post's role for one handle from its forms: by (it carries their post), then source (it relays what they
    said), then reply (it answers them: hidden by default), then mention."""
    fs = set(forms)
    if fs & set(BY_FORMS):
        return "by"
    if fs & set(SOURCE_FORMS):
        return "source"
    if "reply" in fs:
        return "reply"
    return "mention"


URL = re.compile(r"https?://\S+|\b[\w.-]+\.[a-z]{2,}/\S*", re.I)
WORD = re.compile(r"[^\W\d_]")


def _fold(s: str) -> str:
    """Case and spaces folded, digits read as 0 outside addresses (a status id keeps a quoted tweet's link apart)."""
    out, last = [], 0
    for m in URL.finditer(s):
        out.append(re.sub(r"\d", "0", s[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(re.sub(r"\d", "0", s[last:]))
    return re.sub(r"\s+", " ", "".join(out).casefold()).strip()


def _line_at(text: str, pos: int, window: bool = False) -> Tuple[str, str]:
    """(the key of the line holding `pos`, a short snippet around it). A long line is narrowed to its sentence;
    folded (_fold: case, spaces, digits outside addresses) ("s:" keys). `window` (a plain @mention or a profile link):
    the nearest word before, the handle and the nearest word after, punctuation skipped ("w:" keys): a round-up's
    section header ("<Group> @h Discord <the next item's title>") repeats there though its sentence never does, while
    a list of handles ("@a , @h , and @b") keeps its neighbours."""
    snip = re.sub(r"\s+", " ", text[max(0, pos - SNIPPET // 2): pos + SNIPPET // 2]).strip()
    if window:
        before = [t for t in re.findall(r"\S+", text[max(0, pos - 60):pos]) if WORD.search(t)][-1:]
        here = re.findall(r"\S+", text[pos:pos + 80])
        after = [t for t in here[1:] if WORD.search(t)][:1]
        words = _fold(" ".join(before + here[:1] + after))
        return "w:" + hashlib.sha1(words.encode()).hexdigest()[:16], snip
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    end = len(text) if end < 0 else end
    if end - start > LINE_MAX:
        s = max(text.rfind(". ", start, pos), text.rfind("! ", start, pos), text.rfind("? ", start, pos))
        start = s + 2 if s >= 0 else max(start, pos - LINE_MAX // 2)
        cands = [i for i in (text.find(". ", pos, end), text.find("! ", pos, end), text.find("? ", pos, end)) if i >= 0]
        end = min(cands) + 1 if cands else min(end, pos + LINE_MAX // 2)
    return "s:" + hashlib.sha1(_fold(text[start:end]).encode()).hexdigest()[:16], snip


def _ok(platform: str, handle: str) -> bool:
    h = handle.casefold()
    if not h or h in RESERVED.get(platform, ()) or UNIT.match(h):
        return False
    if platform == "x" and not re.fullmatch(r"[a-z0-9_]{2,15}", h):
        return False
    if platform == "telegram" and not re.fullmatch(r"[a-z][a-z0-9_]{3,31}", h):
        return False
    return True


def links_in(text: str) -> List[Tuple[str, str, str, Optional[str], int]]:
    """[(platform, handle as written, form, status id, position)] of the account and post links in `text`."""
    out = []
    for rx, platform in ((X_LINK, "x"), (X_MIRROR, "x"), (BSKY_LINK, "bluesky"), (TG_LINK, "telegram"),
                         (GH_LINK, "github"), (HF_LINK, "hf")):
        for m in rx.finditer(text or ""):
            h = m.group(1)
            status = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            if platform == "bluesky" and h.startswith("did:"):
                continue
            if _ok(platform, h):
                out.append((platform, h, "status" if status else "profile", status, m.start()))
    return out


def _clean_name(raw: str) -> Optional[str]:
    """A pair's display name: the words right before "(@h)", cut at the sentence's punctuation, without a lead word
    ("Tweet from", "Quoting"); a long run keeps its trailing capitalised words; None when nothing name-like is left."""
    s = html.unescape(raw).strip()
    s = PAIR_CUT.split(s)[-1].strip()
    words = s.split()
    while words and words[0].casefold().strip(",") in PAIR_LEAD:
        words = words[1:]
    if not words:
        return None
    if len(words) > 4 or (len(words) > 1 and not words[0][:1].isupper()):
        tail: List[str] = []
        for w in reversed(words):
            if w[:1].isupper() and len(tail) < 4:
                tail.insert(0, w)
            else:
                break
        words = tail
    name = " ".join(words).strip(" ,")
    if not name or len(name) > 60 or not re.search(r"[^\W\d_]", name) or name.casefold() in NOT_NAMES:
        return None
    return name


def scan(*, kind: str, own: Optional[str], title: str, text: str, links: Sequence[str] = (), author: Optional[str] = None,
         quoted: Optional[str] = None, forwarded: Optional[str] = None) -> Tuple[List[Ref], List[Pair]]:
    """The handle refs and name pairs of one post (pure). `kind`: its source's kind (tasks.Post.kind); `own`: the
    source's own account on its platform ("x:handle", "telegram:channel", ...), never cited by its own post;
    `title`: the stored title (Nitter's "RT by @x:" / "R to @x:" read); `links`: its kept links' addresses; `author`:
    posts.author; `quoted`: the tweet it quotes (post_parts.quoted); `forwarded`: a Telegram forward's channel."""
    at_platform = "telegram" if kind == "telegram" else "x"
    own_p, _, own_h = (own or "").partition(":")
    refs: Dict[Tuple[str, str, str], Ref] = {}

    def add(platform: str, handle: str, form: str, *, status: Optional[str] = None, pos: Optional[int] = None,
            body: str = "") -> None:
        h = handle.casefold()
        if not _ok(platform, h) or (platform == own_p and h == own_h.casefold()):
            return
        key = (platform, h, form)
        if key in refs:
            return
        line = snip = None
        if pos is not None:
            line, snip = _line_at(body, pos, window=form in ("at", "profile"))
        refs[key] = Ref(platform, h, handle, form, status, line, snip)

    raw_title = title or ""
    reply = REPLY.match(raw_title)
    if reply:
        add("x", reply.group(1), "reply")
    if kind == "x" and author:
        a = author.lstrip("@")
        if own_p == "x" and a.casefold() != own_h.casefold():
            add("x", a, "repost")
    if kind == "telegram" and forwarded:       # a forward whose header names the channel's username
        add("telegram", forwarded.lstrip("@"), "repost")
    if quoted:
        for platform, h, form, status, _pos in links_in(quoted):
            if form == "status":
                add(platform, h, "quote", status=status)
    body = REPOST.sub("", REPLY.sub("", raw_title)) + "\n" + (text or "")
    pairs: List[Pair] = []
    claimed: Set[int] = set()   # an embed's "(@h)" is its embed, not a mention too
    # v10.16: an embed and a pair both hold "(@": a body without one has neither, and PAIR's lazy name tried 80
    # characters from every position of every body (9 of a scan's 11 s on the scale copy's 2,000 newest posts)
    paren = "(@" in body
    for m in EMBED.finditer(body) if paren else ():
        add("x", m.group(2), "embed", pos=m.start(2), body=body)
        claimed.add(m.start(2) - 1)
    for platform, h, form, status, pos in links_in(body):
        add(platform, h, form, status=status, pos=pos, body=body)
    for m in AT.finditer(body):
        if m.start() in claimed:
            continue
        h = m.group(1)
        nxt = body[m.end():m.end() + 2]
        if h.casefold() in CODE_WORDS or nxt[:1] in ("{", "(", "/", "@") or re.match(r"[.\-][A-Za-z0-9]", nxt):
            continue
        before = body[max(0, m.start() - 24): m.start()]
        said = bool(SAID_AFTER.match(body, m.end())) or bool(SAID_BEFORE.search(before))
        add(at_platform, h, "said" if said else "at", pos=m.start(), body=body)
    if kind != "telegram":
        for m in BSKY_AT.finditer(body):
            d = m.group(1).casefold()
            if d.endswith(".bsky.social"):
                add("bluesky", d, "at", pos=m.start(), body=body)
    for u in links:
        for platform, h, form, status, _pos in links_in(u):
            add(platform, h, form, status=status)
    for m in PAIR.finditer(body) if paren else ():
        name = _clean_name(m.group(1))
        h = m.group(2)
        if name and _ok(at_platform, h.casefold()) and not (at_platform == own_p and h.casefold() == own_h.casefold()):
            pairs.append(Pair(at_platform, h.casefold(), name))
    return list(refs.values()), pairs


def account_of(platform: Optional[str], handle: Optional[str]) -> Optional[Tuple[str, str]]:
    """A source's own account as a handle key ((platform, handle)), or None: an X, Telegram, GitHub, Bluesky or model
    hub account it follows (repo_stories.source_account)."""
    from insight_core.db.repo_stories import source_account
    acc = source_account(platform, handle) or ""
    for prefix, p in (("x.com/", "x"), ("t.me/", "telegram"), ("github.com/", "github"), ("huggingface.co/", "hf"),
                      ("bsky.app/profile/", "bluesky")):
        if acc.startswith(prefix):
            h = re.sub(r"\.(atom|rss|xml|json)$", "", acc[len(prefix):].split("/", 1)[0].lstrip("@").casefold())
            if h and _ok(p, h):
                return p, h
    raw = (handle or "").casefold()
    m = re.search(r"bsky\.app/profile/([a-z0-9._:-]+)", raw)
    if m and not m.group(1).startswith("did:"):
        return "bluesky", m.group(1)
    return None


def own_key(platform: Optional[str], handle: Optional[str]) -> Optional[str]:
    got = account_of(platform, handle)
    return f"{got[0]}:{got[1]}" if got else None


def digest_of(content_hash: Optional[str], title: Optional[str], author: Optional[str]) -> str:
    return hashlib.sha1("\x1f".join((STAMP, content_hash or "", title or "", author or "")).encode()).hexdigest()[:16]


# ---- the database --------------------------------------------------------------------------------------------

def pending(cur: Any, limit: int, *, after: Optional[Tuple[datetime, str]] = None) -> List[str]:
    """Posts not scanned under this rule, or whose text changed since: newest first."""
    cur.execute("""SELECT p.id::text FROM posts p LEFT JOIN mx_handle_scans s ON s.post_id = p.id
                    WHERE s.post_id IS NULL OR s.stamp <> %s OR s.content_hash IS DISTINCT FROM p.content_hash
                    ORDER BY p.fetched_at DESC NULLS LAST, p.id DESC LIMIT %s""", (STAMP, limit))
    return [r[0] for r in cur.fetchall()]


def scan_posts(cur: Any, post_ids: Sequence[str]) -> Dict[str, int]:
    """Scan these posts (their full text, kept links and author fields) and store their refs and pairs under their
    digest: {posts, refs, pairs}. Idempotent; a post read again under new text gets a new row set."""
    from insight_core.utils.post_links import source_kind
    ids = sorted(set(map(str, post_ids)))
    out = Counter({"posts": 0, "refs": 0, "pairs": 0})
    if not ids:
        return dict(out)
    cur.execute(f"""SELECT p.id::text, p.source_id::text, s.platform, s.handle_or_url, p.title, p.content, p.author,
                          p.content_hash, {pairing.ordinary_date('p')}, pp.quoted,
                          p.metadata->'forwarded_from'->>'username'
                     FROM posts p JOIN sources s ON s.id = p.source_id LEFT JOIN post_parts pp ON pp.post_id = p.id
                    WHERE p.id = ANY(%s::uuid[])""", (ids,))
    rows = cur.fetchall()
    cur.execute("""SELECT post_id::text, target_url FROM post_links WHERE NOT boilerplate AND post_id = ANY(%s::uuid[])
                    ORDER BY post_id, position""", (ids,))
    links: Dict[str, List[str]] = defaultdict(list)
    for pid, url in cur.fetchall():
        links[pid].append(url)
    own_cache: Dict[Tuple[Optional[str], Optional[str]], Optional[str]] = {}
    for (pid, sid, platform, handle, title, content, author, chash, at, quoted, fwd_user) in rows:
        k = (platform, handle)
        if k not in own_cache:
            own_cache[k] = own_key(platform, handle)
        refs, pairs = scan(kind=source_kind(platform, handle), own=own_cache[k], title=title or "", text=content or "",
                           links=links.get(pid, ()), author=author, quoted=quoted, forwarded=fwd_user or None)
        dig = digest_of(chash, title, author)
        if refs:
            cur.executemany("""INSERT INTO mx_handle_refs (post_id, digest, platform, handle, shown, form, role, status,
                                                           source_id, line_key, snippet, at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                            [(pid, dig, r.platform, r.handle, r.shown, r.form, r.role, r.status, sid, r.line, r.snippet,
                              at) for r in refs])
        if pairs:
            names: Dict[Tuple[str, str, str], str] = {}
            for p in pairs:
                names.setdefault((p.platform, p.handle, _sq(p.name)), p.name)
            cur.executemany("""INSERT INTO mx_handle_pairs (post_id, digest, platform, handle, name, name_sq, at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                            [(pid, dig, pl, h, n, sq, at) for (pl, h, sq), n in names.items() if sq])
        cur.execute("""INSERT INTO mx_handle_scans (post_id, stamp, content_hash, digest, refs, pairs)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (post_id) DO UPDATE SET stamp = EXCLUDED.stamp, content_hash = EXCLUDED.content_hash,
                           digest = EXCLUDED.digest, refs = EXCLUDED.refs, pairs = EXCLUDED.pairs, at = now()""",
                    (pid, STAMP, chash, dig, len(refs), len(pairs)))
        out["posts"] += 1
        out["refs"] += len(refs)
        out["pairs"] += len(pairs)
    return dict(out)


def scan_pending(cur: Any, *, limit: int = SCAN_LIMIT, deadline: Optional[float] = None) -> Dict[str, Any]:
    """The run's share of the scan: up to `limit` pending posts in batches, newest first, until `deadline`.
    {posts, refs, pairs, done: nothing left pending}."""
    import time
    got: Counter = Counter({"posts": 0, "refs": 0, "pairs": 0})
    first = True   # one batch a run even past the deadline, so a long full pass never starves the scan
    while got["posts"] < limit and (first or deadline is None or time.monotonic() < deadline):
        first = False
        ids = pending(cur, min(SCAN_BATCH, limit - got["posts"]))
        if not ids:
            break
        got.update(scan_posts(cur, ids))
    return {**dict(got), "done": not pending(cur, 1)}


def _sq(name: Optional[str]) -> str:
    from insight_core.markx import names as N
    return N.squash(N.key(name))


# ---- whose handles -----------------------------------------------------------------------------------------------

def answers(cur: Any, members: Iterable[str]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(platform, handle): the newest owner answer about it for these entities} ({answer, display_name, first_seen,
    last_seen, at})."""
    cur.execute("""SELECT DISTINCT ON (platform, handle) platform, handle, answer, display_name, first_seen, last_seen,
                          created_at FROM mx_entity_handles WHERE entity_id = ANY(%s::uuid[])
                    ORDER BY platform, handle, created_at DESC, id DESC""", (sorted(set(members)),))
    return {(p, h): {"answer": a, "display_name": d, "first_seen": f, "last_seen": l, "at": at}
            for p, h, a, d, f, l, at in cur.fetchall()}


def confirmed_elsewhere(cur: Any, book: Any, platform: str, handle: str) -> Set[str]:
    """The roots the owner said have this handle."""
    cur.execute("""SELECT DISTINCT ON (entity_id) entity_id::text, answer FROM mx_entity_handles
                    WHERE platform = %s AND handle = %s ORDER BY entity_id, created_at DESC, id DESC""",
                (platform, handle))
    return {book.root(e) for e, a in cur.fetchall() if a == "yes" and book.root(e) in book.ents}


def entity_handles(cur: Any, book: Any, root: str, members: Iterable[str], by_sources: Sequence[Dict[str, Any]] = ()
                   ) -> List[Dict[str, Any]]:
    """The entity's known handles: the owner's yes (with the display name and time range the pairs gave) and the
    accounts of its own sources (0144 B1's "By": a person's followed account is theirs). [{platform, handle, via,
    display_name, first_seen, last_seen}], current ones first."""
    got: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (p, h), a in answers(cur, members).items():
        if a["answer"] == "yes":
            got[(p, h)] = {"platform": p, "handle": h, "via": "owner", "display_name": a["display_name"],
                           "first_seen": a["first_seen"], "last_seen": a["last_seen"]}
    ids = [s["id"] for s in by_sources]
    if ids:
        cur.execute("SELECT platform, handle_or_url FROM sources WHERE id = ANY(%s::uuid[])", (ids,))
        for platform, handle in cur.fetchall():
            acc = account_of(platform, handle)
            if acc and acc not in got:
                got[acc] = {"platform": acc[0], "handle": acc[1], "via": "source", "display_name": None,
                            "first_seen": None, "last_seen": None}
    return sorted(got.values(), key=lambda x: (x["last_seen"] is not None, -(x["last_seen"].timestamp())
                                               if x["last_seen"] else 0, x["platform"], x["handle"]))


def posts_citing(cur: Any, handles: Sequence[Dict[str, Any]], *, exclude_sources: Iterable[str] = ()
                 ) -> Dict[str, Dict[str, Any]]:
    """{post: {role, forms, handle, at, source_id, read, snippet}} of the posts citing these handles by the rule (their
    current refs), the entity's own sources and boilerplate lines left out. `role`: role_of the post's forms."""
    keys = sorted({(h["platform"], h["handle"]) for h in handles})
    if not keys:
        return {}
    cur.execute(f"""
        WITH cur_refs AS (
            SELECT r.* FROM mx_handle_refs r JOIN mx_handle_scans s ON s.post_id = r.post_id AND s.digest = r.digest
             WHERE (r.platform, r.handle) IN (SELECT * FROM unnest(%s::text[], %s::text[]))
               AND NOT (r.source_id = ANY(%s::uuid[]))),
        boiler AS (
            SELECT x.source_id, x.line_key FROM mx_handle_refs x JOIN mx_handle_scans xs
                ON xs.post_id = x.post_id AND xs.digest = x.digest
             WHERE (x.source_id, x.line_key) IN (SELECT source_id, line_key FROM cur_refs WHERE line_key IS NOT NULL)
             GROUP BY 1, 2
            HAVING count(DISTINCT x.post_id) >= CASE WHEN left(x.line_key, 2) = 'w:' THEN %s ELSE %s END)
        SELECT c.post_id::text, c.platform, c.handle, c.form, c.source_id::text, c.at, c.snippet,
               rs.read_at IS NOT NULL
          FROM cur_refs c LEFT JOIN post_reader_state rs ON rs.post_id = c.post_id
         WHERE NOT EXISTS (SELECT 1 FROM boiler b WHERE b.source_id = c.source_id AND b.line_key = c.line_key)""",
                ([k[0] for k in keys], [k[1] for k in keys], sorted(set(map(str, exclude_sources))), BOILER_WINDOW,
                 BOILER_POSTS))
    out: Dict[str, Dict[str, Any]] = {}
    for pid, platform, handle, form, sid, at, snip, read in cur.fetchall():
        x = out.setdefault(pid, {"forms": set(), "handles": set(), "at": at, "source_id": sid, "read": read,
                                 "snippet": None})
        x["forms"].add(form)
        x["handles"].add(f"{platform}:{handle}")
        x["snippet"] = x["snippet"] or snip
    for x in out.values():
        x["role"] = role_of(x["forms"])
    return out


def learned_names(cur: Any, book: Any) -> Dict[str, Tuple[str, Set[str]]]:
    """{root: (the display name the owner's confirmed handles carry, those handles squashed)}: an entity named by its
    handle is shown by the name its pairs gave (D; entity_repair.shown)."""
    cur.execute("""SELECT DISTINCT ON (entity_id, platform, handle) entity_id::text, handle, answer, display_name
                     FROM mx_entity_handles ORDER BY entity_id, platform, handle, created_at DESC, id DESC""")
    out: Dict[str, Tuple[str, Set[str]]] = {}
    for eid, handle, answer, display in cur.fetchall():
        r = book.root(eid)
        if answer != "yes" or r not in book.ents:
            continue
        name, hs = out.get(r, (None, set()))
        hs.add(_sq(handle))
        out[r] = (name or display, hs)
    return {r: (n, hs) for r, (n, hs) in out.items() if n}


# ---- learning handles from pairs (C, D) --------------------------------------------------------------------------

def pair_names(cur: Any) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(platform, handle): {name, sq, n, total, share, first, last, posts}} of the handles whose current pairs agree.
    A name's support is every pair whose name ends with its words ("Video Ivo Kestrel" and "Ivo Kestrel" both support
    "Ivo Kestrel": a header's preceding word glued on); the best-supported name must hold PAIR_MIN+ posts and AGREE+
    of the handle's pairs."""
    from insight_core.markx import names as N
    cur.execute("""SELECT pr.platform, pr.handle, pr.name_sq, count(DISTINCT pr.post_id), min(pr.at), max(pr.at),
                          (array_agg(pr.name ORDER BY pr.at DESC))[1], (array_agg(pr.post_id::text ORDER BY pr.at DESC))[1:3]
                     FROM mx_handle_pairs pr JOIN mx_handle_scans s ON s.post_id = pr.post_id AND s.digest = pr.digest
                    GROUP BY 1, 2, 3""")
    by: Dict[Tuple[str, str], List[Tuple]] = defaultdict(list)
    for platform, handle, sq, n, first, last, name, posts in cur.fetchall():
        words = tuple(N.squash(w) for w in N.key(name).split() if N.squash(w))
        by[(platform, handle)].append((int(n), sq, name, first, last, posts or [], words))
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, rows in by.items():
        total = sum(r[0] for r in rows)
        best = None
        for cand in rows:
            cw = cand[6]
            if not cw:
                continue
            sup = [r for r in rows if len(r[6]) >= len(cw) and r[6][-len(cw):] == cw]
            rank = (sum(r[0] for r in sup), len(cw), cand[0], cand[1])
            if best is None or rank > best[0]:
                best = (rank, cand, sup)
        if best is None:
            continue
        (n, _w, _own, _sq), cand, sup = best
        if n >= PAIR_MIN and n >= AGREE * total:
            out[key] = {"name": cand[2], "sq": cand[1], "n": n, "total": total, "share": round(n / total, 3),
                        "first": min(r[3] for r in sup if r[3] is not None) if any(r[3] for r in sup) else None,
                        "last": max(r[4] for r in sup if r[4] is not None) if any(r[4] for r in sup) else None,
                        "posts": sorted({p for r in sup for p in r[5]})[:3]}
    return out


def _queued(cur: Any, a: str, platform: str, handle: str) -> bool:
    cur.execute("""SELECT 1 FROM mx_entity_queue WHERE kind = 'handle' AND a = %s AND evidence->>'platform' = %s
                    AND evidence->>'handle' = %s AND (answer IS NOT NULL OR closed_at IS NULL) LIMIT 1""",
                (a, platform, handle))
    return cur.fetchone() is not None


def _ask(cur: Any, *, a: str, reason: str, conf: float, evidence: Dict[str, Any], run_id: Any) -> bool:
    from insight_core.markx import identity as I
    if _queued(cur, a, evidence["platform"], evidence["handle"]):
        return False
    got = I._savepoint(cur, """INSERT INTO mx_entity_queue (kind, a, b, proposal, reason, confidence, evidence, run_id)
                               VALUES ('handle', %s, NULL, 'same', %s, %s, %s::jsonb, %s) RETURNING id""",
                       (a, reason, conf, json.dumps(evidence, default=str), run_id))
    return got is not None


def learn(cur: Any, book: Any, *, run_id: Any = None, limit: int = PROPOSE_LIMIT) -> Dict[str, int]:
    """C + D: the owner questions the agreeing pairs raise (never applied by themselves):
      - a handle for the one person or org named like the pairs' display name (`pairs`; `second_handle` when the
        entity already has another handle on that platform: an old or renamed account, its pairs' time range given);
      - an entity named by the handle itself: an alias question with the display name's entity (`handle_name`), or,
        when none exists, a handle question whose yes shows the display name (`named_by_handle`).
    A namesake (two entities of the name) is never asked. {asked, aliases, skipped}."""
    from insight_core.markx import identity as I
    from insight_core.markx import names as N
    from insight_core.markx import schemas
    got = Counter({"asked": 0, "aliases": 0, "ambiguous": 0})
    agree = pair_names(cur)
    if not agree:
        return dict(got)
    by_sq: Dict[str, Set[str]] = defaultdict(set)
    for eid, e in book.ents.items():
        r = book.root(eid)
        if r not in book.ents or book.ents[r].status == "not_entity" or e.status == "not_entity":
            continue
        if schemas.entity_type(book.ents[r].shown_type or book.ents[r].type) not in ("person", "org"):
            continue
        by_sq[e.sq].add(r)
    kept = {x for xs in by_sq.values() for x in xs}
    for k, eid in book.alias.items():
        r = book.root(eid)
        if r in kept:
            by_sq[N.squash(k)].add(r)
    cur.execute("""SELECT DISTINCT ON (entity_id, platform, handle) entity_id::text, platform, handle, answer
                     FROM mx_entity_handles ORDER BY entity_id, platform, handle, created_at DESC, id DESC""")
    known: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))   # root -> platform -> handles yes
    owner_of: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for eid, platform, handle, answer in cur.fetchall():
        if answer == "yes" and book.root(eid) in book.ents:
            known[book.root(eid)][platform].add(handle)
            owner_of[(platform, handle)].add(book.root(eid))
    for (platform, handle), p in sorted(agree.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        if got["asked"] + got["aliases"] >= limit:
            break
        if owner_of.get((platform, handle)):
            continue                                   # the owner already said whose it is
        named = by_sq.get(p["sq"], set())
        if len(named) > 1:
            got["ambiguous"] += 1                      # namesakes: never by the name alone
            continue
        target = next(iter(named), None)
        ev = {"platform": platform, "handle": handle, "display": p["name"], "pairs": p["n"], "total": p["total"],
              "share": p["share"], "first": p["first"], "last": p["last"], "examples": p["posts"]}
        by_handle = {r for r in by_sq.get(N.squash(handle), set()) if r != target} if p["sq"] != N.squash(handle) else set()
        for h_root in sorted(by_handle):              # D: an entity named by the handle
            if target is not None:
                if I.pair(h_root, target) in book.never:
                    continue
                if I.queue_item(cur, kind="alias", a=h_root, b=target, proposal="same", reason="handle_name",
                                conf=p["share"], evidence={**ev, "rules": ["handle_pairs"]}, call_id=None, run_id=run_id):
                    got["aliases"] += 1
            elif _ask(cur, a=h_root, reason="named_by_handle", conf=p["share"],
                      evidence={**ev, "named_by_handle": True}, run_id=run_id):
                got["asked"] += 1
        if target is None:
            continue
        other = sorted(known.get(target, {}).get(platform, set()) - {handle})
        reason = "second_handle" if other else "pairs"
        if _ask(cur, a=target, reason=reason, conf=p["share"], evidence={**ev, "alias_of": other or None},
                run_id=run_id):
            got["asked"] += 1
    return dict(got)


def answer_item(cur: Any, book: Any, item: Dict[str, Any], ans: str) -> Dict[str, Any]:
    """The owner's answer to a `handle` item: `same` (yes, this is their handle) records it with the display name and
    the pairs' time range; any other answer records a no (never asked again)."""
    ev = item.get("evidence") or {}
    root = book.root(item["a"]) or item["a"]
    yes = ans == "same"
    cur.execute("""INSERT INTO mx_entity_handles (entity_id, platform, handle, answer, display_name, first_seen, last_seen,
                                                  queue_id, evidence)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id::text""",
                (root, ev.get("platform"), ev.get("handle"), "yes" if yes else "no", ev.get("display") if yes else None,
                 ev.get("first"), ev.get("last"), item["id"],
                 json.dumps({k: ev.get(k) for k in ("pairs", "total", "share", "alias_of", "named_by_handle")},
                            default=str)))
    row = cur.fetchone()[0]
    e = book.ents.get(root)
    display = ev.get("display")
    if yes and e is not None and display and _sq(e.shown_name or e.name) == _sq(ev.get("handle")):
        # D at once: an entity shown under this handle is shown by its display name (entity_repair.shown keeps it)
        new = None if display == e.name else display
        cur.execute("""UPDATE mx_entities SET shown_name = %s, shown_by = 'evidence'
                        WHERE id = %s AND shown_by IS DISTINCT FROM 'owner'""", (new, root))
        e.shown_name = new
    return {"handle": {"platform": ev.get("platform"), "handle": ev.get("handle"), "answer": "yes" if yes else "no",
                       "row": row}}


def add_handle(cur: Any, book: Any, entity_id: str, platform: str, handle: str, answer: str = "yes",
               display_name: Optional[str] = None) -> Dict[str, Any]:
    """The owner says (or denies) a handle directly on the entity page."""
    if platform not in PLATFORMS:
        raise ValueError(f"platform: one of {', '.join(PLATFORMS)}")
    h = handle.strip().lstrip("@").casefold()
    if not _ok(platform, h):
        raise ValueError("not a handle on that platform")
    if answer not in ("yes", "no"):
        raise ValueError("answer: yes or no")
    root = book.root(entity_id)
    cur.execute("""INSERT INTO mx_entity_handles (entity_id, platform, handle, answer, display_name)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id::text""", (root, platform, h, answer, display_name))
    return {"platform": platform, "handle": h, "answer": answer, "row": cur.fetchone()[0]}


def stage(cur: Any, book: Any, *, run_id: Any, deadline: Optional[float] = None) -> Dict[str, Any]:
    """The decision run's handle step: scan the pending posts (newest first, within the deadline), then ask what the
    pairs raise."""
    import time
    out: Dict[str, Any] = {"scan": scan_pending(cur, deadline=deadline)}
    if deadline is None or time.monotonic() < deadline:
        out["learn"] = learn(cur, book, run_id=run_id)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m insight_core.markx.handles scan [--limit N]`: the backfill (every pending post, in batches, each
    committed); `learn`: the questions the pairs raise now."""
    import argparse
    from insight_core.markx.api import transaction
    ap = argparse.ArgumentParser(prog="insight_core.markx.handles")
    ap.add_argument("what", choices=("scan", "learn"))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    total = Counter()
    if args.what == "scan":
        while args.limit is None or total["posts"] < args.limit:
            with transaction() as cur:
                ids = pending(cur, SCAN_BATCH if args.limit is None else min(SCAN_BATCH, args.limit - total["posts"]))
                if not ids:
                    break
                total.update(scan_posts(cur, ids))
            print(json.dumps(dict(total)), flush=True)
    else:
        from insight_core.markx import identity as I
        with transaction() as cur:
            total.update(learn(cur, I.load_book(cur), limit=args.limit or PROPOSE_LIMIT))
        print(json.dumps(dict(total)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
