// "Is this worth it?" (issue 0173, Mark X): a candidate source judged by the worker on the owner's tap. Its calls and
// shapes, and its lines in words.
import { request } from '../lib/request';

export type JudgeStatus = 'reading' | 'asked' | 'answered' | 'unreadable' | 'failed';
export type JudgeVerdict = 'follow' | 'maybe' | 'skip';

export interface JudgeExample {
  id: string;
  url: string;
  title: string | null;
  published_at: string | null;
}

export interface SourceJudgement {
  id: string;
  address: string;
  key: string;
  status: JudgeStatus;
  /** Why it could not be read, or why the worker could not answer. */
  reason: string | null;
  verdict: JudgeVerdict | null;
  reasons: string[];
  fits: boolean | null;
  original: 'low' | 'medium' | 'high' | null;
  /** The items the verdict relied on. */
  examples: JudgeExample[];
  /** How many items the test read found. */
  items: number;
  follows_as: 'feed' | 'page' | 'kind' | null;
  follow_address: string | null;
  /** What INSIGHT measured, in words (the question's MEASURED lines). */
  measured: string[];
  reads: string | null;
  cadence: string | null;
  rewriter: boolean;
  /** Asked again, nothing new: the earlier answer stands. */
  same_items: boolean;
  asked_at: string;
  answered_at: string | null;
  fresh_until: string;
  fresh: boolean;
}

const PATH = '/api/markx/source-judge';

export const sourceJudgeApi = {
  get: (address: string) => request<{ judgement: SourceJudgement | null }>(`${PATH}?address=${encodeURIComponent(address)}`),
  ask: (address: string, again = false) =>
    request<{ judgement: SourceJudgement | null }>(PATH, { method: 'POST', body: { address, again } }),
};

const VERDICT_WORDS: Record<JudgeVerdict, string> = { follow: 'Worth following', maybe: 'Maybe', skip: 'Skip it' };

export const verdictWord = (v: JudgeVerdict) => VERDICT_WORDS[v];

/** "Fits what you read · original: high · reads in full · 4 a week". */
export function judgeLine(j: SourceJudgement): string {
  const reads: Record<string, string> = {
    full: 'full text', full_page: 'read in full from its pages', teaser: 'teasers only', paywalled: 'paywalled',
    short: 'short posts', video: 'videos', none: 'no items',
  };
  return [
    j.fits === null ? null : j.fits ? 'fits what you read' : 'not what you read',
    j.original ? `original: ${j.original}` : null,
    j.reads ? reads[j.reads] ?? j.reads : null,
    j.cadence || null,
    j.rewriter ? 'reads like a rewriter' : null,
  ].filter(Boolean).join(' · ');
}

/** What the row says while it is not answered. */
export function waitingLine(j: SourceJudgement): string | null {
  if (j.status === 'reading') return 'Reading its newest items…';
  if (j.status === 'asked') return `Read ${j.items} items · waiting for the worker’s next run`;
  if (j.status === 'unreadable') return `Can’t read it: ${j.reason ?? 'unknown'}`;
  if (j.status === 'failed') return `No answer: ${j.reason ?? 'unknown'}`;
  return null;
}
