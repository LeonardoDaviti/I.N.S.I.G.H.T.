"""Mark X Shadow's task kinds (issue 0086 C): each kind's guide, subject and answer schema.

A guide is a file in markx/guides/<id>.md, copied from the prototype (scrubbed: no channel, account or
subreddit names) and loaded into mx_guides at start by its sha256 (`load_guides`). A changed guide is a
new id and a new file; an id's body is never edited (mx_guides refuses it).

The answer schemas are JSON Schema, in the subset scripts/markx-worker checks before it posts (type, enum,
const, required, properties, additionalProperties, items, min/maxItems, min/maxLength, minimum/maximum,
pattern, anyOf/oneOf). They catch the shape; the checks that read the input (spans, versions, figures,
cited keys) are the server's, in markx/validate.py.

A new kind (S2's `embed`) adds one entry to KINDS (and a guide file when it has one); nothing else here
changes. mx_tasks.kind is not checked by the database, so a kind needs no migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

GUIDES_DIR = Path(__file__).resolve().parent / "guides"

# ---- the sets ------------------------------------------------------------------------------------

READ_KINDS = ["report", "commentary", "roundup", "tool", "other"]
EVENTS = ["one", "several", "none"]
MENTION_ROLES = ["hook", "background", "example"]
ACTIONS = ["released", "announced", "launched", "acquired", "raised", "published", "found", "reported", "sued",
           "delayed", "leaked", "priced", "updated", "other"]

ENTITY_TYPES = ["org", "person", "model", "product", "software", "paper", "dataset", "event", "place", "law", "other"]
ENTITY_ROLES = ["subject", "actor", "compared", "predecessor", "venue", "mention"]
# 0133 (ent-v4): `paper` becomes `document` (a paper, filing, report, forecast, law text, book, video, course); two roles:
# `source` (the post relays or cites its claim, data or forecast as evidence: an org, a person or a document) and
# `recommended` (a work the post recommends or reads, not cited as evidence: a document only). ent-v3's sets above
# stay its schema's.
ENTITY_TYPES_V4 = ["org", "person", "model", "product", "software", "document", "dataset", "event", "place", "law", "other"]
ENTITY_ROLES_V4 = ENTITY_ROLES + ["source", "recommended"]
TYPE_READS = {"paper": "document"}       # a stored ent-v3 type as every reader reads it (no row rewritten)
NOT_SURGING = ("source", "recommended")  # never a surge's credit (surges count subject and actor only)


def entity_type(t: Optional[str]) -> Optional[str]:
    """0133: a stored type as it is read (ent-v3's `paper` is a `document`)."""
    return TYPE_READS.get(t, t) if t else t


def stored_types(types: Any) -> list:
    """0133: the stored values of these read types (`document` is also ent-v3's `paper`), for a filter."""
    out = list(types)
    out += [k for k, v in TYPE_READS.items() if v in out and k not in out]
    return out
ENTITY_RELATIONS = ["released", "announced", "acquired", "invested_in", "partnered_with", "sued", "hired", "joined",
                    "left", "leads", "based_on", "beats", "part_of",
                    "published"]   # v10.10.1: ent-v4.2's guide asks for it (a issues or publishes document b)
MAX_ENTITIES = 20

# The judge's seven relations (judge-*-v1, judge-story-v1, connect-v1), and those that make a post "about" a story.
RELATIONS = ["same_event", "development", "reaction", "mention", "digest_item", "different", "cant_tell"]
ABOUT = ["same_event", "development", "reaction"]

READ_HEADLINE_WORDS = 25     # 0086 C (the guide asks for 20)
STORY_HEADLINE_WORDS = 14    # card and headline: what the guides ask
HEADLINE_WORDS = STORY_HEADLINE_WORDS + 2   # the headline check's slack, as readings have (0121 Decided 2)
BRIEFING_LINES = (5, 7)      # fewer when the day has fewer stories
TRANSLATE_LENGTH = (0.5, 2.0)

_STR = {"type": "string"}
_STR_OR_NULL = {"type": ["string", "null"]}

# ---- the answer schemas ----------------------------------------------------------------------------

READ_SCHEMA = {
    "type": "object",
    "required": ["kind", "events", "main", "items", "mentions", "lang"],
    "properties": {
        "kind": {"enum": READ_KINDS},
        "events": {"enum": EVENTS},
        "main": {"anyOf": [{"type": "null"}, {
            "type": "object", "required": ["headline_en", "actors", "object", "action"],
            "properties": {"headline_en": _STR, "actors": {"type": "array", "items": _STR},
                           "object": _STR, "action": _STR, "date": _STR_OR_NULL,
                           "numbers": {"type": "array", "items": {"type": ["string", "number"]}}}}]},
        "items": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "required": ["headline_en", "link"],
            "properties": {"headline_en": _STR, "link": _STR_OR_NULL}}},
        "mentions": {"type": "array", "items": {
            "type": "object", "required": ["name", "role"],
            "properties": {"name": _STR, "role": {"enum": MENTION_ROLES}}}},
        "lang": {"type": "string", "pattern": r"^[a-z]{2,3}([-_][A-Za-z]{2,4})?$"},
    },
}

