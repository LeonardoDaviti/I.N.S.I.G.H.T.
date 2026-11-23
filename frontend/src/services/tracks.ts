// Tracks as topics (Mark X): their calls and shapes, beside createApi's.
import { request } from '../lib/request';
import type { Byline } from '../lib/byline';

export type TrackLabel = 'in' | 'out';
/** `checked_out`: the blind check said out; `checking`: past its week's review lane, the check decides. */
export type TrackPlace = 'track' | 'joined' | 'discover' | 'checked_out' | 'checking' | 'out';

export interface TrackItem {
  post_id: string;
  title: string | null;
  url: string | null;
  at: string | null;
  source: string | null;
  byline?: Byline | null;
  source_id: string;
  confidence: number | null;
  subtopic: string | null;
  why: string | null;
  origin: 'active' | 'passive';
  /** joined: a passive match that joined by itself (the track's precision passed the bar). */
  place: TrackPlace;
  label: TrackLabel | null;
  /** Discover's calibrated precision (or the confidence until 10 labels). */
  rank: number;
  calibrated: boolean;
  /** The finders that put a passive post up for judging (probe, entity, domain, word, source, story, classifier). */
  found_by?: string[];
  joined_at?: string | null;
}

export interface TrackSection {
  /** null: the items no sub-topic holds ("Other", or "In this track" before any is proposed). */
  id: string | null;
  name: string;
  definition: string | null;
  locked: boolean;
  made_by: 'insight' | 'owner' | null;
  keys: string[];
  count: number;
  items: TrackItem[];
  /** Who named it (judge: its posts' most common judge words, until the worker names it). */
  named_by?: SubtopicNamedBy | null;
  /** new (found this week), active, or quiet (no new post in 30 days: shown last, folded). */
  state?: SubtopicState;
  last_member_at?: string | null;
  digest?: SubtopicDigest | null;
  /** When each of its posts joined the track (epoch seconds, newest first): what is new since a look. */
  joined?: number[];
}

export type TrackSort = 'newest' | 'news';
/** v10.42: a thing (an entity) of the reader's stack. */
export interface StackThing { id: string; name: string; type: string | null }
export interface StackCandidate extends StackThing { level: string | null; mentions: number }
export interface SubTrack {
  id: string; name: string; description: string | null; rest: boolean; sort: TrackSort; stack: StackThing[];
  count: number; items: Array<{ post_id: string; at: string | null; title?: string | null; url?: string | null; source?: string | null }>;
}

export type SubtopicNamedBy = 'judge' | 'haiku' | 'owner';
export type SubtopicState = 'new' | 'active' | 'quiet';

export interface SubtopicDigest {
  points: Array<{ text: string; cites: string[] }>;
  at: string | null;
  /** Its posts changed since it was written (a new one is on its way). */
  stale: boolean;
}

export interface TrackSubtopic {
  id: string; name: string; definition: string | null; keys: string[]; locked: boolean; made_by: 'insight' | 'owner';
  created_at: string | null; count?: number; named_by?: SubtopicNamedBy | null; state?: SubtopicState;
}

export interface TrackTool {
  id: string; name: string; kind: string; what: string | null; posts: number; voices: number;
  last_at: string | null; recent: number; in_track: number;
}

/** A Shadow feature's blind-labelled measure: `right` of `of` rows, the Wilson lower bound, and whether it is on. */
export interface ShadowMeasure { what: string; right: number; of: number; lower: number; on: boolean }

export interface TrackSeen { track: string | null; subtopics: Record<string, string> }

export interface TrackBand { edge: number; labels: number; right: number; precision: number | null; lower: number }

export interface TrackCalibration {
  labels: number; right: number; precision: number | null; lower: number | null; bands: TrackBand[];
  /** The confidence at or above which passive matches join by themselves; null: they wait in Discover. */
  join_edge: number | null;
  bar: { precision: number; lower: number; labels: number };
}

export interface TrackSuggestion {
  track: string; track_name: string; source_id: string; source: string; n: number;
  of?: number; share?: number; lower?: number;
}

