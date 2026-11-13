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
  /** 0127: its fold in its Mark X story (null: not read under read-v3 yet, or its story has no group). */
  fold?: MarkxFold | null;
}

/** 0127: duplicates folded. `head` shows; `folded` sits under it; `shown` is a read member outside the group. */
export type MarkxFoldAnswer = 'same' | 'not_same' | 'undo';
export interface MarkxFold {
  state: 'head' | 'folded' | 'shown';
  head: string | null;
  /** Who folded it: the rule or the owner's answer. */
  by: 'rule' | 'owner' | null;
  /** The owner's standing answer, if any. */
  answer: Exclude<MarkxFoldAnswer, 'undo'> | null;
  /** What the rule says: folded, head or shown. */
  rule: 'folded' | 'head' | 'shown';
  count: number | null;
}
export interface MarkxFoldScore {
  answered: number;
  folded: { n: number; right: number; precision: number | null; interval: [number, number] | null };
  missed: number;
  shown_right?: number;
  lab: { f1: number; single_runs: number[]; set: string; date: string };
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
  /** 0127: how many of its posts are folded under a head. */
  folded?: number;
  removed: MarkxLeftOut[];
  /** 0119 A2: the entities its posts make surge (3+ voices that day). */
  surging?: { id: string; name: string; day: string; voices: number }[];
  ix: { id: string; title: string | null; voices?: number; first_at?: string }[];
}

export interface MarkxNews {
  run: { id: string; started_at: string; finished_at: string | null; code_version: string | null } | null;
  counts: Partial<Record<MarkxTag, number>> & { rows?: number; ix_rows?: number; gone?: number; untitled?: number };
  items: MarkxRow[];
  gone: { id: string; title: string | null; voices?: number; first_at?: string; posts: MarkxLeftOut[] }[];
  /** 0127: the fold's count (the lab's F1 and the owner's labels). */
  folds?: MarkxFoldScore;
  /** 0174: Haiku's titled sections over the rows shown (null: no run yet). */
  sections?: MarkxNewsSections | null;
}

/** 0174: the newest valid sectioning over the page's rows: groups in the page's order, `new` the rows added since. */
export interface MarkxNewsSections {
  at: string | null;
  pending: boolean;
  groups: { title: string; rows: string[] }[];
  new: string[];
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
    version: string | null; variant: string | null; span: string; entity_id?: string | null;
    /** 0133: 'citation' when the citation rule found it; a document's publisher; the guide of the answer. */
    rule?: string | null; by?: string | null; guide?: string;
    /** 0133 v4.2: its number in the set; the second question's; a new entity (labelled right / wrong); the owner's label. */
    n?: number; q2?: boolean; new?: boolean; label?: 'right' | 'wrong' | null }[];
  /** 0133: the guide of the post's current entities (its newest valid answer); its documents and cited sources. */
  entities_guide?: string | null;
  documents?: MarkxPostPanel['entities'];
  sources?: MarkxPostPanel['entities'];
  recommended?: MarkxPostPanel['entities'];
  stories: (MarkxWhy & { id: string; headline: string | null; first_at: string | null; posts: number })[];
  connections: { relation: string; p: number | null; rule: string | null; from: 'post' | 'story'; other_kind: 'post' | 'story';
    other: string; title?: string | null; reason: string | null }[];
  /** 0131: the older posts this post connects to (authors' links, entity identity, the judge), oldest first, 10 at most. */
  before?: MarkxBefore[];
  /** 0131: how many more the list leaves out. */
  before_more?: number;
  /** 0165 D: the post's subjects' previous events from their timelines (birth, last release, first outside mention). */
  before_timeline?: { entity: { id: string; name: string | null }; items: MarkxTimelineEvent[] }[];
}

/** 0165 C: one dated line of an entity's timeline, and why it is on the line. */
export type MarkxTimelineKind = 'birth' | 'earlier_name' | 'renamed' | 'release' | 'first_outside' | 'outside' | 'story'
  | 'later' | 'back';
