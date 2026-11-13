"""Pairing (issue 0166): which pairs of posts, or of stories, may ever be compared, for each relation.

A relation is a question a judge may later be asked about a pair: `same_story` (one story? the join, pair and merge
questions of markx/decide.py) and `connected` (a typed connection between two News stories, decide's connect
questions). Each relation has one row of POLICIES: its window, its entity-type policy, its cosine bars, its
independence rule and its unit rule. Every gate of a relation reads that row, so a window or a type list lives in one
place, and a new signal is one more source.

The interface (what a caller must know):
  - `find(cur, relation, post_ids, sources=...)`: the relation's candidate pairs touching these posts, found by its
    sources and stored once per source (mx_candidates, never deleted); {source: pairs added}.
  - `admits(policy, a, b, cos, posts, kinds)`: whether a stored post pair may be judged (decide's gate).
  - `admits_stories(policy, cos, voices_a, voices_b)` and `story_pairs(cur, policy, groups, posts)`: the same for
    two stories (by their centroids, their first posts within the story window).
  - `policy(relation, **overrides)`: the row, with a caller's overrides (decide.Config's bars).
  - `attach_targets(cur, units)` and `attaches(policy, ...)`: the attach relation (0181) for round-up items.
  - the basics every module reads the same way: the dates (`post_date`: the post's date, a round-up's issue time
    when its items are known, else when it surfaced, else published, else fetched; `ordinary_date`, `published_date`
    and `ix_date`: the post's own, 0128's published and Mark IX's time; see "the dates" below), `page_key` and its
    lower layer `page_address` (a page's compared form), `document_key` (a document page's key). Who a post counts
    as, and how many voices posts are, is Voice's (utils/voice.py, Policy.MARKX; issue 0189): every gate here asks it.

The sources (adapters; each idempotent, each writes only mx_candidates):
  - `embedding`: a post's nearest posts by cosine among other sources' voices within the window, at the cosine bar,
    the k nearest of either post, not already in one Mark IX story.
  - `centroid`: Mark IX stories holding a post against every other story whose centroid is at the story bar, their
    first posts within the story window (pairs of stories, kind story_story).
  - `link`: Mark IX's own joins (story_posts' parent edges), read, never changed.
  - `entity`: posts of other sources within the window sharing a subject mention of a type the policy lists, the same
    name key and the same version, not already in one Mark IX story.
  - `burst`: posts of different places linking one page within the window of each other, both more than `late_after`
    after the page's first linker (Mark IX's link window is measured from the first linker), not in one story.
  - `document` (decide's, in memory): two stories two of whose posts link one document page within the document
    window; a roundup's links never count.
  - `happening` (markx/happening.py, off unless the mx_settings flag HAPPENING_KEY is on): posts of different voices
    whose readings name one happening (action group and parties) within the group's window.
  - `link` (attach, 0181; stored by units.py, never in mx_candidates): a round-up's item (a unit) and the
    stored post whose address it links, from ATTACH_WINDOW before the round-up to ATTACH_AFTER after it.

Step 1 of 0166 moved the sources and decide's re-gates here unchanged (the equivalence tests:
tests/test_markx_pairing.py). 0180 (anchors): the third relation, `develops` (a post that follows up an anchor: a
story or a happening), holds back.py's and later.py's gates (their windows, type lists, quiet rule) and E6's
happening windows; `develops(pol, earlier, later, gap)` is its happening gate, `specific(pol, ...)` its subject gate.
graph.py keeps its own gates for now. 0181 (units): the fourth relation, `attach` (a round-up's item -> the stored
post it links, and the story holding it, as a digest item, never a voice), and the round-up's issue time in
`post_date` (its latest attached item's time), so every consumer of the post date reads it.
"""
from __future__ import annotations

import bisect
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

from psycopg import Cursor

from insight_core.markx import repo, schemas
from insight_core.utils import voice
from insight_core.utils.post_links import is_home, source_kind

log = logging.getLogger(__name__)

MODEL = "bge-m3"
POST_POST, STORY_STORY = "post_post", "story_story"
SAME_STORY, CONNECTED, DEVELOPS, ATTACH = "same_story", "connected", "develops", "attach"
# An experiment (0166, 0175; kept as one in v10.17's 0190): the happening source runs only while this mx_settings flag
# is on (off by default): E1 measured its company groups (deal, funding, legal, people), the other groups are
# unmeasured, and nothing turns it on but the owner. Its key is stored either way (mx_happenings, for anchors).
HAPPENING_KEY = "pairing_happening"

# ---- the dates (v10.17, 0190: one owner per decision) ---------------------------------------------------------
# Every SQL date of a post is one of these four meanings, named here and nowhere else (tests/test_dates_owner.py
# fails on an inline COALESCE of a post's dates outside this module):
#   - `post_date`: Mark X's time of a post, what a Mark X comparison reads (windows, timelines, an entity's
#     mentions): a round-up's issue time when its items are known (0181), else its own date.
#   - `ordinary_date`: the post's own date (surfaced, else published, else fetched): the feed's sort key (indexed:
#     posts_feed_order_idx, posts_source_feed_order_idx, 0037), the planners' and the lease's order and reading windows
#     (0176), every task input (0128: a changed input is a new question), and what the issue time is made from.
#   - `published_date`: 0128's "published" (published, else surfaced, else fetched): the order and times a story's
#     lines are shown in (a News row, the folds, the story page) and graph's G2.
#   - `ix_date`: Mark IX's time (published, else fetched; StoryPost.t, 0111's News window, Discover, the source and
#     fetch statistics).
# They differ only on a round-up with an issue time (post_date) and on a post with surfaced_at (49,384 posts on the
# 2026-11-05 copy: 211 issue times, 51 surfaced_at).
ORDINARY_DATE = "COALESCE({p}.surfaced_at, {p}.published_at, {p}.fetched_at)"   # a post's own time
PUBLISHED_DATE = "COALESCE({p}.published_at, {p}.surfaced_at, {p}.fetched_at)"  # 0128's published order
IX_DATE = "COALESCE({p}.published_at, {p}.fetched_at)"                          # Mark IX's time
# 0181: a round-up's time is its issue's (mx_roundups.issue_at: its latest attached item's time within ISSUE_REACH of
# its own date), when its items are known; every other post's (and a round-up's with no such item) is its own time.
# The issue times are read once a query (an InitPlan: one object of a few hundred rows, by a partial index) and looked
# up per row: a correlated lookup on every row made the callers' window queries 3-6x slower on the scratch copy
# (its cost estimate also switched JIT on); this form measured as fast as the old expression (plan/research, private).
POST_DATE = ("COALESCE(((SELECT jsonb_object_agg(r_.post_id, r_.issue_at) FROM mx_roundups r_ "
             "WHERE r_.issue_at IS NOT NULL) ->> ({p}.id::text))::timestamptz, "
             + ORDINARY_DATE + ")")   # Mark X's time of a post