# 0127 (v10.3): read-v3, a reading plus the post's event type and origin (the duplicates fold's input, markx/folds.py).
EVENT_TYPES = ["model_release", "product_release", "research_result", "business_event", "policy_legal", "incident",
               "public_statement", "promotion_event", "leak_rumour", "opinion_analysis", "tutorial_explainer", "digest",
               "community_post", "other"]
ORIGINS = ["maker", "relay", "other"]
READ3_SCHEMA = {
    "type": "object",
    "required": READ_SCHEMA["required"] + ["type_why", "event_type", "origin"],
    "properties": {**READ_SCHEMA["properties"], "type_why": _STR, "event_type": {"enum": EVENT_TYPES},
                   "origin": {"enum": ORIGINS}},
}

ENTITIES_SCHEMA = {
    "type": "object",
    "required": ["entities"],
    "properties": {
        "entities": {"type": "array", "maxItems": MAX_ENTITIES, "items": {
            "type": "object", "required": ["span", "name", "type", "role"],
            "properties": {"span": {"type": "string", "minLength": 1}, "name": {"type": "string", "minLength": 1},
                           "type": {"enum": ENTITY_TYPES}, "role": {"enum": ENTITY_ROLES},
                           "maker": _STR_OR_NULL, "family": _STR_OR_NULL, "version": _STR_OR_NULL,
                           "variant": _STR_OR_NULL, "size": _STR_OR_NULL, "build": _STR_OR_NULL}}},
        "relations": {"type": "array", "items": {
            "type": "object", "required": ["a", "rel", "b"],
            "properties": {"a": _STR, "rel": {"enum": ENTITY_RELATIONS}, "b": _STR}}},
    },
}

# 0133: ent-v4's answer: ent-v3's shape with the new sets, and `by` (a document's publisher or author, as the post
# names it: identity makes it a `published` edge).
ENTITIES_V4_SCHEMA = {
    "type": "object",
    "required": ["entities"],
    "properties": {
        "entities": {"type": "array", "maxItems": MAX_ENTITIES, "items": {
            "type": "object", "required": ["span", "name", "type", "role"],
            "properties": {**ENTITIES_SCHEMA["properties"]["entities"]["items"]["properties"],
                           "type": {"enum": ENTITY_TYPES_V4}, "role": {"enum": ENTITY_ROLES_V4}, "by": _STR_OR_NULL}}},
        "relations": ENTITIES_SCHEMA["properties"]["relations"],
    },
}

# 0133 v4.2: the second question (cite-v1): every document and cited org or person, nothing else; at most 30. A
# document is a source, recommended or subject (a subject is dropped in the merge, ent42.merge_cite); an org or a
# person is a source only (validate._cite).
CITE_TYPES = ["document", "org", "person"]
CITE_ROLES = ["source", "recommended", "subject"]
CITE_MAX = 30
CITE_SCHEMA = {
    "type": "object",
    "required": ["entities"],
    "properties": {
        "entities": {"type": "array", "maxItems": CITE_MAX, "items": {
            "type": "object", "required": ["span", "name", "type", "role"],
            "properties": {"span": {"type": "string", "minLength": 1}, "name": {"type": "string", "minLength": 1},
                           "type": {"enum": CITE_TYPES}, "role": {"enum": CITE_ROLES}, "by": _STR_OR_NULL}}}},
}