export interface MarkxTimelineEvent {
  kind: MarkxTimelineKind;
  at: string;
  rank: number;
  /** One of the 8 most important (shown before "all"). */
  top?: boolean;
  post: { id: string; title: string | null; source: string | null; kind: string | null; url: string | null } | null;
  /** The name it was written as (birth, release), its earlier name (earlier_name), its name now (renamed). */
  name?: string | null;
  /** Other reasons the same post is on the line (the birth may be the maker's release, the first outside mention). */
  also?: MarkxTimelineKind[];
  /** outside: the month's posts and sources; first_outside: found by a post linking back. */
  month?: string; n?: number; sources?: number; linked?: boolean;
  /** story, later, back. */
  story?: string; mark?: 'x' | 'ix'; headline?: string | null; voices?: number;
}
export interface MarkxTimeline {
  items: MarkxTimelineEvent[];
  shown: number;
  total: number;
  earlier: { id: string; name: string | null; names: string[] }[];
}

/** 0131: one older post a post connects to (Stalker's first edges). `uncertain`: the judge's alone (label it). */
export interface MarkxBefore {
  post_id: string;
  relation: string;
  rule: 'author_link_other' | 'author_link_own' | 'entity_next_version' | null;
  p: number | null;
  reason: string | null;
  uncertain: boolean;
  at: string | null;
  title: string | null;
  source: string | null;
  label: 'right' | 'wrong' | null;
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
  /** 0144: how far back the decision run makes Mark X's own stories (absent from an older API). */
  story_window?: MarkxStoryWindow;
  /** 0133: the entities guide switch (absent from an older API). */
  entities_guide?: MarkxEntitiesGuide;
  /** 0164 C: the last run's entity invariants (absent from an older API; null before a run counted them). */
  entity_invariants?: MarkxEntityInvariants | null;
}

/** 0164 C: what must hold after every entities run. `family_org`: the groups holding a product family and an org
 * (0 after the repair; `held`: those your own merges hold together), up to 10 listed. */
export interface MarkxEntityInvariants {
  at?: string | null;
  family_org?: { count: number; held: number; clusters: { id: string; name: string | null; family: string[]; org: string[] }[] };
  error?: string;
}

/** 0144 C: the labelled old stories' answers (first post older than 30 days when offered) and the recent ones'. */
export interface MarkxSamplePrecision { right: number; wrong: number; missed: number; labelled: number; precision: number | null }

/** 0144 A: the story window: the owner's days (null: everything), the window in force (after the fallback), how far
 *  back the backfill reached, and the old stories' precision that keeps "everything". */
export interface MarkxStoryWindow {
  days: number | null;
  default: number;
  in_force: number | null;
  fallback: { days: number; why: string } | null;
  run_days: number;
  reached: string | null;
  precision: Record<'old' | 'recent', MarkxSamplePrecision>;
  keep: number;
  min_labels: number;
}

/** 0133: which guide new entities tasks are asked under; `ready` false while a guide is the lab's placeholder. */
export interface MarkxEntitiesGuide {
  guide: string;
  chars: number;
  rule: boolean;
  default: string;
  arms: { guide: string; chars: number; rule: boolean; ready: boolean; /** 0133 v4.2: the lab's stated line. */ note?: string }[];
  /** 0133 v4.2: ent-v4.2's running precision on its new entities, from the owner's labels (absent from an older API). */
  labels?: MarkxMentionPrecision;
}

/** 0133 v4.2: the owner's labels on a guide's new entities: all, and the second question's alone (Wilson 95%). */
export interface MarkxPrecisionStat {
  labelled: number;
  right: number;
  precision: number | null;
  low: number | null;
  high: number | null;
}

