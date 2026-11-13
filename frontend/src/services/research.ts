// Research (issue 0162, Mark X): from a pasted post, a link, an entity, a name or a question, INSIGHT finds what it has,
// the same announcement elsewhere, the maker, its channels, its papers and who discusses it. Calls and shapes.
import { request } from '../lib/request';
import type { ScoutCandidate } from './scout';
import type { Byline } from '../lib/byline';

export type SeedKind = 'post' | 'link' | 'entity' | 'name' | 'question';
export type RunStatus = 'running' | 'waiting' | 'done' | 'failed';

export interface ResearchPostRow {
  post_id: string; title: string | null; at: string | null; source: string | null; byline?: Byline | null; url: string | null;
  why?: string; strength?: 'link' | 'text' | 'around'; new?: boolean;
}

export interface ResearchHeldEntity {
  key: string;
  entity?: { id: string; name: string; type: string | null; maker: string | null };
  posts?: number; stories?: number; voices?: number;
  addresses?: Array<{ kind: string; url: string; owner: string | null }>;
  newest?: ResearchPostRow[];
  /** a post linking one of its addresses */
  post_id?: string; title?: string | null; source?: string | null; why?: string; new: boolean;
}

export interface ResearchAccount {
  key: string; address?: string; platform: string; kind: string; handle?: string | null; title?: string | null;
  name?: string | null; hop?: number; how?: string; same?: 'seed' | 'yes' | 'no' | 'unsure' | 'pending' | null;
  rule?: string | null; read?: boolean | null; read_error?: string | null; new?: boolean;
}

export interface ResearchPaper {
  ref: string | null; url: string | null; title: string; date: string | null; role: 'seed' | 'reference' | 'citing' | 'newer';
  held: string | null; authors?: string[]; why?: string; new?: boolean;
}

export interface ResearchChannel extends ScoutCandidate { fit: string | null }

export interface ResearchPage {
  run: {
    id: string; seed_kind: SeedKind; seed: string; status: RunStatus; steps: Record<string, string>;
    entity_id: string | null; track_id: string | null; previous_id: string | null; created_at: string | null;
    finished_at: string | null;
    spent: { page_requests: number; paper_calls: number; search_calls: number; identity_asked: number;
      identity_open: number; identity_pairs: number };
    budget: { page_requests: number; paper_calls: number; identity: number; test_reads: number; judgements: number;
      web_queries: number; discussion_searches: number };
  };
  held: ResearchHeldEntity[];
  same_post: ResearchPostRow[];
  entities: Array<{ id?: string; name: string; why: string; proposed?: boolean; new?: boolean }>;
  maker: {
    accounts: ResearchAccount[]; asking: ResearchAccount[]; not_same: ResearchAccount[];
    these_are: { entity: { id: string; name: string }; by: Array<{ id: string; name: string }>;
      proposed: Array<{ id: string; name: string }> } | null;
  };
  channels: { to_follow: ResearchChannel[]; unread: ResearchChannel[]; cannot: ResearchChannel[] };
  papers: { seed: ResearchPaper[]; reference: ResearchPaper[]; citing: ResearchPaper[]; newer: ResearchPaper[];
    held_references: number; references: number };
  discussion: Array<{ url: string; title: string | null; at: string | null; query: string; why: string; where: string; new?: boolean }>;
  unread: Array<{ key: string; url?: string; ref?: string; query?: string; why: string }>;
}

export interface ResearchRunRow { id: string; seed_kind: SeedKind; seed: string; status: RunStatus; created_at: string | null }

const run = (id: string) => `/api/markx/research/${encodeURIComponent(id)}`;

export const researchApi = {
  start: (seed: string, kind?: SeedKind) =>
    request<{ id: string; seed_kind: SeedKind }>('/api/markx/research', { method: 'POST', body: { seed, kind } }),
  runs: () => request<ResearchRunRow[]>('/api/markx/research'),
  page: (id: string) => request<ResearchPage>(run(id)),
  rerun: (id: string) => request<{ id: string }>(`${run(id)}/rerun`, { method: 'POST' }),
  watch: (id: string) => request<{ track_id: string; made: boolean }>(`${run(id)}/watch`, { method: 'POST' }),
  follow: (id: string, candidate: string) =>
    request<{ source_id: string; as: string }>(`${run(id)}/channels/${encodeURIComponent(candidate)}/follow`, { method: 'POST' }),
  notThis: (id: string, candidate: string) =>
    request<{ answer: 'not' }>(`${run(id)}/channels/${encodeURIComponent(candidate)}/not`, { method: 'POST' }),
  answerSources: (entity: string, sourceIds: string[], answer: 'yes' | 'no') =>
    request(`/api/markx/entities/${encodeURIComponent(entity)}/sources`, { method: 'POST', body: { source_ids: sourceIds, answer } }),
};

export const researchHref = (id: string) => `/research/${encodeURIComponent(id)}`;
export const researchStartHref = (seed: string) => `/research?seed=${encodeURIComponent(seed)}`;

const SEED_WORDS: Record<SeedKind, string> = {
  post: 'a pasted post', link: 'a link', entity: 'an entity', name: 'a name', question: 'a question',
};
export const seedWords = (k: SeedKind) => SEED_WORDS[k] ?? k;

/** The run's state in words. */
export function statusLine(page: ResearchPage): string {
  const r = page.run;
  const spent = `${r.spent.page_requests} of ${r.budget.page_requests} page requests · ${r.spent.identity_asked} identity questions`;
  if (r.status === 'running') return `Researching · ${spent}`;
  if (r.status === 'waiting') {
    return r.spent.identity_open
      ? `Waiting for Haiku: ${r.spent.identity_open} same-maker questions (the worker’s next run) · ${spent}`
      : `Waiting for Haiku to judge the channels’ posts · ${spent}`;
  }
  return `Done · ${spent}`;
}

/** "github.com/acme (code): the platform says this account owns it". */
export function accountLine(a: ResearchAccount): string {
  const name = a.address ? a.address.replace(/^https?:\/\//, '').replace(/\/$/, '') : a.name ?? a.key;
  const label = a.name && a.platform === 'paper' ? a.name : name;
  return `${label} (${a.platform})${a.rule ? `: ${a.rule}` : ''}`;
}

/** "53 references: 12 in INSIGHT". */
export function referencesLine(p: ResearchPage['papers']): string {
  return `${p.references} references: ${p.held_references} in INSIGHT`;
}
