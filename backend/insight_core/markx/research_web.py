"""Research's rules and outside services (issue 0162): what an address is, a page's declared links, when two accounts
are one maker by plain rules, every version of an address, the paper index, the web search, and the exact match of a
discussion hit. Pure where it can be; the services take the caller's http client (the server's fetcher), so every
request is the caller's to budget and the tests stub them all.

**What an address is** (`classify`, platform classes only, never a site list of its own): a paper (an id on its host,
utils/addresses.paper_id); an account on a platform INSIGHT reads (X, YouTube, a Reddit user, Telegram: PLATFORM_SITES)
or a community (a subreddit); a code host's, a model hub's or a package index's account or project
(entity_originals' vocabularies: CODE_SITES, MODEL_HUBS, PACKAGE_SITES); else a site (a front page) or a site's section
(one path segment: a blog platform's account, a docs site). A page deeper than that on a site is someone's article:
never an identity, never followed as one.

**A page's declared links** (`declared_links`): the links a profile or a project page shows as its own (rel=me first),
classified, on another site or under the page's own owner on its platform; never the platform's own menus, a share or
login link, nor another site's article.

**Same maker by plain rules** (`same_identity`): the platform states it (an account that owns a project page on its
platform, `<host>/<owner>/<thing>`); declared both ways (each links the other); the same handle on two platforms (handles
from addresses, 3+ characters, never a display name); the page names the other's handle or address. A name alone never
suffices (a namesake): anything else is unclear and goes to Haiku's `identity` question (research.py).

**Versions of an address** (`versions`): a paper under every page of it (abstract, PDF, HTML, each vN, its arXiv DOI);
a project's page and its releases, tags and files under it (a prefix).

**The paper index** (`paper_index`): a free open one first, OpenAlex, behind the setting `research_paper_index`
(mx_settings: "openalex", the default, or "off"; a keyed index is a new class here later). Matched by DOI or arXiv id
exactly; an author's newer papers are kept only when they share a co-author or the field with the seed (the index
merges namesakes into one author: test 1 of the spec).

**Web search** (`web_search`): a pluggable provider, off until configured (INSIGHT_WEB_SEARCH = searxng | brave, with
INSIGHT_WEB_SEARCH_URL for a SearXNG instance or INSIGHT_WEB_SEARCH_KEY for Brave's API; the key is read from the
environment only, never stored or logged). Its results are candidates only: a result is an identity after the plain
rules or Haiku say so.

**A discussion hit is exact** (`exact_hit`): the item contains the paper's id or the project's owner/name as a whole token
(2606.13843 is not 2406.13843), links an address of the seed, or carries its exact title. No fuzzy match.
"""
from __future__ import annotations

import html as htmllib
import logging
import os
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

log = logging.getLogger(__name__)

PAGE_BYTES = 800_000
TEXT_CHARS = 4000
MAX_LINKS = 25
X_RESERVED = frozenset({"home", "search", "explore", "i", "intent", "share", "hashtag", "settings", "messages",
                        "notifications", "login", "signup", "tos", "privacy", "about", "status"})
NOT_ACCOUNT = frozenset({"login", "signup", "join", "share", "intent", "sharer", "search", "explore", "settings",
                         "about", "pricing", "features", "enterprise", "terms", "privacy", "legal", "contact", "blog",
                         "docs", "help", "support", "sponsors", "marketplace", "topics", "trending", "collections",
                         "events", "security", "customer-stories", "readme", "team", "site", "home", "new", "notifications",
                         "models", "datasets", "spaces", "organizations", "papers", "posts", "learn", "tasks", "chat"})
SHARE_WORDS = ("share", "sharer", "intent", "login", "signin", "signup", "subscribe", "oauth", "auth")
_SQUASH = re.compile(r"[^a-z0-9]+")
_HANDLE_AT = re.compile(r"(?<![\w.])@([A-Za-z0-9_]{3,40})\b")


def squash(text: Optional[str]) -> str:
    return _SQUASH.sub("", (text or "").casefold())


def _segments(url: str) -> List[str]:
    try:
        path = urllib.parse.urlparse(url).path
    except ValueError:
        return []
    return [urllib.parse.unquote(s) for s in path.split("/") if s]


def _host(url: str) -> str:
    from insight_core.utils.addresses import host_of
    h = host_of(url)
    return h[4:] if h.startswith("www.") else h