export interface MarkxMentionPrecision extends MarkxPrecisionStat {
  guide: string;
  q2: MarkxPrecisionStat;
  lab: string;
  leave_at: { labelled: number; low: number };
}

/** POST /api/markx/settings/reading-window's answer. */
export interface MarkxSettings {
  reading_window_days: number | null;
  default: number;
  /** 0144: the story window's days (null: everything). */
  story_window_days?: number | null;
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
  /** 0182: the newest decision run's queue is not built yet (insight-ingestion builds it after each run); absent from an older API. */
  building?: boolean;
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
  /** 0182: as MarkxLabelQueue.building. */
  building?: boolean;
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
  /** 0144: false for a story's post that neither names the entity nor is by it. */
  about?: boolean;
}

/** 0144 B2-B3: a Mark X story (mark x) or, for a post in none, its Mark IX story (mark ix), with every post, the
 *  original first: the entity's own earliest post (why `by`), else the root (Mark IX's outside page: why `origin`). */
export interface MarkxEntityStory {
  story: string;
  headline: string | null;
  voices: number;
  newest: string;
  mark?: 'x' | 'ix';
  first_at?: string;
  original?: { post: string | null; url: string | null; why: 'by' | 'origin' | 'root'; title?: string | null; stored?: string | null };
  posts: MarkxEntityPost[];
}

/** 0144 B1: the sources that are the entity (through its voice, or the owner's yes), and those offered. */
export interface MarkxEntityBy {
  sources: { id: string; name: string | null; kind: string | null; via: 'voice' | 'owner' }[];
  proposed: { id: string; name: string | null; kind: string | null }[];
  posts: number;
}

/** 0168: the platforms a handle is keyed by (the same handle on two platforms is two accounts). */
export type MarkxHandlePlatform = 'x' | 'github' | 'telegram' | 'bluesky' | 'hf';

/** 0168: an entity's known handles (the owner's yes, its own sources' accounts) and the posts citing them. */
export interface MarkxEntityHandles {
  known: { platform: MarkxHandlePlatform; handle: string; via: 'owner' | 'source'; display_name: string | null;
    first_seen: string | null; last_seen: string | null }[];
  posts: number;
  /** Replies to them, hidden unless asked (`replies_shown`). */
  replies: number;
  replies_shown: boolean;
}

export type MarkxSampleAnswer = 'right' | 'wrong' | 'missed';

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
  stories: MarkxEntityStory[];
  loose: MarkxEntityPost[];
  /** 0144 B4: the loose posts by role: subject or actor, by, venue / source / recommended, mentions. */
  loose_counts?: Record<'report' | 'by' | 'other' | 'mention', number>;
  /** 0144 B1 (absent from an older API). */
  by?: MarkxEntityBy;
  /** 0168 (absent from an older API). */
  handles?: MarkxEntityHandles;
  /** 0144 C: old stories offered to label here (10 a page, 30 a day). */
  sample?: { story: string; first_at: string | null; answer: MarkxSampleAnswer | null }[];
  sources: { id: string; name: string | null; kind: string | null; posts: number; reports: number; by?: boolean }[];
  surges: MarkxSurge[];
  accuracy: MarkxEntityAccuracy;
  queue: MarkxQueueItem[];
  /** 0133: who published it, what it published, the posts citing it as evidence and those recommending it. */
  published_by?: { id: string; name: string; type: string | null }[];
  published?: { id: string; name: string; type: string | null }[];
  citing?: MarkxEntityPost[];
  recommending?: MarkxEntityPost[];
  /** 0138 A: its original (a paper or release page its posts link, found by rules), stored or not, and its other pages. */
  original?: MarkxOriginal | null;
  addresses?: { kind: 'paper' | 'code' | 'demo' | 'release' | 'package'; url: string; rule: string }[];
  /** 0138: false when no post's current reading names it; `older` then lists the posts an earlier guide named it in. */
  current?: boolean;
  older?: MarkxOlderPost[];
  /** 0138 E3: an org, person or document with 2+ works or 10+ posts: its sites, works and people. */
  rabbit_hole?: MarkxRabbitHole | null;
  /** 0165 A: a product's components (things under it), with their posts. */
  components?: { id: string; name: string | null; type: string | null; posts: number }[];
  /** 0165 C: its timeline (null under two dated events). */
  timeline?: MarkxTimeline | null;
}

