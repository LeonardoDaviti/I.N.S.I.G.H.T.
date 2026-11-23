"""Originals from entities (0138): pure rules. The database side is markx/entity_addresses.py (A: an entity's
addresses), services/originals_service.py (B: collect its original; C: the title lookup; D2: the sites that supply
originals) and db/repo_discover.py (D1: the Pages rows).

A. An entity's address, no request: for an entity of a type that names one thing, the links its posts carry that
are that thing's page, by rule (RULE_ORDER): `identifier` (the mention's arXiv id or DOI, else the one paper a post
links beside its only document), `title` (the link's read title is the entity's name or alias), `repo` (a code host's,
model hub's or package index's page of one thing named as it; one_owner keeps the stated maker's among forks) and
`maker` (a page on the maker's own site whose title is about the name). A paper or a release page is the original;
code and demo pages are its links.

Cited, not its own (0229): a match by rule 1 or 2 shows the post cites a page, not that the page is the entity. Such a
page is kind `cited`, never an original or an address: rule 1's paper is own only when the mention carries its id or
its title names the entity (`paper_is_its_own`); a model's, product's or software's page is own only on its own or
its maker's site (`own_site`) or as its own platform page (`platform_page_own`: a voice platform's post is its
account's; an app conversation is nobody's). A document's page titled with its name is the document wherever it is.
With no own page the entity shows no Original rather than a page its posts cite.

B. The trigger: the entity is the `subject` of posts from 2+ voices in 7 days, or of one voice's post that leads a
News row. C. A lookup by title (off by default): arXiv's title search, else Crossref's, matched by name and author.
D2. A site that was the address of 3+ originals in 30 days, that you don't follow, is a Sources suggestion; a paper
host never is.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import quote

from insight_core.utils.addresses import (PLATFORM_SITES, account_key, bare, host_of, paper_file, paper_id,
                                          paper_page_order, site_of)
from insight_core.utils.discover_rules import paper_address, place_kind
from insight_core.utils.post_links import is_home
from insight_core.utils.url_normalization import normalize_url

PAPER, CODE, DEMO, RELEASE, WORK, PACKAGE = "paper", "code", "demo", "release", "work", "package"
CITED = "cited"                    # a page the posts cite, not the entity's own: never an original or an address
KINDS = (PAPER, CODE, DEMO, RELEASE, WORK, PACKAGE)
ORIGINAL_KINDS = (PAPER, RELEASE, WORK)
IDENTIFIER, TITLE, MAKER, SITE, LOOKUP, REPO = "identifier", "title", "maker", "site", "lookup", "repo"
RULE_ORDER = (IDENTIFIER, TITLE, REPO, SITE, MAKER, LOOKUP)
# E2: a front page is a work only for a document; one an entity of these types is named by (its site word) never is.
NEVER_FRONT_TYPES = ("product", "software", "model", "org", "person")
WORK_PAGES_MAX = 20                # E2: a work site's own pages your posts link, at most
CLASSICS_DAILY = 100               # E1: the backfill allowance, pages a day (Classics and works), apart from the credit
BACKFILL_PER_RUN = 12              # a run's share of it (hourly ticks spend the day's allowance over the day)
PAGE_DELAY_S = 2.0                 # one host at a time, this far apart
LONGREAD_CHARS = 8000              # F1: a curated long-read's own text, at least
LONGREAD_LINKS = 8                 # F1: the outside article pages it cites, at least
LONGREAD_KINDS = ("commentary", "roundup")   # F1: Mark X's reading kinds (commentary holds analysis), never a report
REFERENCES_MAX = 30                # F1: a long-read's references collected, at most
MISSED_WITHIN = timedelta(days=30)  # F2: links this recent to a followed source's page its feed never carried
MAKER_TYPES = ("model", "product", "software")
NAME_MIN = 4                       # a name key shorter than this names nothing by a title (an id, an initialism)
TRIGGER_WITHIN = timedelta(days=7)
TRIGGER_VOICES = 2
WAIT_RAISES_CAP = timedelta(hours=72)   # B5: entity originals waiting longer on the credit raise its cap
RAISED_CAP = 6.0
SUPPLY_WITHIN = timedelta(days=30)
SUPPLY_MIN = 3
LOOKUP_RESULTS = 3
CODE_SITES = frozenset({"github.com", "gitlab.com", "codeberg.org", "bitbucket.org", "sr.ht"})
DEMO_SUFFIX = (".hf.space",)
MODEL_HUBS = frozenset({"huggingface.co", "hf.co"})   # the model hub address_kind knows (hf.co: its short host)
# a package index's page of one package: the section word before its name (npm's may be @scope/<name>)
PACKAGE_SITES = {"pypi.org": "project", "npmjs.com": "package", "crates.io": "crates"}
# a code host's or a model hub's own sections where an owner would stand: page kinds, not sites
PLATFORM_SECTIONS = frozenset({
    "about", "apps", "blog", "changelog", "chat", "codespaces", "collections", "contact", "customer-stories",
    "dashboard", "datasets", "docs", "enterprise", "events", "explore", "features", "groups", "help", "issues", "join",
    "learn", "login", "marketplace", "models", "new", "notifications", "organizations", "orgs", "papers", "posts",
    "pricing", "pulls", "readme", "resources", "search", "security", "settings", "signup", "site", "solutions",
    "spaces", "sponsors", "tasks", "team", "topics", "trending", "users", "-"})
_TITLE_PARTS = re.compile(r"\s+[|·—–-]\s+")
_LEADING_ID = re.compile(r"^\s*\[[^\]]{1,40}\]\s*")


def _segments(url: str) -> List[str]:
    _, _, rest = bare(url).partition("/")
    return [s for s in re.split(r"[?#]", rest, maxsplit=1)[0].split("/") if s]


def address_kind(url: str) -> str:
    """paper, code (a code host's owner/repository), demo (a model hub's space) or release."""
    host = host_of(url)
    segs = _segments(url)
    if paper_id(url) or paper_address(url):
        return PAPER
    if site_of(host) in CODE_SITES and len(segs) >= 2:
        return CODE
    if host.endswith(DEMO_SUFFIX) or (site_of(host) == "huggingface.co" and len(segs) >= 3 and segs[0] == "spaces"):
        return DEMO
    return RELEASE


def paper_ref(url: str) -> Optional[str]:
    """One paper whatever page of it an address is: arXiv:<id>, doi:<doi>, else <host>:<id>."""
    pid = paper_id(url)
    if not pid:
        return None
    m = re.fullmatch(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", pid)
    if m:
        return "arXiv:" + m.group(1)
    if re.fullmatch(r"\d{4}\.\d{4,5}", pid) and site_of(host_of(url)) == "arxiv.org":
        return "arXiv:" + pid
    if pid.startswith("10."):
        return "doi:" + pid
    return f"{site_of(host_of(url))}:{pid}"


def ref_page(ref: Optional[str]) -> Optional[str]:
    if not ref:
        return None
    if ref.startswith("arXiv:"):
        return normalize_url("https://arxiv.org/abs/" + ref[6:])
    if ref.startswith("doi:"):
        return normalize_url("https://doi.org/" + ref[4:])
    return None


def paper_page(ref: str, links: Iterable[str]) -> Optional[str]:
    """The post's own link to paper `ref`'s page (not its file), else the canonical page."""
    own = sorted((u for u in links if paper_ref(u) == ref and not paper_file(u)), key=paper_page_order)
    return own[0] if own else ref_page(ref)


def by_identifier(*, ref: Optional[str], span_ids: Sequence[str], links: Sequence[str], documents: int,
                  is_document: bool) -> Optional[str]:
    """Rule 1: the paper page of the mention's identifier (or an id in its span or name), else, for its post's only
    document, of the one paper the post links."""
    for r in ([ref] if ref else []) + list(span_ids):
        if r and (r.startswith("arXiv:") or r.startswith("doi:")):
            return paper_page(r, links)
    if not is_document or documents != 1:
        return None
    refs = {r for r in (paper_ref(u) for u in links) if r}
    if len(refs) != 1:
        return None
    return paper_page(refs.pop(), links)


def carries_id(ref: Optional[str], span_ids: Sequence[str]) -> bool:
    return any(r and (r.startswith("arXiv:") or r.startswith("doi:")) for r in [ref, *span_ids])


def paper_names_it(title: Optional[str], names: Iterable[str], key) -> bool:
    """A paper's read title names the entity: by title keys, or by the head before its colon ("Nimbus: ...")."""
    names = {n for n in names if len(n) >= NAME_MIN}
    if not title or not names:
        return False
    heads = {key(t.split(":", 1)[0]) for t in (title, _LEADING_ID.sub("", title)) if ":" in t}
    return bool(names & (title_keys(title, key) | heads))


