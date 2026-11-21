"""Originals from entities (issue 0138): pure rules. The database side is markx/entity_addresses.py (A: an entity's
addresses), services/originals_service.py (B: collect its original; C: the title lookup; D2: the sites that supply
originals) and db/repo_discover.py (D1: the Pages rows).

**A. An entity's address, no request.** For an entity of a type that names one thing (candidates.SPECIFIC_TYPES),
the links its posts carry that are that thing's page, by these rules in this order:
  1. `identifier`: the mention's identifier (0133's citation rule: an arXiv id, a DOI), else the one paper the post
     links when the entity is the post's only document (ent-v4.2 runs no rule, so a post linking one paper about one
     document names it so). Its page is the paper's abstract page (the post's own link when it is the page, else the
     host's canonical page).
  2. `title`: a link whose read title (the page's title, else the link's own words) is the entity's name or an alias
     by identity's name key (whole, or one part of a "Title | Site" title).
  3. `repo` (v10.13.5): a platform's page of one thing, <host>/<owner>/<thing> on a code host or a model hub (a
     dataset's /datasets/<owner>/<thing>), or a package index's page of one package, whose <thing> is the entity's
     name or an alias whole (the name key run together, no suffix dropped). A bare platform link has no link words,
     the platform's read title is "<owner>/<thing> · Hub" (never the name alone), and the platform is nobody's maker
     site, so rules 2 and 4 never took it. Kind by the platform: code, release (a model hub's card) or package;
     <owner> is kept on the row (`owner`) as a maker candidate, shown, never asserted. Never a longer name holding
     the entity's, never an owner's page alone (`is_home`), never a platform's own section (/topics/). One entity's
     rows of one kind under 2+ owners (a fork, a namesake) keep only the stated maker's (`one_owner`).
  4. `maker`: a model, product or software entity whose maker's name is the site's own word: a page on that site
     whose title holds the entity's name (word for word). Never a front page or a profile (`is_home`).
A paper or a release page is the **original**; a code repository and a demo are kept as its links (the post that
gave the paper by rule 1 gives them, when it links one of each).

**Cited, not its own (v10.25, 0229).** A match by rule 1 or 2 is evidence that the post CITES a page, not that the page
IS the entity: an org's report whose posts link a paper the report cites got that paper as its Original; a model whose
posts link a third party's dashboard titled with its name got the dashboard. Such a page is kept as kind `cited`
(never an original, an address, a work or a site; the entity's page lists it apart, as what its posts cite):
  - rule 1's paper is the entity's own only when the mention carries the identifier itself (its ref, or an id in its
    span or name: it names that paper), or the paper's read title names the entity (`paper_names_it`: rule 2's title
    keys, or the head before its colon); the one paper a post links beside its only document is otherwise cited, and
    so are the code and demo links that come with it;
  - rule 2's release page of a model, product or software is its own only on its own or its maker's site
    (`own_site`); a document's page titled with its name is the document (a filing, a report) wherever it is.
With no own page the entity shows no Original rather than a page its posts cite.

**Whose page it is (v10.35).** A page under someone on a platform is that someone's, whatever its title says:
  - a conversation with an app (`conversation`: discover_rules.app_address, an opaque id after /c/, /share/, /chat/:
    chatgpt.com/g/<gpt>/c/<id>, claude.ai/chat/<id>) is nobody's publication: never an address, never cited;
  - a post or a thread on a voice platform (addresses.PLATFORM_SITES: a tweet, a Reddit or Hacker News thread, a
    Telegram post, a video) is its account's (`voice_account`): the entity's own only when the account is the
    entity's or its maker's (`owner_agrees`), else cited;
  - a code host's, a model hub's or a package index's page is the entity's own as rule `repo`'s page of one thing
    named as it, or as the page or a release page of a repository that is the entity's: named as it (a version aside)
    or under its maker (`platform_page_own`); a file, an issue, a pull request in a repository and another owner's
    project holding its name (someone's claude-code-mcp) are cited. A maker's handle is its name with a word after it
    as well (`owner_agrees`: Anthropic's `anthropics`, Google's `google-deepmind`), so one_owner keeps the maker's
    repository among forks.
  These hold for a model, a product and software (MAKER_TYPES); a document's or a video's page titled with its name
  is the thing wherever it is.
A title is a page's one line: a post's text stored as its title (a tweet's lines, "- Linux\n- React") names no
thing by a line of it (`title_keys` reads the first line only). The maker rule never takes a page of a longer name
holding the entity's with a version after it ("Redeploying Claude Fable 5" is Fable 5's page, not the family's).

**B. The trigger.** The entity is the `subject` of posts from 2+ voices in 7 days, or of 1 voice's post that leads a
News row. Roles `source` and `recommended` never count (0133: evidence, not news).

**C. A lookup by title** (its own switch, off by default): the arXiv API's title search, else Crossref's; a match is
a result whose title is the entity's name by the name key and with an author of `by` among its authors.

**D2. Sites that supply originals:** a site that was the address of 3+ originals in 30 days, that you don't follow,
is a Sources suggestion; a paper host never is (0109), a summariser of papers can be.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import quote

from insight_core.utils.addresses import (PLATFORM_SITES, account_key, bare, host_of, paper_file, paper_id,
                                          paper_page_order, site_of)
from insight_core.utils.discover_rules import paper_address, place_kind
from insight_core.utils.post_links import is_home
from insight_core.utils.url_normalization import normalize_url

PAPER, CODE, DEMO, RELEASE, WORK, PACKAGE = "paper", "code", "demo", "release", "work", "package"
CITED = "cited"                    # 0229: a page the posts cite, not the entity's own: never an original or an address
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
# a code host's or a model hub's own sections where an owner would stand, never an owner (github.com/topics/<x>,
# huggingface.co/blog/<slug>): a vocabulary of page kinds, not of sites
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
    """What a page of a thing is: a paper (its id, a /paper/ path), a code repository (a code host's
    owner/repository), a demo (a model hub's space, a space's own host), else a release page."""
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
    """One paper whatever page of it an address is: arXiv:<id> on an arXiv host or by the arXiv DOI, doi:<doi>,
    else <host>:<id>."""
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
    """The canonical page of an identifier (0133's refs): an arXiv abstract page, a DOI's resolver page."""
    if not ref:
        return None
    if ref.startswith("arXiv:"):
        return normalize_url("https://arxiv.org/abs/" + ref[6:])
    if ref.startswith("doi:"):
        return normalize_url("https://doi.org/" + ref[4:])
    return None


def paper_page(ref: str, links: Iterable[str]) -> Optional[str]:
    """The page of paper `ref`: the post's own link to its page (not its file) when it has one, else canonical."""
    own = sorted((u for u in links if paper_ref(u) == ref and not paper_file(u)), key=paper_page_order)
    return own[0] if own else ref_page(ref)


def by_identifier(*, ref: Optional[str], span_ids: Sequence[str], links: Sequence[str], documents: int,
                  is_document: bool) -> Optional[str]:
    """Rule 1: the paper page of the mention's identifier, else of an id its span or name holds, else (a document
    that is its post's only document) of the one paper the post links."""
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
    """0229: the mention carries an identifier itself (its ref, an id in its span or name): it names that paper."""
    return any(r and (r.startswith("arXiv:") or r.startswith("doi:")) for r in [ref, *span_ids])


def paper_names_it(title: Optional[str], names: Iterable[str], key) -> bool:
    """0229: a paper's read title names the entity: rule 2's title keys, or the head before its colon ("Nimbus:
    Proving a Hypothesis with Lattices" names Nimbus)."""
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
    """0229: what a link's own words name, when they name a thing: None for no words, an address, an identifier
    ("arXiv:2507.02825"), page-kind labels only (LINK_LABELS) and an author-year citation ("Baker et al., 2025": whose
    work it is, not which); else the words."""
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
    """0229: rule 1's paper is the entity's own when the mention carries its identifier (`carries_id`), or what
    names the page names the entity: its read title, else the link's own words (`link_names`), naming it when it is
    the entity's name by paper_names_it or one's words are a run of the other's. A read title or link words naming
    another thing make it a paper the post cites. With neither (a bare link, "Paper"), the post's only document and
    its one paper stay its own (0138's rule 1)."""
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
    """0229: a page of the thing on its own site or its maker's (a platform's page is `platform_page_own`'s, v10.35):
    a label of the host (blog.example.com: blog, example; an ending of 3 letters or fewer is
    none), the site's word or its whole registrable
    address run together (z.example: zexample) is a name or maker key of it run together, one word of one (3+
    characters, not a number), or a maker's initials (Black Forest Labs: bfl)."""
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
    """The name keys a title can stand for: whole, without a leading [id], and each part of "Title | Site"."""
    title = (title or "").strip().split("\n", 1)[0]   # v10.35: a post's text stored as its title: its first line
    if not title:
        return set()
    out: Set[str] = set()
    for t in (title, _LEADING_ID.sub("", title)):
        out.add(key(t))
        out.update(key(p) for p in _TITLE_PARTS.split(t))
    return {k.rstrip(" .!?") for k in out if k.rstrip(" .!?")}


_PAGE_FILE = re.compile(r"\.(?!html?$|php$|aspx?$)[a-z0-9]{1,5}$", re.I)


def not_a_release(url: str) -> bool:
    """Measured on the server's copy (0138's check 2): a page no thing's release is, whatever its title says: a help or
    docs page (0109's reference shape), a store's or a catalog's listing of it (an app marketplace, a podcast
    directory: discover_rules.CATALOG_LABELS in its host or path) and a raw file (a .md, a .json: a repository's
    file, never its page). A paper keeps its own rules (rule 1)."""
    from insight_core.utils.discover_rules import CATALOG_LABELS, reference_address
    host = host_of(url)
    segs = [s.lower() for s in _segments(url)]
    return (reference_address(url) or any(label in CATALOG_LABELS for label in host.split(".")[:-1])
            or any(s in CATALOG_LABELS for s in segs[:3]) or bool(segs and _PAGE_FILE.search(segs[-1])))


def by_title(title: Optional[str], names: Iterable[str], key) -> bool:
    """Rule 2: the read title names the entity (a name or alias key of NAME_MIN+ characters)."""
    names = {n for n in names if len(n) >= NAME_MIN}
    return bool(names & title_keys(title, key))


def by_maker(url: str, title: Optional[str], *, makers: Iterable[str], names: Iterable[str], squash) -> bool:
    """Rule 3: a page on the maker's own site (its registrable word is the maker's name run together) whose title
    holds the entity's name word for word. Never a front page or a profile."""
    if is_home(url) or not title:
        return False
    word = re.sub(r"[^0-9a-z]+", "", site_of(host_of(url)).split(".", 1)[0].lower())
    if len(word) < NAME_MIN or not any(squash(m) == word for m in makers if m):
        return False
    from insight_core.markx.names import key as name_key, word_contains
    t = name_key(title.strip().split("\n", 1)[0])
    # the name is what the page is about: half its title's words or more ("Introducing Nimbus 4"), never a page that
    # names it in passing ("How Nimbus helped a lab ...": measured, the maker rule's wrong rows were all so), and never
    # a longer name holding it, a version after it (v10.35: "Redeploying Claude Fable 5" is Fable 5's, not Fable's)
    return any(len(n) >= NAME_MIN and word_contains(n, t) and 2 * len(n.split()) >= len(t.split())
               and not versioned(n, t) for n in names)


_VERSION = re.compile(r"v?\d[\w.]*$", re.I)


def versioned(name: str, title_key: str) -> bool:
    """v10.35: every place the name stands in the title, a version follows it ("fable 5", "nimbus v2"): the title
    names a longer name holding it (a member of the family, a release of the thing), not the name itself."""
    words, want = title_key.split(), name.split()
    at = [i for i in range(len(words) - len(want) + 1) if words[i:i + len(want)] == want]
    return bool(at) and all(i + len(want) < len(words) and _VERSION.match(words[i + len(want)]) for i in at)


def platform_thing(url: str) -> Optional[Tuple[str, Optional[str], str]]:
    """(kind, owner, thing) of a platform's page of one thing: a code host's <owner>/<repository> (kind code), a model
    hub's <owner>/<model> or datasets/<owner>/<dataset> (kind release), a package index's page of one package (kind
    package: npm's @scope is its owner, the others name none). The platform's own host only (not docs., gist.), and
    the thing's own page only, not a file or an issue under it; None otherwise."""
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
    """Rule `repo`: (kind, owner) when `url` is a platform's page of one thing (platform_thing) whose thing is the
    entity's name or an alias, whole, by the name key run together (NAME_MIN+ characters); None otherwise, and for any
    home page. No suffix is dropped: measured on the server's copy (v10.13.5), dropping a build tag (-GGUF, -FP8)
    took a third party's quantised copy for the model's own page (21 of its 53 extra rows), and dropping a variant
    (-Instruct, -Base) added one entity in 2,161."""
    if is_home(url):
        return None
    got = platform_thing(url)
    if not got:
        return None
    kind, owner, thing = got
    want = {w for w in (squash(n) for n in names if n) if len(w) >= NAME_MIN}
    return (kind, owner or None) if squash(key(thing)) in want else None


def owner_agrees(owner: Optional[str], makers: Iterable[str], squash) -> bool:
    """A platform owner is the entity's stated maker: the maker's name run together is the owner's, whole or less a
    handle suffix ("acme-ai" is Acme's)."""
    if not owner:
        return False
    from insight_core.markx.names import handle_forms
    forms = set(handle_forms(owner)) | {squash(owner.casefold())}
    wants = {squash(m) for m in makers if m}
    # v10.35: or the owner's handle starts with the maker's name (4+ characters): an org's handle is its name with a
    # word after it (anthropics, google-deepmind, meta-llama, qwenlm), never another's holding it inside
    return any(w in forms for w in wants if len(w) >= 3) or \
        any(f.startswith(w) for f in forms for w in wants if len(w) >= NAME_MIN)


def one_owner(rows: Sequence[Tuple[str, str, Optional[str]]], makers: Iterable[str], squash) -> Set[str]:
    """(kind, url, owner) rows of rule `repo` -> the urls kept: a kind whose rows name 2+ owners (a fork, a namesake,
    a republisher: measured, 5 of 530 entities) keeps only the rows whose owner is the stated maker, none when no
    owner is; a kind of one owner keeps its rows."""
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
    """v10.35: a conversation with an app, not a publication (discover_rules.app_address: an opaque id after a share
    or chat segment: chatgpt.com/c/<id>, /g/<gpt>/c/<id>, /share/<id>, claude.ai/chat/<id>): never an address of
    anything, never a page its posts cite (a private chat)."""
    from insight_core.utils.discover_rules import app_address
    return app_address(url)


_VOICE_SITES = frozenset(s for sites in PLATFORM_SITES.values() for s in sites)


def voice_account(url: str) -> Optional[str]:
    """v10.35: the account a voice platform's page is under (a tweet's author, a subreddit, a channel, a Bluesky handle:
    addresses.account_key's last part); "" for a platform page under no account (a Hacker News item, a /watch video);
    None off the voice platforms."""
    if site_of(host_of(url)) not in _VOICE_SITES:
        return None
    from insight_core.utils.discover_rules import NOT_ACCOUNT
    parts = account_key(url).split("/")
    if len(parts) == 3 and parts[1] == "r":
        return ""   # a community (a subreddit) is nobody's account: its threads are its members'
    seg = parts[-1].lstrip("@")
    return "" if not seg or seg in NOT_ACCOUNT or seg in ("item", "watch", "comments", "v") else seg


def platform_page_own(url: str, *, repo: Optional[Tuple[str, Optional[str]]], names: Iterable[str],
                      makers: Iterable[str], squash) -> Optional[bool]:
    """v10.35: whether a platform's page is the entity's own (None: not a platform's page, the site rules decide):
    a voice platform's post is its account's, own when that account is the entity's or its maker's; a code host's, a
    model hub's or a package index's page is own as rule `repo`'s page of one thing named as it (a fork's or a
    namesake's: one_owner, by the stated maker), else as a page in a repository that is the entity's: named as it or
    a word run of its name (its version aside: llm-tool/releases/tag/0.22 for "llm-tool 0.22"; isaac-sim/IsaacSim for
    "NVIDIA Isaac Sim 6.0"), or under its maker (lightninglabs/loop for Lightning Labs' "Lightning Loop"); with no
    stated maker, a repository's own page whose name holds the entity's too. A page in another's repository (a pull
    request in vllm, a logs folder), or another owner's project holding its name (someone's claude-code-mcp for
    Anthropic's Claude Code), is a page its post cites. The platform's other sites (docs., gist.) are the site
    rules'."""
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
    o = squash(owner.casefold())
    if (len(o) >= NAME_MIN and any(b.startswith(o) for b in bare_names)):
        return True   # the owner is the name's family (Qwen/... for "Qwen2.5-Omni"): the entity's own line
    if (t in bare_names or squash(name_key(f"{owner}/{thing}")) in bare_names
            or (len(t) >= NAME_MIN and any(t in b for b in bare_names)) or owner_agrees(owner, makers + names, squash)):
        return True
    # a repository's own page whose name holds the entity's, with no stated maker its owner contradicts
    return not makers and not lesser(url) and any(len(b) >= NAME_MIN and b in t for b in bare_names)


HUB_OWNED = (["datasets"], ["collections"], ["blog"])   # a model hub's sections whose pages are an owner's


def repository(url: str) -> Optional[Tuple[str, str]]:
    """v10.35: (owner, thing) of the repository a code host's or a model hub's page is in (its page, a file, a release,
    a pull request in it); None for a platform's own section."""
    segs = _segments(url)
    if site_of(host_of(url)) in MODEL_HUBS and segs[:1] in HUB_OWNED:
        segs = segs[1:]   # a dataset's page, a collection, a blog post (/blog/<owner>/<slug>) of the owner's
    if len(segs) < 2 or segs[0].lower() in PLATFORM_SECTIONS:
        return None
    return segs[0].lstrip("~@"), segs[1]


def lesser(url: str) -> bool:
    """v10.35: a page chosen as an address only when no page of the thing is: a voice platform's post (its maker's
    tweet), a page inside a repository (a file, a pull request, its tree) rather than the repository's page."""
    if voice_account(url) is not None:
        return True
    site = site_of(host_of(url))
    if site not in CODE_SITES and site not in MODEL_HUBS:
        return False
    segs = [s.lower() for s in _segments(url)]
    n = 3 if segs[:1] in HUB_OWNED else 2
    return len(segs) > n and segs[n] != "releases"


def _unversioned(words: List[str]) -> List[str]:
    """A name's words, a version after them aside ("llm-tool 0.22" -> "llm-tool")."""
    while len(words) > 1 and _VERSION.match(words[-1]):
        words = words[:-1]
    return words


def front_page(url: str) -> bool:
    """A site's front page: no path, query or fragment (E2; a one-segment profile is not one)."""
    _, _, rest = bare(url).partition("/")
    return rest.strip("/") == ""


def site_word(url: str) -> str:
    """A site's own word, run together: ai-2027.example -> ai2027."""
    return re.sub(r"[^0-9a-z]+", "", site_of(host_of(url)).split(".", 1)[0].lower())


def by_site(url: str, title: Optional[str], names: Iterable[str], key, squash) -> Optional[str]:
    """E2: a document's work site: a front page whose site word is its name run together (rule `site`), or whose
    read title names it (rule `title`); None otherwise, and for any page that is not a front page."""
    if not front_page(url):
        return None
    names = {n for n in names if len(n) >= NAME_MIN}
    word = site_word(url)
    if len(word) >= NAME_MIN and any(squash(n) == word for n in names):
        return SITE
    return TITLE if names & title_keys(title, key) else None


def work_front_allowed(url: str, never: Mapping[str, Set[str]]) -> bool:
    """E5: never a product's, app's, model's, org's or person's front page: `never` is {site word: the types of the
    entities named so}; a front page whose site word names one of NEVER_FRONT_TYPES is no work."""
    return not (set(never.get(site_word(url), ())) & set(NEVER_FRONT_TYPES))


def cited_page(url: str, post_url: Optional[str]) -> bool:
    """F1: a page a long-read cites as a reference: another site's (not the post's own), not a front page, not a
    platform's profile, not an archive's copy, an app's shared page or a reference (help, docs) page. A one-segment
    path elsewhere is an article (news sites' /<slug>: measured on the owner's long-read, 7 of its 27 links)."""
    from insight_core.utils.discover_rules import DISCOVER_PLATFORMS, app_address, archive_address, reference_address
    host = host_of(url)
    if not host or front_page(url) or (is_home(url) and site_of(host) in DISCOVER_PLATFORMS):
        return False
    if archive_address(url) or app_address(url) or reference_address(url):
        return False
    return not post_url or site_of(host_of(url)) != site_of(host_of(post_url))


def pick(addresses: Iterable[Tuple[str, str, str, Any]]) -> Dict[str, Tuple[str, str, Any]]:
    """(kind, url, rule, first_at) rows -> {kind: (url, rule, first_at)}: one a kind, a page of the thing before a
    lesser one (v10.35: its maker's post, a file in its repository), then by the rules' order, then the first found,
    then the address."""
    order = {r: n for n, r in enumerate(RULE_ORDER)}
    out: Dict[str, Tuple[str, str, Any]] = {}
    # 0229: a page its posts cite is no address of it; v10.35: a conversation never is, whatever a row says
    addresses = [a for a in addresses if a[0] != CITED and not conversation(a[1])]
    for kind, url, rule, at in sorted(addresses, key=lambda a: (lesser(a[1]), order.get(a[2], 9), a[3] is None,
                                                                 a[3].timestamp() if a[3] else 0.0, a[1])):
        out.setdefault(kind, (url, rule, at))
    return out


def original_of(picked: Mapping[str, Tuple[str, str, Any]]) -> Optional[Tuple[str, str]]:
    """(kind, url) of the original: the paper page, else the release page; None when it has neither."""
    for kind in ORIGINAL_KINDS:
        if kind in picked:
            return kind, picked[kind][0]
    return None


# ---- B ---------------------------------------------------------------------------------------------

def triggered(voices: int, lead: bool) -> bool:
    """B1: the subject of posts from 2+ voices, or of one voice's post that leads a News row."""
    return voices >= TRIGGER_VOICES or (voices >= 1 and lead)


def credit_cap(oldest_wait: Optional[timedelta], base: float) -> float:
    """B5: the credit's cap rises to RAISED_CAP while an entity original has waited on it over 72 hours."""
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
    """The arXiv API's Atom answer: [(title, authors, abstract page)]."""
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
    """Crossref's works answer: [(title, authors, the DOI's page)]."""
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
    """`by` as written ("A, B and C") as names."""
    return [p.strip() for p in re.split(r",|;|\s+(?:and|и|&)\s+|&", by or "") if p.strip()]


def _same_person(a: str, b: str, key) -> bool:
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return False
    return ka == kb or (ka.split()[-1] == kb.split()[-1] and len(ka.split()[-1]) >= 3)


def lookup_match(name: str, by: Iterable[str], results: Sequence[Tuple[str, Sequence[str], str]], key) -> Optional[str]:
    """C's match: a result whose title is the entity's name by the name key and with an author of `by`."""
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
    """(Discover's address key of the original's site, the original's address, when) rows -> {key: {n, urls,
    since}} for the keys that supplied `least`+ distinct originals in `within`, that you don't follow or hid, and
    that are no paper host (0109: papers stay in stories and Classics)."""
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
    "by_site", "conversation", "front_page", "lesser", "platform_page_own", "repository", "versioned", "voice_account",
    "site_word", "work_front_allowed",
    "MODEL_HUBS", "PACKAGE", "PACKAGE_SITES", "PLATFORM_SECTIONS", "REPO", "by_repo", "one_owner", "owner_agrees", "platform_thing",
    "CITED", "LINK_LABELS", "carries_id", "link_names", "own_site", "paper_is_its_own", "paper_names_it",
    "CODE", "DEMO", "IDENTIFIER", "KINDS", "LOOKUP", "MAKER", "MAKER_TYPES", "PAPER", "RELEASE", "TITLE",
    "not_a_release", "address_kind", "arxiv_query", "by_identifier", "by_maker", "by_names", "by_title", "credit_cap", "crossref_query",
    "lookup_match", "original_of", "paper_page", "paper_ref", "parse_arxiv", "parse_crossref", "pick", "ref_page",
    "supplier_reason", "suppliers", "title_keys", "triggered",
]