export interface MarkxRabbitHole {
  /** followed / stored: you have it; feed: Follow; page: Watch page; untested: Follow (the feed finder decides). */
  sites: { url: string; host: string; state: 'followed' | 'stored' | 'feed' | 'page' | 'untested' }[];
  works: { id: string; name: string; url: string | null; kind: string | null; stored: boolean; post_id: string | null }[];
  people: { id: string; name: string }[];
  left: { sites: number; works: number };
}

export interface MarkxOriginal {
  url: string;
  kind: 'paper' | 'release';
  /** How it was found: identifier (an arXiv id, a DOI), title, maker (its maker's own site), lookup. */
  rule: string;
  /** The stored post at it; `collected` when Collect originals stored it. */
  post: { id: string; title: string | null; collected: boolean } | null;
  asked: { outcome: string; at: string } | null;
}

export interface MarkxOlderPost {
  id: string;
  title: string | null;
  source: string | null;
  at: string | null;
  url: string | null;
  guide: string;
  span: string;
  /** What the post's current reading names as its subjects instead. */
  now: { id: string | null; name: string; type: string | null }[];
}

export type MarkxEntityAnswer = 'same' | 'other_version' | 'different' | 'not_entity';

/** 0164 A: the group (cluster) a queue item's name is in: its shown name and type, its names, its sides. */
export interface MarkxEntityGroup {
  root: string;
  name: string | null;
  type: string | null;
  size: number;
  names: string[];
  more: number;
  sides: { family: string[]; org: string[] };
}

export interface MarkxQueueSide extends MarkxEntityRef {
  root: string;
  posts: { id: string; title: string | null; source: string | null; at: string | null; span: string; role: string | null }[];
  group?: MarkxEntityGroup;
}

/** 0164 A: what `same` would do when it would put a product family and an org in one group: only the two names
 * join (`only_names`), each `apart` group staying apart `from` the other side; `needs_choice`: it can't (your own
 * earlier merge holds a name there, or the names are a family's and an org's). */
export interface MarkxQueueJoin {
  mixes: boolean;
  only_names: boolean;
  apart: { name: string; from: string }[];
  needs_choice: boolean;
}

export interface MarkxQueueItem {
  id: string;
  kind: 'alias' | 'collision' | 'rename' | 'handle';   // 0165 B: rename (a: the older name, b: the newer); 0168: handle (a only)
  a: MarkxQueueSide;
  b: MarkxQueueSide | null;
  proposal: 'same' | 'other_version' | 'different' | 'split';
  reason: string;
  confidence: number | null;
  answer: MarkxEntityAnswer | null;
  answered_at: string | null;
  created_at: string;
  join?: MarkxQueueJoin | null;
  evidence: {
    judge?: { relation?: string; confidence?: number; evidence?: string } | null;
    rules?: string[] | null;
    senses?: { m: number[]; what?: string }[] | null;
    mentions?: { n: number; span: string; type: string; maker: string | null }[];
    split_runs?: number | null;
    runs?: number | null;
    /** 0165 B: why a rename was asked (a shared address, the new post naming the old one). */
    asked_because?: string | null;
    /** 0168: a handle question's (or a handle-named alias's) "Name (@handle)" pairs. */
    platform?: MarkxHandlePlatform;
    handle?: string;
    display?: string | null;
    pairs?: number;
    total?: number;
    first?: string | null;
    last?: string | null;
    alias_of?: string[] | null;
    named_by_handle?: boolean | null;
  };
}