# link words that say what kind of page a link is, not what it is ("Paper", "[link]", "статья"): no evidence either way
LINK_LABELS = frozenset({
    "abstract", "arxiv", "article", "doi", "full", "here", "link", "paper", "pdf", "preprint", "read", "source", "text",
    "the", "this", "здесь", "препринт", "ссылка", "ссылке", "статье", "статьи", "статью", "статья", "тут"})
_AUTHOR_YEAR = re.compile(r"\bet\s+al\b|\bи\s+др\b|\(?(?:19|20)\d{2}[a-z]?\)?\s*$", re.I)


def link_names(words: Optional[str], url: str) -> Optional[str]:
    """What a link's own words name; None for no words, an address, an identifier, page-kind labels only
    (LINK_LABELS) or an author-year citation ("Baker et al., 2025")."""
    w = " ".join((words or "").split())
    if not w or "://" in w or w.startswith("www.") or bare(url).split("/", 1)[0] in w.lower():
        return None
    from insight_core.markx.citations import ids_in
    if ids_in(w) or _AUTHOR_YEAR.search(w):
        return None
    tokens = re.findall(r"[^\W\d_]+", w.lower())
    return w if tokens and not all(t in LINK_LABELS for t in tokens) else None


def paper_is_its_own(*, carried: bool, title: Optional[str], words: Optional[str], url: str, names: Iterable[str],
                     key) -> bool:
    """Rule 1's paper is the entity's own when the mention carries its id, or its read title (else the link's words)
    names the entity; words naming another thing make it cited; with neither (a bare link) it stays its own."""
    from insight_core.markx.names import word_contains
    if carried:
        return True
    said = title or link_names(words, url)
    if not said:
        return True
    names = set(names)
    k = key(said)
    return paper_names_it(said, names, key) or any(word_contains(n, k) for n in names if n)