JUDGE_SCHEMA = {
    "type": "object",
    "required": ["relation", "confidence"],
    "properties": {"relation": {"enum": RELATIONS}, "confidence": {"type": "number", "minimum": 0, "maximum": 100},
                   "reason": _STR},
}

CARD_SCHEMA = {
    "type": "object",
    "required": ["headline_en", "actors", "object", "action"],
    "properties": {"headline_en": {"type": "string", "minLength": 1},
                   "actors": {"type": ["array", "string"]}, "object": _STR, "action": _STR, "date": _STR_OR_NULL,
                   "summary_en": _STR, "odd": {"type": "array", "items": {"type": ["string", "integer"]}}},
}

HEADLINE_SCHEMA = {
    "type": "object",
    "required": ["headline_en"],
    "properties": {"headline_en": {"type": "string", "minLength": 1}, "summary_en": _STR},
}

BRIEFING_SCHEMA = {
    "type": "object",
    "required": ["lines"],
    "properties": {"lines": {"type": "array", "minItems": 1, "maxItems": BRIEFING_LINES[1], "items": {
        "type": "object", "required": ["text", "stories"],
        "properties": {"text": {"type": "string", "minLength": 1},
                       "stories": {"type": "array", "minItems": 1, "items": _STR}}}}},
}

# An embed task's vector, as POST /api/markx/embeddings takes it (markx/embed.py): 1,024 little-endian float16, base64.
EMBED_SCHEMA = {
    "type": "object",
    "required": ["vector"],
    "properties": {"vector": {"type": "string", "minLength": 2732, "maxLength": 2732}},
}

# 0119 A1: the entity identity judge (alias-v1, the lab's eid_judge.md) and the collision judge (collide-v1, eid_collide.md v4).
ALIAS_RELATIONS = ["same", "other_version", "part", "different", "cant_tell"]
ALIAS_SCHEMA = {
    "type": "object",
    "required": ["relation", "confidence"],
    "properties": {"evidence": _STR, "relation": {"enum": ALIAS_RELATIONS},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
}

COLLIDE_MENTIONS = 8          # mentions a collision question shows (the lab's MAXM)
COLLIDE_RUNS = 3              # asked three times; a split two runs make goes to the queue (never applied by itself)
COLLIDE_SCHEMA = {
    "type": "object",
    "required": ["senses"],
    "properties": {
        "evidence": _STR,
        "senses": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["m"],
            "properties": {"m": {"type": "array", "minItems": 1, "items": {"type": "integer", "minimum": 1}},
                           "what": _STR}}},
        "related": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 3}},
        "unclear": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

# 0119 B (0120 v3.2f): what each member of a story adds (persp-v1, the lab's persp_v32f_frozen.md) and the sheet's
# merged facts (persp-merge-v1, persp_merge_v1.md). Loose, as the lab's answer check was (members with a known label;
# groups as a list): a fact without its span, a line number out of range, a member not asked are the final checks'
# to drop (markx/perspectives.py), never a reason to ask again.
PERSPECTIVE_LABELS = ["original", "new_facts", "opinion", "same", "not_this_story"]
_BOOL_OR_NULL = {"type": ["boolean", "null"]}
PERSPECTIVE_SCHEMA = {
    "type": "object",
    "required": ["members"],
    "properties": {"members": {"type": "array", "items": {
        "type": "object", "required": ["id", "label"],
        "properties": {"id": _STR, "label": {"enum": PERSPECTIVE_LABELS},
                       "facts": {"type": "array", "items": {
                           "type": "object", "required": ["fact"],
                           "properties": {"fact": _STR, "span": _STR_OR_NULL, "correction": _BOOL_OR_NULL,
                                          "about_story": _BOOL_OR_NULL}}},
                       "claims": {"type": "array", "items": {
                           "type": "object", "required": ["claim"],
                           "properties": {"claim": _STR, "span": _STR_OR_NULL}}},
                       "point": _STR_OR_NULL}}}},
}