export interface TrackPage {
  track: {
    id: string; name: string; kind: string; topic: boolean; description: string | null; excludes: string | null;
    sources: Array<{ id: string; name: string }>; version?: number; version_at?: string | null;
    /** v10.42: a sub-track's parent (its posts are the parent's), whether it takes the rest, its order, its stack. */
    parent?: { id: string; name: string } | null;
    rest?: boolean;
    sort?: TrackSort;
    stack?: StackThing[];
  };
  /** v10.42: the track's sub-tracks, each with its newest (or News-ranked) first posts. */
  subtracks?: SubTrack[];
  sections: TrackSection[];
  discover: TrackItem[];
  discover_per_week?: number;
  discover_weeks?: number;
  counts: Partial<Record<'track' | 'joined' | 'discover' | 'checked_out' | 'checking' | 'out' | 'waiting' | 'judged', number>>;
  calibration: TrackCalibration | null;
  suggestions: TrackSuggestion[];
  examples: {
    in: Array<{ post_id: string; title: string }>; out: Array<{ post_id: string; title: string }>;
    /** ✓ examples the judge, asked against the description alone, says do not fit (flagged, never removed). */
    misleading?: Array<{ post_id: string; title: string; why: string | null; subject?: string | null }>;
  };
  subtopics: TrackSubtopic[];
  tools?: TrackTool[];
  shadow?: { subtopics?: ShadowMeasure; digests?: ShadowMeasure; tools?: ShadowMeasure; bar?: number; lower_bar?: number };
  footer: { cost_usd: number; cost_per_day: number; items_per_day: number; tasks: number } | null;
  prefilter: {
    threshold: number; ready: boolean; pos: number; neg: number; description: boolean;
    last: Record<string, unknown> | null; totals: Record<string, number> | null;
    history: { done: string | null; at: string | null };
    probes?: number; near_misses?: number; found_by?: Record<string, number>;
  } | null;
}

export type SubtopicEdit =
  | { action: 'rename'; id: string; name: string; definition?: string }
  | { action: 'merge'; id: string; ids: string[] }
  | { action: 'split'; id: string; name: string; keys: string[] }
  | { action: 'lock' | 'unlock'; id: string }
  | { action: 'add'; name: string; definition?: string };

export type TrackWhyState = 'in' | 'joined' | 'discover' | 'checked_out' | 'checking' | 'out' | 'waiting' | 'invalid'
  | 'not_asked';
export type TrackWhyReason = 'not_a_topic' | 'labelled' | 'outside_window' | 'not_planned' | 'not_embedded' | 'no_profile'
  | 'history_pending' | 'below_bar';
export interface TrackWhy {
  track: string;
  post: string;
  state: TrackWhyState;
  origin: 'active' | 'passive';
  reason?: TrackWhyReason;
  label?: TrackLabel | null;
  verdict?: boolean | null;
  confidence?: number | null;
  why?: string | null;
  subtopic?: string | null;
  found_by?: string[];
  version?: number;
  /** false: the verdict was asked under an older description. */
  current?: boolean;
  /** The current description's question (or guide's) is open while an older verdict stands. */
  waiting_again?: boolean;
  guide?: string | null;
  /** state 'invalid': the last answer's error. */
  error?: string | null;
  shown?: boolean;
  position?: number;
  of?: number;
  cut?: number;
  section_items?: number;
  days?: number;
  bar?: number | null;
}

const base = (id: string) => `/api/markx/tracks/${encodeURIComponent(id)}`;

export const tracksApi = {
  page: (id: string) => request<TrackPage>(base(id)),
  describe: (id: string, body: { description: string; excludes: string }) =>
    request<TrackPage>(base(id), { method: 'PUT', body }),
  label: (id: string, post: string, answer: TrackLabel | 'undo') =>
    request<{ id: string; label: TrackLabel | null }>(`${base(id)}/labels`, { method: 'POST', body: { post, answer } }),
  editSubtopics: (id: string, edit: SubtopicEdit) =>
    request<TrackSubtopic[]>(`${base(id)}/subtopics`, { method: 'POST', body: edit }),
  activate: (id: string, sourceId: string) =>
    request<{ added: boolean }>(`${base(id)}/sources/${encodeURIComponent(sourceId)}`, { method: 'POST' }),
  suggestions: () => request<TrackSuggestion[]>('/api/markx/tracks/suggestions'),
  why: (id: string, post: string) => request<TrackWhy>(`${base(id)}/why?post=${encodeURIComponent(post)}`),
  seen: (id: string) => request<TrackSeen>(`${base(id)}/seen`),
  look: (id: string, subtopic?: string | null) =>
    request<{ before: TrackSeen; now: TrackSeen }>(`${base(id)}/seen`, { method: 'POST', body: { subtopic: subtopic ?? null } }),
  /** v10.42: the reader's stack (entity ids; a change is a new version) and the picker's search. */
  setStack: (id: string, things: string[]) => request<TrackPage>(`${base(id)}/stack`, { method: 'PUT', body: { things } }),
  findThings: (id: string, q: string) => request<StackCandidate[]>(`${base(id)}/stack/find?q=${encodeURIComponent(q)}`),
};