def own_site(url: str, words: Iterable[str], squash) -> bool:
    """A page on the thing's own site or its maker's: a host label, the site's word or its registrable address run
    together matches a name or maker key run together, one of its words (3+ characters), or a maker's initials."""
    host = host_of(url)
    site = site_of(host)
    if host.split(".", 1)[0] in _CODE_WORDS:   # a code host's own install (gitlab.<org>.example): the org's
        return True
    labels = [x for x in host.lower().split(".") if x and x != "www"]
    if labels and len(labels[-1]) <= 3:   # a short ending (com, org, dev) is nobody's word; a brand's (google) is
        labels = labels[:-1]
    forms = {re.sub(r"[^0-9a-z]+", "", x) for x in labels + [site_word(url), site.lower()]}
    want: Set[str] = set()
    for w in words:
        if not w:
            continue
        parts = [p for p in w.split() if not re.fullmatch(r"[\d.]+", p)]
        want.add(squash(w))
        want.update(squash(p) for p in parts)
        if len(parts) >= 3:
            want.add("".join(p[0] for p in parts))
    return bool({f for f in forms if len(f) >= 3} & {w for w in want if len(w) >= 3})


_CODE_WORDS = frozenset(s.split(".", 1)[0] for s in CODE_SITES)   # a code host's own install (gitlab.<org>.example)