# ---- what an address is ------------------------------------------------------------------------------------

def classify(url: str) -> Optional[Dict[str, Any]]:
    """{platform, kind, key, handle, address} of an address, or None for one that is no identity (an article, a menu
    page, a share link). kind: paper | account | community | project | site."""
    from insight_core.utils.addresses import PLATFORM_SITES, paper_id, site_of
    from insight_core.utils.entity_originals import CODE_SITES, MODEL_HUBS, PACKAGE_SITES, platform_thing
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    host = _host(url)
    site = site_of(host)
    segs = _segments(url)
    low = [s.lower() for s in segs]
    if any(w in s for s in low for w in SHARE_WORDS) and site not in PLATFORM_SITES["telegram"]:
        return None
    pid = paper_id(url)
    if pid:
        return {"platform": "paper", "kind": "paper", "key": f"paper:{pid.lower()}", "handle": None,
                "address": url}
    if site in PLATFORM_SITES["x"]:
        if len(segs) == 1 and low[0] not in X_RESERVED and re.fullmatch(r"@?[A-Za-z0-9_]{1,30}", segs[0]):
            handle = segs[0].lstrip("@")
            return {"platform": "x", "kind": "account", "key": f"x.com/{handle.lower()}", "handle": handle,
                    "address": f"https://x.com/{handle}"}
        return None
    if site in PLATFORM_SITES["youtube"]:
        if len(segs) >= 1 and segs[0].startswith("@"):
            return {"platform": "youtube", "kind": "account", "key": f"youtube.com/{segs[0].lower()}",
                    "handle": segs[0][1:], "address": f"https://www.youtube.com/{segs[0]}"}
        if len(segs) >= 2 and low[0] in ("channel", "c", "user"):
            return {"platform": "youtube", "kind": "account", "key": f"youtube.com/{low[0]}/{segs[1].lower()}",
                    "handle": segs[1] if low[0] != "channel" else None,
                    "address": f"https://www.youtube.com/{segs[0]}/{segs[1]}"}
        return None
    if site in PLATFORM_SITES["reddit"]:
        if len(segs) >= 2 and low[0] in ("u", "user"):
            return {"platform": "reddit", "kind": "account", "key": f"reddit.com/user/{low[1]}", "handle": segs[1],
                    "address": f"https://www.reddit.com/user/{segs[1]}"}
        if len(segs) >= 2 and low[0] == "r":
            return {"platform": "reddit", "kind": "community", "key": f"reddit.com/r/{low[1]}", "handle": None,
                    "address": f"https://www.reddit.com/r/{segs[1]}"}
        return None
    if site in PLATFORM_SITES["telegram"]:
        if host != "telegram.org" and segs and (low[0] != "s" or len(segs) > 1):
            name = segs[1] if low[0] == "s" else segs[0]
            if re.fullmatch(r"[A-Za-z0-9_]{4,40}", name) and name.lower() not in ("joinchat", "share", "addstickers"):
                return {"platform": "telegram", "kind": "account", "key": f"t.me/{name.lower()}", "handle": name,
                        "address": f"https://t.me/{name}"}
        return None
    if host == site and (site in CODE_SITES or site in MODEL_HUBS or site in PACKAGE_SITES):
        platform = "code" if site in CODE_SITES else "hub"
        thing = platform_thing(url)
        if thing:
            kind, owner, name = thing
            owner_part = f"{owner.lower()}/" if owner else ""
            return {"platform": platform, "kind": "project", "key": f"{site}/{owner_part}{name.lower()}",
                    "handle": owner, "owner": owner, "address": url.split("?", 1)[0].split("#", 1)[0].rstrip("/")}
        if len(segs) == 1 and low[0] not in NOT_ACCOUNT and site not in PACKAGE_SITES:
            return {"platform": platform, "kind": "account", "key": f"{site}/{low[0]}", "handle": segs[0],
                    "address": f"https://{site}/{segs[0]}"}
        return None
    if not segs:
        return {"platform": "site", "kind": "site", "key": host, "handle": None, "address": f"https://{host}/"}
    if len(segs) == 1 and low[0] not in NOT_ACCOUNT and not re.search(r"\.(html?|php|aspx?|pdf)$", low[0]):
        handle = segs[0][1:] if segs[0].startswith(("@", "~")) else None
        return {"platform": "site", "kind": "account" if handle else "site", "key": f"{host}/{low[0]}",
                "handle": handle, "address": f"https://{host}/{segs[0]}"}
    return None