// ---- The general track briefer. Behind the backend's switch: every answer says `on`; off, the shapes are
// empty and the UI shows none of it. ----

export type ThingFieldType = 'text' | 'number' | 'money' | 'link' | 'enum';

export interface ThingFieldDef {
  name: string; type: ThingFieldType; unit?: string | null; values?: string[]; key?: boolean; about?: string | null;
}
export interface ThingKindDef { kind: string; about?: string | null; fields: ThingFieldDef[] }

/** A typed value: number and money come as {number, range_to, unit | currency}; the rest as a string. */
export type ThingValue = string | { number: number; range_to?: number | null; unit?: string | null; currency?: string | null };

export interface ThingPost { id: string; title: string | null; url: string | null; at: string | null; why?: string | null }

export interface Thing {
  id: string;
  kind: string;
  fields: Record<string, { value: ThingValue; shown: string; quote?: string | null; post?: string | null }>;
  posts: ThingPost[];
  first_at: string | null; last_at: string | null; found_at: string | null;
  new?: boolean;
  sources?: number;
  practices?: Thing[];
}

export interface ThingSection {
  kind: string; header: string; about: string; count: number; new: number;
  inside?: number; quiet?: number;
  fields: ThingFieldDef[];
  things: Thing[];
}

export interface BriefPoint { text: string; cites: Array<{ thing: string; n: number | null }> }

export interface QuickLook {
  on: boolean;
  track: { id: string; name: string };
  since: string;
  sections: ThingSection[];
  points: BriefPoint[];
  /** When the points were written; `stale`: a thing was found after them. */
  as_of: string | null;
  stale: boolean;
  also: ThingPost[];
  counts: { things: number; also: number };
  nothing_new: boolean;
  last_issue: string | null;
  weeks?: string[];
}

export interface WeekIssue {
  on: boolean;
  track: { id: string; name: string };
  week: { start: string; end: string; closed: boolean };
  points: BriefPoint[];
  points_at: string | null;
  sections: ThingSection[];
  also: ThingPost[];
  counts: { things: number; new: number; posts: number; also: number };
  built_at: string;
  first_built_at?: string;
  updated: boolean;
}

export interface ThingTable {
  on: boolean;
  track: { id: string; name: string };
  kind: string;
  kinds: string[];
  about?: string;
  fields: ThingFieldDef[];
  filters: Record<string, string>;
  search?: { q: string; entity: string; entity_type: string };
  chips?: { entities: Array<{ id: string; name: string; type: string; rows: number }>; types: Array<{ type: string; rows: number }> };
  count: number;
  things: Thing[];
}

/** A field INSIGHT suggests a kind add (never applied: Add is the owner's schema edit). */
export interface FieldSuggestion extends ThingFieldDef { kind: string; why: string }

export interface FieldSuggestions {
  on: boolean;
  asked_for: number | null;
  at: string | null;
  fields: FieldSuggestion[];
}

export const OWNER_FIELDS = 16;

export interface TrackSchemaView {
  on: boolean;
  version: number | null;
  by: 'haiku' | 'owner' | null;
  track_version: number | null;
  /** Proposed for an older description (a new one is on its way). */
  stale: boolean;
  at?: string;
  schema: { kinds: ThingKindDef[] } | null;
}

/** The kind code adds to every track (track_things.PRACTICE_KIND): shown, never edited. */
export const PRACTICE_KIND = 'practice_or_claim';

const query = (params: Record<string, string>) => {
  const q = new URLSearchParams(params).toString();
  return q ? `?${q}` : '';
};

export const briefApi = {
  schema: (id: string) => request<TrackSchemaView>(`${base(id)}/schema`),
  saveSchema: (id: string, kinds: ThingKindDef[]) =>
    request<TrackSchemaView>(`${base(id)}/schema`, { method: 'PUT', body: { kinds } }),
  quickLook: (id: string, since: string) => request<QuickLook>(`${base(id)}/brief${query({ since })}`),
  issue: (id: string, week: string) => request<WeekIssue>(`${base(id)}/brief${query({ week })}`),
  things: (id: string, kind: string, filters: Record<string, string> = {}) =>
    request<ThingTable>(`${base(id)}/things${query({ kind, ...filters, limit: '500' })}`),
  suggestions: (id: string) => request<FieldSuggestions>(`${base(id)}/schema/suggestions`),
  dismissField: (id: string, kind: string, name: string) =>
    request<FieldSuggestions>(`${base(id)}/schema/suggestions/dismiss`, { method: 'POST', body: { kind, name } }),
};