def title_keys(title: Optional[str], key) -> Set[str]:
    title = (title or "").strip().split("\n", 1)[0]   # a post's text stored as its title: its first line only
    if not title:
        return set()
    out: Set[str] = set()
    for t in (title, _LEADING_ID.sub("", title)):
        out.add(key(t))
        out.update(key(p) for p in _TITLE_PARTS.split(t))
    return {k.rstrip(" .!?") for k in out if k.rstrip(" .!?")}


_PAGE_FILE = re.compile(r"\.(?!html?$|php$|aspx?$)[a-z0-9]{1,5}$", re.I)


def not_a_release(url: str) -> bool:
    """A page no thing's release is: a help or docs page, a store's or catalog's listing, or a raw file (.md, .json)."""
    from insight_core.utils.discover_rules import CATALOG_LABELS, reference_address
    host = host_of(url)
    segs = [s.lower() for s in _segments(url)]
    return (reference_address(url) or any(label in CATALOG_LABELS for label in host.split(".")[:-1])
            or any(s in CATALOG_LABELS for s in segs[:3]) or bool(segs and _PAGE_FILE.search(segs[-1])))


def by_title(title: Optional[str], names: Iterable[str], key) -> bool:
    """Rule 2: the read title names the entity (a name or alias key of NAME_MIN+ characters)."""
    names = {n for n in names if len(n) >= NAME_MIN}
    return bool(names & title_keys(title, key))


def by_maker(url: str, title: Optional[str], *, makers: Iterable[str], names: Iterable[str], squash,
             known: Optional[Callable[[str], bool]] = None) -> bool:
    """The maker rule: a page on the maker's own site whose title is about the entity's name (`versioned` pages of a
    longer name aside; `known`: whether a name key is an entity's, None: every such name counts)."""
    if is_home(url) or not title:
        return False
    word = re.sub(r"[^0-9a-z]+", "", site_of(host_of(url)).split(".", 1)[0].lower())
    if len(word) < NAME_MIN or not any(squash(m) == word for m in makers if m):
        return False
    from insight_core.markx.names import key as name_key, word_contains
    t = name_key(title.strip().split("\n", 1)[0])
    # about the name: half its title's words or more, never in passing (measured), nor a longer versioned name
    return any(len(n) >= NAME_MIN and word_contains(n, t) and 2 * len(n.split()) >= len(t.split())
               and not versioned(n, t, known) for n in names)


_VERSION = re.compile(r"v?\d[\w.]*$", re.I)


def versioned(name: str, title_key: str, known: Optional[Callable[[str], bool]] = None) -> bool:
    """Every place the name stands in the title, a version follows that makes another entity's name ("claude fable
    5"); a version no entity is named by keeps the page the entity's. `known` None counts every version."""
    words, want = title_key.split(), name.split()
    at = [i for i in range(len(words) - len(want) + 1) if words[i:i + len(want)] == want]

    def longer(i: int) -> bool:
        j = i + len(want)
        if j >= len(words) or not _VERSION.match(words[j]):
            return False
        return known is None or known(" ".join(want + [words[j]]))
    return bool(at) and all(longer(i) for i in at)


def platform_thing(url: str) -> Optional[Tuple[str, Optional[str], str]]:
    """(kind, owner, thing) of a platform's page of one thing (a code host's repository, a model hub's model or
    dataset, a package index's package), on the platform's own host and the thing's own page only; else None."""
    host = host_of(url)
    host = host[4:] if host.startswith("www.") else host
    site = site_of(host)
    if host != site:
        return None
    segs = _segments(url)
    if site in PACKAGE_SITES:
        if len(segs) < 2 or segs[0] != PACKAGE_SITES[site]:
            return None
        if segs[1].startswith("@"):
            return (PACKAGE, segs[1][1:], segs[2]) if len(segs) >= 3 and len(segs[1]) > 1 else None
        return PACKAGE, None, segs[1]
    if site in CODE_SITES:
        if len(segs) == 2 and segs[0].lower() not in PLATFORM_SECTIONS:
            return CODE, segs[0].lstrip("~"), segs[1]
        return None
    if site in MODEL_HUBS:
        if len(segs) == 3 and segs[0].lower() == "datasets":
            return RELEASE, segs[1], segs[2]
        if len(segs) == 2 and segs[0].lower() not in PLATFORM_SECTIONS:
            return RELEASE, segs[0], segs[1]
    return None