# ---- a page and its declared links --------------------------------------------------------------------------

class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.links, self.me = "", {}, [], []
        self.text: List[str] = []
        self._in: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        if tag == "title":
            self._in.append("title")
        elif tag == "meta":
            name = (a.get("property") or a.get("name") or "").lower()
            if name in ("og:title", "og:description", "description", "twitter:description", "author"):
                self.meta.setdefault(name, a.get("content", ""))
        elif tag in ("a", "link") and a.get("href"):
            rel = a.get("rel", "").lower().split()
            if "me" in rel:
                self.me.append(a["href"])
            if tag == "a":
                self.links.append(a["href"])

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if tag == "title" and self._in:
            self._in.pop()

    def handle_data(self, data: str) -> None:
        if self._in and self._in[-1] == "title":
            self.title += data
        elif not self._skip and data.strip():
            self.text.append(data.strip())


def page_summary(body: Any, url: str) -> Dict[str, Any]:
    """{title, description, text, links (declared, classified addresses), handles (@names it writes)} of a page."""
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
    p = _Page()
    try:
        p.feed(text)
        p.close()
    except Exception:  # noqa: BLE001 - what was read before the page broke the parser
        pass
    title = " ".join((p.meta.get("og:title") or p.title or "").split())[:300]
    description = " ".join((p.meta.get("og:description") or p.meta.get("description")
                            or p.meta.get("twitter:description") or "").split())[:600]
    words = " ".join(p.text)
    return {"title": htmllib.unescape(title), "description": htmllib.unescape(description),
            "text": words[:TEXT_CHARS], "links": declared_links(p.me + p.links, url),
            "handles": sorted({h for h in _HANDLE_AT.findall(words)})[:40]}


def declared_links(hrefs: Iterable[str], page_url: str) -> List[str]:
    """The page's own links that name an identity (classify), absolute, once each, rel=me first (the caller passes
    them first): on another site, or on the page's own platform under the page's own owner; at most MAX_LINKS."""
    from insight_core.utils.addresses import same_site
    here = classify(page_url) or {}
    own = (here.get("owner") or here.get("handle") or "").lower()
    out: List[str] = []
    seen: Set[str] = set()
    for href in hrefs:
        try:
            url = urllib.parse.urldefrag(urllib.parse.urljoin(page_url, (href or "").strip()))[0]
        except ValueError:
            continue
        if not url.startswith(("http://", "https://")):
            continue
        got = classify(url)
        if not got or got["key"] in seen or got["key"] == here.get("key"):
            continue
        if same_site(_host(url), _host(page_url)):
            segs = [s.lower() for s in _segments(url)]
            if not own or not segs or segs[0].lstrip("@~") != own:
                continue          # the platform's own pages, or someone else's on it: not this page's
        seen.add(got["key"])
        out.append(got["address"])
        if len(out) >= MAX_LINKS:
            break
    return out


def profile_address(c: Dict[str, Any]) -> str:
    """Where an account's own page is read: an X account through the configured bridge (x.com wants a login), else
    its address."""
    if c.get("platform") == "x" and c.get("handle"):
        from insight_core.ingestion.kinds.nitter_rss import nitter_origin
        try:
            origin = nitter_origin()
        except Exception:  # noqa: BLE001
            origin = None
        if origin:
            return f"{origin}/{c['handle']}"
    return c["address"]


# ---- same maker, by plain rules ---------------------------------------------------------------------------------

def _keys_in(links: Iterable[str]) -> Set[str]:
    return {got["key"] for got in (classify(u) for u in links) if got}