def _alias(alias: str) -> str:
    """'p' -> 'p.', '' -> '' (a query over posts with no alias)."""
    return f"{alias}." if alias else ""


def _form(template: str, alias: str) -> str:
    return template.replace("{p}.", _alias(alias))


def post_date(alias: str = "p") -> str:
    """The post's date as SQL: a round-up's issue time when its items are known (0181); else when INSIGHT first saw
    it surface, else its published time, else its fetch. Never a rewrite of the post's own dates. Needs an alias
    (the issue time is looked up by the post's id)."""
    if not alias:
        raise ValueError("post_date needs the posts alias")
    return POST_DATE.format(p=alias)


def post_date_within(alias: str, lo: str, hi: Optional[str] = None) -> str:
    """A window over Mark X's time as SQL: `post_date` at `lo` or later (and at `hi` or earlier), the same bounds
    widened by the issue reach tested on the post's own date first, so the feed's index on `ordinary_date` finds the
    rows (a round-up's issue time is within the attach row's `issue_reach` of its own date: units._times) and the post
    date, which no index holds, is computed only for those. The same rows as `post_date` alone. `lo` / `hi`: SQL,
    each written twice, in the order lo, lo, hi, hi (a positional %s takes its value twice)."""
    reach = f"make_interval(secs => {int(POLICIES[ATTACH].issue_reach.total_seconds())})"
    own, at = ordinary_date(alias), post_date(alias)
    parts = [f"{own} >= ({lo}) - {reach}", f"{at} >= ({lo})"]
    if hi is not None:
        parts += [f"{own} <= ({hi}) + {reach}", f"{at} <= ({hi})"]
    return "(" + " AND ".join(parts) + ")"


def ordinary_date(alias: str = "p") -> str:
    """The post's own date as SQL (surfaced, else published, else fetched), round-up or not: the feed's indexed sort
    key, the planners' and the lease's order and windows, a task's input, and what the issue time of a round-up is
    computed from (units.py). `alias` '' for a query over posts with no alias."""
    return _form(ORDINARY_DATE, alias)


def published_date(alias: str = "p") -> str:
    """0128's published time as SQL (published, else surfaced, else fetched): the order a story's lines are shown in."""
    return _form(PUBLISHED_DATE, alias)


def ix_date(alias: str = "p") -> str:
    """Mark IX's time as SQL (published, else fetched): StoryPost.t's, News's window, Discover's and the statistics'."""
    return _form(IX_DATE, alias)


SOCIAL = {"t.me", "x.com", "twitter.com", "youtube.com", "reddit.com", "instagram.com", "facebook.com", "linkedin.com",
          "threads.net", "bsky.app", "github.com", "huggingface.co", "medium.com", "substack.com", "youtu.be"}


