"""Mark X perspectives inside a story and the story sheet (issue 0119 B, 0120 v3.2f), in Shadow.

The decision run's stage `perspectives_plan` (after `entities` and `surges`, so the members' mentions are linked),
in the run's one snapshot, writing mx_perspectives, mx_sheets and tasks only:

  B1. **Which stories:** the Mark X stories of the newest written News rows of the News window with 3 or more voices.
      A story is judged again only when its member set changed since its sheet (the member set hash, `member_hash`).
      A story waits while one of its members has an entities task not answered yet (the maker comes from them).
  B2. **The inputs, by code** (the lab's persp32.Story, plan/research/lab/markx/proto, without its word lists and
      handle maps): duplicates and near-copies folded (same source, same folded text or shingle Jaccard >= 0.6);
      the original by links (the page most members link), by the maker (0090's maker field read through part A's
      identity, `Makers`), by a page-kind member on the maker's page and by a link post carrying the maker's page
      (repository and model page titles read); one original per page; when no member is the original, the page
      members link is shown as the source page. The maker's own account is a hint for Haiku ("[the maker's own
      account or staff]"), never a label. Members in published order (a saved page by its own date); "same" settled
      by code where it is certain (nothing of its own, a copy, a bare link to a page already in the story).
  B3. **`perspective` tasks** (persp-v1 = the lab's frozen persp_v32f_frozen.md, md5 ee89e27e...): one task a story,
      or a group of at most PER_CALL members; a member the answer skips is asked again alone, at most twice (the
      second time the same task reopened). The answer per member is checked by `final` (the lab's `final()`): every
      span occurs in the member's text, facts not about the story dropped, a fact whose quantities all appear earlier
      dropped, at most MAX_FACTS facts, the label order enforced, a one-line take is `same`.
  B4. **One `sheet` task** (persp-merge-v1 = persp_merge_v1.md) a story with two or more fact lines, then the sheet
      (`build_sheet`, the lab's `sheet()` as data): the original or source page, new facts merged with their members,
      before the release, unconfirmed claims, opinions, related, "N more say the same".
  B5. **Storage:** a perspective or sheet that changes opens a new row and closes the old one (valid_to); a member
      gone from the story is closed. Nothing is deleted.

Inputs are content only (the posts' texts and links, the code's findings): the same story asks the same question,
whatever its ids. A member's key in the input is "<the story's first kept post, 8>:<the post, 8>", as the lab's.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import names as N

LABELS = ("original", "new_facts", "opinion", "same", "not_this_story")
WORTH = frozenset({"original", "new_facts", "opinion"})
PER_CALL = 5             # members a perspective task judges (the lab's PER_CALL: long inputs mixed items up at 10)
RETRIES = 2              # a member a call skips is asked again alone, at most twice
MAX_FACTS = 4            # facts a member keeps (the guide asks at most 4)
MIN_VOICES = 3           # B1
VERSION = "persp-v1-code-1"   # the code steps' version: in the member hash, so a change re-plans every story
PLATFORMS = {"reddit.com", "t.me", "youtube.com", "youtu.be", "news.ycombinator.com", "arxiv.org", "medium.com",
             "substack.com", "piped.video", "nitter.local"}   # hosts whose pages are a platform's, not an owner's
PAGE_KINDS = {"site", "hn", "saved", "youtube"}
X_HOSTS = ("x.com", "twitter.com", "nitter.local")
MAKER_ROLES = ("subject", "actor")
ORG_TYPES = ("org",)


# ---- the members, as the code steps read them ---------------------------------------------------------

@dataclass
class Member:
    id: str
    src: str                  # the source's id
    src_name: str
    kind: str
    at: datetime              # COALESCE(surfaced_at, published_at, fetched_at)
    published: Optional[datetime]
    title: str
    text: str
    url: Optional[str] = None
    nurl: Optional[str] = None
    links: List[str] = field(default_factory=list)   # raw link targets, in order


def load_members(cur: Any, ids: Iterable[Any]) -> Dict[str, Member]:
    """{id: Member}: markx text v1 (tasks.load_posts) with each post's address and published date."""
    from insight_core.markx import tasks
    ids = [str(i) for i in ids]
    got = tasks.load_posts(cur, ids)
    if not got:
        return {}
    cur.execute("SELECT id::text, url, normalized_url, published_at FROM posts WHERE id = ANY(%s::uuid[])", (list(got),))
    extra = {r[0]: r[1:] for r in cur.fetchall()}
    out = {}
    for pid, p in got.items():
        url, nu, published = extra.get(pid, (None, None, None))
        out[pid] = Member(id=pid, src=p.source_id, src_name=p.source, kind=p.kind, at=p.at, published=published,
                          title=p.title, text=(p.text or "")[:8000], url=url, nurl=nu,
                          links=[u for u, _ in p.links if u])
    return out


# ---- the lab's text helpers (x1_persp, persp32) ---------------------------------------------------------

def nurl(u: Optional[str]) -> str:
    u = re.sub(r"^https?://(www\.|m\.|mobile\.)?", "", (u or "").strip().lower())
    return re.sub(r"[?#].*$", "", u).rstrip("/")