def same_identity(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """('yes', rule) when a plain rule ties account or page `b` to the confirmed `a`; (None, why unclear) otherwise.
    Each is {key, handle, owner?, links, handles, text, read}. A name alone is never a rule."""
    ka, kb = a.get("key"), b.get("key")
    if a.get("kind") == "project" and b.get("kind") == "account" and a.get("owner") and b.get("handle") \
            and squash(a["owner"]) == squash(b["handle"]) and a.get("platform") == b.get("platform"):
        return "yes", "the platform says this account owns it"
    if b.get("kind") == "project" and a.get("kind") == "account" and b.get("owner") and a.get("handle") \
            and squash(b["owner"]) == squash(a["handle"]) and a.get("platform") == b.get("platform"):
        return "yes", "the platform says this account owns it"
    a_links, b_links = _keys_in(a.get("links") or ()), _keys_in(b.get("links") or ())
    if kb in a_links and ka in b_links:
        return "yes", "each links the other"
    ha, hb = squash(a.get("handle")), squash(b.get("handle"))
    if len(ha) >= 3 and ha == hb and (kb in a_links or ka in b_links):
        return "yes", "the same handle, and one links the other"
    if b.get("read") and ka in b_links:
        return "yes", "its profile names the other (links it as its own)"
    text = (b.get("text") or "").casefold()
    if b.get("read") and ha and len(ha) >= 4 and (f"@{ha}" in {f"@{squash(h)}" for h in b.get("handles") or ()}):
        return "yes", "its page names the other's handle"
    if b.get("read") and ka and ka.split("/", 1)[-1] and ka in text:
        return "yes", "its page names the other's address"
    if not b.get("read"):
        return None, "its page could not be read"
    return None, "nothing ties them but what the confirmed page says"


# ---- versions of an address ------------------------------------------------------------------------------------

def versions(url: str) -> Tuple[List[str], List[str]]:
    """(exact addresses, prefixes) that are this address under another version: a paper's every page, a project's
    releases and files."""
    from insight_core.utils.entity_originals import paper_ref
    from insight_core.utils.url_normalization import normalize_url
    exact: List[str] = []
    prefixes: List[str] = []
    ref = paper_ref(url)
    if ref and ref.startswith("arXiv:"):
        pid = ref[6:]
        for kind in ("abs", "pdf", "html"):
            exact.append(f"https://arxiv.org/{kind}/{pid}")
            exact += [f"https://arxiv.org/{kind}/{pid}v{n}" for n in range(1, 10)]
        exact += [f"https://arxiv.org/pdf/{pid}.pdf"] + [f"https://arxiv.org/pdf/{pid}v{n}.pdf" for n in range(1, 10)]
        exact += [f"https://doi.org/10.48550/arXiv.{pid}", f"https://doi.org/10.48550/arxiv.{pid}"]
    elif ref and ref.startswith("doi:"):
        doi = ref[4:]
        exact += [f"https://doi.org/{doi}", f"https://dx.doi.org/{doi}"]
    got = classify(url)
    if got and got["kind"] == "project":
        base = got["address"]
        exact.append(base)
        prefixes.append(base + "/")
    exact.append(url)
    normal = [normalize_url(u) or u for u in exact]
    return list(dict.fromkeys(exact + normal)), list(dict.fromkeys(prefixes))


# ---- exact discussion hits ---------------------------------------------------------------------------------------

def id_terms(url: str, title: Optional[str] = None) -> List[str]:
    """The exact things a discussion of this address must contain: a paper's id, a project's owner/name."""
    from insight_core.utils.entity_originals import paper_ref
    ref = paper_ref(url)
    out = []
    if ref:
        out.append(ref.split(":", 1)[1])
    got = classify(url)
    if got and got["kind"] == "project" and got.get("owner"):
        out.append(got["key"].split("/", 1)[1])
    return out


def _term_re(term: str) -> re.Pattern:
    if re.fullmatch(r"\d{4}\.\d{4,5}", term):
        return re.compile(rf"(?<![\d.]){re.escape(term)}(?:v\d+)?(?![\d])")
    return re.compile(rf"(?<![\w-]){re.escape(term.casefold())}(?![\w-])")


def exact_hit(item: Dict[str, Any], *, terms: Sequence[str], addresses: Sequence[str], title: Optional[str]) -> Optional[str]:
    """Why a found item is a discussion of the seed (it contains an id term whole, links one of its addresses, or
    carries its exact title), else None."""
    hay = " ".join(str(item.get(k) or "") for k in ("title", "text", "url", "html")).casefold()
    for term in terms:
        if term and _term_re(term).search(hay):
            return f"contains {term}"
    for address in addresses:
        bare = address.split("://", 1)[-1].casefold().rstrip("/")
        if bare and len(bare) > 8 and bare in hay:
            return f"links {bare}"
    t = " ".join((title or "").split()).casefold()
    if len(t) >= 20 and t in " ".join(hay.split()):
        return "carries its exact title"
    return None


# ---- the paper index ---------------------------------------------------------------------------------------------

PAPER_INDEX_SETTING = "research_paper_index"
OPENALEX = "https://api.openalex.org"
WORK_FIELDS = "id,doi,title,display_name,publication_date,authorships,primary_topic,ids,cited_by_count"
LIST_FIELDS = "id,doi,title,display_name,publication_date,ids,authorships,primary_topic"


def openalex_doi(ref: str) -> Optional[str]:
    if ref.startswith("arXiv:"):
        return f"10.48550/arXiv.{ref[6:]}"
    if ref.startswith("doi:"):
        return ref[4:]
    return None


def work_ref(work: Dict[str, Any]) -> Optional[str]:
    """A work's exact id: arXiv:<id> for an arXiv DOI (or the index's arxiv id), else doi:<doi>."""
    doi = str(work.get("doi") or "").lower().removeprefix("https://doi.org/")
    m = re.fullmatch(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})(?:v\d+)?", doi)
    if m:
        return "arXiv:" + m.group(1)
    arxiv = str((work.get("ids") or {}).get("arxiv") or "")
    m = re.search(r"(\d{4}\.\d{4,5})", arxiv)
    if m:
        return "arXiv:" + m.group(1)
    return f"doi:{doi}" if doi.startswith("10.") else None


