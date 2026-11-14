// Tracks as topics (issue 0145, Mark X): their calls and shapes, beside createApi's, as the smart archiver's are.
import { request } from '../lib/request';
import type { Byline } from '../lib/byline';

export type TrackLabel = 'in' | 'out';
export type TrackPlace = 'track' | 'joined' | 'discover' | 'out';

export interface TrackItem {
  post_id: string;
  title: string | null;
  url: string | null;
  at: string | null;
  source: string | null;
  /** Who wrote it, via whom (issue 0185). */
  byline?: Byline | null;
  source_id: string;
  confidence: number | null;
  /** The judge's sub-topic words for it. */
  subtopic: string | null;
  /** One line: what it is and why it is worth it, in the track's terms. */
  why: string | null;
  origin: 'active' | 'passive';
  /** joined: a passive match that joined by itself (the track's precision passed the bar). */
  place: TrackPlace;
  label: TrackLabel | null;
  /** Discover's calibrated precision (or the confidence until 10 labels). */
  rank: number;
  /** The rank is calibrated on 10+ labels (else it is the confidence). */
  calibrated: boolean;
  /** 0147: the finders that put a passive post up for judging (probe, entity, domain, word, source, story, classifier). */
  found_by?: string[];
  /** 0207: when it joined the track (its verdict's time). */
  joined_at?: string | null;
}

export interface TrackSection {
  /** null: the items no sub-topic holds ("Other", or "In this track" before any is proposed). */
  id: string | null;
  name: string;
  definition: string | null;
  locked: boolean;
  made_by: 'insight' | 'owner' | null;
  /** The judge's sub-topic words it collects. */
  keys: string[];
  count: number;
  items: TrackItem[];
  /** 0207: who named it (judge: its posts' most common judge words, until the worker names it). */
  named_by?: SubtopicNamedBy | null;
  /** 0207: new (found this week), active, or quiet (no new post in 30 days: shown last, folded). */
  state?: SubtopicState;
  last_member_at?: string | null;
  /** 0207: the worker's digest of its newest posts, each point citing the posts it rests on. */
  digest?: SubtopicDigest | null;
  /** 0207: when each of its posts joined the track (epoch seconds, newest first): what is new since a look. */
  joined?: number[];
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

/** 0207: a tool or product the track's practitioners discuss, counted by voices. */
export interface TrackTool {
  id: string; name: string; kind: string; what: string | null; posts: number; voices: number;
  last_at: string | null; recent: number; in_track: number;
}

/** 0207: a Shadow feature's blind-labelled measure: `right` of `of` rows, the Wilson lower bound, and whether it is on. */
export interface ShadowMeasure { what: string; right: number; of: number; lower: number; on: boolean }

/** 0207: the reader's last looks at the track and at each sub-topic (ISO), for "new since you looked". */
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
  /** 0207: the source's posts in those 30 days, the share in the track's sphere and its lower bound. */
  of?: number; share?: number; lower?: number;
}

export interface TrackPage {
  track: {
    id: string; name: string; kind: string; topic: boolean; description: string | null; excludes: string | null;
    sources: Array<{ id: string; name: string }>; version?: number; version_at?: string | null;
  };
  sections: TrackSection[];
  discover: TrackItem[];
  counts: Partial<Record<'track' | 'joined' | 'discover' | 'out' | 'waiting' | 'judged', number>>;
  calibration: TrackCalibration | null;
  suggestions: TrackSuggestion[];
  examples: { in: Array<{ post_id: string; title: string }>; out: Array<{ post_id: string; title: string }> };
  subtopics: TrackSubtopic[];
  /** 0207: the tools the track's practitioners use or build. */
  tools?: TrackTool[];
  /** 0207: what is Shadow (shown, labelled, not acted on) and its blind-labelled measure. */
  shadow?: { subtopics?: ShadowMeasure; digests?: ShadowMeasure; tools?: ShadowMeasure; bar?: number; lower_bar?: number };
  footer: { cost_usd: number; cost_per_day: number; items_per_day: number; tasks: number } | null;
  prefilter: {
    threshold: number; ready: boolean; pos: number; neg: number; description: boolean;
    last: Record<string, unknown> | null; totals: Record<string, number> | null;
    history: { done: string | null; at: string | null };
    /** 0147: this version's example posts and near-misses, and how many items each finder found. */
    probes?: number; near_misses?: number; found_by?: Record<string, number>;
  } | null;
}

export type SubtopicEdit =
  | { action: 'rename'; id: string; name: string; definition?: string }
  | { action: 'merge'; id: string; ids: string[] }
  | { action: 'split'; id: string; name: string; keys: string[] }
  | { action: 'lock' | 'unlock'; id: string }
  | { action: 'add'; name: string; definition?: string };

/** Where one post stands in a track and why (issue 0185, GET /tracks/{id}/why): stored rows only. */
export type TrackWhyState = 'in' | 'joined' | 'discover' | 'out' | 'waiting' | 'not_asked';
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
  /** The current description's question is open while an older verdict stands. */
  waiting_again?: boolean;
  shown?: boolean;
  /** Discover: its place among the Discover items, and how many the page shows. */
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
  /** Issue 0185: a post (its id, its INSIGHT link or its address) in this track, and why. */
  why: (id: string, post: string) => request<TrackWhy>(`${base(id)}/why?post=${encodeURIComponent(post)}`),
  /** 0207: the last looks at the track and its sub-topics. */
  seen: (id: string) => request<TrackSeen>(`${base(id)}/seen`),
  /** 0207: the reader looked at the track (or one sub-topic) now; answers the looks before and now. */
  look: (id: string, subtopic?: string | null) =>
    request<{ before: TrackSeen; now: TrackSeen }>(`${base(id)}/seen`, { method: 'POST', body: { subtopic: subtopic ?? null } }),
};
