// v10.43: "Your interests": what you raised or lowered (markx/personal.py's mx_interests, the newest tap of each),
// removed with "undo", and a thing added as "more" from the entity picker. Replaces running scripts/seed_interests.
import { request } from '../lib/request';
import type { InterestAnswer, InterestDim } from './api';

export interface TaughtInterest {
  dim: InterestDim; key: string; answer: InterestAnswer; name: string | null; origin: 'reader' | 'seed' | string; at: string;
}
export interface InterestThing { id: string; name: string; type: string | null; level: string | null; mentions: number }

export const interestsApi = {
  list: () => request<{ taught: TaughtInterest[] }>('/api/markx/interests'),
  find: (q: string) => request<InterestThing[]>(`/api/markx/interests/find?q=${encodeURIComponent(q)}`),
  teach: (body: { dim: InterestDim; key: string; answer: InterestAnswer; name?: string | null }) =>
    request<{ id: string }>('/api/markx/interests', { method: 'POST', body }),
};

const DIM_WORDS: Record<InterestDim, string> = { thing: '', kind: 'kind: ', source: 'source: ' };

/** "GrapheneOS", "kind: builds of an existing model", "source: Example Blog". */
export function interestLabel(t: TaughtInterest): string {
  return `${DIM_WORDS[t.dim]}${t.name || t.key}`;
}

/** Where an interest links: a thing's page, a source's feed; a kind: nowhere. */
export function interestHref(t: TaughtInterest): string | null {
  if (t.dim === 'thing') return `/markx/entities/${encodeURIComponent(t.key)}`;
  if (t.dim === 'source') return `/read/source/${encodeURIComponent(t.key)}`;
  return null;
}