SHEET_SCHEMA = {
    "type": "object",
    "required": ["groups"],
    "properties": {"groups": {"type": "array", "items": {
        "type": "object", "required": ["lines"],
        "properties": {"lines": {"type": "array", "items": {"type": "integer"}}, "fact": _STR_OR_NULL,
                       "correction": _BOOL_OR_NULL}}}},
}

# 0131 (Stalker's first edges): how a newer post relates to an older one (relate-v1, the lab's frozen G2 judge v3).
RELATE_RELATIONS = ["same_event", "follows_up", "next_version", "builds_on", "refers_back", "background", "unrelated"]
RELATE_SCHEMA = {
    "type": "object",
    "required": ["reason", "relation"],
    "properties": {"reason": {"type": "string", "minLength": 1}, "relation": {"enum": RELATE_RELATIONS},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 100}},
}

# 0136 (back in the news): a verdict per new post (back-v1, the lab's frozen back_v3c.md); code makes the candidate's.
BACK_VERDICTS = ["development", "retold", "related", "unrelated"]
BACK_SCHEMA = {
    "type": "object",
    "required": ["posts"],
    "properties": {"old_thing": _STR_OR_NULL, "what_new": _STR_OR_NULL,
                   "posts": {"type": "array", "minItems": 1, "items": {
                       "type": "object", "required": ["n", "verdict"],
                       "properties": {"n": {"type": "integer"}, "about": _STR_OR_NULL,
                                      "verdict": {"enum": BACK_VERDICTS}}}}},
}

TRANSLATE_SCHEMA = {
    "type": "object",
    "required": ["title_en", "text_en"],
    "properties": {"title_en": _STR, "text_en": _STR},
}

# 0132 B: a source's stance and framing (stance-v1, the lab's sources_bias_v1.md). Loose on the quotes: a quote not
# found in its post is the grounding's to drop (validate.stance_grounded: a pattern keeps 2+ exact quotes from 2
# posts, or isn't shown), never a reason to ask again.
STANCE_KINDS = ["stance", "framing", "selection", "tone", "interest"]
STANCE_VOICES = ["official", "staff_or_insider", "analyst", "commentator", "aggregator", "news_outlet", "unclear"]
STANCE_PATTERNS = 4
STANCE_SCHEMA = {
    "type": "object",
    "required": ["patterns"],
    "properties": {
        "patterns": {"type": "array", "maxItems": STANCE_PATTERNS, "items": {
            "type": "object", "required": ["pattern", "evidence"],
            "properties": {"pattern": {"type": "string", "minLength": 1}, "kind": {"enum": STANCE_KINDS},
                           "strength": {"enum": ["clear", "some", "weak"]},
                           "evidence": {"type": "array", "items": {
                               "type": "object", "required": ["post", "quote"],
                               "properties": {"post": {"type": "integer"}, "quote": _STR}}}}}},
        "voice": {"enum": STANCE_VOICES},
        "interest": _STR_OR_NULL,
        "too_few": {"type": "boolean"},
    },
}