def ref_url(ref: Optional[str]) -> Optional[str]:
    if not ref:
        return None
    return f"https://arxiv.org/abs/{ref[6:]}" if ref.startswith("arXiv:") else f"https://doi.org/{ref[4:]}"


def _short(work: Dict[str, Any]) -> Dict[str, Any]:
    ref = work_ref(work)
    return {"ref": ref, "url": ref_url(ref), "title": " ".join(str(work.get("display_name") or work.get("title") or "").split()),
            "date": work.get("publication_date"), "openalex": work.get("id"),
            "authors": [a.get("author", {}).get("display_name") for a in work.get("authorships") or []][:8],
            "author_ids": [a.get("author", {}).get("id") for a in work.get("authorships") or [] if a.get("author", {}).get("id")],
            "field": ((work.get("primary_topic") or {}).get("field") or {}).get("id")}


class OpenAlex:
    """The free open paper index (OpenAlex's REST API, its polite pool when INSIGHT_OPENALEX_MAILTO is set)."""
    name = "openalex"

    def __init__(self, base: str = OPENALEX) -> None:
        self.base = base.rstrip("/")
        self.mailto = os.getenv("INSIGHT_OPENALEX_MAILTO", "").strip()

    def _url(self, path: str, **params: Any) -> str:
        if self.mailto:
            params["mailto"] = self.mailto
        query = urllib.parse.urlencode(params, safe=":|,")
        return f"{self.base}{path}" + (f"?{query}" if query else "")

    async def work(self, http: Any, ref: str) -> Optional[Dict[str, Any]]:
        doi = openalex_doi(ref)
        if not doi:
            return None
        got = await http.get_json(self._url(f"/works/doi:{doi}", select=WORK_FIELDS))
        if not isinstance(got, dict) or work_ref(got) != (ref if ref.startswith("arXiv:") else f"doi:{doi.lower()}"):
            return None                     # an exact id only
        return got

    async def _list(self, http: Any, flt: str, n: int) -> List[Dict[str, Any]]:
        got = await http.get_json(self._url("/works", filter=flt, select=LIST_FIELDS, **{"per-page": n}))
        return [w for w in (got or {}).get("results") or [] if isinstance(w, dict)]

    async def references(self, http: Any, work: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [_short(w) for w in await self._list(http, f"cited_by:{_wid(work)}", 100)]

    async def citing(self, http: Any, work: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [_short(w) for w in await self._list(http, f"cites:{_wid(work)}", 50)]

    async def newer(self, http: Any, work: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The authors' papers after the seed, kept only when they share a co-author or the field with it."""
        seed = _short(work)
        ids = [i.rsplit("/", 1)[-1] for i in seed["author_ids"]][:10]
        if not ids or not seed["date"]:
            return []
        rows = [_short(w) for w in await self._list(http, f"author.id:{'|'.join(ids)},from_publication_date:{seed['date']}", 50)]
        out = []
        for r in rows:
            if r["ref"] == seed["ref"] or not r["ref"]:
                continue
            shared = set(r["author_ids"]) & set(seed["author_ids"])
            if len(shared) >= 2:
                out.append(dict(r, why="shares co-authors"))
            elif shared and r["field"] and r["field"] == seed["field"]:
                out.append(dict(r, why="shares an author and the field"))
        return out


def _wid(work: Dict[str, Any]) -> str:
    return str(work.get("id") or "").rsplit("/", 1)[-1]


def paper_index(cur: Any) -> Optional[OpenAlex]:
    """The paper index the setting names ("openalex", the default; "off": none)."""
    from insight_core.markx import repo
    value = repo.get_setting(cur, PAPER_INDEX_SETTING, default="openalex")
    return OpenAlex() if value == "openalex" else None


def short_work(work: Dict[str, Any]) -> Dict[str, Any]:
    return _short(work)


# ---- web search ------------------------------------------------------------------------------------------------

WEB_SEARCH_ENV, WEB_SEARCH_URL_ENV, WEB_SEARCH_KEY_ENV = "INSIGHT_WEB_SEARCH", "INSIGHT_WEB_SEARCH_URL", "INSIGHT_WEB_SEARCH_KEY"
BRAVE = "https://api.search.brave.com/res/v1/web/search"


class SearxngSearch:
    """A SearXNG instance's JSON API (self-hosted; INSIGHT_WEB_SEARCH_URL its address)."""
    name = "searxng"

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    async def search(self, http: Any, query: str) -> List[Dict[str, str]]:
        got = await http.get_json(f"{self.base}/search?" + urllib.parse.urlencode({"q": query, "format": "json"}))
        return [{"url": r.get("url"), "title": r.get("title") or "", "snippet": r.get("content") or ""}
                for r in (got or {}).get("results") or [] if isinstance(r, dict) and r.get("url")]


class BraveSearch:
    """Brave's web search API (INSIGHT_WEB_SEARCH_KEY its key, sent as a header, never logged)."""
    name = "brave"

    def __init__(self, key: str, base: str = BRAVE) -> None:
        self.key, self.base = key, base

    async def search(self, http: Any, query: str) -> List[Dict[str, str]]:
        import json
        body, _ = await http.get_text(f"{self.base}?" + urllib.parse.urlencode({"q": query, "count": 10}),
                                      headers={"X-Subscription-Token": self.key, "Accept": "application/json"})
        got = json.loads(body)
        return [{"url": r.get("url"), "title": r.get("title") or "", "snippet": r.get("description") or ""}
                for r in ((got or {}).get("web") or {}).get("results") or [] if isinstance(r, dict) and r.get("url")]


def web_search() -> Optional[Any]:
    """The configured web search provider, or None (off) when nothing is configured."""
    provider = os.getenv(WEB_SEARCH_ENV, "").strip().lower()
    if provider == "searxng" and os.getenv(WEB_SEARCH_URL_ENV, "").strip():
        return SearxngSearch(os.environ[WEB_SEARCH_URL_ENV].strip())
    if provider == "brave" and os.getenv(WEB_SEARCH_KEY_ENV, "").strip():
        return BraveSearch(os.environ[WEB_SEARCH_KEY_ENV].strip())
    return None


# The platform classes' own hosts, as `classify` writes their accounts' addresses.
CLASS_HOSTS = {"x": "x.com", "youtube": "youtube.com", "reddit": "reddit.com", "telegram": "t.me"}


def web_queries(name: str, n: int) -> List[str]:
    """For a maker's name: the name alone, then the name on each platform class INSIGHT reads."""
    name = " ".join((name or "").split())
    if len(squash(name)) < 3:
        return []
    out = [f'"{name}"']
    for platform in ("x", "youtube", "reddit", "telegram"):
        out.append(f'"{name}" site:{CLASS_HOSTS[platform]}')
    return out[:n]


__all__ = ["BraveSearch", "OpenAlex", "SearxngSearch", "classify", "declared_links", "exact_hit", "id_terms",
           "page_summary", "paper_index", "profile_address", "same_identity", "versions", "web_queries", "web_search",
           "work_ref"]