def words(s: Optional[str]) -> List[str]:
    return re.findall(r"\w+", (s or "").lower())


def shingles(s: Optional[str], k: int = 5) -> Set[Tuple[str, ...]]:
    w = words(s)
    return {tuple(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def jacc(a: Set, b: Set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def fold(s: Optional[str]) -> str:
    return re.sub(r"[\W_]+", " ", (s or "").lower().replace("ё", "е")).strip()


def squash(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def pub(p: Member) -> datetime:
    """Published order: a saved page by the page's own date, every other post by when it was posted."""
    return (p.published or p.at) if p.kind == "saved" else p.at


def iso16(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat()[:16]


def text(p: Member) -> str:
    return (p.title or "") + " " + (p.text or "")


def links(p: Member) -> List[str]:
    return [nurl(u) for u in p.links if u]


def own_pages(p: Member) -> Set[str]:
    return {nurl(p.url), nurl(p.nurl)} - {""}


def owner(u: Optional[str]) -> Optional[str]:
    """Who a page belongs to: an X account, a GitHub / Hugging Face org (its blog too), or a site's name."""
    if not u:
        return None
    parts = u.split("/")
    d_ = parts[0]
    if d_ in X_HOSTS:
        return parts[1].lower() if len(parts) > 1 else None
    if d_ in ("github.com", "huggingface.co"):
        if len(parts) > 2 and parts[1] == "blog":
            return parts[2].lower() if len(parts) > 3 else None
        return parts[1].lower() if len(parts) > 1 and parts[1] not in ("blog", "spaces", "papers", "collections") else \
            (parts[2].lower() if len(parts) > 2 and parts[1] == "collections" else None)
    if d_ in PLATFORMS or any(d_.endswith("." + p) for p in PLATFORMS):
        return None
    lab = d_.split(".")
    return lab[-2] if len(lab) >= 2 else None


# ---- the maker, by identity (part A) instead of the lab's word lists ------------------------------------

class Makers:
    """Who makes what, read from the members' mentions (ent-v3, linked by part A) and the entity book: a mention's
    stated maker, an org named as subject or actor, an entity's maker or its ancestors'. A page owner, an account or a
    source's name is the maker when one of its handle forms is one of the maker's names (its aliases, squashed)."""

    def __init__(self, book: Any, mentions: Dict[str, List[Dict[str, Any]]]) -> None:
        self.book, self.mentions = book, mentions
        self._forms: Dict[str, Set[str]] = defaultdict(set)
        for k, eid in book.alias.items():
            r = book.root(eid)
            if r:
                self._forms[r].add(N.squash(k))
        for eid, e in book.ents.items():
            r = book.root(eid)
            if r:
                self._forms[r].add(N.squash(e.key))
        makers = {self.of_name(e.maker) for e in book.ents.values() if e.maker} - {None}
        self._index: Dict[str, Set[str]] = defaultdict(set)
        for r, fs in self._forms.items():
            e = book.ents.get(r)
            if e is not None and (e.type in ORG_TYPES or r in makers):
                for f in fs:
                    if f:
                        self._index[f].add(r)

    def root(self, eid: Optional[str]) -> Optional[str]:
        return self.book.root(eid) if eid else None

    def of_name(self, name: Optional[str]) -> Optional[str]:
        k = N.key(name)
        return self.root(self.book.by_key(k)) if k else None

    def forms(self, root: Optional[str]) -> Set[str]:
        return self._forms.get(root, set()) if root else set()

    def of_owner(self, o: Optional[str]) -> Optional[str]:
        """The one maker an owner string (a handle, an org, a site's name) names, or None."""
        if not o:
            return None
        found = set()
        for f in N.handle_forms(o):
            found |= self._index.get(f, set())
        return next(iter(found)) if len(found) == 1 else None

    def is_maker(self, o: Optional[str], mk: Optional[str]) -> bool:
        """Whether an owner string is the maker `mk` (a root entity)."""
        if not o or not mk:
            return False
        fs = self.forms(mk)
        return any(f in fs for f in N.handle_forms(o))

    def ancestors(self, root: Optional[str]) -> List[str]:
        out, seen = [], set()
        e = self.book.ents.get(root) if root else None
        while e is not None and e.id not in seen:
            seen.add(e.id)
            up = [self.root(e.parent)] if e.parent else []
            if e.maker:
                up.append(self.of_name(e.maker))
            for u in up:
                if u and u not in out:
                    out.append(u)
            e = self.book.ents.get(up[0]) if up and up[0] else None
        return out

    def hits(self, post: str) -> Set[str]:
        """The makers a post names as its subject's: stated makers, orgs as subject or actor, and their entities'."""
        out: Set[str] = set()
        for m in self.mentions.get(post, ()):
            if m.get("role") not in MAKER_ROLES:
                continue
            r = self.root(m.get("entity_id"))
            if m.get("maker"):
                got = self.of_name(m["maker"])
                if got:
                    out.add(got)
            elif m.get("type") in ORG_TYPES:
                got = r or self.of_name(m.get("name"))
                if got:
                    out.add(got)
            if r and m.get("type") not in ORG_TYPES:
                for a in self.ancestors(r):
                    e = self.book.ents.get(a)
                    if e is not None and e.type in ORG_TYPES:
                        out.add(a)
                        break
        return out

    def author_is(self, p: Member, mk: Optional[str]) -> bool:
        """The member's source is the maker or the maker's (its name an entity whose maker or ancestor is `mk`, or one
        of the maker's names)."""
        if not mk:
            return False
        r = self.of_name(p.src_name)
        if r and (r == mk or mk in self.ancestors(r)):
            return True
        return self.is_maker(re.sub(r"\s+", "", (p.src_name or "").lower()), mk)


# ---- one story's code steps (persp32.Story) -------------------------------------------------------------

class Story:
    """by: post id -> Member; posts: the member ids; makers: who makes what (None: no maker is ever found)."""

    def __init__(self, posts: Sequence[str], by: Dict[str, Member], makers: Optional[Makers] = None) -> None:
        self.by, self.mk = by, makers
        ids = sorted(posts, key=lambda i: (pub(by[i]), i))
        seen: Dict[Tuple[str, str], str] = {}
        keep: List[str] = []
        dup: Dict[str, List[str]] = defaultdict(list)
        for i in ids:                                          # 1. duplicates: same source, same folded text
            k = (by[i].src, fold(text(by[i]))[:400])
            near = next((j for j in keep if by[j].src == by[i].src
                         and jacc(shingles(text(by[i])), shingles(text(by[j]))) >= 0.6), None)
            if k in seen:
                dup[seen[k]].append(i)
            elif near:                                         # the same source posting it again, a little edited
                dup[near].append(i)
            else:
                seen[k] = i
                keep.append(i)
        self.ids, self.dup = keep, dict(dup)
        self.dup_of = {c: k for k, cs in dup.items() for c in cs}
        self.sid = self.ids[0][:8] if self.ids else ""
        self.maker = self._maker()
        self.code: Dict[str, Tuple[str, str]] = {}
        self.how: Set[str] = set()
        self._originals()
        self._same()

    # the maker
    def _maker(self) -> Optional[str]:
        if self.mk is None:
            return None
        c: Counter = Counter()
        for i in self.ids:
            P = self.by[i]
            hit = set(self.mk.hits(i))
            for u in links(P)[:3] + sorted(own_pages(P)):
                got = self.mk.of_owner(owner(u))
                if got:
                    hit.add(got)
            for o in hit:
                c[o] += 1
        if not c:
            return None
        o, n = sorted(c.items(), key=lambda x: (-x[1], x[0]))[0]
        return o if n * 2 >= len(self.ids) else None

    def is_maker(self, o: Optional[str]) -> bool:
        return self.mk is not None and self.mk.is_maker(o, self.maker)

    def own_words(self, i: str, before: Sequence[str]) -> int:
        seen: Set[str] = set()
        for j in before:
            seen |= set(words(text(self.by[j])))
            seen |= set(w for u in links(self.by[j]) for w in words(u))
        seen |= set(w for u in links(self.by[i]) for w in words(u))
        return sum(1 for w in words(text(self.by[i])) if w not in seen)

    def main_link(self, i: str) -> Optional[str]:
        """The page a link post carries: a repository or model page by its title, a link whose last path part is in
        the title, else the first link of a short post."""
        P = self.by[i]
        tt = fold(P.title)
        m = re.match(r"^\s*([\w.-]+)/([\w.-]+) · Hugging Face\s*$", P.title or "") or \
            re.match(r"^\s*GitHub - ([\w.-]+)/([\w.-]+)", P.title or "")
        if m:
            host = "huggingface.co" if "Hugging Face" in (P.title or "") else "github.com"
            return f"{host}/{m.group(1).lower()}/{m.group(2).lower()}"
        for u in links(P)[:6]:
            seg = fold(u.rstrip("/").split("/")[-1])
            if len(seg) >= 6 and seg in tt:
                return u
        if len(words(P.text)) < 40 and links(P):
            return links(P)[0]
        return None

    def _originals(self) -> None:
        by, mk = self.by, self.maker
        cnt = Counter(u for i in self.ids for u in set(links(by[i])))
        if cnt:                                                # 2a. the page most members link to
            u, n = sorted(cnt.items(), key=lambda x: (-x[1], x[0]))[0]
            if n >= 2:
                for i in self.ids:
                    if u in own_pages(by[i]):
                        self.code[i] = ("original", "links")
                        self.how.add("links")
        for i in self.ids:                                     # 2b. the maker: its source, its page
            if i in self.code or not mk:
                continue
            P = by[i]
            src_is = self.mk.author_is(P, mk) or (P.kind == "site" and self.is_maker(owner(nurl(P.url))))
            if P.kind == "x" and self.is_maker(owner(nurl(P.url))):
                src_is = True                                  # the maker's own account (a repost carrier keeps its url)
            if src_is:
                k = self.ids.index(i)
                earlier = [j for j in self.ids[:k] if self.code.get(j, ("", ""))[1] in ("maker", "maker-page", "links")]
                if not earlier or self.own_words(i, self.ids[:k]) >= 25:
                    self.code[i] = ("original", "maker")
                    self.how.add("maker")
            elif any(self.is_maker(owner(u)) for u in own_pages(P)) and P.kind in PAGE_KINDS:
                self.code[i] = ("original", "maker-page")
                self.how.add("maker-page")
        for i in self.ids:                                     # a link post to the maker's page, not yet in the story
            if i in self.code or not mk:
                continue
            ml = self.main_link(i)
            P = by[i]
            carrier = P.kind in ("reddit", "hn") or len(words(P.text)) < 25
            if ml and carrier and self.is_maker(owner(ml)):
                have = set().union(*[own_pages(by[j]) for j in self.ids]) | \
                    set().union(*[set(links(by[j])) for j in self.ids if self.code.get(j, ("",))[0] == "original"])
                if ml not in have:
                    self.code[i] = ("original", "maker-link")
                    self.how.add("maker-link")
        pages: Dict[str, str] = {}                             # one original per page; the maker's own posts stay
        for i in self.ids:
            if self.code.get(i, ("",))[0] != "original" or self.code[i][1] == "maker":
                continue
            pg = (own_pages(by[i]) if by[i].kind in PAGE_KINDS or self.code[i][1] == "links" else set()) | \
                ({self.main_link(i)} if self.code[i][1] == "maker-link" else set())
            pg = frozenset(p for p in pg if p)
            first = next((pages[p] for p in sorted(pg) if p in pages), None)
            if first:
                self.code[i] = ("same", "same-page")
            else:
                for p in pg:
                    pages[p] = i
        self.hint: Dict[str, str] = {}                         # v3.2f: the maker's own account is a hint, not a label
        for i in [i for i in self.ids if self.code.get(i, ("", ""))[1] == "maker"]:
            del self.code[i]
            self.hint[i] = " [the maker's own account or staff]"
        self.origs = [i for i in self.ids if self.code.get(i, ("",))[0] == "original"]
        txt = lambda i: len(words(by[i].text)) >= 30
        self.ref = next((i for i in self.origs if txt(i)), None) or next((i for i in self.ids if txt(i)), self.ids[0])
        self.ref_is_original = self.ref in self.origs
        self.t0 = pub(by[self.ref]) if self.ref_is_original else None
        self.src_page = None                                   # no member is the source: the page members link
        if not self.origs:
            member_pages = set().union(*[own_pages(by[i]) for i in self.ids])
            c = Counter(u for i in self.ids for u in set(links(by[i])[:4]) if u not in member_pages and owner(u))
            ranked = sorted(c.items(), key=lambda x: (-x[1], x[0]))
            best = [u for u, n in ranked if n >= 2] + [u for u, _ in ranked if mk and self.is_maker(owner(u))]
            self.src_page = best[0] if best else None

    def story_pages(self, k: int) -> Set[str]:
        s: Set[str] = set()
        for i in self.ids[:k]:
            s |= own_pages(self.by[i])
        for i in self.origs:
            s |= set(links(self.by[i])) | own_pages(self.by[i])
        return s

    def _same(self) -> None:
        by = self.by
        for n_, i in enumerate(self.ids):                      # 4. same by code
            if i in self.code:
                continue
            pages = self.story_pages(n_)
            P = by[i]
            before = list(self.ids[:n_])
            if self.ref_is_original and self.ref not in before:
                before.append(self.ref)                        # the original is read first
            ow = self.own_words(i, [j for j in before if j != i])
            if len(words(text(P))) >= 80 or ow >= 15:
                continue
            if ow < 4:
                self.code[i] = ("same", "nothing-own")
                continue
            for j in before:
                if j != i and jacc(shingles(text(P)), shingles(text(by[j]))) >= 0.3:
                    self.code[i] = ("same", "copy")
                    break
            else:
                ml = links(P)
                if ml and any(u in pages for u in ml[:2]) and ow < 15:
                    self.code[i] = ("same", "links-source")

    # the input
    def who(self, i: str) -> str:
        """The address, and for a repost or quote the account that wrote it."""
        P = self.by[i]
        u = nurl(P.url)
        a = owner(u) if u.split("/")[0] in X_HOSTS else None
        by_ = (f", written by @{a}" if a and a != fold(P.src_name).replace(" ", "")
               and a.lower() != (P.src_name or "").lower() else "")
        return f", address {u[:110]}{by_}"

    def mid(self, i: str) -> str:
        return f"{self.sid}:{i[:8]}"

    def subject(self) -> str:
        return squash(self.by[self.ref].title)[:160]

    def context(self) -> str:
        R = self.by[self.ref]
        head = "ORIGINAL" if self.ref_is_original else "EARLIEST REPORT (no primary source found by links)"
        out = [f"SUBJECT: {self.subject()}",
               f"{head} = member id {self.mid(self.ref)} [{R.src_name}, {R.kind}, {iso16(pub(R))}{self.who(self.ref)}]"
               f"{self.hint.get(self.ref, '')}",
               f"Title: {R.title}", "Text: " + squash(R.text)[:1500]]
        if self.src_page:
            out.insert(1, f"SOURCE PAGE (the primary source; not a member, members link it): {self.src_page}")
        other = [i for i in self.origs if i != self.ref]
        if other:
            out.append("Also primary sources: " + "; ".join(f"{self.by[i].src_name} ({(self.by[i].title or '')[:80]})"
                                                            for i in other))
        out += ["", "MEMBERS IN PUBLISHED ORDER:"]
        for i in self.ids:
            if i == self.ref:
                continue
            P = self.by[i]
            tag = " [before the original]" if self.t0 and pub(P) < self.t0 else ""
            ln = (f"- id {self.mid(i)} [{P.src_name}, {P.kind}, {iso16(pub(P))}{self.who(i)}]{self.hint.get(i, '')}{tag} "
                  f"{(P.title or '')[:140]} :: {squash(P.text)[:700]}")
            if P.links:
                ln += " || links: " + " | ".join(P.links[:3])
            out.append(ln)
        return "\n".join(out)

    def targets(self) -> List[str]:
        """The member keys Haiku is asked about (those the code did not settle), in published order."""
        return [self.mid(i) for i in self.ids if i not in self.code]

    def groups(self) -> List[List[str]]:
        t = self.targets()
        return [t[k:k + PER_CALL] for k in range(0, len(t), PER_CALL)]

    def input(self, keys: Sequence[str]) -> str:
        return self.context() + "\n\nJUDGE: " + ", ".join(keys)

    def post_of(self, key: str) -> Optional[str]:
        return next((i for i in self.ids if self.mid(i) == key), None)


# ---- the final checks (persp32.final) ---------------------------------------------------------------------

QTY = re.compile(r"(?<![\w.-])[$€]?\d+(?:[.,]\d+)?\s?(?:%|x|×|b|t|m|k|bn|billion|trillion|million|\$)?(?![\w.-])", re.I)


def quantities(s: Optional[str]) -> Set[str]:
    return {re.sub(r"\s|,", "", q.lower()) for q in QTY.findall(s or "")}


def earlier_ids(st: Story, i: str) -> List[str]:
    k = st.ids.index(i)
    return [j for j in st.ids[:k] + ([st.ref] if st.ref not in st.ids[:k] else []) if j != i]


def earlier_text(st: Story, i: str) -> str:
    return " ".join(text(st.by[j]) for j in earlier_ids(st, i))


def repeated(f: Dict[str, Any], seen: str) -> bool:
    """A fact that only repeats figures given before: every quantity in its span already appears earlier."""
    q = quantities(f.get("span"))
    return bool(q) and q <= quantities(seen)


def final(st: Story, raw: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The code steps and Haiku's answers ({member key: answer}) -> {member key: record}, the order enforced. A member
    with no answer has no record."""
    out: Dict[str, Dict[str, Any]] = {}
    for i in st.ids:
        k = st.mid(i)
        if i in st.code:
            out[k] = {"label": st.code[i][0], "by": "code:" + st.code[i][1], "facts": [], "claims": [], "point": None,
                      "haiku_label": None, "dropped": 0, "before": bool(st.t0 and pub(st.by[i]) < st.t0)}
            continue
        if k not in raw:
            continue
        o = raw[k]
        t = fold(text(st.by[i]))
        inpost = lambda s: isinstance(s, str) and bool(s) and fold(s)[:120] in t
        allf = [f for f in (o.get("facts") or []) if isinstance(f, dict)]
        seen = earlier_text(st, i)
        facts = [f for f in allf if inpost(f.get("span")) and f.get("about_story", True) is not False
                 and not repeated(f, seen)][:MAX_FACTS]
        claims = [c for c in (o.get("claims") or []) if isinstance(c, dict) and inpost(c.get("span"))]
        lab = o.get("label")
        if lab not in ("not_this_story", "original"):
            if facts:
                lab = "new_facts"
            elif lab == "new_facts":
                lab = "opinion" if (claims or o.get("point")) else "same"
        if lab == "opinion" and not claims and st.own_words(i, earlier_ids(st, i)) < 12:
            lab = "same"                                       # a one-line take: few words of its own
        out[k] = {"label": lab, "by": "haiku", "haiku_label": o.get("label"),
                  "facts": [{k2: f.get(k2) for k2 in ("fact", "span", "correction", "about_story")} for f in facts],
                  "claims": [{"claim": c.get("claim"), "span": c.get("span")} for c in claims],
                  "dropped": len(allf) - len(facts), "point": o.get("point") if isinstance(o.get("point"), str) else None,
                  "before": bool(st.t0 and pub(st.by[i]) < st.t0)}
    return out


# ---- the sheet (persp32.merge_facts, sheet) -------------------------------------------------------------

def fact_lines(st: Story, fin: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    lines = []
    for i in st.ids:
        a = fin.get(st.mid(i)) or {}
        for f in a.get("facts") or []:
            lines.append({"n": len(lines) + 1, "fact": f.get("fact") or "", "post": i, "src": st.by[i].src_name,
                          "correction": bool(f.get("correction")), "before": bool(a.get("before"))})
    return lines


def merge_input(st: Story, lines: Sequence[Dict[str, Any]]) -> Optional[str]:
    """The sheet task's input: the subject and the numbered fact lines with their sources; None under two lines."""
    if len(lines) < 2:
        return None
    return f"SUBJECT: {st.subject()}\nFACT LINES:\n" + "\n".join(f"{l['n']}. {l['fact']} ({l['src']})" for l in lines)


def merged(lines: Sequence[Dict[str, Any]], answer: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The fact lines grouped by the merge answer (lines it leaves out stay alone; a line in two groups counts once)."""
    used: Set[int] = set()
    out = []
    for g in (answer or {}).get("groups") or []:
        if not isinstance(g, dict):
            continue
        ns = [n for n in g.get("lines") or [] if isinstance(n, int) and not isinstance(n, bool)
              and 1 <= n <= len(lines) and n not in used]
        if not ns:
            continue
        used |= set(ns)
        ls = [lines[n - 1] for n in ns]
        out.append({"fact": g.get("fact") or ls[0]["fact"], "posts": list(dict.fromkeys(l["post"] for l in ls)),
                    "sources": list(dict.fromkeys(l["src"] for l in ls)),
                    "correction": bool(g.get("correction")) or any(l["correction"] for l in ls),
                    "before": all(l["before"] for l in ls), "lines": ns})
    for l in lines:
        if l["n"] not in used:
            out.append({"fact": l["fact"], "posts": [l["post"]], "sources": [l["src"]], "correction": l["correction"],
                        "before": l["before"], "lines": [l["n"]]})
    return out


def build_sheet(st: Story, fin: Dict[str, Dict[str, Any]], answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The sheet as data: what the page shows above the members."""
    R = st.by[st.ref]
    rec = lambda i: fin.get(st.mid(i)) or {}
    facts = merged(fact_lines(st, fin), answer)
    claims = [{"claim": c.get("claim"), "post": i, "source": st.by[i].src_name}
              for i in st.ids if rec(i).get("label") != "not_this_story" for c in rec(i).get("claims") or []]
    before_claims = [c for c in claims if rec(c["post"]).get("before")]
    related, seen = [], set()
    for i in st.ids:
        if rec(i).get("label") == "not_this_story":
            k = (st.by[i].src_name, fold(st.by[i].title)[:80])
            if k not in seen:
                seen.add(k)
                related.append({"post": i, "source": st.by[i].src_name, "title": (st.by[i].title or "")[:140]})
    return {
        "subject": st.subject(),
        "original": {"post": st.ref, "is_original": st.ref_is_original, "title": R.title, "source": R.src_name,
                     "at": pub(R).isoformat(), "text": squash(R.text)[:260],
                     "also": [{"post": i, "source": st.by[i].src_name, "title": (st.by[i].title or "")[:80]}
                              for i in st.origs if i != st.ref]},
        "source_page": st.src_page,
        "new_facts": [f for f in facts if not f["before"]],
        "before": {"facts": [f for f in facts if f["before"]], "claims": before_claims},
        "claims": [c for c in claims if not rec(c["post"]).get("before")],
        "opinions": [{"point": rec(i).get("point"), "post": i, "source": st.by[i].src_name}
                     for i in st.ids if rec(i).get("label") == "opinion"],
        "same": sum(1 for i in st.ids if rec(i).get("label") == "same"),
        "copies": sum(len(v) for v in st.dup.values()),
        "related": related,
        "lines": sum(len(f["lines"]) for f in facts), "merged": len(facts),
    }


# ---- the stage ---------------------------------------------------------------------------------------------

def member_hash(members: Iterable[str]) -> str:
    return hashlib.sha256(json.dumps([VERSION, sorted(set(members))]).encode()).hexdigest()


def news_stories(cur: Any, now: datetime) -> Dict[str, List[str]]:
    """{Mark X story: its current members} of the newest written News rows begun in the News window."""
    from insight_core.markx import news as mx_news, repo
    from insight_core.utils.news_rules import NEWS_DAYS
    run = mx_news.last_written(cur)
    if run is None:
        return {}
    since = now - timedelta(days=NEWS_DAYS)
    ids = sorted({str(p["story"]) for r in repo.news_rows(cur, run) if r["first_at"] >= since
                  for p in r["posts"] or [] if p.get("story")})
    if not ids:
        return {}
    cur.execute("""SELECT sp.story_id::text, sp.post_id::text FROM mx_story_posts sp JOIN mx_stories s ON s.id = sp.story_id
                    WHERE sp.story_id = ANY(%s::uuid[]) AND sp.valid_to IS NULL AND sp.role = 'member'
                      AND s.merged_into IS NULL ORDER BY 1, 2""", (ids,))
    out: Dict[str, List[str]] = defaultdict(list)
    for sid, pid in cur.fetchall():
        out[sid].append(pid)
    return dict(out)


def done_hashes(cur: Any, story_ids: Sequence[str]) -> Dict[str, str]:
    cur.execute("SELECT story_id::text, member_hash FROM mx_sheets WHERE valid_to IS NULL AND story_id = ANY(%s::uuid[])",
                (list(story_ids),))
    return dict(cur.fetchall())


def entities_waiting(cur: Any, posts: Sequence[str]) -> Set[str]:
    """The posts whose entities task is open or leased (their mentions, the maker's evidence, are still to come)."""
    cur.execute("""SELECT DISTINCT a::text FROM mx_tasks WHERE kind = 'entities' AND status IN ('open', 'leased')
                    AND a = ANY(%s::uuid[])""", (list(posts),))
    return {r[0] for r in cur.fetchall()}


def mentions_of(cur: Any, posts: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    cur.execute("""SELECT post_id::text, type, role, maker, entity_id::text, name FROM mx_mentions
                    WHERE guide = 'ent-v3' AND post_id = ANY(%s::uuid[]) ORDER BY post_id, n""", (list(posts),))
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for pid, type_, role, maker, eid, name in cur.fetchall():
        out[pid].append({"type": type_, "role": role, "maker": maker, "entity_id": eid, "name": name})
    return dict(out)


def _status(cur: Any, kind: str, text: str) -> Optional[str]:
    from insight_core.markx import repo, schemas
    t = repo.task_for(cur, kind=kind, guide=schemas.KINDS[kind].guide, input=text)
    return None if t is None else t["status"]


class Judged:
    """One story's answers as the run reads them: {member key: (answer, call id)}, and the members still waiting."""

    def __init__(self) -> None:
        self.raw: Dict[str, Dict[str, Any]] = {}
        self.calls: Dict[str, str] = {}
        self.waiting: Set[str] = set()
        self.given_up: Set[str] = set()

    def take(self, answer: Optional[Dict[str, Any]], call: Optional[str], keys: Sequence[str]) -> None:
        for x in (answer or {}).get("members") or []:
            if isinstance(x, dict) and x.get("id") in keys and x["id"] not in self.raw and x.get("label") in LABELS:
                self.raw[x["id"]] = x
                self.calls[x["id"]] = call


def judge(cur: Any, st: Story, ask: Any, story_id: str) -> Judged:
    """Asks (or reads) each group's task; a member its group skipped is asked alone, its task reopened once more when
    the first solo answer skips it too."""
    j = Judged()
    missed: List[str] = []
    for g in st.groups():
        text = st.input(g)
        got = ask.answer("perspective", text, a=story_id)
        if got is None:
            if _status(cur, "perspective", text) == "failed":
                missed += g
            else:
                j.waiting |= set(g)
            continue
        j.take(got[0], got[1], g)
        missed += [k for k in g if k not in j.raw]
    for k in missed:
        text = st.input([k])
        got = ask.answer("perspective", text, a=story_id)
        if got is None:
            (j.given_up if _status(cur, "perspective", text) == "failed" else j.waiting).add(k)
            continue
        j.take(got[0], got[1], [k])
        if k in j.raw:
            continue
        later = later_answers(cur, got[1])
        for a, c in later[:RETRIES - 1]:
            j.take(a, c, [k])
        if k in j.raw:
            continue
        if len(later) >= RETRIES - 1:
            j.given_up.add(k)
        else:
            ask.ask_again("perspective", got[1])
            j.waiting.add(k)
    return j


def later_answers(cur: Any, first_call: str) -> List[Tuple[Dict[str, Any], str]]:
    cur.execute("""SELECT answer, id::text FROM mx_calls WHERE valid AND task_id = (SELECT task_id FROM mx_calls WHERE id = %s)
                    ORDER BY created_at, ctid""", (first_call,))
    return [(a, c) for a, c in cur.fetchall() if c != first_call]


def _row(rec: Dict[str, Any], copies: Sequence[str]) -> Dict[str, Any]:
    return {"label": rec["label"], "by": rec["by"], "haiku_label": rec.get("haiku_label"), "facts": rec.get("facts") or [],
            "claims": rec.get("claims") or [], "point": rec.get("point"), "before": bool(rec.get("before")),
            "copies": sorted(copies), "dropped": int(rec.get("dropped") or 0), "call_id": rec.get("call_id")}


_FIELDS = ("label", "by", "haiku_label", "facts", "claims", "point", "before", "copies", "dropped", "call_id")


def store(cur: Any, story_id: str, run_id: Any, mhash: str, rows: Dict[str, Dict[str, Any]], now: datetime) -> Dict[str, int]:
    """Each member's row: kept when unchanged, else the old closed and a new one opened; members gone are closed."""
    cur.execute("""SELECT id::text, post_id::text, label, by, haiku_label, facts, claims, point, before, copies, dropped,
                          call_id::text FROM mx_perspectives WHERE story_id = %s AND valid_to IS NULL""", (story_id,))
    have = {r[1]: (r[0], dict(zip(_FIELDS, r[2:]))) for r in cur.fetchall()}
    out = Counter()
    for pid, (rid, old) in have.items():
        if pid not in rows or any(old[f] != rows[pid][f] for f in _FIELDS):
            cur.execute("UPDATE mx_perspectives SET valid_to = %s WHERE id = %s", (max(now, _opened(cur, rid)), rid))
            out["closed"] += 1
    for pid, r in rows.items():
        if pid in have and all(have[pid][1][f] == r[f] for f in _FIELDS):
            out["kept"] += 1
            continue
        cur.execute("""INSERT INTO mx_perspectives (story_id, post_id, run_id, member_hash, label, by, haiku_label, facts,
                                                    claims, point, before, copies, dropped, call_id, valid_from)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, %s, %s, %s)""",
                    (story_id, pid, run_id, mhash, r["label"], r["by"], r["haiku_label"], json.dumps(r["facts"]),
                     json.dumps(r["claims"]), r["point"], r["before"], json.dumps(r["copies"]), r["dropped"],
                     r["call_id"], now))
        out["opened"] += 1
    return dict(out)


def _opened(cur: Any, table_row: str, table: str = "mx_perspectives") -> datetime:
    cur.execute(f"SELECT valid_from FROM {table} WHERE id = %s", (table_row,))
    return cur.fetchone()[0]


def store_sheet(cur: Any, story_id: str, run_id: Any, mhash: str, sheet: Dict[str, Any], call_id: Optional[str],
                now: datetime) -> bool:
    """The story's sheet row: kept when the same, else the old closed and a new one opened. True when opened."""
    cur.execute("SELECT id::text, sheet, call_id::text, member_hash FROM mx_sheets WHERE story_id = %s AND valid_to IS NULL",
                (story_id,))
    got = cur.fetchone()
    if got and got[1] == json.loads(json.dumps(sheet)) and got[2] == call_id and got[3] == mhash:
        return False
    if got:
        cur.execute("UPDATE mx_sheets SET valid_to = %s WHERE id = %s", (max(now, _opened(cur, got[0], "mx_sheets")), got[0]))
    cur.execute("""INSERT INTO mx_sheets (story_id, run_id, member_hash, sheet, call_id, valid_from)
                   VALUES (%s, %s, %s, %s::jsonb, %s, %s)""", (story_id, run_id, mhash, json.dumps(sheet), call_id, now))
    return True


def story_of(cur: Any, members: Sequence[str], posts: Optional[Dict[str, Member]] = None,
             makers: Optional[Makers] = None) -> Optional[Story]:
    posts = posts if posts is not None else load_members(cur, members)
    ids = [p for p in members if p in posts]
    return Story(ids, posts, makers) if ids else None


def one(cur: Any, story_id: str, st: Story, ask: Any, *, run_id: Any, mhash: str, now: datetime) -> Dict[str, Any]:
    """One story: its perspectives asked or read; once every member is settled, its rows, then its sheet."""
    j = judge(cur, st, ask, story_id)
    if j.waiting:
        return {"state": "waiting", "members": len(j.waiting)}
    fin = final(st, j.raw)
    for k, rec in fin.items():
        rec["call_id"] = j.calls.get(k)
    rows = {}
    for i in st.ids:
        rec = fin.get(st.mid(i))
        if rec is not None:
            rows[i] = _row(rec, st.dup.get(i, []))
    lines = fact_lines(st, fin)
    text = merge_input(st, lines)
    answer, call = None, None
    if text is not None:
        got = ask.answer("sheet", text, a=story_id)
        if got is None:
            if _status(cur, "sheet", text) != "failed":
                stored = store(cur, story_id, run_id, mhash, rows, now)
                return {"state": "sheet waiting", **stored}
        else:
            answer, call = got
    stored = store(cur, story_id, run_id, mhash, rows, now)
    opened = store_sheet(cur, story_id, run_id, mhash, build_sheet(st, fin, answer), call, now)
    return {"state": "done", "sheet_opened": opened, "given_up": len(j.given_up), **stored}


def stage(cur: Any, *, ask: Any, now: datetime, run_id: Any, limit: Optional[int] = None) -> Dict[str, Any]:
    """B1-B5 over the News window's stories of MIN_VOICES or more voices (`limit`: at most that many stories built)."""
    from insight_core.markx import identity, tasks
    stories = news_stories(cur, now)
    out: Counter = Counter()
    out["stories"] = len(stories)
    done = done_hashes(cur, sorted(stories))
    todo = {sid: ms for sid, ms in stories.items() if done.get(sid) != member_hash(ms)}
    out["unchanged"] = len(stories) - len(todo)
    if not todo:
        return dict(out)
    every = sorted({p for ms in todo.values() for p in ms})
    posts = load_members(cur, every)
    eligible = {sid: ms for sid, ms in todo.items()
                if len({posts[p].src for p in ms if p in posts and posts[p].kind not in tasks.NOT_VOICE}) >= MIN_VOICES}
    out["fewer_voices"] = len(todo) - len(eligible)
    if not eligible:
        return dict(out)
    waiting = entities_waiting(cur, sorted({p for ms in eligible.values() for p in ms}))
    makers = Makers(identity.load_book(cur), mentions_of(cur, sorted({p for ms in eligible.values() for p in ms})))
    built = 0
    for sid in sorted(eligible, key=lambda s: (-len(eligible[s]), s)):
        ms = eligible[sid]
        if waiting & set(ms):
            out["waiting_entities"] += 1
            continue
        if limit is not None and built >= limit:
            out["over_limit"] += 1
            continue
        st = story_of(cur, ms, posts, makers)
        if st is None:
            continue
        built += 1
        got = one(cur, sid, st, ask, run_id=run_id, mhash=member_hash(ms), now=now)
        out[got["state"]] += 1
        for k in ("opened", "closed", "kept", "given_up"):
            out[k] += got.get(k, 0)
    again = ask.reopen()                     # a skipped member's solo task, asked once more (after the run's own reopen)
    if again.get("perspective"):
        out["reasked"] = again["perspective"]
    return dict(out)
