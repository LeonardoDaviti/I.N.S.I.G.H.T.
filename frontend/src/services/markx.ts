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
  /** Its Mark X story (the one tap's key, 0086 F), and the owner's standing one-tap answer, if any. */
  story?: string | null;
  flag?: Exclude<MarkxFlag, 'ok'> | null;
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
  /** 0119 A2: the entities its posts make surge (3+ voices that day). */
  surging?: { id: string; name: string; day: string; voices: number }[];
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
    version: string | null; variant: string | null; span: string; entity_id?: string | null }[];
  stories: (MarkxWhy & { id: string; headline: string | null; first_at: string | null; posts: number })[];
  connections: { relation: string; p: number | null; rule: string | null; from: 'post' | 'story'; other_kind: 'post' | 'story';
    other: string; title?: string | null; reason: string | null }[];
}

/** One Mark X job's state: a running run's start and stage, work waiting for a run, how the last run ended. */
export interface MarkxJob {
  running: boolean;
  started_at: string | null;
  stage: string | null;
  stage_at: string | null;
  wanted_at: string | null;
  finished_at: string | null;
  last: { ok?: boolean; error?: string; seconds?: number } | null;
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
    /** Mark X's jobs, run by insight-ingestion (issue 0112 Decided 10, 12); absent from an older API. */
    jobs?: Record<'decide' | 'candidates', MarkxJob>;
  };
  briefing: { day: string | null; briefings: { created_at: string; guide: string | null;
    lines: { text: string; keys: string[]; stories: string[]; rows?: string[] }[] }[] };
  entities: Record<'today' | 'week', { key: string; version: string | null; name: string; type: string | null; posts: number;
    voices: number; examples: { id: string | null; title: string | null; source: string | null }[] }[]>;
  /** The read, entities and embed planners' window (issue 0112): days, or null for every post. */
  reading_window: { days: number | null; default: number };
}

/** POST /api/markx/settings/reading-window's answer. */
export interface MarkxSettings {
  reading_window_days: number | null;
  default: number;
}

// ---- Labels (issue 0086 F): /api/markx/labels ----

export type MarkxFeature = 'check' | 'join' | 'pair' | 'merge' | 'connect' | 'entities';
export type MarkxAnswer = 'same_event' | 'follow_up' | 'related' | 'different' | 'unsure' | 'right' | 'wrong';
export type MarkxFlag = 'wrong_story' | 'not_about' | 'ok';

export interface MarkxLabelQueue {
  run: string | null;
  /** The first test day (ISO date): older items are dev. */
  cut: string | null;
  total: number;
  done: number;
  features: { feature: MarkxFeature; name: string; total: number; done: number; population: number }[];
  next: string[];
  answered: string[];
  pools: Record<string, number>;
}

export interface MarkxVerdict {
  relation?: string | null;
  p?: number | null;
  reason?: string | null;
  bar?: number | null;
  decision: string | null;
}

export interface MarkxLabelItem {
  id: string;
  feature: MarkxFeature;
  name: string;
  question: string;
  answers: MarkxAnswer[];
  /** The judge's input, exactly as it saw it. */
  evidence: string;
  /** For an entities item: what the extraction named. */
  extracted: { name: string; type: string | null; role: string | null; version: string | null; maker: string | null }[] | null;
  day: string | null;
  split: 'dev' | 'test';
  pool: string | null;
  position: number | null;
  label: { answer: MarkxAnswer; note: string | null; split: string; created_at: string } | null;
  /** Null until the item has a label. */
  verdict: MarkxVerdict | null;
}

export interface MarkxLabelled {
  label: { id: string; answer: MarkxAnswer; note: string | null; split: string };
  verdict: MarkxVerdict;
  next: string | null;
  done: number;
  total: number;
}

export interface MarkxStat {
  labelled: number;
  right: number;
  precision: number | null;
  lo: number | null;
  hi: number | null;
  n_eff: number;
}

