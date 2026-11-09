// Tracks as topics (issue 0145, Mark X): their calls and shapes, beside createApi's, as the smart archiver's are.
import { request } from '../lib/request';

export type TrackLabel = 'in' | 'out';
export type TrackPlace = 'track' | 'joined' | 'discover' | 'out';

export interface TrackItem {
  post_id: string;
  title: string | null;
  url: string | null;
  at: string | null;
  source: string | null;
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
}

export interface TrackSubtopic {
  id: string; name: string; definition: string | null; keys: string[]; locked: boolean; made_by: 'insight' | 'owner';
  created_at: string | null; count?: number;
}

export interface TrackBand { edge: number; labels: number; right: number; precision: number | null; lower: number }

export interface TrackCalibration {
  labels: number; right: number; precision: number | null; lower: number | null; bands: TrackBand[];
  /** The confidence at or above which passive matches join by themselves; null: they wait in Discover. */
  join_edge: number | null;
  bar: { precision: number; lower: number; labels: number };
}

export interface TrackSuggestion { track: string; track_name: string; source_id: string; source: string; n: number }

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
  footer: { cost_usd: number; cost_per_day: number; items_per_day: number; tasks: number } | null;
  prefilter: {
    threshold: number; ready: boolean; pos: number; neg: number; description: boolean;
    last: Record<string, unknown> | null; totals: Record<string, number> | null;
    history: { done: string | null; at: string | null };
  } | null;
}

export type SubtopicEdit =
  | { action: 'rename'; id: string; name: string; definition?: string }
  | { action: 'merge'; id: string; ids: string[] }
  | { action: 'split'; id: string; name: string; keys: string[] }
  | { action: 'lock' | 'unlock'; id: string }
  | { action: 'add'; name: string; definition?: string };

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
};
