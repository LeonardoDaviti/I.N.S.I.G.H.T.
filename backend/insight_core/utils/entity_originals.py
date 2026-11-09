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
  3. `maker`: a model, product or software entity whose maker's name is the site's own word: a page on that site
     whose title holds the entity's name (word for word). Never a front page or a profile (`is_home`).
A paper or a release page is the **original**; a code repository and a demo are kept as its links (the post that
gave the paper by rule 1 gives them, when it links one of each).

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

from insight_core.utils.addresses import bare, host_of, paper_file, paper_id, paper_page_order, site_of
from insight_core.utils.discover_rules import paper_address, place_kind
from insight_core.utils.post_links import is_home
from insight_core.utils.url_normalization import normalize_url

PAPER, CODE, DEMO, RELEASE, WORK = "paper", "code", "demo", "release", "work"
KINDS = (PAPER, CODE, DEMO, RELEASE, WORK)
ORIGINAL_KINDS = (PAPER, RELEASE, WORK)
IDENTIFIER, TITLE, MAKER, SITE, LOOKUP = "identifier", "title", "maker", "site", "lookup"
RULE_ORDER = (IDENTIFIER, TITLE, SITE, MAKER, LOOKUP)
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


def title_keys(title: Optional[str], key) -> Set[str]:
    """The name keys a title can stand for: whole, without a leading [id], and each part of "Title | Site"."""
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
    t = name_key(title)
    # the name is what the page is about: half its title's words or more ("Introducing Nimbus 4"), never a page that
    # names it in passing ("How Nimbus helped a lab ...": measured, the maker rule's wrong rows were all so)
    return any(len(n) >= NAME_MIN and word_contains(n, t) and 2 * len(n.split()) >= len(t.split()) for n in names)


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
    """(kind, url, rule, first_at) rows -> {kind: (url, rule, first_at)}: one a kind, by the rules' order, then the
    first found, then the address."""
    order = {r: n for n, r in enumerate(RULE_ORDER)}
    out: Dict[str, Tuple[str, str, Any]] = {}
    for kind, url, rule, at in sorted(addresses, key=lambda a: (order.get(a[2], 9), a[3] is None, a[3].timestamp() if a[3] else 0.0, a[1])):
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
    "by_site", "front_page", "site_word", "work_front_allowed",
    "CODE", "DEMO", "IDENTIFIER", "KINDS", "LOOKUP", "MAKER", "MAKER_TYPES", "PAPER", "RELEASE", "TITLE",
    "not_a_release", "address_kind", "arxiv_query", "by_identifier", "by_maker", "by_names", "by_title", "credit_cap", "crossref_query",
    "lookup_match", "original_of", "paper_page", "paper_ref", "parse_arxiv", "parse_crossref", "pick", "ref_page",
    "supplier_reason", "suppliers", "title_keys", "triggered",
]