def page_address(u: Optional[str]) -> Optional[str]:
    """A page's compared form (host/path, lowercased), or None for no page: a home page, a social profile or channel
    page, a subreddit. (back's pages; the lab's norm.)"""
    if not u:
        return None
    try:
        s = urlsplit(u.strip())
        host = s.hostname
    except ValueError:
        return None
    h = (host or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("mobile.")
    if not h:
        return None
    segs = [x for x in re.sub(r"/+$", "", s.path or "").split("/") if x]
    if h == "youtube.com" and "v=" in (s.query or ""):
        m = re.search(r"v=([\w-]+)", s.query)
        if m:
            segs = ["watch", m.group(1)]
    if h == "twitter.com":
        h = "x.com"
    if not segs:
        return None
    if h in SOCIAL and len(segs) == 1:
        return None
    if h == "reddit.com" and len(segs) <= 2:
        return None
    return h + "/" + "/".join(segs).lower()


def page_key(u: Optional[str]) -> Optional[str]:
    """A page's key: 'paper <ref>' for a paper's page (any of its forms and versions), else `page_address`."""
    if not u:
        return None
    from insight_core.utils.entity_originals import paper_ref
    try:
        ref = paper_ref(u.strip())
    except Exception:   # an address the paper rules can't read is compared as a page
        ref = None
    return f"paper {ref}" if ref else page_address(u)


def document_key(url: Optional[str]) -> Optional[str]:
    """The document page an address is, as a key (a paper's id on its host; else the address without its query), or
    None when it is no document (0121 Decided 5: a paper, or a record, a filing or a data page, 0106's and 0109's
    address shapes; an article, a home page, a social post are not)."""
    from insight_core.utils.addresses import bare, paper_id
    from insight_core.utils.discover_rules import document_address, paper_address
    if not url or is_home(url):
        return None
    host = bare(url).partition("/")[0]
    pid = paper_id(url)
    if pid:
        return f"paper:{host}:{pid}"
    if document_address(url) or paper_address(url):
        return "page:" + bare(url).split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return None


# ---- the policy table ------------------------------------------------------------------------------------

OTHER_SOURCE = "other_source"   # two posts: both voices, of different sources (burst: of different places)
NEVER_VOICE = "never_voice"     # attach (0181): a round-up's item is a digest item, never a voice, of any source
ROUNDUP_WHOLE_EXCLUDED = "roundup_whole_excluded"   # a roundup is never judged as a whole (until units exist)
ROUNDUP_UNITS = "roundup_units"   # attach (0181): a round-up is compared by its items (units), never whole
ROUNDUP_ANCHORS = 3             # story_rules.ROUNDUP_ANCHORS: a post with 3+ links is about its first only (burst)
SPECIFIC_TYPES = ("model", "product", "software", "document", "dataset")   # 0133: ent-v3's paper is read as document
H, D = timedelta(hours=1), timedelta(days=1)
# E1/E3's windows (plan/research/exp-2026-11-12/e1): a deal of 2+ parties is one story to 30 days, a people move to 14
# (2+ parties only), a legal step to 7; funding, releases and the rest keep the 72-hour window.
HAPPENING_WINDOWS: Mapping[str, timedelta] = {"deal": 30 * D, "people": 14 * D, "legal": 7 * D}
HAPPENING_WINDOW = 72 * H
# The groups the source pairs: the company groups E1 measured (49/52 right with 2+ shared parties). release, research,
# pricing and announcement keys are made but not paired until measured (the 72-hour sources keep them).
HAPPENING_GROUPS = ("deal", "funding", "legal", "people")
# E6 (plan/research/exp-2026-11-12/e1): a later post of one happening develops it from 3 days on, a deal to 120 days
# (12/12 right), a legal step to 30 (company follow-ups with 2+ parties 23/27 = 85%); funding and people moves never
# (one participant 8/21); release, research, pricing and announcement unmeasured, so never.
DEVELOPS_WINDOWS: Mapping[str, Tuple[timedelta, timedelta]] = {"deal": (3 * D, 120 * D), "legal": (3 * D, 30 * D)}
# 0181 (plan/research/roundups-1016, private): a round-up's cited post is dated at most ATTACH_WINDOW before it and
# ATTACH_AFTER after it (a daily digest dated at the start of its day cites that day's posts: 591 of 642 forward hits
# within 42 hours; the rest were an archive's issues stored under one date). The issue's time is its latest item
# within ISSUE_REACH of its own date (a weekly's two-week-old background link never moves it).
ATTACH_WINDOW = 14 * D
ATTACH_AFTER = 2 * D
ISSUE_REACH = 2 * D


@dataclass(frozen=True)
class Policy:
    """One relation's gates. Post pairs: `window`, `cosine`, `nearest`, `types`, `late_after`, `happening_windows`,
    `min_words`, `roundups`, `independence`. Story pairs: `story_window`, `story_cosine`, `document_window`,
    `min_voices`. `units`: what is compared (a post, or a round-up's item: `unit`, the attach relation, 0181).
    Attach: `window` back from the round-up and `after` forward (a cited post stored after its digest)."""
    relation: str
    sources: Tuple[str, ...]
    window: Optional[timedelta] = None          # two posts at most this far apart (post_date)
    cosine: Optional[float] = None              # embedding: a pair's cosine, at least
    nearest: Optional[int] = None               # embedding: one post among the other's k nearest
    types: Optional[Tuple[str, ...]] = None     # entity: the subject types that name one thing
    late_after: Optional[timedelta] = None      # burst: both posts this long after the page's first linker
    story_window: Optional[timedelta] = None    # stories: first posts at most this far apart
    story_cosine: Optional[float] = None        # stories: centroid cosine, at least
    document_window: Optional[timedelta] = None  # document: two linkers at most this far apart
    happening_windows: Mapping[str, timedelta] = field(default_factory=dict)   # happening: by action group
    happening_window: Optional[timedelta] = None                               # ... any other group
    happening_groups: Tuple[str, ...] = ()                                     # happening: the groups paired
    independence: str = OTHER_SOURCE
    min_voices: int = 2                         # stories: each of this many voices
    min_words: Optional[int] = None             # judged: each post of this many words
    roundups: str = ROUNDUP_WHOLE_EXCLUDED
    units: str = "post"
    # develops (0180): a follow-up of an anchor (markx/anchors.py; back.py and later.py read these, never their own)
    develops_windows: Mapping[str, Tuple[timedelta, timedelta]] = field(default_factory=dict)  # group: (from, to)
    first_after: Optional[timedelta] = None     # back: a burst starts this long after the story's first post ...
    last_after: Optional[timedelta] = None      # ... and this long after its last one
    again: Optional[timedelta] = None           # back: a story still followed fires again this long after its window
    hub_weeks: Optional[int] = None             # back: a page linked in this many ISO weeks is a hub, no story page
    always_types: Tuple[str, ...] = ()          # later: a subject of these types is specific ...
    release_types: Tuple[str, ...] = ()         # ... of these only as one release ...
    release_levels: Tuple[str, ...] = ()        # ... (an entity level that is one release)
    main_share: Optional[float] = None          # later: the main subject is the subject of this share of read members
    quiet_days: Optional[int] = None            # later: in the days before a follow-up ...
    quiet_max: Optional[int] = None             # ... at most this many sources named its subject (subject matches)
    quiet_for_links: bool = True                # ... and for page matches too
    after: Optional[timedelta] = None           # attach (0181): a cited post at most this long after its round-up
    issue_reach: Optional[timedelta] = None     # ... and an item this close to it (either side) sets the issue's time

    def within(self, ta: Any, tb: Any) -> bool:
        return abs(ta - tb) <= self.window

    def story_within(self, ta: Any, tb: Any) -> bool:
        return abs(ta - tb) <= self.story_window

    def happening_span(self, group: str) -> timedelta:
        return self.happening_windows.get(group, self.happening_window)

    @property
    def develops_groups(self) -> Tuple[str, ...]:
        return tuple(self.develops_windows)

    def develops_span(self, group: str) -> Optional[Tuple[timedelta, timedelta]]:
        """(from, to): how long after a post of this group's happening another may develop it; None: never."""
        return self.develops_windows.get(group)


POLICIES: Dict[str, Policy] = {
    # 0086 B's thresholds (none tuned): the 72-hour window is Mark IX's link window (experiment W).
    SAME_STORY: Policy(SAME_STORY, sources=("embedding", "centroid", "link", "entity", "burst", "document", "happening"),
                       window=72 * H, cosine=0.65, nearest=8, types=SPECIFIC_TYPES, late_after=72 * H,
                       story_window=14 * D, story_cosine=0.70, document_window=30 * D,
                       happening_windows=HAPPENING_WINDOWS, happening_window=HAPPENING_WINDOW, happening_groups=HAPPENING_GROUPS,
                       min_words=20),
    # decide's connect questions (F6): two News stories, a typed connection.
    CONNECTED: Policy(CONNECTED, sources=("centroid",), story_window=30 * D, story_cosine=0.60, min_voices=2),
    # 0180: a post that follows up an anchor (a Mark IX story, a Mark X story, a happening; markx/anchors.py). The
    # happening first: E6's windows by group (2+ separate shared parties, no money clash); funding and people never.
    # Then the subject: back's gates (0136: a `window` burst of `min_voices` sources, `first_after` the first post and
    # `last_after` the last, the centre at `cosine`, hubs of `hub_weeks`, subjects of the `types`) and later's (0163:
    # one specific main subject, `quiet_days` / `quiet_max`), the values those modules wrote down.
    DEVELOPS: Policy(DEVELOPS, sources=("happening", "subject", "page", "centre"),
                     window=72 * H, cosine=0.70, min_voices=2,
                     types=("model", "product", "software", "paper", "document", "dataset", "event", "law", "other"),
                     develops_windows=DEVELOPS_WINDOWS, first_after=14 * D, last_after=7 * D, again=30 * D,
                     hub_weeks=6, always_types=("paper", "document", "dataset", "method"),
                     release_types=("model", "software"), release_levels=("version", "variant", "checkpoint"),
                     main_share=0.5, quiet_days=14, quiet_max=2, quiet_for_links=True),
    # 0181: a round-up's item (a unit, markx/units.py) -> the stored post it links, and the story holding it, as a
    # digest item. NEVER a voice (`independence`), never a member, a mention or a News count: stored by units.py,
    # read only by "also in round-ups" and the digest. A round-up's own source may be cited (a channel's weekly digest
    # of its own posts); the target is no round-up and not the round-up itself. Windows: ATTACH_WINDOW, ATTACH_AFTER.
    ATTACH: Policy(ATTACH, sources=("link",), window=ATTACH_WINDOW, after=ATTACH_AFTER, issue_reach=ISSUE_REACH,
                   independence=NEVER_VOICE, min_voices=0, roundups=ROUNDUP_UNITS, units="unit"),
}


def policy(relation: str, **overrides: Any) -> Policy:
    """The relation's row, with `overrides` (None values left as the row's)."""
    return replace(POLICIES[relation], **{k: v for k, v in overrides.items() if v is not None})


# ---- the gates (in memory) ---------------------------------------------------------------------------------

def admits(pol: Policy, a: str, b: str, cos: Optional[float], posts: Mapping[str, Any],
           kinds: Mapping[str, Optional[str]]) -> bool:
    """Whether a stored post pair may be judged: found by meaning at the cosine bar or more (None: found otherwise),
    both posts known and of `min_words`+ words (rule A), neither a roundup as a whole."""
    if cos is not None and pol.cosine is not None and cos < pol.cosine:
        return False
    pa, pb = posts.get(a), posts.get(b)
    if not pa or not pb:
        return False
    if pol.min_words is not None and (pa.words < pol.min_words or pb.words < pol.min_words):
        return False
    if pol.roundups == ROUNDUP_WHOLE_EXCLUDED and (kinds.get(a) == "roundup" or kinds.get(b) == "roundup"):
        return False                           # a roundup is matched per item, never whole
    return True


def admits_stories(pol: Policy, cos: Optional[float], voices_a: int, voices_b: int) -> bool:
    """Whether two stories may be judged: both of `min_voices`+ voices, at the story bar (None: found otherwise)."""
    if voices_a < pol.min_voices or voices_b < pol.min_voices:
        return False
    return cos is None or pol.story_cosine is None or cos >= pol.story_cosine


def develops(pol: Policy, earlier: Any, later: Any, gap: timedelta) -> bool:
    """Whether a post whose happening is `later` (happening.Happening), `gap` after a post whose happening is
    `earlier`, may be judged a development of it (the develops row): one group the row names, 2+ shared separate
    parties, no money clash (happening.MONEY_TOLERANCE), the gap within the group's window. The stage and the stated
    day are not compared: a later stage of one happening is what a development is."""
    from insight_core.markx.happening import MIN_PARTIES, MONEY_TOLERANCE
    span = pol.develops_span(earlier.group)
    if span is None or earlier.group != later.group or not (span[0] <= gap <= span[1]):
        return False
    if len(earlier.parties & later.parties) < MIN_PARTIES:
        return False
    a, b = earlier.numbers, later.numbers
    return not (a and b and not any(abs(x - y) <= MONEY_TOLERANCE * max(x, y) for x in a for y in b))


def specific(pol: Policy, type_: Optional[str], *, level: Optional[str] = None, version: Optional[str] = None,
             variant: Optional[str] = None, build: Optional[str] = None, status: Optional[str] = None) -> bool:
    """Whether an entity is specific enough to keep a story listening by its subject (the develops row; 0163's rule):
    a type of `always_types` always; of `release_types` only as one release (a level of `release_levels`, or a
    version, a variant or a build named; a family never); any other type never; an entity marked not one never."""
    if status == "not_entity":
        return False
    if type_ in pol.always_types:
        return True
    if type_ not in pol.release_types or level == "family":
        return False
    return level in pol.release_levels or any((v or "").strip() for v in (version, variant, build))


def centroid_cosines(cur: Any, groups: Dict[str, Sequence[str]], lo: float,
                     only: Optional[Iterable[str]] = None, model: str = MODEL) -> Dict[Tuple[str, str], float]:
    """{(x, y): cosine} of the groups' mean vectors (x < y), at `lo` or more; with `only`, pairs touching one of them."""
    keys, ids = [], []
    for k, ps in groups.items():
        for p in ps:
            keys.append(k)
            ids.append(p)
    if not keys:
        return {}
    cur.execute("""WITH g AS (SELECT * FROM unnest(%(k)s::text[], %(p)s::uuid[]) AS g(k, post_id)),
                        c AS (SELECT g.k, avg(e.v::vector) AS v FROM g
                                JOIN mx_embeddings e ON e.post_id = g.post_id AND e.model = %(m)s GROUP BY g.k)
                   SELECT x.k, y.k, 1 - (x.v <=> y.v) FROM c x JOIN c y ON x.k < y.k
                    WHERE (%(only)s::text[] IS NULL OR x.k = ANY(%(only)s) OR y.k = ANY(%(only)s))
                      AND 1 - (x.v <=> y.v) >= %(lo)s""",
                {"k": keys, "p": ids, "m": model, "lo": lo, "only": None if only is None else list(only)})
    return {(x, y): float(c) for x, y, c in cur.fetchall()}


def story_pairs(cur: Any, pol: Policy, groups: Dict[str, Sequence[str]], posts: Mapping[str, Any]
                ) -> Dict[Tuple[str, str], float]:
    """{(x, y): centroid cosine} (x < y) of the stories `groups` (key: its posts, earliest first) of `min_voices`+
    voices, at the story bar, their first posts within the story window. `posts`: id -> .source, .kind, .at."""
    groups = {k: ps for k, ps in groups.items()
              if ps and voice.count((voice.Said(posts[p].source, posts[p].kind) for p in ps if p in posts),
                                    voice.Policy.MARKX) >= pol.min_voices}
    first = {k: posts[ps[0]].at for k, ps in groups.items()}
    return {(x, y): c for (x, y), c in centroid_cosines(cur, groups, pol.story_cosine).items()
            if pol.story_within(first[x], first[y])}


class Documents:
    """The `document` source (0121 Decided 5): the document pages each post links (`document_key`), a roundup's never
    (it lists them), and which stories two of whose posts link one within the document window. A merge question,
    never a rule. `text`: post id -> an object with .links [(url, stored)]; `posts`: id -> .at."""

    def __init__(self, text: Mapping[str, Any], posts: Mapping[str, Any], kinds: Mapping[str, Optional[str]],
                 pol: Policy) -> None:
        self.posts, self.span = posts, pol.document_window
        self.of: Dict[str, Set[str]] = {}
        for pid, p in text.items():
            if not (pol.roundups == ROUNDUP_WHOLE_EXCLUDED and kinds.get(pid) == "roundup") and pid in posts:
                keys = {k for k in (document_key(url) for url, _ in p.links) if k}
                if keys:
                    self.of[pid] = keys

    def _linkers(self, ps: Sequence[str]) -> Dict[str, List[Any]]:
        out: Dict[str, List[Any]] = defaultdict(list)
        for p in ps:
            for k in self.of.get(p, ()):
                out[k].append(self.posts[p].at)
        return out

    def _near(self, xs: Sequence[Any], ys: Sequence[Any]) -> bool:
        return any(abs(a - b) <= self.span for a in xs for b in ys)

    def shared(self, pa: Sequence[str], pb: Sequence[str]) -> bool:
        la, lb = self._linkers(pa), self._linkers(pb)
        return any(self._near(la[k], lb[k]) for k in la.keys() & lb.keys())

    def pairs(self, groups: Dict[str, Sequence[str]]) -> List[Tuple[str, str]]:
        """The (x, y) of `groups` (x < y) sharing a document within the days."""
        by_key: Dict[str, Dict[str, List[Any]]] = defaultdict(dict)
        for g, ps in groups.items():
            for k, ats in self._linkers(ps).items():
                by_key[k][g] = ats
        out = set()
        for k, held in by_key.items():
            gs = sorted(held)
            for i, x in enumerate(gs):
                for y in gs[i + 1:]:
                    if self._near(held[x], held[y]):
                        out.add((x, y))
        return sorted(out)


# ---- what every stored source reads ------------------------------------------------------------------------

class Posts:
    """Mark X's time, source and kind of the embedded posts (and of any post loaded), and their Mark IX stories.
    `embedded` False: none of the embedded posts is read (the entity source alone reads only the posts it names).
    v10.14: the embedded posts read are those within 2 x the window of a post of `extra` (the new posts), the only
    ones a new post's embedding pairs reach (its window, and its neighbours' own windows); before, every embedded post
    and every story row was read on each run. A post's story is read as the post is loaded."""

    def __init__(self, cur: Cursor, model: str = MODEL, extra: Iterable[str] = (), embedded: bool = True,
                 pol: Optional[Policy] = None) -> None:
        self.cur = cur
        self.pol = pol or POLICIES[SAME_STORY]
        self.source: Dict[str, str] = {}
        self.at: Dict[str, datetime] = {}
        self.kind: Dict[str, str] = {}
        self.story: Dict[str, str] = {}
        self._storied: Set[str] = set()
        extra = set(extra)
        self.load(extra)
        self.embedded: Set[str] = set()
        if embedded:
            lo, hi = spans((self.at[p] for p in extra if p in self.at), 2 * self.pol.window)
            cur.execute(f"""SELECT e.post_id::text FROM mx_embeddings e JOIN posts p ON p.id = e.post_id
                             WHERE e.model = %s AND EXISTS (
                                   SELECT 1 FROM unnest(%s::timestamptz[], %s::timestamptz[]) AS w(lo, hi)
                                    WHERE {post_date()} BETWEEN w.lo AND w.hi)""",
                        (model, lo, hi))
            self.embedded = {r[0] for r in cur.fetchall()}
            self.load(self.embedded)
        self.order = sorted((self.at[p], p) for p in self.embedded if p in self.at)
        self.times = [t for t, _ in self.order]

    def load(self, ids: Iterable[str]) -> None:
        ids = list(ids)
        self._stories(ids)
        ids = [i for i in ids if i not in self.at]
        if not ids:
            return
        self.cur.execute(f"""SELECT p.id::text, p.source_id::text, {post_date()},
                                    s.platform, s.handle_or_url
                               FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ANY(%s::uuid[])""", (ids,))
        for pid, source, at, platform, handle in self.cur.fetchall():
            if at is not None:
                self.source[pid], self.at[pid], self.kind[pid] = source, at, source_kind(platform, handle)

    def _stories(self, ids: Iterable[str]) -> None:
        ids = sorted({str(i) for i in ids} - self._storied)
        if not ids:
            return
        self.cur.execute("SELECT post_id::text, story_id::text FROM story_posts WHERE post_id = ANY(%s::uuid[])", (ids,))
        self.story.update(self.cur.fetchall())
        self._storied.update(ids)

    def voice(self, pid: str) -> bool:
        return pid in self.at and voice.is_voice(self.kind[pid])

    def independent(self, a: str, b: str) -> bool:
        return self.voice(a) and self.voice(b) and self.source[a] != self.source[b]

    def one_story(self, a: str, b: str) -> bool:
        self._stories((a, b))
        sa = self.story.get(a)
        return sa is not None and sa == self.story.get(b)

    def ordered(self, a: str, b: str) -> Tuple[str, str]:
        return tuple(sorted((a, b), key=lambda p: (self.at[p], p)))  # type: ignore[return-value]

    def window(self, pid: str, span: Optional[timedelta] = None) -> List[str]:
        """The embedded voices of other sources within the window (default the policy's) of `pid`."""
        t, span = self.at[pid], span or self.pol.window
        lo, hi = bisect.bisect_left(self.times, t - span), bisect.bisect_right(self.times, t + span)
        return [q for _, q in self.order[lo:hi] if q != pid and self.source[q] != self.source[pid] and self.voice(q)]


def spans(times: Iterable[datetime], reach: timedelta) -> Tuple[List[datetime], List[datetime]]:
    """v10.14: the time spans within `reach` of any of `times`, overlapping ones merged: (starts, ends), inclusive."""
    lo: List[datetime] = []
    hi: List[datetime] = []
    for t in sorted(times):
        if hi and t - reach <= hi[-1]:
            hi[-1] = max(hi[-1], t + reach)
        else:
            lo.append(t - reach)
            hi.append(t + reach)
    return lo, hi


def _add(cur: Cursor, kind: str, a: str, b: str, source: str, score: Optional[float]) -> bool:
    return repo.add_candidate(cur, kind=kind, a=a, b=b, source=source,
                              score=None if score is None else round(float(score), 4))


# ---- embedding ---------------------------------------------------------------------------------------------

def _cosines(cur: Cursor, pid: str, others: Sequence[str], model: str) -> Dict[str, float]:
    if not others:
        return {}
    cur.execute("""SELECT e.post_id::text, 1 - (e.v <=> q.v) FROM mx_embeddings e,
                          (SELECT v FROM mx_embeddings WHERE post_id = %s AND model = %s) q
                    WHERE e.model = %s AND e.post_id = ANY(%s::uuid[])""", (pid, model, model, list(others)))
    return {q: float(c) for q, c in cur.fetchall()}


def _top(cos: Dict[str, float], k: int) -> List[str]:
    return [q for q, _ in sorted(cos.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def embedding_pairs(cur: Cursor, posts: Posts, new: Iterable[str], model: str = MODEL) -> int:
    """Post pairs: (i, q) when q is among i's k nearest or i among q's, at the cosine bar, i one of `new`; never two
    posts of one vector whose texts are not near-copies (embed.same_vector)."""
    from insight_core.markx.embed import same_vector
    pol = posts.pol
    added = 0
    near_of: Dict[str, List[str]] = {}

    def nearest_of(q: str) -> List[str]:
        if q not in near_of:
            near_of[q] = _top(_cosines(cur, q, posts.window(q), model), pol.nearest)
        return near_of[q]

    for i in new:
        if i not in posts.embedded or not posts.voice(i):
            continue
        cos = _cosines(cur, i, posts.window(i), model)
        top = set(_top(cos, pol.nearest))
        one = same_vector(cur, [(i, q, c) for q, c in cos.items()])   # one vector, not one meaning (embed text v2)
        for q, c in cos.items():
            if c < pol.cosine or posts.one_story(i, q) or (i, q) in one:
                continue
            if q in top or i in nearest_of(q):
                a, b = posts.ordered(i, q)
                added += _add(cur, POST_POST, a, b, "embedding", c)
    return added


# ---- centroid (story pairs) ----------------------------------------------------------------------------------

def centroid_pairs(cur: Cursor, posts: Posts, new: Iterable[str], model: str = MODEL) -> int:
    """Story pairs: Mark IX's stories holding a `new` post against every other story whose centroid is at the story
    bar, their first posts within the story window. Each story by its earliest member post (post_date). Stored as
    source 'embedding' (kind story_story), as before 0166."""
    pol = posts.pol
    cur.execute(
        f"""WITH m AS (SELECT sp.story_id, sp.post_id, e.v::vector AS v,
                              {post_date()} AS at
                         FROM story_posts sp JOIN mx_embeddings e ON e.post_id = sp.post_id AND e.model = %(model)s
                         JOIN posts p ON p.id = sp.post_id),
                 c AS (SELECT story_id, avg(v) AS v, min(at) AS first_at,
                              (array_agg(post_id::text ORDER BY at, post_id))[1] AS first_post
                         FROM m GROUP BY story_id),
                 t AS (SELECT DISTINCT story_id FROM story_posts WHERE post_id = ANY(%(new)s::uuid[]))
            SELECT x.first_post, x.first_at, y.first_post, y.first_at, 1 - (x.v <=> y.v)
              FROM c x JOIN c y ON y.story_id <> x.story_id
                               AND y.first_at BETWEEN x.first_at - %(days)s AND x.first_at + %(days)s
             WHERE x.story_id IN (SELECT story_id FROM t) AND 1 - (x.v <=> y.v) >= %(min)s""",
        {"model": model, "new": list(new), "days": pol.story_window, "min": pol.story_cosine})
    added = 0
    for pa, ta, pb, tb, c in cur.fetchall():
        (a, _), (b, _) = sorted([(pa, ta), (pb, tb)], key=lambda x: (x[1], x[0]))
        added += _add(cur, STORY_STORY, a, b, "embedding", c)
    return added


# ---- link ----------------------------------------------------------------------------------------------------

def link_pairs(cur: Cursor, posts: Posts, new: Iterable[str]) -> int:
    """Mark IX's joins (parent edges) touching a `new` post, as they are now."""
    cur.execute("""SELECT parent_id::text, post_id::text FROM story_posts
                    WHERE parent_id IS NOT NULL AND (post_id = ANY(%(n)s::uuid[]) OR parent_id = ANY(%(n)s::uuid[]))""",
                {"n": list(new)})
    edges = cur.fetchall()
    posts.load({p for edge in edges for p in edge})
    added = 0
    for parent, child in edges:
        if parent in posts.at and child in posts.at and parent != child:
            a, b = posts.ordered(parent, child)
            added += _add(cur, POST_POST, a, b, "link", None)
    return added


# ---- entity --------------------------------------------------------------------------------------------------

def _subjects(cur: Cursor, where: str, params: Dict[str, Any], types: Sequence[str]) -> Dict[str, Set[Tuple[str, str]]]:
    cur.execute(f"""SELECT post_id::text, name_key, lower(COALESCE(version, '')) FROM mx_mentions_now
                     WHERE guide = ANY(%(guide)s) AND role = 'subject' AND type = ANY(%(types)s) AND name_key <> ''
                       AND {where}""", {"guide": schemas.mention_guides(), "types": schemas.stored_types(types), **params})
    out: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)
    for pid, key, version in cur.fetchall():
        out[pid].add((key, version))
    return out


def entity_pairs(cur: Cursor, posts: Posts, new: Iterable[str]) -> int:
    """Post pairs sharing a main subject of the policy's types (name key and version) within the window, other
    sources, not in one Mark IX story."""
    pol = posts.pol
    mine = _subjects(cur, "post_id = ANY(%(n)s::uuid[])", {"n": list(new)}, pol.types)
    keys = sorted({k for s in mine.values() for k, _ in s})
    if not keys:
        return 0
    posts.load(mine)
    # v10.14: only the subjects' posts within the window of one of `mine` (the pairs' own window), not every post ever
    lo, hi = spans((posts.at[i] for i in mine if i in posts.at), pol.window)
    theirs = _subjects(cur, f"""name_key = ANY(%(k)s) AND EXISTS (
                                    SELECT 1 FROM posts p, unnest(%(lo)s::timestamptz[], %(hi)s::timestamptz[]) AS w(lo, hi)
                                     WHERE p.id = mx_mentions_now.post_id
                                       AND {post_date()} BETWEEN w.lo AND w.hi)""",
                       {"k": keys, "lo": lo, "hi": hi}, pol.types)
    posts.load(theirs)
    by_subject: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for pid, s in theirs.items():
        for subject in s:
            by_subject[subject].append(pid)
    added = 0
    for i, s in mine.items():
        if not posts.voice(i):
            continue
        for subject in s:
            for q in by_subject[subject]:
                if q == i or not posts.independent(i, q) or not pol.within(posts.at[q], posts.at[i]) \
                        or posts.one_story(i, q):
                    continue
                a, b = posts.ordered(i, q)
                added += _add(cur, POST_POST, a, b, "entity", None)
    return added


# ---- burst ---------------------------------------------------------------------------------------------------

def _targets(links: Sequence[Tuple[str, Optional[str]]]) -> List[str]:
    """The pages a post links, as the story rules count them for a shared link."""
    considered = links[:1] if len(links) >= ROUNDUP_ANCHORS else links
    return [t for t, stored in considered if not stored and not is_home(t)]


def burst_pairs(cur: Cursor, posts: Posts, new: Iterable[str]) -> int:
    """Late-burst pairs on the pages a `new` post links (0089, experiment W's window_bursts)."""
    from insight_core.db.repo_stories import SourceFacts, StoriesRepository
    from insight_core.services.stories_service import StoriesService

    pol = posts.pol
    new = list(new)
    cur.execute("SELECT DISTINCT target_url FROM post_links WHERE NOT boilerplate AND post_id = ANY(%s::uuid[])", (new,))
    pages = [r[0] for r in cur.fetchall() if not is_home(r[0])]
    if not pages:
        return 0
    # Only posts Mark IX has read (post_parts), so load_posts never parses one: Mark X writes no Mark IX table.
    cur.execute("""SELECT DISTINCT pl.post_id::text FROM post_links pl
                    WHERE NOT pl.boilerplate AND pl.target_url = ANY(%s)
                      AND EXISTS (SELECT 1 FROM post_parts pp WHERE pp.post_id = pl.post_id)""", (pages,))
    ids = [r[0] for r in cur.fetchall()]
    posts.load(ids)
    sources = SourceFacts(cur)
    linkers: Dict[str, List[Any]] = defaultdict(list)
    for row in StoriesRepository.load_posts(cur, sources, ids):
        p = StoriesService._story_post(row, sources)
        for target in _targets(p.links):
            linkers[target].append(p)
    added = 0
    for target in pages:
        ps = sorted(linkers.get(target, []), key=lambda p: (p.t, p.id))
        if len({p.place for p in ps}) < 2:
            continue
        late = [p for p in ps if p.t - ps[0].t > pol.late_after]
        for n, b in enumerate(late):
            for a in late[:n]:
                if a.place != b.place and b.t - a.t <= pol.window and not posts.one_story(a.id, b.id):
                    x, y = posts.ordered(a.id, b.id) if a.id in posts.at and b.id in posts.at else (a.id, b.id)
                    added += _add(cur, POST_POST, x, y, "burst", None)
    return added


# ---- happening -----------------------------------------------------------------------------------------------

def happening_on(cur: Cursor) -> bool:
    """Whether the happening source runs (HAPPENING_KEY in mx_settings; off by default)."""
    return bool(repo.get_setting(cur, HAPPENING_KEY, default=False))


def happening_pairs(cur: Cursor, posts: Posts, new: Iterable[str]) -> int:
    from insight_core.markx import happening
    return happening.pairs(cur, posts, new)


# ---- attach (0181): a round-up's items -> the stored posts they link --------------------------------------------

def attaches(pol: Policy, roundup_at: datetime, target_at: datetime, *, target_is_roundup: bool,
             same_post: bool) -> bool:
    """Whether a unit may attach to a stored post it links (the attach row): not its own round-up, no round-up
    itself, dated from `window` before the round-up to `after` after it. Who wrote it never matters: an item is
    never a voice (`independence` NEVER_VOICE), so no voice rule applies."""
    if same_post or target_is_roundup:
        return False
    return roundup_at - pol.window <= target_at <= roundup_at + pol.after


def attach_targets(cur: Cursor, units: Sequence[Any], pol: Optional[Policy] = None) -> List[Tuple[int, str, str]]:
    """The attach relation's `link` source: [(unit id, stored post, 'link')] for units (.id, .post, .links) whose
    links are a stored post's address (posts.normalized_url, as post_links targets join posts), gated by `attaches`.
    Each round-up's and each target's own date (`ordinary_date`: the issue time is made from these, never read)."""
    pol = pol or POLICIES[ATTACH]
    links = sorted({u for x in units for u in x.links})
    if not links:
        return []
    cur.execute(f"""SELECT p.id::text, p.normalized_url, {ordinary_date('p')}, COALESCE(r.roundup, false)
                      FROM posts p LEFT JOIN mx_roundups r ON r.post_id = p.id
                     WHERE p.normalized_url = ANY(%s)""", (links,))
    by_url: Dict[str, List[Tuple[str, datetime, bool]]] = defaultdict(list)
    for pid, url, at, rd in cur.fetchall():
        if at is not None:
            by_url[url].append((pid, at, rd))
    cur.execute(f"SELECT p.id::text, {ordinary_date('p')} FROM posts p WHERE p.id = ANY(%s::uuid[])",
                (sorted({x.post for x in units}),))
    own_at = dict(cur.fetchall())
    out: List[Tuple[int, str, str]] = []
    for x in units:
        at = own_at.get(x.post)
        if at is None:
            continue
        seen: Set[str] = set()
        for url in x.links:
            for pid, t_at, rd in by_url.get(url, ()):
                if pid not in seen and attaches(pol, at, t_at, target_is_roundup=rd, same_post=pid == x.post):
                    seen.add(pid)
                    out.append((x.id, pid, "link"))
    return out


# ---- the interface -------------------------------------------------------------------------------------------

STORED = {"embedding": embedding_pairs, "centroid": centroid_pairs, "link": link_pairs, "entity": entity_pairs,
          "burst": burst_pairs, "happening": happening_pairs}
EMBEDDED = ("embedding", "centroid")   # the sources that read every embedded post


def find(cur: Cursor, relation: str, post_ids: Iterable[str], *, sources: Optional[Sequence[str]] = None,
         model: str = MODEL) -> Counter:
    """The candidate pairs of `relation` touching these posts, by its stored sources (default: all of its sources,
    the happening source only while HAPPENING_KEY is on), each stored once per source: {source: pairs added}."""
    pol = POLICIES[relation]
    new = sorted({str(p) for p in post_ids})
    out: Counter = Counter()
    if not new:
        return out
    if sources is None:
        sources = [s for s in pol.sources if s in STORED and (s != "happening" or happening_on(cur))]
    unknown = [s for s in sources if s not in pol.sources or s not in STORED]
    if unknown:
        raise ValueError(f"not a stored source of {relation}: {unknown}")
    posts = Posts(cur, model, extra=new, embedded=any(s in EMBEDDED for s in sources), pol=pol)
    for s in sources:
        fn = STORED[s]
        out[s] += fn(cur, posts, new, model) if s in EMBEDDED else fn(cur, posts, new)
    return out
