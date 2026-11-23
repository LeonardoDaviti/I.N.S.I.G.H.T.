"""Mark X's task kinds: each kind's guide, subject and answer schema (KINDS), and the guide switches.

A guide is a file markx/guides/<id>.md, loaded into mx_guides by its sha256 (`load_guides`); a changed guide is a
new id and a new file (an id's body is never edited). The answer schemas are JSON Schema in the subset
scripts/markx-worker checks before it posts; they catch the shape, and the checks that read the input are
markx/validate.py's. A new kind is one entry in KINDS (mx_tasks.kind needs no migration).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

GUIDES_DIR = Path(__file__).resolve().parent / "guides"

# ---- the sets ------------------------------------------------------------------------------------

READ_KINDS = ["report", "commentary", "roundup", "tool", "other"]
EVENTS = ["one", "several", "none"]
MENTION_ROLES = ["hook", "background", "example"]
ACTIONS = ["released", "announced", "launched", "acquired", "raised", "published", "found", "reported", "sued",
           "delayed", "leaked", "priced", "updated", "other"]

ENTITY_TYPES = ["org", "person", "model", "product", "software", "paper", "dataset", "event", "place", "law", "other"]
ENTITY_ROLES = ["subject", "actor", "compared", "predecessor", "venue", "mention"]
# ent-v4's sets: `document` (a paper, filing, report, law text, book, video, course) and two roles: `source` (cited as
# evidence: an org, a person or a document) and `recommended` (a work recommended, not cited: a document only).
# ent-v3's sets above stay its schema's.
ENTITY_TYPES_V4 = ["org", "person", "model", "product", "software", "document", "dataset", "event", "place", "law", "other"]
ENTITY_ROLES_V4 = ENTITY_ROLES + ["source", "recommended"]
TYPE_READS = {"paper": "document"}       # a stored ent-v3 type as every reader reads it (no row rewritten)


def entity_type(t: Optional[str]) -> Optional[str]:
    """A stored type as it is read (ent-v3's `paper` is a `document`)."""
    return TYPE_READS.get(t, t) if t else t


def stored_types(types: Any) -> list:
    """The stored values of these read types (`document` is also ent-v3's `paper`), for a filter."""
    out = list(types)
    out += [k for k, v in TYPE_READS.items() if v in out and k not in out]
    return out
ENTITY_RELATIONS = ["released", "announced", "acquired", "invested_in", "partnered_with", "sued", "hired", "joined",
                    "left", "leads", "based_on", "beats", "part_of",
                    "published"]   # a issues or publishes document b
MAX_ENTITIES = 20

# The judge's seven relations (judge-*-v1, judge-story-v1, connect-v1), and those that make a post "about" a story.
RELATIONS = ["same_event", "development", "reaction", "mention", "digest_item", "different", "cant_tell"]
ABOUT = ["same_event", "development", "reaction"]

READ_HEADLINE_WORDS = 25     # the guide asks for 20
STORY_HEADLINE_WORDS = 14    # card and headline: what the guides ask
HEADLINE_WORDS = STORY_HEADLINE_WORDS + 2   # the headline check's slack, as readings have
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

# read-v3: a reading plus the post's event type and origin (the duplicates fold's input, markx/folds.py).
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

# ent-v4's answer: ent-v3's shape with the new sets, and `by` (a document's publisher or author, as the post names
# it: identity makes it a `published` edge).
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

# the second question (cite-v1): every document and cited org or person, at most 30. A document is a source,
# recommended or subject (a subject is dropped in ent42.merge_cite); an org or person is a source only.
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

# ent-v5, one reading of a post: read-v3's reading (`reading`, without `main`), read-v2's `main` (as `event`),
# ent-v4.2's entities, and the claims slot (not asked yet). A later window's `reading` and `event` are null.
# Entities may leave out the fields with no value (read as null).
READING_V5_SCHEMA = {
    "type": "object",
    "required": ["reading", "event", "entities"],
    "properties": {
        "reading": {"anyOf": [{"type": "null"}, {
            "type": "object",
            "required": ["kind", "events", "lang", "type_why", "event_type", "origin", "items", "mentions"],
            "properties": {k: READ3_SCHEMA["properties"][k] for k in ("kind", "events", "lang", "type_why",
                                                                       "event_type", "origin", "items", "mentions")}}]},
        "event": READ_SCHEMA["properties"]["main"],
        "entities": ENTITIES_V4_SCHEMA["properties"]["entities"],
        "claims": {"type": ["array", "null"]},
    },
}

# v10.42 (ent-v6): the reading's `subtype`, the finer kind of a release, a technical post or an incident (a new model
# vs a quant or adapter of an existing one, a method vs a benchmark, ...), each allowed only under its event types; null
# for every other type. validate._reading5 refuses a subtype its event type does not allow.
SUBTYPE_TYPES: Dict[str, Tuple[str, ...]] = {
    "new_model": ("model_release",),
    "build": ("model_release", "product_release"),
    "dataset": ("model_release", "research_result"),
    "product": ("product_release",),
    "software": ("product_release",),
    "method": ("research_result", "tutorial_explainer", "product_release", "model_release"),
    "benchmark": ("research_result",),
    "finding": ("research_result",),
    "guide": ("tutorial_explainer",),
    "security": ("incident",),
    "failure": ("incident",),
}
SUBTYPES = list(SUBTYPE_TYPES)
_V5_READING = READING_V5_SCHEMA["properties"]["reading"]["anyOf"][1]
READING_V6_SCHEMA = {
    **READING_V5_SCHEMA,
    "properties": {**READING_V5_SCHEMA["properties"], "reading": {"anyOf": [{"type": "null"}, {
        "type": "object", "required": _V5_READING["required"] + ["subtype"],
        "properties": {**_V5_READING["properties"], "subtype": {"enum": SUBTYPES + [None]}}}]}},
}

JUDGE_SCHEMA = {
    "type": "object",
    "required": ["relation", "confidence"],
    "properties": {"relation": {"enum": RELATIONS}, "confidence": {"type": "number", "minimum": 0, "maximum": 100},
                   "reason": _STR},
}

# judge-read-v2 (join, pair) also quotes the POST it judged: `post_quote`, a short verbatim phrase its verdict rests on,
# and for "about" optionally `story_quote`. validate._judge_read checks each is in its own block of this question: an
# answer written from another question of its batch quotes a post this one does not show, and is refused.
JUDGE_QUOTE_CHARS = 300
JUDGE_V2_SCHEMA = {
    "type": "object",
    "required": ["relation", "confidence", "post_quote"],
    "properties": {**JUDGE_SCHEMA["properties"],
                   "post_quote": {"type": "string", "maxLength": JUDGE_QUOTE_CHARS},
                   "story_quote": {"type": ["string", "null"], "maxLength": JUDGE_QUOTE_CHARS}},
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

# the entity identity judge (alias-v1) and the collision judge (collide-v1).
ALIAS_RELATIONS = ["same", "other_version", "part", "different", "cant_tell"]
ALIAS_SCHEMA = {
    "type": "object",
    "required": ["relation", "confidence"],
    "properties": {"evidence": _STR, "relation": {"enum": ALIAS_RELATIONS},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
}

# alias-v2, the question for pairs alias-v1 left unsure: each side's facts first, then the relation.
_SIDE = {"type": "object", "properties": {"what": _STR, "kind": {"type": ["string", "null"]},
                                         "maker": {"type": ["string", "null"]}}}
ALIAS_V2_SCHEMA = {
    "type": "object",
    "required": ["relation", "confidence"],
    "properties": {"a": _SIDE, "b": _SIDE, "evidence": _STR, "relation": {"enum": ALIAS_RELATIONS},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
}

# two entities of one maker, one older, that shared evidence says may be one thing renamed (rename-v1).
RENAME_RELATIONS = ["renamed", "successor", "part", "different", "cant_tell"]
RENAME_SCHEMA = {
    "type": "object",
    "required": ["relation", "confidence"],
    "properties": {"evidence": _STR, "relation": {"enum": RENAME_RELATIONS},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
}

# what happened to a thing in a story about it, a stop on its timeline (stop-v1, markx/stops.py).
STOP_KINDS = ["teaser", "preview", "launch", "availability", "update", "weights", "benchmark", "ranking", "adoption",
              "research", "incident", "deal", "analysis", "other"]
STOP_SCHEMA = {
    "type": "object",
    "required": ["about", "stop"],
    "properties": {"evidence": _STR, "about": {"type": "boolean"}, "stop": {"enum": STOP_KINDS}},
}

COLLIDE_MENTIONS = 8          # mentions a collision question shows
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

# collide-v2, the same question with each sense's identity facts (markx/entity_facts.py): a superset of collide-v1's
# answer.
FACT_KINDS = ["person", "org", "model", "product", "software", "dataset", "paper", "event", "place", "project", "law",
              "other"]
COLLIDE2_SCHEMA = {
    "type": "object",
    "required": ["senses"],
    "properties": {
        "evidence": _STR,
        "senses": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["m"],
            "properties": {"m": {"type": "array", "minItems": 1, "items": {"type": "integer", "minimum": 1}},
                           "known": {"type": ["string", "null"]}, "what": _STR,
                           "kind": {"enum": FACT_KINDS}, "maker": {"type": ["string", "null"]},
                           "context": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
                           "generic": {"type": "boolean"}}}},
        "related": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 3}},
        "unclear": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

# collide-makers-v1 (a guide variant): two maker groups of one bare name, each with its samples, types, dates and
# co-mentioned names: one thing whose maker names differ, or different things sharing the name?
COLLIDE_MAKERS_VERDICTS = ["same", "different", "cant_tell"]
_PAIR_SIDE = {"type": "object", "properties": {"what": _STR, "kind": {"enum": FACT_KINDS}}}
COLLIDE_MAKERS_SCHEMA = {
    "type": "object",
    "required": ["evidence", "verdict"],
    "properties": {"evidence": _STR, "a": _PAIR_SIDE, "b": _PAIR_SIDE, "verdict": {"enum": COLLIDE_MAKERS_VERDICTS},
                   "why": {"enum": ["owner_change", "founder", "foundation", "legal_name", "same_maker", "other",
                                    "different_things", "cant_tell"]},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
}

# what each member of a story adds (persp-v1) and the sheet's merged facts (persp-merge-v1). Loose: a fact without
# its span, a line number out of range, a member not asked are dropped by markx/perspectives.py, never asked again.
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

# where a story's sources differ (dispute-v1). Loose as the sheet's: a side whose lines or quote the code cannot check
# is dropped by perspectives.disputes_of, never asked again.
DISPUTE_SCHEMA = {
    "type": "object",
    "required": ["disputes"],
    "properties": {"disputes": {"type": "array", "items": {
        "type": "object", "required": ["fact", "sides"],
        "properties": {"fact": _STR, "kind": _STR_OR_NULL, "sides": {"type": "array", "items": {
            "type": "object", "required": ["lines", "says"],
            "properties": {"lines": {"type": "array", "items": {"type": "integer"}}, "says": _STR,
                           "quote": _STR_OR_NULL}}}}}}},
}

# how a newer post relates to an older one (relate-v1).
RELATE_RELATIONS = ["same_event", "follows_up", "next_version", "builds_on", "refers_back", "background", "unrelated"]
RELATE_SCHEMA = {
    "type": "object",
    "required": ["reason", "relation"],
    "properties": {"reason": {"type": "string", "minLength": 1}, "relation": {"enum": RELATE_RELATIONS},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 100}},
}

# how a later story about a thing relates to an earlier one about the same thing (chain, markx/graph.py's story
# chains). next_version is never one of them: a successor is an entity relation, by rule. same_release also covers
# sibling things one release launches together (graph.chain_siblings).
CHAIN_RELATIONS = ["same_release", "same_event", "follows_up", "development", "reaction", "builds_on", "unrelated"]
CHAIN_SCHEMA = {
    "type": "object",
    "required": ["reason", "relation"],
    "properties": {"reason": {"type": "string", "minLength": 1}, "relation": {"enum": CHAIN_RELATIONS},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 100}},
}


# what a post says of a thing and the predecessor its reading names (derive-v1, graph.py's based_on edges): `derived`
# alone makes the edge.
DERIVE_RELATIONS = ["derived", "replaces", "compared", "other"]
DERIVE_SCHEMA = {
    "type": "object",
    "required": ["reason", "relation"],
    "properties": {"reason": {"type": "string", "minLength": 1}, "relation": {"enum": DERIVE_RELATIONS},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 100}},
}

# back in the news: a verdict per new post (back-v1); code makes the candidate's.
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

# a source's stance and framing (stance-v1). Loose on the quotes: a quote not found in its post is dropped by
# validate.stance_grounded, never asked again.
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

# the judge's verdict on one post for one track (track-v1, v2). The checks that read the input are validate's.
TRACK_WHY_CHARS = 300
TRACK_SCHEMA = {
    "type": "object",
    "required": ["in", "confidence", "why"],
    "properties": {"in": {"type": "boolean"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                   "subtopic": _STR_OR_NULL, "why": {"type": "string", "minLength": 1}},
}
# track-v3, track-check-v2: the verdict follows a fit stated before it. `subject` the post's main subject, `fits`
# whether `Belongs:` asks for it, `matches` / `excluded` the words of `Belongs:` / `Not:` it is (copied).
# validate._track_v3 checks that `in` agrees with them and that the quotes are the question's own: a verdict that
# contradicts its own stated fit is no verdict.
TRACK_SCHEMA_V3 = {
    "type": "object",
    "required": ["subject", "fits", "matches", "excluded", "in", "confidence", "why"],
    "properties": {"subject": {"type": "string", "minLength": 1}, "fits": {"type": "boolean"},
                   "matches": _STR_OR_NULL, "excluded": _STR_OR_NULL, **TRACK_SCHEMA["properties"]},
}
# the sub-topics the clustering found, named (subtopics-v2: groups g1..gK), the posts placed into them
# (subtopic-place-v1: p1..pN into s1..sK or none), and a sub-topic's digest (digest-v1: 2-4 points, each citing the
# posts [n] it rests on). The checks that read the input are validate's.
SUBTOPIC_NAME_CHARS, SUBTOPIC_DEFINITION_CHARS = 60, 200
SUBTOPIC_NAMES_SCHEMA = {
    "type": "object",
    "required": ["names"],
    "properties": {"names": {"type": "array", "minItems": 1, "items": {
        "type": "object", "required": ["key", "name"],
        "properties": {"key": {"type": "string", "pattern": "^g[0-9]{1,2}$"},
                       "name": {"type": "string", "minLength": 1, "maxLength": SUBTOPIC_NAME_CHARS},
                       "definition": _STR_OR_NULL}}}},
}
SUBTOPIC_PLACE_SCHEMA = {
    "type": "object",
    "required": ["placements"],
    "properties": {"placements": {"type": "array", "minItems": 1, "items": {
        "type": "object", "required": ["post", "subtopic"],
        "properties": {"post": {"type": "string", "pattern": "^p[0-9]{1,3}$"},
                       "subtopic": {"type": "string", "pattern": "^(s[0-9]{1,2}|none)$"}}}}},
}
DIGEST_POINTS = (2, 4)
DIGEST_POINT_CHARS = 260
DIGEST_SCHEMA = {
    "type": "object",
    "required": ["points"],
    "properties": {"points": {"type": "array", "minItems": DIGEST_POINTS[0], "maxItems": DIGEST_POINTS[1], "items": {
        "type": "object", "required": ["text", "cites"],
        "properties": {"text": {"type": "string", "minLength": 1, "maxLength": DIGEST_POINT_CHARS},
                       "cites": {"type": "array", "minItems": 1, "items": {"type": "integer", "minimum": 1}}}}}},
}
# the general track briefer: a track's kinds of thing proposed from its description (track-schema-v1: 1-3 kinds, up to
# 8 typed fields each; code adds `practice_or_claim`), the things one post (or window) describes (track-things: each
# value with its quote, checked value by value in track_things.salvage: a bad value is dropped, never the answer), and
# whether two rows are one thing (track-same). The brief's "what changed" is the digest kind's digest-v2.
THING_TYPES = ["text", "number", "money", "link", "enum"]
THING_NAME = "^[a-z][a-z0-9_]{0,39}$"
THING_KINDS, THING_FIELDS, THING_ENUM = (1, 3), 8, (2, 10)
TRACK_SCHEMA_SCHEMA = {
    "type": "object",
    "required": ["kinds"],
    "properties": {"kinds": {"type": "array", "minItems": THING_KINDS[0], "maxItems": THING_KINDS[1], "items": {
        "type": "object", "required": ["kind", "fields"],
        "properties": {"kind": {"type": "string", "pattern": THING_NAME},
                       "about": _STR_OR_NULL,
                       "fields": {"type": "array", "minItems": 1, "maxItems": THING_FIELDS, "items": {
                           "type": "object", "required": ["name", "type"],
                           "properties": {"name": {"type": "string", "pattern": THING_NAME},
                                          "type": {"enum": THING_TYPES},
                                          "unit": _STR_OR_NULL,
                                          "values": {"type": "array", "maxItems": THING_ENUM[1],
                                                     "items": {"type": "string", "minLength": 1, "maxLength": 40}},
                                          "key": {"type": "boolean"},
                                          "about": _STR_OR_NULL}}}}}}},
}
# the owner's schema edit may give a kind more fields than Haiku proposes (fields are the owner's decision);
# track_things.set_schema checks against this one.
OWNER_FIELDS = 16
OWNER_SCHEMA_SCHEMA = {
    **TRACK_SCHEMA_SCHEMA,
    "properties": {"kinds": {**TRACK_SCHEMA_SCHEMA["properties"]["kinds"], "items": {
        **TRACK_SCHEMA_SCHEMA["properties"]["kinds"]["items"],
        "properties": {**TRACK_SCHEMA_SCHEMA["properties"]["kinds"]["items"]["properties"],
                       "fields": {**TRACK_SCHEMA_SCHEMA["properties"]["kinds"]["items"]["properties"]["fields"],
                                  "maxItems": OWNER_FIELDS}}}}},
}
# the fields a track's records miss (track-fields-v1, the track_schema kind's second guide; never applied:
# markx/track_fields.py shows them as suggestions the owner adds or dismisses).
TRACK_FIELDS_SCHEMA = {
    "type": "object",
    "required": ["fields"],
    "properties": {"fields": {"type": "array", "maxItems": 6, "items": {
        "type": "object", "required": ["kind", "name", "type", "why"],
        "properties": {"kind": {"type": "string", "pattern": THING_NAME},
                       "name": {"type": "string", "pattern": THING_NAME},
                       "type": {"enum": THING_TYPES},
                       "unit": _STR_OR_NULL,
                       "values": {"type": "array", "maxItems": THING_ENUM[1],
                                  "items": {"type": "string", "minLength": 1, "maxLength": 40}},
                       "about": _STR_OR_NULL,
                       "why": {"type": "string", "minLength": 1, "maxLength": 300}}}}},
}
THINGS_PER_ANSWER = 20
TRACK_THINGS_SCHEMA = {
    "type": "object",
    "required": ["things"],
    "properties": {"things": {"type": "array", "items": {"type": "object"}}},
}
TRACK_SAME_SCHEMA = {
    "type": "object",
    "required": ["same", "why"],
    "properties": {"same": {"type": "boolean"}, "why": {"type": "string", "minLength": 1, "maxLength": 300}},
}
# a track's example posts (probes-v1): 12-20 that belong, up to 4 near-misses that don't.
PROBES_MIN, PROBES_MAX, NEAR_MAX, PROBE_CHARS = 12, 20, 4, 300
PROBES_SCHEMA = {
    "type": "object",
    "required": ["probes"],
    "properties": {"probes": {"type": "array", "minItems": PROBES_MIN, "maxItems": PROBES_MAX,
                              "items": {"type": "string", "minLength": 1}},
                   "near_misses": {"type": "array", "maxItems": NEAR_MAX, "items": {"type": "string", "minLength": 1}}},
}
# the sources Haiku names for a track's sphere (scout-v1): each a platform class INSIGHT reads, its address or handle
# and why. Never trusted as is: each is test-read (markx/scout.py).
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
# are two accounts one person or org (identity-v1)? Asked only for a pair the plain rules leave unclear.
IDENTITY_ANSWERS = ["yes", "no", "unsure"]
IDENTITY_SCHEMA = {
    "type": "object",
    "required": ["same", "confidence", "why"],
    "properties": {"same": {"enum": IDENTITY_ANSWERS}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                   "why": {"type": "string", "minLength": 1}},
}
# the accounts and sites a maker has on the web, found by Claude's web search on the owner's device (websearch-v1).
# Candidates only: each is read and judged by research's same-identity rules or the `identity` question; a name alone
# never counts. `queries`: what was searched (at most WEBSEARCH_QUERIES).
WEBSEARCH_QUERIES, WEBSEARCH_MAX = 5, 15
WEBSEARCH_URL_CHARS, WEBSEARCH_TITLE_CHARS, WEBSEARCH_WHY_CHARS, WEBSEARCH_QUERY_CHARS = 500, 300, 300, 200
WEBSEARCH_SCHEMA = {
    "type": "object",
    "required": ["candidates", "queries"],
    "properties": {
        "candidates": {"type": "array", "maxItems": WEBSEARCH_MAX, "items": {
            "type": "object", "required": ["url", "why"],
            "properties": {"url": {"type": "string", "minLength": 8}, "title": _STR_OR_NULL,
                           "why": {"type": "string", "minLength": 1}}}},
        "queries": {"type": "array", "maxItems": WEBSEARCH_QUERIES, "items": {"type": "string", "minLength": 1}}},
}
# "Is this worth it?" on the owner's tap (source-judge-v1): one candidate source, its newest items and what INSIGHT
# measured; a verdict with its reasons and the items it relied on. How it reads (full, teasers, a paywall) is measured
# by code, never asked (the model fails at it).
SOURCE_VERDICTS = ["follow", "maybe", "skip"]
SOURCE_ORIGINAL = ["low", "medium", "high"]
SOURCE_REASONS_MAX, SOURCE_REASON_CHARS, SOURCE_EXAMPLES_MAX = 4, 240, 4
SOURCE_JUDGE_SCHEMA = {
    "type": "object",
    "required": ["verdict", "reasons", "examples", "fits", "original"],
    "properties": {
        "verdict": {"enum": SOURCE_VERDICTS},
        "reasons": {"type": "array", "minItems": 1, "maxItems": SOURCE_REASONS_MAX,
                    "items": {"type": "string", "minLength": 1, "maxLength": SOURCE_REASON_CHARS}},
        "examples": {"type": "array", "minItems": 1, "maxItems": SOURCE_EXAMPLES_MAX,
                     "items": {"type": "string", "pattern": "^i[0-9]{1,2}$"}},
        "fits": {"type": "boolean"},
        "original": {"enum": SOURCE_ORIGINAL}},
}
# source-judge-v2: v1 with, for a feed mixing releases and automatic builds, an item filter it proposes: `filter`
# {kind, hide [{field, regex, why}], keep [item ids]}, checked by validate._source_judge (utils/item_filter.check) and
# applied by code to every new item when the channel is added. Absent or null for any other source.
SOURCE_FILTER_SCHEMA = {
    "anyOf": [{"type": "null"}, {
        "type": "object", "required": ["kind", "hide", "keep"],
        "properties": {"kind": {"enum": ["releases", "builds", "mixed"]},
                       "hide": {"type": "array", "maxItems": 4, "items": {
                           "type": "object", "required": ["field", "regex", "why"],
                           "properties": {"field": {"enum": ["tag", "title"]},
                                          "regex": {"type": "string", "minLength": 1, "maxLength": 120},
                                          "why": {"type": "string", "minLength": 1, "maxLength": 200}}}},
                       "keep": {"type": "array", "maxItems": 10, "items": {"type": "string", "pattern": "^i[0-9]{1,2}$"}}}}]}
# a question the reader asked, answered only from the posts it shows (question-v1, markx/questions.py): each sentence
# with the numbers of the posts it rests on; `answerable` false (no sentences) when the posts don't say.
QUESTION_SENTENCES = 6
QUESTION_SENTENCE_CHARS = 400
QUESTION_SCHEMA = {
    "type": "object",
    "required": ["answerable", "sentences"],
    "properties": {"answerable": {"type": "boolean"},
                   "sentences": {"type": "array", "maxItems": QUESTION_SENTENCES, "items": {
                       "type": "object", "required": ["text", "cites"],
                       "properties": {"text": {"type": "string", "minLength": 1, "maxLength": QUESTION_SENTENCE_CHARS},
                                      "cites": {"type": "array", "items": {"type": "integer", "minimum": 1}}}}}},
}
SOURCE_JUDGE_V2_SCHEMA = {**SOURCE_JUDGE_SCHEMA,
                          "properties": {**SOURCE_JUDGE_SCHEMA["properties"], "filter": SOURCE_FILTER_SCHEMA}}
# who announces an event and where (websearch-official-v1, the websearch kind's second guide). Candidates only: the
# maker is written through identity's facts and each channel is proven by code before anything is followed.
OFFICIAL_CHANNEL_KINDS = ["x", "telegram", "youtube", "site_section", "releases", "repository", "site", "page", "other"]
OFFICIAL_SCHEMA = {
    "type": "object",
    "required": ["actor", "channels", "official", "queries"],
    "properties": {
        "actor": {"anyOf": [{"type": "null"}, {
            "type": "object", "required": ["name"],
            "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 120}, "site": _STR_OR_NULL,
                           "kind": {"enum": ["org", "person", "project"]}}}]},
        "thing_maker": _STR_OR_NULL,
        "announcement": {"anyOf": [{"type": "null"}, {
            "type": "object", "required": ["url"],
            "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 500}, "why": _STR_OR_NULL}}]},
        "channels": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "required": ["url", "kind", "why"],
            "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 500},
                           "kind": {"enum": OFFICIAL_CHANNEL_KINDS},
                           "why": {"type": "string", "minLength": 1, "maxLength": 300}}}},
        "official": {"type": "boolean"},
        "why_not": _STR_OR_NULL,
        "queries": {"type": "array", "maxItems": WEBSEARCH_QUERIES, "items": {"type": "string", "minLength": 1}}},
}
# Mark X News divided into 3-8 sections Haiku titles (news-sections-v1), every row (r1..rN) in exactly one. No fixed
# list of sections in code: the titles are the answer's.
NEWS_SECTIONS = (3, 8)
NEWS_SECTION_TITLE_CHARS, NEWS_SECTION_TITLE_WORDS = 40, 4
NEWS_SECTIONS_SCHEMA = {
    "type": "object",
    "required": ["sections"],
    "properties": {"sections": {"type": "array", "minItems": NEWS_SECTIONS[0], "maxItems": NEWS_SECTIONS[1], "items": {
        "type": "object", "required": ["title", "row_ids"],
        "properties": {"title": {"type": "string", "minLength": 1, "maxLength": NEWS_SECTION_TITLE_CHARS},
                       "row_ids": {"type": "array", "minItems": 1,
                                   "items": {"type": "string", "pattern": "^r[0-9]{1,4}$"}}}}}},
}
# the rows added since the last sectioning, each placed into one of its sections (s1..sM) or "new" (it waits for the
# next full sectioning), news-place-v1. Every row once (validate.py).
NEWS_PLACE_SCHEMA = {
    "type": "object",
    "required": ["placements"],
    "properties": {"placements": {"type": "array", "minItems": 1, "items": {
        "type": "object", "required": ["row_id", "section"],
        "properties": {"row_id": {"type": "string", "pattern": "^r[0-9]{1,4}$"},
                       "section": {"type": "string", "pattern": "^(s[0-9]{1,2}|new)$"}}}}},
}

# a round-up's items (units, markx/units.py), ~20 a question: each its type, a short headline and whether it only
# continues the item before it. The types are read-v3's, with `promo` in place of `promotion_event` and no `digest`.
# Which of them are news: markx/event_types.py (UNIT_NEWS).
UNIT_TYPES = [t for t in EVENT_TYPES if t not in ("digest", "promotion_event")] + ["promo"]
UNIT_HEADLINE_WORDS = 14
UNITS_PER_QUESTION = 20
UNIT_TYPES_SCHEMA = {
    "type": "object",
    "required": ["units"],
    "properties": {"units": {"type": "array", "minItems": 1, "maxItems": UNITS_PER_QUESTION, "items": {
        "type": "object", "required": ["key", "type", "headline", "continues"],
        "properties": {"key": {"type": "string", "pattern": "^u[0-9]{1,3}$"}, "type": {"enum": UNIT_TYPES},
                       "headline": {"type": "string", "minLength": 1, "maxLength": 200},
                       "continues": {"type": "boolean"}}}}},
}

# how significant a News row's event is for people in its field, whatever its loudness (significance-v1, asked again
# only when the row's members change: markx/significance).
SIGNIFICANCE_EVENTS = ["new_method", "new_model", "new_tool", "release_update", "research_result", "benchmark",
                       "product_launch", "deal_funding", "policy_legal", "security_incident", "outage", "people",
                       "opinion_analysis", "tutorial", "other"]
SIGNIFICANCE_USABLE = ["now", "soon", "no"]
SIGNIFICANCE_ADOPTION = ["widely_used_library", "open_code", "open_weights", "api", "paper", "paper_with_code",
                         "official", "benchmark_result"]
SIGNIFICANCE_COVERAGE = ["expert_breakdown", "reports", "passing_mentions"]
SIGNIFICANCE_SCOPE = ["field_wide", "subfield", "niche"]
SIGNIFICANCE_SCHEMA = {
    "type": "object",
    "required": ["event", "usable", "adoption", "coverage", "effect", "scope", "why"],
    "properties": {
        "event": {"enum": SIGNIFICANCE_EVENTS},
        "usable": {"enum": SIGNIFICANCE_USABLE},
        "shipped_in": _STR_OR_NULL,
        "adoption": {"type": "array", "maxItems": len(SIGNIFICANCE_ADOPTION), "items": {"enum": SIGNIFICANCE_ADOPTION}},
        "coverage": {"enum": SIGNIFICANCE_COVERAGE},
        "effect": {"type": "integer", "minimum": 1, "maximum": 5},
        "scope": {"enum": SIGNIFICANCE_SCOPE},
        "why": {"type": "string", "minLength": 1, "maxLength": 400}},
}
# significance-v2 also names the posts shown that are an expert breakdown (keys [1]..[6] as numbers), which a News row
# shows apart from its reports (news_rank.analysis).
SIGNIFICANCE_V2_SCHEMA = {
    **SIGNIFICANCE_SCHEMA,
    "required": SIGNIFICANCE_SCHEMA["required"] + ["breakdowns"],
    "properties": {**SIGNIFICANCE_SCHEMA["properties"],
                   "breakdowns": {"type": "array", "maxItems": 6, "items": {"type": "integer", "minimum": 1, "maximum": 6}}},
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
    Kind("join", "judge-read-v2", "post_story", JUDGE_V2_SCHEMA),   # v2 quotes the post (v1's tasks kept:
    Kind("pair", "judge-read-v2", "post_post", JUDGE_V2_SCHEMA),    # EARLIER_GUIDES)
    Kind("merge", "judge-story-v1", "story_story", JUDGE_SCHEMA),
    Kind("connect", "connect-v1", "story_story", JUDGE_SCHEMA),
    Kind("card", "card-v1", "story", CARD_SCHEMA),
    Kind("headline", "headline-v2", "story", HEADLINE_SCHEMA),     # core members; who acted, its date
    Kind("briefing", "briefing-v1", "day", BRIEFING_SCHEMA),
    Kind("translate", "translate-v1", "post", TRANSLATE_SCHEMA),
    Kind("embed", "embed-v1", "post", EMBED_SCHEMA),   # answered by an embedder, at POST /api/markx/embeddings
    Kind("alias", "alias-v1", "entity_entity", ALIAS_SCHEMA),        # are two names one thing?
    Kind("alias2", "alias-v1", "entity_entity", ALIAS_SCHEMA),       # the second opinion (other posts)
    Kind("alias3", "alias-v2", "entity_entity", ALIAS_V2_SCHEMA),    # the unsure queue's question (each side's facts)
    Kind("alias4", "alias-v2", "entity_entity", ALIAS_V2_SCHEMA),    # the same, for a class asked with its own model
    Kind("collide", "collide-v1", "entity", COLLIDE_SCHEMA),         # one name, several things?
    Kind("rename", "rename-v1", "entity_entity", RENAME_SCHEMA),     # one thing under an earlier name?
    Kind("stop", "stop-v1", "story", STOP_SCHEMA),
    Kind("embed_name", "embed-name-v1", "entity", EMBED_SCHEMA),     # a name's vector (the alias candidates)
    Kind("perspective", "persp-v1", "story", PERSPECTIVE_SCHEMA),    # what each member of a story adds
    Kind("sheet", "persp-merge-v1", "story", SHEET_SCHEMA),          # the story sheet's facts, merged
    Kind("dispute", "dispute-v1", "story", DISPUTE_SCHEMA),
    Kind("read3", "read-v3", "post", READ3_SCHEMA),                  # event type and origin (the fold)
    Kind("relate", "relate-v1", "post_post", RELATE_SCHEMA),         # a newer post and an older one
    Kind("chain", "chain-v4", "story_story", CHAIN_SCHEMA),          # a later story and an earlier one, one thing
    Kind("derive", "derive-v1", "entity_entity", DERIVE_SCHEMA),     # is a thing made from its predecessor?
    Kind("stance", "stance-v1", "source", STANCE_SCHEMA),
    Kind("back", "back-v1", "story", BACK_SCHEMA),                   # an old story back in the news
    Kind("cite", "cite-v1", "post", CITE_SCHEMA),                    # ent-v4.2's second question (ent42.py)
    Kind("track", "track-v3", "post_track", TRACK_SCHEMA_V3),        # does a post belong in a track (tracks.py)
    Kind("subtopics", "subtopics-v2", "track", SUBTOPIC_NAMES_SCHEMA),
    Kind("digest", "digest-v1", "track", DIGEST_SCHEMA),
    Kind("subtopic_place", "subtopic-place-v1", "track", SUBTOPIC_PLACE_SCHEMA),
    Kind("probes", "probes-v1", "track", PROBES_SCHEMA),             # a track's example posts (track recall)
    Kind("scout", "scout-v1", "track", SCOUT_SCHEMA),
    Kind("identity", "identity-v1", "research_pair", IDENTITY_SCHEMA),   # two accounts, one maker? (research.py)
    Kind("websearch", "websearch-v1", "research_run", WEBSEARCH_SCHEMA),
    Kind("source_judge", "source-judge-v2", "source_candidate", SOURCE_JUDGE_V2_SCHEMA),   # + an item filter
    Kind("news_sections", "news-sections-v1", "news_run", NEWS_SECTIONS_SCHEMA),
    Kind("news_place", "news-place-v1", "news_run", NEWS_PLACE_SCHEMA),
    Kind("unit_types", "unit-types-v1", "post", UNIT_TYPES_SCHEMA),   # a round-up's items: type, headline
    Kind("significance", "significance-v2", "story", SIGNIFICANCE_V2_SCHEMA),   # a News row's significance and
                                                                                # its breakdowns
    Kind("reading", "ent-v6", "post", READING_V6_SCHEMA),           # read, read3 and entities in one reading, + subtype
    Kind("track_schema", "track-schema-v1", "track", TRACK_SCHEMA_SCHEMA),
    Kind("track_things", "track-things-v3", "post_track", TRACK_THINGS_SCHEMA),   # a catalog is one row
    Kind("track_same", "track-same-v2", "thing_thing", TRACK_SAME_SCHEMA),   # two rows, one thing?
    Kind("question", "question-v1", "question", QUESTION_SCHEMA),   # the reader's question, from their posts
)}