def by_repo(url: str, names: Iterable[str], key, squash) -> Optional[Tuple[str, Optional[str]]]:
    """Rule `repo`: (kind, owner) when `url` is a platform's page of one thing named as the entity, whole (no suffix
    dropped: a build tag's page is a third party's copy); else None, and for any home page."""
    if is_home(url):
        return None
    got = platform_thing(url)
    if not got:
        return None
    kind, owner, thing = got
    want = {w for w in (squash(n) for n in names if n) if len(w) >= NAME_MIN}
    return (kind, owner or None) if squash(key(thing)) in want else None


def owner_agrees(owner: Optional[str], makers: Iterable[str], squash) -> bool:
    """A platform owner is the entity's stated maker ("acme-ai" is Acme's)."""
    if not owner:
        return False
    from insight_core.markx.names import handle_forms
    forms = set(handle_forms(owner)) | {squash(owner.casefold())}
    wants = {squash(m) for m in makers if m}
    # or the handle starts with the maker's name (4+ characters): anthropics, google-deepmind
    return any(w in forms for w in wants if len(w) >= 3) or \
        any(f.startswith(w) for f in forms for w in wants if len(w) >= NAME_MIN)


def one_owner(rows: Sequence[Tuple[str, str, Optional[str]]], makers: Iterable[str], squash) -> Set[str]:
    """The `repo` rows (kind, url, owner) kept: of a kind under 2+ owners (forks, namesakes) only the stated maker's."""
    makers = [m for m in makers if m]
    by_kind: Dict[str, List[Tuple[str, Optional[str]]]] = {}
    for kind, url, owner in rows:
        by_kind.setdefault(kind, []).append((url, owner))
    keep: Set[str] = set()
    for items in by_kind.values():
        owners = {squash((o or "").casefold()) for _, o in items}
        if len(owners) <= 1:
            keep.update(u for u, _ in items)
        else:
            keep.update(u for u, o in items if owner_agrees(o, makers, squash))
    return keep


def conversation(url: str) -> bool:
    """A conversation with an app (discover_rules.app_address): never an address, never cited (a private chat)."""
    from insight_core.utils.discover_rules import app_address
    return app_address(url)


_VOICE_SITES = frozenset(s for sites in PLATFORM_SITES.values() for s in sites)


def voice_account(url: str) -> Optional[str]:
    """The account a voice platform's page is under; "" for a page under none (an HN item, a /watch video, a
    subreddit); None off the voice platforms."""
    host = host_of(url)
    site = site_of(host)
    if site not in _VOICE_SITES or re.sub(r"^(?:www|m|mobile|old|news)\.", "", host) != re.sub(r"^news\.", "", site):
        return None   # the platform's own other sites (its blog.<platform>) are the site rules'; news.ycombinator.com is HN
    from insight_core.utils.discover_rules import NOT_ACCOUNT
    parts = account_key(url).split("/")
    if len(parts) == 3 and parts[1] == "r":
        return ""   # a community (a subreddit) is nobody's account: its threads are its members'
    seg = parts[-1].lstrip("@")
    return "" if not seg or seg in NOT_ACCOUNT or seg in ("item", "watch", "comments", "v") else seg