export interface MarkxFeaturePrecision {
  feature: MarkxFeature;
  name: string;
  acted: string;
  bar: number | null;
  population: number;
  labelled: number;
  splits: Record<'dev' | 'test' | 'all', { acted: MarkxStat; rejected: MarkxStat }>;
  sweep: { bar: number; dev: MarkxStat; test: MarkxStat }[];
  repick: { bar: number; dev: MarkxStat; test: MarkxStat } | null;
  flags: Partial<Record<MarkxFlag, number>>;
}

export interface MarkxPrecision {
  labeller: string;
  labellers: string[];
  cut: string | null;
  target: number;
  features: MarkxFeaturePrecision[];
  stale: number;
  unsure: number;
  flags: Record<string, Partial<Record<MarkxFlag, number>>>;
}

// ---- 0119 A3: entities (the list, an entity's page, the review queue) ------------------------------------------

export interface MarkxEntityRef {
  id: string;
  name: string;
  type: string | null;
  maker: string | null;
  level: 'thing' | 'family' | 'version' | 'variant' | 'checkpoint';
  version: string | null;
  variant: string | null;
  size: string | null;
  build: string | null;
  status: 'provisional' | 'confirmed' | 'not_entity';
  family: { id: string; name: string } | null;
}

export interface MarkxSurge { day: string; voices: number; posts: number; via: { entity: string; name: string | null; posts: number }[] }

export interface MarkxEntityPost {
  id: string;
  title: string | null;
  source: string | null;
  kind?: string | null;
  at: string | null;
  url?: string | null;
  read?: boolean;
  roles?: string[];
}

export interface MarkxEntityRow extends MarkxEntityRef {
  voices: number;
  posts: number;
  reports: number;
  mentions: number;
  last_at: string;
  last_seen: string | null;
  stories: { id: string; headline: string | null }[];
  newest: MarkxEntityPost[];
  surges: MarkxSurge[];
}

export type MarkxEntityAccuracy = Record<'merges' | 'surges' | 'collisions', string>;

export interface MarkxEntityList {
  window_days: number;
  total: number;
  items: MarkxEntityRow[];
  accuracy: MarkxEntityAccuracy;
  queue: number;
}

export interface MarkxEntityPage {
  entity: MarkxEntityRef;
  asked: string;
  redirected: boolean;
  aliases: string[];
  maker: { id: string; name: string } | null;
  family: { id: string; name: string } | null;
  versions: { id: string; name: string; version: string | null; variant: string | null; level: string }[];
  posts: number;
  voices: number;
  stories: { story: string; headline: string | null; voices: number; newest: string; posts: MarkxEntityPost[] }[];
  loose: MarkxEntityPost[];
  sources: { id: string; name: string | null; kind: string | null; posts: number; reports: number }[];
  surges: MarkxSurge[];
  accuracy: MarkxEntityAccuracy;
  queue: MarkxQueueItem[];
}

export type MarkxEntityAnswer = 'same' | 'other_version' | 'different' | 'not_entity';

export interface MarkxQueueSide extends MarkxEntityRef {
  root: string;
  posts: { id: string; title: string | null; source: string | null; at: string | null; span: string; role: string | null }[];
}

export interface MarkxQueueItem {
  id: string;
  kind: 'alias' | 'collision';
  a: MarkxQueueSide;
  b: MarkxQueueSide | null;
  proposal: 'same' | 'other_version' | 'different' | 'split';
  reason: string;
  confidence: number | null;
  answer: MarkxEntityAnswer | null;
  answered_at: string | null;
  created_at: string;
  evidence: {
    judge?: { relation?: string; confidence?: number; evidence?: string } | null;
    rules?: string[] | null;
    senses?: { m: number[]; what?: string }[] | null;
    mentions?: { n: number; span: string; type: string; maker: string | null }[];
    split_runs?: number | null;
    runs?: number | null;
  };
}

export interface MarkxEntityQueue {
  open: MarkxQueueItem[];
  answered: MarkxQueueItem[];
  merges: { id: string; from: { id: string; name: string | null }; to: { id: string; name: string | null }; by: string;
    automatic: boolean; at: string; undone_at: string | null; confidence: number | null }[];
  counts: { open: number; answered: Partial<Record<MarkxEntityAnswer, number>>; automatic_merges: number; automatic_undone: number };
  accuracy: MarkxEntityAccuracy;
}
