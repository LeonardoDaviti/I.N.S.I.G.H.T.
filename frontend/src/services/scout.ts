// The track scout (issue 0148, Mark X): a track finds sources in a sphere INSIGHT doesn't read yet. Its calls and
// shapes, beside tracks.ts's.
import { request } from '../lib/request';

export type ScoutPlace = 'suggested' | 'judging' | 'below_floor' | 'reads_badly' | 'unreadable' | 'unread';

export interface ScoutCandidate {
  id: string;
  run_id: string;
  track: string | null;
  /** match: the track's matches link it; shape: a platform's address for the track's words; haiku: Haiku named it. */
  finder: string;
  platform: string;
  address: string;
  key: string;
  name: string;
  why: string | null;
  place: ScoutPlace;
  /** Why it can't be read, or can't be read well (no items, undated, titles only, stopped). */
  reason: string | null;
  items: number;
  judged: number;
  fits: number;
  precision: number | null;
  per_week: number | null;
  /** "3 a week", "2 a month". */
  cadence: string;
  /** Not a stop: "summaries only", "in de", "no transcripts". */
  labels: string[];
  reads_well: boolean;
  /** How the add path follows it: a feed, a watched page, or a source kind. */
  follows_as: 'feed' | 'page' | 'kind' | null;
  follow_address: string | null;
  answer: 'active' | 'passive' | 'not' | null;
  source_id: string | null;
  /** Discover's rows only. */
  track_name?: string;
}

export interface ScoutFollowed {
  source_id: string; name: string; as: 'active' | 'passive'; since: string | null;
  judged: number; fits: number; precision: number | null;
}

export interface ScoutRun {
  id: string; trigger: 'tap' | 'weekly'; status: 'running' | 'waiting' | 'done' | 'failed';
  reads: number; requests: number; judgements: number; asked: string | null;
  finders: Record<string, { candidates: number; read: number; read_well: number }>;
  started_at: string | null; finished_at: string | null;
}

export interface ScoutPage {
  suggested: ScoutCandidate[];
  reads_badly: ScoutCandidate[];
  unreadable: ScoutCandidate[];
  judging: ScoutCandidate[];
  unread: number;
  followed: ScoutFollowed[];
  runs: ScoutRun[];
  floor: number;
  budget: { reads: number; judgements: number; requests: number };
}

const track = (id: string) => `/api/markx/tracks/${encodeURIComponent(id)}/scout`;
const candidate = (id: string) => `/api/markx/scout/candidates/${encodeURIComponent(id)}`;

export const scoutApi = {
  page: (trackId: string) => request<ScoutPage>(track(trackId)),
  start: (trackId: string) => request<{ id: string; candidates: Record<string, number> }>(track(trackId), { method: 'POST' }),
  suggestions: () => request<ScoutCandidate[]>('/api/markx/scout/suggestions'),
  follow: (candidateId: string, as: 'active' | 'passive') =>
    request<{ source_id: string; as: string }>(`${candidate(candidateId)}/follow`, { method: 'POST', body: { as } }),
  notThis: (candidateId: string) => request<{ answer: 'not' }>(`${candidate(candidateId)}/not`, { method: 'POST' }),
};

const PLATFORM_WORDS: Record<string, string> = {
  site: 'site', reddit: 'Reddit', youtube: 'YouTube', telegram: 'Telegram', x: 'X', hn: 'Hacker News', code: 'code',
  hub: 'hub', paper: 'papers', podcast: 'podcast', newsletter: 'newsletter', account: 'account',
};

export const platformWord = (p: string) => PLATFORM_WORDS[p] ?? p;

/** "Example Makers (Reddit): 14 of its last 20 posts fit · 3 a week · reads well". */
export function scoutLine(c: ScoutCandidate): string {
  const head = `${c.name} (${platformWord(c.platform)})`;
  const fit = c.judged ? `${c.fits} of its last ${c.judged} posts fit` : `${c.items} posts read, not judged yet`;
  const health = c.reads_well ? ['reads well', ...c.labels] : [`can't read well: ${c.reason ?? 'unknown'}`];
  return [`${head}: ${fit}`, c.cadence || null, ...health].filter(Boolean).join(' · ');
}

/** "Example Site (site): can't read: blocked". */
export function unreadLine(c: ScoutCandidate): string {
  const why = c.place === 'unreadable' ? `can't read: ${c.reason ?? 'unknown'}` : `can't read well: ${c.reason ?? 'unknown'}`;
  return `${c.name} (${platformWord(c.platform)}): ${why}`;
}

/** The run's state in words: what it is waiting for. */
export function runLine(run: ScoutRun | undefined, page: Pick<ScoutPage, 'unread' | 'judging'>): string | null {
  if (!run) return null;
  if (run.status === 'running') return `Reading candidates · ${run.reads} read so far`;
  if (run.status === 'waiting') {
    if (run.asked === 'open' || run.asked === 'leased') return 'Waiting for Haiku to name more sources (the worker’s next run)';
    if (page.judging.length) return `Waiting for Haiku to judge ${page.judging.length} sources’ posts`;
    return 'Waiting for the worker';
  }
  return `Last looked ${run.finished_at ? new Date(run.finished_at).toLocaleDateString() : ''} · ${run.reads} read · ${run.requests} requests`.trim();
}