def platform_page_own(url: str, *, repo: Optional[Tuple[str, Optional[str]]], names: Iterable[str],
                      makers: Iterable[str], squash) -> Optional[bool]:
    """Whether a platform's page is the entity's own (None: the site rules decide): a voice platform's post when its
    account is the entity's or maker's; a code host's, hub's or index's page as rule `repo`'s, or in a repository
    named as the entity or under its maker. A page in another's repository, or another's project holding its name,
    is cited."""
    account = voice_account(url)
    names, makers = [n for n in names if n], [m for m in makers if m]
    if account is not None:
        return bool(account) and owner_agrees(account, names + makers, squash)
    host = host_of(url)
    site = site_of(host)
    if site not in CODE_SITES and site not in MODEL_HUBS and site not in PACKAGE_SITES:
        return None
    if repo:
        return True
    if (host[4:] if host.startswith("www.") else host) != site:
        return None   # the platform's own other sites (docs.github.com, gist.github.com): the site rules decide
    got = repository(url)
    if not got:
        return False
    owner, thing = got
    from insight_core.markx.names import key as name_key
    bare_names = {b for n in names for b in (squash(n), squash(" ".join(_unversioned(n.split())))) if len(b) >= 2}
    t = squash(name_key(thing))
    if any(named_as(thing, n) for n in names):
        return True   # named as it, its version or size aside, any owner
    o = squash(owner.casefold())
    if (len(o) >= NAME_MIN and any(b.startswith(o) for b in bare_names)):
        return True   # the owner is the name's family (Qwen/... for "Qwen2.5-Omni")
    if (t in bare_names or squash(name_key(f"{owner}/{thing}")) in bare_names
            or (len(t) >= NAME_MIN and any(t in b for b in bare_names)) or owner_agrees(owner, makers + names, squash)):
        return True
    # a repository's own page whose name holds the entity's, with no stated maker its owner contradicts
    return not makers and not lesser(url) and any(len(b) >= NAME_MIN and b in t for b in bare_names)


HUB_OWNED = (["datasets"], ["collections"], ["blog"])   # a model hub's sections whose pages are an owner's


def repository(url: str) -> Optional[Tuple[str, str]]:
    """(owner, thing) of the repository a code host's or a model hub's page is in; None for a platform's section."""
    segs = _segments(url)
    if site_of(host_of(url)) in MODEL_HUBS and segs[:1] in HUB_OWNED:
        segs = segs[1:]   # a dataset's page, a collection, a blog post (/blog/<owner>/<slug>) of the owner's
    if len(segs) < 2 or segs[0].lower() in PLATFORM_SECTIONS:
        return None
    return segs[0].lstrip("~@"), segs[1]


def platform_owned(url: str) -> bool:
    host = host_of(url)
    site = site_of(host)
    return (site in CODE_SITES or site in MODEL_HUBS) and (host[4:] if host.startswith("www.") else host) == site \
        and repository(url) is not None


def lesser(url: str) -> bool:
    """A page chosen as an address only when no page of the thing is: a voice platform's post, a page inside a
    repository."""
    if voice_account(url) is not None:
        return True
    site = site_of(host_of(url))
    if site not in CODE_SITES and site not in MODEL_HUBS:
        return False
    segs = [s.lower() for s in _segments(url)]
    n = 3 if segs[:1] in HUB_OWNED else 2
    return len(segs) > n and segs[n] != "releases"


def named_as(thing: str, name: str) -> bool:
    """A repository named as the entity, one trailing version or size word aside on one side; never a build tag."""
    def forms(x: str) -> Tuple[str, str]:
        words = [w for w in re.split(r"[^0-9a-z]+", x.casefold()) if w]
        cut = words[:-1] if len(words) > 1 and re.fullmatch(r"v?\d+[a-z]?|\d+(?:[bmkt]|gb)", words[-1]) else words
        return "".join(words), "".join(cut)
    (t, t_cut), (n, n_cut) = forms(thing), forms(name)
    return len(n) >= NAME_MIN and (t == n or t_cut == n or (len(n_cut) >= NAME_MIN and t == n_cut))


def _unversioned(words: List[str]) -> List[str]:
    while len(words) > 1 and _VERSION.match(words[-1]):
        words = words[:-1]
    return words


def front_page(url: str) -> bool:
    _, _, rest = bare(url).partition("/")
    return rest.strip("/") == ""


