/**
 * Mark X Shadow's page and panel (issue 0086 E): the shapes of /api/markx/news, /posts/:id and /overview.
 * Types only, so the reader's bundle carries none of it (the page and the panel are their own chunks).
 */

export type MarkxTag = 'NEW' | 'MERGED' | 'SPLIT' | 'CHANGED' | 'SAME';

/** Why a post is in a Mark X story: the rule (Mark IX's link evidence) or the judge's relation, p and words. */
export interface MarkxWhy {
  role: 'member' | 'mention' | 'digest_item';
  reason: string;            // rule:citation, judge:join, judge:pair, merge, judge:check
  p: number | null;
  relation: string | null;
  words: string | null;
}

export interface MarkxCheck {
  relation: string | null;
  p: number;
  words: string | null;
}

export interface MarkxLine {
  id: string;
  title: string | null;
  source: string | null;
  kind: string | null;
  at: string | null;
  url?: string | null;
  role?: string;
  /** The surging name Mark IX's News joined it by, when it did. */
  name?: string | null;
  why: MarkxWhy | null;
  /** What Mark IX did with it: the News row it is in (and whether that is this row's), or null: none. */
  ix: { row: string; title: string | null; same_row: boolean } | null;
}

export interface MarkxLeftOut {
  id: string;
  title: string | null;
  source: string | null;
  kind: string | null;
  at: string | null;
  /** The newest check of it, when one was asked. */
  check: MarkxCheck | null;
  /** The Mark X row it is in now, if any. */
  now_in?: string | null;
  /** Kept as a mention or digest item. */
  mention: MarkxWhy | null;
}

export interface MarkxRow {
  id: string;
  tag: MarkxTag;
  headline: { text: string; from: 'haiku' | 'lead title' };
  first_at: string;
  voices: number;
  reports: number;
  shares: number;
  mentions: number;
  score: number;
  story: string | null;
  posts: MarkxLine[];
  removed: MarkxLeftOut[];
  ix: { id: string; title: string | null; voices?: number; first_at?: string }[];
}

export interface MarkxNews {
  run: { id: string; started_at: string; finished_at: string | null; code_version: string | null } | null;
  counts: Partial<Record<MarkxTag, number>> & { rows?: number; ix_rows?: number; gone?: number };
  items: MarkxRow[];
  gone: { id: string; title: string | null; voices?: number; first_at?: string; posts: MarkxLeftOut[] }[];
}

export interface MarkxPostPanel {
  post_id: string;
  read: boolean;
  reading: {
    guide: string;
    kind: string | null;
    events: string | null;
    lang: string | null;
    headline: string | null;
    main: { headline_en?: string; actors?: string[]; object?: string; action?: string; date?: string | null } | null;
    mentions: { name: string; role: string }[];
  } | null;
  entities: { name: string; type: string | null; role: string | null; maker: string | null; family: string | null;
    version: string | null; variant: string | null; span: string }[];
  stories: (MarkxWhy & { id: string; headline: string | null; first_at: string | null; posts: number })[];
  connections: { relation: string; p: number | null; rule: string | null; from: 'post' | 'story'; other_kind: 'post' | 'story';
    other: string; title?: string | null; reason: string | null }[];
}

export interface MarkxOverview {
  worker: {
    queue: Record<string, Record<string, number>>;
    days: { day: string; calls: number; valid: number; tokens_in: number; tokens_out: number; api_usd: number }[];
    tokens: { calls: number; tokens_in: number; tokens_out: number; paid_usd: number; api_usd: number };
    failed: { kind: string; error: string | null; tasks: number }[];
    invalid: { kind: string; error: string | null; at: string }[];
    workers: { worker: string; last_contact: string | null; leased: number }[];
    last_run: { id: string; started_at: string; finished_at: string | null; code_version: string | null;
      counts: Record<string, unknown> | null } | null;
  };
  briefing: { day: string | null; briefings: { created_at: string; guide: string | null;
    lines: { text: string; keys: string[]; stories: string[]; rows?: string[] }[] }[] };
  entities: Record<'today' | 'week', { key: string; version: string | null; name: string; type: string | null; posts: number;
    voices: number; examples: { id: string | null; title: string | null; source: string | null }[] }[]>;
}