# 0145 (tracks as topics): the judge's verdict on one post for one track (track-v1), and a track's sub-topics proposed
# from its items (subtopics-v1). The checks that read the input (one line, the item numbers) are validate's.
TRACK_WHY_CHARS = 300
TRACK_SCHEMA = {
    "type": "object",
    "required": ["in", "confidence", "why"],
    "properties": {"in": {"type": "boolean"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                   "subtopic": _STR_OR_NULL, "why": {"type": "string", "minLength": 1}},
}
SUBTOPICS_MAX = 8             # the guide asks for 3-8 (fewer when the items are few or alike)
SUBTOPICS_SCHEMA = {
    "type": "object",
    "required": ["subtopics"],
    "properties": {"subtopics": {"type": "array", "minItems": 1, "maxItems": SUBTOPICS_MAX, "items": {
        "type": "object", "required": ["name", "items"],
        "properties": {"name": {"type": "string", "minLength": 1}, "definition": _STR_OR_NULL,
                       "items": {"type": "array", "items": {"type": "integer", "minimum": 1}}}}}},
}
# 0147 (track recall): a track's example posts (probes-v1): 12-20 that belong, up to 4 near-misses that don't.
PROBES_MIN, PROBES_MAX, NEAR_MAX, PROBE_CHARS = 12, 20, 4, 300
PROBES_SCHEMA = {
    "type": "object",
    "required": ["probes"],
    "properties": {"probes": {"type": "array", "minItems": PROBES_MIN, "maxItems": PROBES_MAX,
                              "items": {"type": "string", "minLength": 1}},
                   "near_misses": {"type": "array", "maxItems": NEAR_MAX, "items": {"type": "string", "minLength": 1}}},
}
# 0148 (track scout): the sources Haiku names for a track's sphere (scout-v1): 20-30 asked, 5-30 taken, each a platform
# class INSIGHT reads, its address or handle and why. Never trusted as is: each is test-read (markx/scout.py).
SCOUT_PLATFORMS = ["site", "reddit", "youtube", "telegram", "x", "hn", "code", "hub", "paper", "podcast", "newsletter"]
SCOUT_MIN, SCOUT_MAX, SCOUT_ADDRESS_CHARS, SCOUT_WHY_CHARS = 5, 30, 300, 300
SCOUT_SCHEMA = {
    "type": "object",
    "required": ["sources"],
    "properties": {"sources": {"type": "array", "minItems": SCOUT_MIN, "maxItems": SCOUT_MAX, "items": {
        "type": "object", "required": ["platform", "address"],
        "properties": {"name": _STR_OR_NULL, "platform": {"enum": SCOUT_PLATFORMS},
                       "address": {"type": "string", "minLength": 1}, "why": _STR_OR_NULL}}}},
}
# 0162 (research): are two accounts one person or org (identity-v1)? Asked only for a pair the plain rules leave unclear.
IDENTITY_ANSWERS = ["yes", "no", "unsure"]
IDENTITY_SCHEMA = {
    "type": "object",
    "required": ["same", "confidence", "why"],
    "properties": {"same": {"enum": IDENTITY_ANSWERS}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                   "why": {"type": "string", "minLength": 1}},
}


# ---- the kinds -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Kind:
    name: str
    guide: Optional[str]          # the guide id (markx/guides/<id>.md); None: a kind with no prompt
    subject: str                  # mx_tasks.subject_kind
    schema: Optional[Dict[str, Any]]



KINDS: Dict[str, Kind] = {k.name: k for k in (
    Kind("read", "read-v2", "post", READ_SCHEMA),
    Kind("entities", "ent-v3", "post", ENTITIES_SCHEMA),
    Kind("check", "judge-raw-v1", "post_story", JUDGE_SCHEMA),
    Kind("join", "judge-read-v1", "post_story", JUDGE_SCHEMA),
    Kind("pair", "judge-read-v1", "post_post", JUDGE_SCHEMA),
    Kind("merge", "judge-story-v1", "story_story", JUDGE_SCHEMA),
    Kind("connect", "connect-v1", "story_story", JUDGE_SCHEMA),
    Kind("card", "card-v1", "story", CARD_SCHEMA),
    Kind("headline", "headline-v1", "story", HEADLINE_SCHEMA),
    Kind("briefing", "briefing-v1", "day", BRIEFING_SCHEMA),
    Kind("translate", "translate-v1", "post", TRANSLATE_SCHEMA),
    Kind("embed", "embed-v1", "post", EMBED_SCHEMA),   # S2: answered by an embedder, at POST /api/markx/embeddings
    Kind("alias", "alias-v1", "entity_entity", ALIAS_SCHEMA),        # 0119 A1: are two names one thing?
    Kind("alias2", "alias-v1", "entity_entity", ALIAS_SCHEMA),       # 0130 A2: the second opinion (other posts)
    Kind("collide", "collide-v1", "entity", COLLIDE_SCHEMA),         # 0119 A1: one name, several things?
    Kind("embed_name", "embed-name-v1", "entity", EMBED_SCHEMA),     # 0119 A1: a name's vector (the alias candidates)
    Kind("perspective", "persp-v1", "story", PERSPECTIVE_SCHEMA),    # 0119 B3: what each member of a story adds
    Kind("sheet", "persp-merge-v1", "story", SHEET_SCHEMA),          # 0119 B4: the story sheet's facts, merged
    Kind("read3", "read-v3", "post", READ3_SCHEMA),                  # 0127: event type and origin (the fold)
    Kind("relate", "relate-v1", "post_post", RELATE_SCHEMA),         # 0131: a newer post and an older one (Stalker)
    Kind("stance", "stance-v1", "source", STANCE_SCHEMA),            # 0132 B: a source's stance and framing
    Kind("back", "back-v1", "story", BACK_SCHEMA),                   # 0136: an old Mark IX story back in the news
    Kind("cite", "cite-v1", "post", CITE_SCHEMA),                    # 0133 v4.2: ent-v4.2's second question (ent42.py)
    Kind("track", "track-v1", "post_track", TRACK_SCHEMA),           # 0145: does a post belong in a track (tracks.py)
    Kind("subtopics", "subtopics-v1", "track", SUBTOPICS_SCHEMA),    # 0145: a track's sub-topics, proposed
    Kind("probes", "probes-v1", "track", PROBES_SCHEMA),             # 0147: a track's example posts (track recall)
    Kind("scout", "scout-v1", "track", SCOUT_SCHEMA),                # 0148: sources for a track's sphere (scout.py)
    Kind("identity", "identity-v1", "research_pair", IDENTITY_SCHEMA),   # 0162: two accounts, one maker? (research.py)
)}


# ---- 0133: the entities guide switch ---------------------------------------------------------------------
# The `entities` kind's guide is the owner's choice (mx_settings ENTITIES_GUIDE, set on the /markx Worker tab): each
# arm is a guide, the characters of the post its input shows, whether the citation rule runs with its answers, and
# its answer schema. No row (the default): ent-v3 at 1,500 characters, no rule, exactly as before 0133. A guide is a
# new task (tasks are unique per kind, guide and input), so switching plans new tasks and rewrites no row.
# KINDS["entities"].guide stays ent-v3: the readers that name it read ent-v3's rows, as before.

@dataclass(frozen=True)
class Arm:
    guide: str
    chars: int
    rule: bool
    schema: Dict[str, Any]


ENTITIES_GUIDE = "entities_guide"
ENTITY_ARMS: Dict[str, Arm] = {a.guide: a for a in (
    Arm("ent-v3", 1500, False, ENTITIES_SCHEMA),          # the default (the deploy changes nothing)
    Arm("ent-v4", 6000, True, ENTITIES_V4_SCHEMA),        # the lab's guide (a placeholder until out/entv41_v1 passes)
    Arm("ent-v3-6k", 6000, True, ENTITIES_SCHEMA),        # the spec's fallback: ent-v3's text at 6,000, with the rule
    Arm("ent-v4.2", 6000, False, ENTITIES_V4_SCHEMA),     # 0133 v4.2: the lab's ent42_extract.md, the rule off, + `cite`
)}
DEFAULT_ARM = "ent-v3"
PLACEHOLDER = "<!-- 0133 placeholder:"                    # a guide file starting so is not the lab's: never switched to


def entities_arm(cur) -> Arm:
    """The entities guide the owner switched to (ent-v3 when none, or when the stored one is unknown)."""
    from insight_core.markx import repo
    got = repo.get_setting(cur, ENTITIES_GUIDE)
    return ENTITY_ARMS.get(got if isinstance(got, str) else DEFAULT_ARM) or ENTITY_ARMS[DEFAULT_ARM]


def is_placeholder(guide_id: str) -> bool:
    return guide_body(guide_id).lstrip().startswith(PLACEHOLDER)


def set_entities_arm(cur, guide: str, *, allow_placeholder: bool = False) -> Arm:
    """Switch the entities guide (from the next planner run). A placeholder guide is refused (ValueError) unless
    `allow_placeholder` (tests): its body would be stored under the lab's id, which the frozen guide then can't take."""
    from insight_core.markx import repo
    if guide not in ENTITY_ARMS:
        raise ValueError(f"unknown entities guide {guide!r}: one of {', '.join(ENTITY_ARMS)}")
    if guide != DEFAULT_ARM and is_placeholder(guide) and not allow_placeholder:
        raise ValueError(f"{guide} is still the placeholder: the lab's frozen guide replaces it first")
    arm = ENTITY_ARMS[guide]
    repo.put_guide(cur, arm.guide, "entities", guide_body(arm.guide), arm.schema)
    repo.set_setting(cur, ENTITIES_GUIDE, guide)
    return arm


def mention_guides() -> list:
    """Every entities guide (identity reads the current set, mx_mentions_now, of any of them)."""
    return list(ENTITY_ARMS)


def guide_of(cur, kind: str) -> Optional[str]:
    """The guide a new task of `kind` is asked under: the switch's for entities, else the kind's."""
    return entities_arm(cur).guide if kind == "entities" else KINDS[kind].guide


def schema_for(kind: str, guide: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The answer schema of `kind` under `guide` (an entities arm's own; else the kind's)."""
    if kind == "entities" and guide in ENTITY_ARMS:
        return ENTITY_ARMS[guide].schema
    spec = KINDS.get(kind)
    return spec.schema if spec else None


def guide_ids() -> Dict[str, str]:
    """{guide id: kind}: every guide a kind names (a guide two kinds share, judge-read-v1, takes the first)."""
    out: Dict[str, str] = {}
    for kind in KINDS.values():
        if kind.guide:
            out.setdefault(kind.guide, kind.name)
    return out


def guide_body(guide_id: str) -> str:
    return (GUIDES_DIR / f"{guide_id}.md").read_text(encoding="utf-8")


def load_guides(cur) -> Dict[str, str]:
    """Every guide into mx_guides (at start, every time): {id: sha256}. A guide id stored with another body is
    refused (ValueError): a changed guide is a new id."""
    from insight_core.markx import repo
    out = {}
    for guide_id, kind in guide_ids().items():
        schema = next(k.schema for k in KINDS.values() if k.guide == guide_id)
        out[guide_id] = repo.put_guide(cur, guide_id, kind, guide_body(guide_id), schema)
    arm = entities_arm(cur)          # 0133: the switched-to entities guide (only that one: a placeholder never loads)
    if arm.guide not in out:
        out[arm.guide] = repo.put_guide(cur, arm.guide, "entities", guide_body(arm.guide), arm.schema)
    return out


_ready: set = set()


def ensure_guides(cur) -> None:
    """The guides loaded once per process and database, before the first task or lease that names one (0086 C:
    loaded at start, by sha256). The database is told apart by its connection's host, port and name.

    It is ready only once the transaction that loaded them commits (0112 bug 4: marked ready before, a second
    thread's lease planned tasks naming a guide not committed yet, a foreign-key failure). Until then each caller
    loads them in its own transaction, once per transaction: a concurrent first lease waits on the first one's
    rows (the database's lock, never a lock of this process held while waiting), then sees them committed; a
    failed load leaves the database not ready and the next caller loads again. On a plain connection (not
    `database.transaction`'s, so no commit to wait for) the database never becomes ready: each transaction loads."""
    from insight_core.db import database
    info = cur.connection.info
    where = (info.host, info.port, info.dbname)
    if where in _ready:
        return
    conn = cur.connection
    cur.execute("SELECT pg_current_xact_id()::text")
    xact = (where, cur.fetchone()[0])
    if getattr(conn, "_insight_guides_loaded", None) == xact:
        return
    load_guides(cur)
    conn._insight_guides_loaded = xact
    database.after_commit(conn, lambda: _ready.add(where))