def site_word(url: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", site_of(host_of(url)).split(".", 1)[0].lower())


def by_site(url: str, title: Optional[str], names: Iterable[str], key, squash) -> Optional[str]:
    """A document's work site: a front page named as it by its site word (`site`) or read title (`title`); else None."""
    if not front_page(url):
        return None
    names = {n for n in names if len(n) >= NAME_MIN}
    word = site_word(url)
    if len(word) >= NAME_MIN and any(squash(n) == word for n in names):
        return SITE
    return TITLE if names & title_keys(title, key) else None


def work_front_allowed(url: str, never: Mapping[str, Set[str]]) -> bool:
    """No product's, app's, model's, org's or person's front page is a work (`never`: site word -> named types)."""
    return not (set(never.get(site_word(url), ())) & set(NEVER_FRONT_TYPES))


def cited_page(url: str, post_url: Optional[str]) -> bool:
    """A page a long-read cites as a reference: another site's article, not a front page, a profile, an archive's
    copy, an app's shared page or a reference page."""
    from insight_core.utils.discover_rules import DISCOVER_PLATFORMS, app_address, archive_address, reference_address
    host = host_of(url)
    if not host or front_page(url) or (is_home(url) and site_of(host) in DISCOVER_PLATFORMS):
        return False
    if archive_address(url) or app_address(url) or reference_address(url):
        return False
    return not post_url or site_of(host_of(url)) != site_of(host_of(post_url))


def pick(addresses: Iterable[Tuple[str, str, str, Any]]) -> Dict[str, Tuple[str, str, Any]]:
    """{kind: (url, rule, first_at)}: one a kind, a thing's page before a lesser one, then by rule order and time."""
    order = {r: n for n, r in enumerate(RULE_ORDER)}
    out: Dict[str, Tuple[str, str, Any]] = {}
    # a page its posts cite is no address of it, nor a conversation, whatever a row says
    addresses = [a for a in addresses if a[0] != CITED and not conversation(a[1])]
    for kind, url, rule, at in sorted(addresses, key=lambda a: (lesser(a[1]), order.get(a[2], 9), a[3] is None,
                                                                 a[3].timestamp() if a[3] else 0.0, a[1])):
        out.setdefault(kind, (url, rule, at))
    return out


def original_of(picked: Mapping[str, Tuple[str, str, Any]]) -> Optional[Tuple[str, str]]:
    for kind in ORIGINAL_KINDS:
        if kind in picked:
            return kind, picked[kind][0]
    return None


# ---- B ---------------------------------------------------------------------------------------------

def triggered(voices: int, lead: bool) -> bool:
    return voices >= TRIGGER_VOICES or (voices >= 1 and lead)


def credit_cap(oldest_wait: Optional[timedelta], base: float) -> float:
    return max(base, RAISED_CAP) if oldest_wait is not None and oldest_wait > WAIT_RAISES_CAP else base


# ---- C ---------------------------------------------------------------------------------------------

def arxiv_query(name: str) -> str:
    phrase = re.sub(r"[\"\s]+", " ", name).strip()
    return ("https://export.arxiv.org/api/query?search_query=" + quote(f'ti:"{phrase}"') +
            f"&max_results={LOOKUP_RESULTS}")


def crossref_query(name: str) -> str:
    return f"https://api.crossref.org/works?query.title={quote(name.strip())}&rows={LOOKUP_RESULTS}"


_ATOM = "{http://www.w3.org/2005/Atom}"


def parse_arxiv(xml: str) -> List[Tuple[str, List[str], str]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
        authors = [" ".join((a.findtext(f"{_ATOM}name") or "").split()) for a in entry.findall(f"{_ATOM}author")]
        link = (entry.findtext(f"{_ATOM}id") or "").strip()
        ref = paper_ref(link)
        if title and ref:
            out.append((title, authors, ref_page(ref) or link))
    return out


def parse_crossref(data: Any) -> List[Tuple[str, List[str], str]]:
    items = ((data or {}).get("message") or {}).get("items") or [] if isinstance(data, dict) else []
    out = []
    for item in items:
        title = " ".join(" ".join(item.get("title") or []).split())
        authors = [" ".join(filter(None, (a.get("given"), a.get("family")))) for a in item.get("author") or []]
        doi = (item.get("DOI") or "").strip()
        if title and doi:
            out.append((title, authors, ref_page("doi:" + doi.lower()) or ""))
    return out


def by_names(by: Optional[str]) -> List[str]:
    return [p.strip() for p in re.split(r",|;|\s+(?:and|и|&)\s+|&", by or "") if p.strip()]


def _same_person(a: str, b: str, key) -> bool:
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return False
    return ka == kb or (ka.split()[-1] == kb.split()[-1] and len(ka.split()[-1]) >= 3)


def lookup_match(name: str, by: Iterable[str], results: Sequence[Tuple[str, Sequence[str], str]], key) -> Optional[str]:
    """A result whose title is the entity's name by the name key, with an author of `by`."""
    want = key(name)
    by = [b for b in by if b]
    if len(want) < NAME_MIN or not by:
        return None
    for title, authors, url in results:
        if url and want in title_keys(title, key) and any(_same_person(a, b, key) for a in authors for b in by):
            return url
    return None


# ---- D2 --------------------------------------------------------------------------------------------

def suppliers(rows: Iterable[Tuple[str, str, datetime]], *, now: datetime, followed: Set[str], hidden: Set[str],
              within: timedelta = SUPPLY_WITHIN, least: int = SUPPLY_MIN) -> Dict[str, Dict[str, Any]]:
    """{key: {n, urls, since}} of the sites that supplied `least`+ distinct originals in `within`, not followed or
    hidden, no paper host. `rows`: (Discover's key of the original's site, its address, when)."""
    by: Dict[str, Dict[str, datetime]] = {}
    for key, url, at in rows:
        if not key or at is None or at < now - within:
            continue
        seen = by.setdefault(key, {})
        seen[url] = min(at, seen.get(url, at))
    out = {}
    for key, urls in by.items():
        site = key.split("/", 1)[0]
        if len(urls) < least or key.lower() in hidden or key in followed or site in followed or site_of(site) in followed \
                or site in hidden or site_of(site) in hidden:
            continue
        if place_kind(key, urls) == "paper" or any(paper_address(u) for u in urls):
            continue
        out[key] = {"n": len(urls), "urls": sorted(urls), "since": min(urls.values())}
    return out


def supplier_reason(n: int) -> str:
    return f"the original of {n} thing{'s' if n != 1 else ''} your sources talked about"


__all__ = [
    "LONGREAD_CHARS", "LONGREAD_KINDS", "LONGREAD_LINKS", "MISSED_WITHIN", "REFERENCES_MAX", "cited_page",
    "BACKFILL_PER_RUN", "CLASSICS_DAILY", "NEVER_FRONT_TYPES", "PAGE_DELAY_S", "SITE", "WORK", "WORK_PAGES_MAX",
    "by_site", "named_as", "conversation", "front_page", "lesser", "platform_owned", "platform_page_own", "repository", "versioned", "voice_account",
    "site_word", "work_front_allowed",
    "MODEL_HUBS", "PACKAGE", "PACKAGE_SITES", "PLATFORM_SECTIONS", "REPO", "by_repo", "one_owner", "owner_agrees", "platform_thing",
    "CITED", "LINK_LABELS", "carries_id", "link_names", "own_site", "paper_is_its_own", "paper_names_it",
    "CODE", "DEMO", "IDENTIFIER", "KINDS", "LOOKUP", "MAKER", "MAKER_TYPES", "PAPER", "RELEASE", "TITLE",
    "not_a_release", "address_kind", "arxiv_query", "by_identifier", "by_maker", "by_names", "by_title", "credit_cap", "crossref_query",
    "lookup_match", "original_of", "paper_page", "paper_ref", "parse_arxiv", "parse_crossref", "pick", "ref_page",
    "supplier_reason", "suppliers", "title_keys", "triggered",
]