# ---- the entities guide switch ------------------------------------------------------------------------------
# The `entities` kind's guide is the owner's choice (mx_settings ENTITIES_GUIDE, the /markx Worker tab): each arm is a
# guide, the characters of the post its input shows, whether the citation rule runs, and its answer schema. No row:
# ent-v3 at 1,500 characters, no rule. A guide is a new task (tasks are unique per kind, guide and input), so
# switching plans new tasks and rewrites no row. KINDS["entities"].guide stays ent-v3 (its readers read ent-v3's rows).

@dataclass(frozen=True)
class Arm:
    guide: str
    chars: int
    rule: bool
    schema: Dict[str, Any]


ENTITIES_GUIDE = "entities_guide"
ENTITY_ARMS: Dict[str, Arm] = {a.guide: a for a in (
    Arm("ent-v3", 1500, False, ENTITIES_SCHEMA),          # the default
    Arm("ent-v4", 6000, True, ENTITIES_V4_SCHEMA),        # a placeholder until the lab's guide passes
    Arm("ent-v3-6k", 6000, True, ENTITIES_SCHEMA),        # the fallback: ent-v3's text at 6,000, with the rule
    Arm("ent-v4.2", 6000, False, ENTITIES_V4_SCHEMA),     # the rule off, + `cite`
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
    """Every entities guide (identity reads the current set, mx_mentions_now, of any of them), and ent-v5's, whose rows
    are current only once its switch is on."""
    return list(ENTITY_ARMS) + ["ent-v5"]


# the `significance` kind's guide behind a switch (entity_bands.json `significance.results`): on, a new ask is
# significance-v3 (a result scored by what it changes in the field too); off, significance-v2. Same schema; a guide is
# a new task only when a row is asked (significance.due), never a mass re-ask.
SIGNIFICANCE_RESULTS_GUIDE = "significance-v3"


def significance_guide() -> str:
    from insight_core.markx import identity   # identity reads this module
    on = bool((identity.bands().get("significance") or {}).get("results", False))
    return SIGNIFICANCE_RESULTS_GUIDE if on else KINDS["significance"].guide


def guide_of(cur, kind: str) -> Optional[str]:
    """The guide a new task of `kind` is asked under: the switch's for entities and significance, else the kind's."""
    if kind == "entities":
        return entities_arm(cur).guide
    if kind == "significance":
        return significance_guide()
    return KINDS[kind].guide


# a kind's second guide with a schema of its own (the same kind, so the worker asks it with that kind's tools and
# per-call setting): {guide: (kind, schema)}. A task names its guide; its answers are checked by that guide's schema.
GUIDE_VARIANTS: Dict[str, Tuple[str, Dict[str, Any]]] = {
    "websearch-official-v1": ("websearch", OFFICIAL_SCHEMA),
    "track-v1": ("track", TRACK_SCHEMA),   # the judge before track-v2; its open questions are still answered
    "track-v2": ("track", TRACK_SCHEMA),   # the judge before track-v3; its open questions are still answered
    "track-check-v1": ("track", TRACK_SCHEMA),   # the blind check of a passive `in` (tracks.plan_checks)
    "track-check-v2": ("track", TRACK_SCHEMA_V3),   # the blind check, its verdict following its stated fit
    "digest-v2": ("digest", DIGEST_SCHEMA),   # a track brief's "what changed", citing its rows (track_brief.py)
    "digest-v3": ("digest", DIGEST_SCHEMA),   # the same, its points state facts (no reporting words, no hedges)
    "collide-makers-v1": ("collide", COLLIDE_MAKERS_SCHEMA),   # two maker groups of one bare name
    "collide-v2": ("collide", COLLIDE2_SCHEMA),   # also an entity brief's senses (entity_brief.senses, b set)
    "significance-v3": ("significance", SIGNIFICANCE_V2_SCHEMA),   # results by what they change (the switch above)
    "track-fields-v1": ("track_schema", TRACK_FIELDS_SCHEMA),   # fields a track's records miss (track_fields.py)
}


# a kind's earlier guides, {guide: (its kinds, the schema its answers were checked by)}. A question already asked under
# one keeps its task and answers (`answer_guides`), and a task still open there is answered and checked under it. A
# guide change asks new questions only, never the history again.
EARLIER_GUIDES: Dict[str, Tuple[Tuple[str, ...], Dict[str, Any]]] = {
    "judge-read-v1": (("join", "pair"), JUDGE_SCHEMA),   # before the post quote
    "track-things-v1": (("track_things",), TRACK_THINGS_SCHEMA),   # before v2 (values only from their quote)
    "track-things-v2": (("track_things",), TRACK_THINGS_SCHEMA),   # before v3 (a catalog or roundup is one row);
                                                                   # its catalog posts are asked again (track_things.repair)
    "track-same-v1": (("track_same",), TRACK_SAME_SCHEMA),   # before v2 (practices only); its pairs are not asked again
    "chain-v1": (("chain",), CHAIN_SCHEMA),   # before v2's clause (a result achieved with the thing is not
                                                 # its release); its same_release pairs are asked again (graph.plan_chains)
    "chain-v2": (("chain",), CHAIN_SCHEMA),   # before v3's sibling things of one release; its sibling pairs
                                              # that linked nothing are asked again (graph.chain_asked)
    "chain-v3": (("chain",), CHAIN_SCHEMA),   # before v4's project made with the thing (builds_on); its
                                              # same_release and unknown pairs are asked again (graph.chain_asked)
    "ent-v5": (("reading",), READING_V5_SCHEMA),   # v10.42: before v6's subtype; its readings are not asked again
}


def answer_guides(kind: str) -> Tuple[str, ...]:
    """The guides whose task answers a question of `kind`: the current one first, then its earlier ones."""
    return (KINDS[kind].guide,) + tuple(g for g, (kinds, _s) in EARLIER_GUIDES.items() if kind in kinds)


def schema_for(kind: str, guide: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The answer schema of `kind` under `guide` (an entities arm's own, a guide variant's own, an earlier guide's
    own; else the kind's)."""
    if kind == "entities" and guide in ENTITY_ARMS:
        return ENTITY_ARMS[guide].schema
    if guide in GUIDE_VARIANTS and GUIDE_VARIANTS[guide][0] == kind:
        return GUIDE_VARIANTS[guide][1]
    if guide in EARLIER_GUIDES and kind in EARLIER_GUIDES[guide][0]:
        return EARLIER_GUIDES[guide][1]
    spec = KINDS.get(kind)
    return spec.schema if spec else None


def guide_ids() -> Dict[str, str]:
    """{guide id: kind}: every guide a kind names (a guide two kinds share, judge-read-v2, takes the first), each kind's
    second guide (GUIDE_VARIANTS) and its earlier ones (EARLIER_GUIDES: their tasks are kept)."""
    out: Dict[str, str] = {}
    for kind in KINDS.values():
        if kind.guide:
            out.setdefault(kind.guide, kind.name)
    for guide_id, (kind_name, _schema) in GUIDE_VARIANTS.items():
        out.setdefault(guide_id, kind_name)
    for guide_id, (kind_names, _schema) in EARLIER_GUIDES.items():
        out.setdefault(guide_id, kind_names[0])   # judge-read-v1 stays stored as join's
    return out


def guide_body(guide_id: str) -> str:
    return (GUIDES_DIR / f"{guide_id}.md").read_text(encoding="utf-8")


def load_guides(cur) -> Dict[str, str]:
    """Every guide into mx_guides (at start, every time): {id: sha256}. A guide id stored with another body is
    refused (ValueError): a changed guide is a new id."""
    from insight_core.markx import repo
    out = {}
    for guide_id, kind in guide_ids().items():
        schema = schema_for(kind, guide_id)   # a guide variant's own schema, else its kind's
        out[guide_id] = repo.put_guide(cur, guide_id, kind, guide_body(guide_id), schema)
    arm = entities_arm(cur)          # the switched-to entities guide (only that one: a placeholder never loads)
    if arm.guide not in out:
        out[arm.guide] = repo.put_guide(cur, arm.guide, "entities", guide_body(arm.guide), arm.schema)
    return out


_ready: set = set()


def ensure_guides(cur) -> None:
    """The guides loaded once per process and database (told apart by host, port and name), before the first task or
    lease that names one.

    It is ready only once the transaction that loaded them commits (else a second thread's lease could plan tasks naming
    a guide not committed yet). Until then each caller loads them in its own transaction, once per transaction: a
    concurrent first lease waits on the first one's rows (the database's lock, never a lock of this process), then sees
    them committed; a failed load leaves it not ready. On a plain connection (no commit to wait for) the database never
    becomes ready: each transaction loads."""
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