export interface MarkxEntityQueue {
  open: MarkxQueueItem[];
  answered: MarkxQueueItem[];
  merges: { id: string; from: { id: string; name: string | null }; to: { id: string; name: string | null }; by: string;
    automatic: boolean; at: string; undone_at: string | null; confidence: number | null; kind?: 'same' | 'rename' }[];
  counts: { open: number; answered: Partial<Record<MarkxEntityAnswer, number>>; automatic_merges: number; automatic_undone: number };
  accuracy: MarkxEntityAccuracy;
}

// ---- perspectives inside a story and the story sheet (issue 0119 B6-B7) ----------------------------------------

export type MarkxPerspectiveLabel = 'original' | 'new_facts' | 'opinion' | 'same' | 'not_this_story';
export type MarkxPerspectiveAnswer = 'right' | 'wrong' | MarkxPerspectiveLabel;
export type MarkxFactAnswer = 'right' | 'not_new' | 'not_true' | 'not_about';

export interface MarkxFact {
  index: number;
  fact: string;
  span: string | null;
  correction: boolean | null;
  about_story?: boolean | null;
  mine: MarkxFactAnswer | null;
}

export interface MarkxPerspectiveLine {
  post: string;
  member: boolean;
  label: MarkxPerspectiveLabel | null;   // null: not judged (yet)
  sign: string | null;
  by: string | null;                     // 'haiku' or 'code:<rule>'
  worth: boolean | null;
  before: boolean;
  point: string | null;
  claims: { claim: string; span: string | null }[];
  copies: string[];
  facts: MarkxFact[];
  mine: { answer: MarkxPerspectiveAnswer; shown: MarkxPerspectiveLabel | null } | null;
}

export interface MarkxSheetFact {
  fact: string;
  posts: string[];
  sources: string[];
  correction: boolean;
  before: boolean;
  lines: number[];
}

export interface MarkxSheet {
  subject: string;
  original: { post: string; is_original: boolean; title: string | null; source: string | null; at: string; text: string;
    also: { post: string; source: string | null; title: string }[] };
  source_page: string | null;
  new_facts: MarkxSheetFact[];
  before: { facts: MarkxSheetFact[]; claims: { claim: string; post: string; source: string | null }[] };
  claims: { claim: string; post: string; source: string | null }[];
  opinions: { point: string | null; post: string; source: string | null }[];
  same: number;
  copies: number;
  related: { post: string; source: string | null; title: string }[];
  lines: number;
  merged: number;
  at?: string;
}

export interface MarkxStoryPost {
  id: string;
  title: string | null;
  source: string | null;
  kind: string | null;
  at: string;
  url: string | null;
}

export interface MarkxStoryView {
  story: { id: string; headline: string | null; first_at: string | null };
  judged: boolean;
  sheet: MarkxSheet | null;
  header: { text: string; source: 'lab' | 'owner'; labels: number };
  members: MarkxPerspectiveLine[];
  counts: { members: number; worth: number; same: number; copies: number; unjudged: number };
  posts: Record<string, MarkxStoryPost>;
  /** 0181: the round-ups carrying a member as an item (display only, never a voice). */
  roundups?: { post: string; source: string | null; title: string | null; n: number; item: string }[];
}

export interface MarkxRate {
  k: number;
  n: number;
  p: number | null;
  lo: number;
  hi: number;
}

export interface MarkxPerspectiveAccuracy {
  labels: number;
  fact_labels: number;
  lab: { worth: number; four: number; new_facts: number; date: string };
  four: MarkxRate;
  worth: MarkxRate;
  new_facts: MarkxRate;
  per_label: Partial<Record<MarkxPerspectiveLabel, MarkxRate>>;
  facts: MarkxRate & { answers: Partial<Record<MarkxFactAnswer, number>> };
  errors: Record<string, number>;
  source: 'lab' | 'owner';
  text: string;
}
