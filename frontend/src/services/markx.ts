/** Shapes of the Mark X pages' API (/api/markx/*). Types only, so the reader's bundle carries none of it. */

import type { Byline } from '../lib/byline';
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
  byline?: Byline | null;
  kind: string | null;
  at: string | null;
  url?: string | null;
  role?: string;
  name?: string | null;
  why: MarkxWhy | null;
  /** What Mark IX did with it: the News row it is in (and whether that is this row's), or null: none. */
  ix: { row: string; title: string | null; same_row: boolean } | null;
  /** Its Mark X story (the one tap's key), and the owner's standing one-tap answer, if any. */
  story?: string | null;
  flag?: Exclude<MarkxFlag, 'ok'> | null;
  /** Its fold in its Mark X story (null: not read yet, or its story has no group). */
  fold?: MarkxFold | null;
}

/** Duplicates folded: `head` shows; `folded` sits under it; `shown` is a read member outside the group. */
export type MarkxFoldAnswer = 'same' | 'not_same' | 'undo';
export interface MarkxFold {
  state: 'head' | 'folded' | 'shown';
  head: string | null;
  by: 'rule' | 'owner' | null;
  answer: Exclude<MarkxFoldAnswer, 'undo'> | null;
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
  byline?: Byline | null;
  kind: string | null;
  at: string | null;
  check: MarkxCheck | null;
  now_in?: string | null;
  mention: MarkxWhy | null;
}

export interface MarkxRow {
  id: string;
  tag: MarkxTag;
  headline: { text: string; from: 'haiku' | 'lead title' | 'maker title' };
  first_at: string;
  voices: number;
  reports: number;
  shares: number;
  mentions: number;
  score: number;
  story: string | null;
  posts: MarkxLine[];
  folded?: number;
  removed: MarkxLeftOut[];
  surging?: { id: string; name: string; day: string; voices: number }[];
  ix: { id: string; title: string | null; voices?: number; first_at?: string }[];
  /** Its kept rank (significance, fit, coverage, score in 0..1; the lane; why); null: not ranked yet. */
  rank?: MarkxRank | null;
  chain?: MarkxRowChain | null;
}

/** A row's rank as the jobs process kept it. `why`: the significance answer's fields and the fit's parts. */
export interface MarkxRank {
  significance: number | null; fit: number; coverage: number; score: number; notable: boolean;
  why: { event?: string; effect?: number; usable?: string; shipped_in?: string | null; why?: string;
         fit?: { source?: number; entity?: number; thing?: string | null; track?: boolean }; coverage_place?: number;
         analysis?: string[] };
}

export interface MarkxNews {
  run: { id: string; started_at: string; finished_at: string | null; code_version: string | null } | null;
  counts: Partial<Record<MarkxTag, number>> & { rows?: number; ix_rows?: number; gone?: number; untitled?: number };
  items: MarkxRow[];
  gone: { id: string; title: string | null; voices?: number; first_at?: string; posts: MarkxLeftOut[] }[];
  folds?: MarkxFoldScore;
  sections?: MarkxNewsSections | null;
  order?: 'ranked' | 'coverage';
  notable?: string[];
}

/** The newest valid sectioning over the page's rows: groups in the page's order, `new` the rows added since. */
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
    /** v10.44: the event type and its subtype ("model_release" / "build"), from the type guides' readings. */
    event_type?: string | null;
    subtype?: string | null;
    origin?: string | null;
  } | null;
  entities: { name: string; type: string | null; role: string | null; maker: string | null; family: string | null;
    version: string | null; variant: string | null; span: string; entity_id?: string | null;
    /** 'citation' when the citation rule found it; a document's publisher; the guide of the answer. */
    rule?: string | null; by?: string | null; guide?: string;
    /** Its number in the set; the second question's; a new entity (labelled right / wrong); the owner's label. */
    n?: number; q2?: boolean; new?: boolean; label?: 'right' | 'wrong' | null }[];
  entities_guide?: string | null;
  documents?: MarkxPostPanel['entities'];
  sources?: MarkxPostPanel['entities'];
  recommended?: MarkxPostPanel['entities'];
  stories: (MarkxWhy & { id: string; headline: string | null; first_at: string | null; posts: number })[];
  connections: { relation: string; p: number | null; rule: string | null; from: 'post' | 'story'; other_kind: 'post' | 'story';
    other: string; title?: string | null; reason: string | null }[];
  before?: MarkxBefore[];
  before_more?: number;
  before_timeline?: { entity: { id: string; name: string | null }; items: MarkxTimelineEvent[] }[];
}

export type MarkxTimelineKind = 'birth' | 'earlier_name' | 'renamed' | 'release' | 'first_outside' | 'outside' | 'story'
  | 'later' | 'back' | 'analysis' | 'in_story';
export type MarkxStop = 'teaser' | 'preview' | 'launch' | 'availability' | 'update' | 'weights' | 'benchmark' | 'ranking'
  | 'adoption' | 'research' | 'incident' | 'deal' | 'analysis' | 'other';
export interface MarkxTimelineEvent {
  kind: MarkxTimelineKind;
  at: string;
  rank: number;
  top?: boolean;
  post: { id: string; title: string | null; source: string | null; kind: string | null; url: string | null; byline?: Byline | null } | null;
  /** The name it was written as (birth, release), its earlier name (earlier_name), its name now (renamed). */
  name?: string | null;
  also?: MarkxTimelineKind[];
  /** outside: the month's posts and sources; first_outside: found by a post linking back. */
  month?: string; n?: number; sources?: number; linked?: boolean;
  story?: string; mark?: 'x' | 'ix'; headline?: string | null; voices?: number;
  /** story (a stop on the line): what happened to it there, when shown (null: not shown); its share of the members. */
  stop?: MarkxStop | null; stop_by?: 'asked' | 'type'; share?: [number, number];
  on?: string | null;
}
export interface MarkxTimeline {
  items: MarkxTimelineEvent[];
  shown: number;
  /** False when only the top events are listed (the page asks ?all=true for every one). */
  items_all?: boolean;
  total: number;
  earlier: { id: string; name: string | null; names: string[] }[];
}

/** GET /api/markx/posts/{id}/related: the posts nearest a post by its stored vector. `vector`: false when the
 *  post has none yet; `guide`: its reading types it a tutorial or explainer. */
export interface MarkxRelated {
  post_id: string;
  vector: boolean;
  about?: string | null;
  /** `about`: the page the post reports; `loose`: under the floor (the nearest, when few are close). */
  items: { id: string; title: string; source: string; at: string | null; url: string | null; byline?: Byline | null;
    cosine: number; guide: boolean; about?: boolean; loose?: boolean }[];
}

/** GET /api/markx/posts/{id}/discussion (0280): what the post's Hacker News or Lobsters thread adds. */
export interface MarkxDiscussionComment {
  id: string; parent: string | null; author: string | null; score: number | null; at: string | null; text: string;
  url: string;
}
export interface MarkxDiscussion {
  thread: { host: string; name: string; url: string; total: number | null; kept: number | null;
    fetched_at: string | null; next_at: string | null; failed: string | null } | null;
  status: 'none' | 'waiting' | 'fetched' | 'answered';
  wanted: boolean;
  stance: string | null;
  points: { kind: string; text: string; quote: string; comments: string[] }[];
  tools: { name: string; url: string | null; what: string | null; comments: string[] }[];
  comments: Record<string, MarkxDiscussionComment>;
  dropped: number;
  answered_at?: string | null;
}
/** GET /api/markx/discussions?posts=: {post id: {points, total, name}} for the posts with an answered thread. */
export type MarkxDiscussionCounts = Record<string, { points: number; total: number | null; name: string }>;

/** One older post a post connects to. `uncertain`: the judge's alone (label it). */
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
  byline?: Byline | null;
  label: 'right' | 'wrong' | null;
}

export interface MarkxJob {
  running: boolean;
  started_at: string | null;
  stage: string | null;
  stage_at: string | null;
  wanted_at: string | null;
  finished_at: string | null;
  last: { ok?: boolean; error?: string; seconds?: number; skip_next?: string } | null;
  /** Failed runs in a row, shown failing from 3 on, and the next try after its backoff. */
  failures?: number;
  failing?: boolean;
  retry_at?: string | null;
}

export interface MarkxOverview {
  worker: {
    queue: Record<string, Record<string, number>>;
    days: { day: string; calls: number; valid: number; tokens_in: number; tokens_out: number; api_usd: number }[];
    tokens: { calls: number; tokens_in: number; tokens_out: number; paid_usd: number; api_usd: number };
    failed: { kind: string; error: string | null; tasks: number }[];
    invalid: { kind: string; error: string | null; at: string }[];
    workers: { worker: string; last_contact: string | null; leased: number; stale?: boolean }[];
    last_run: { id: string; started_at: string; finished_at: string | null; code_version: string | null;
      counts: Record<string, unknown> | null } | null;
    jobs?: Record<'decide' | 'candidates', MarkxJob>;
  };
  briefing: { day: string | null; briefings: { created_at: string; guide: string | null;
    lines: { text: string; keys: string[]; stories: string[]; rows?: string[] }[] }[] };
  entities: Record<'today' | 'week', { key: string; version: string | null; name: string; type: string | null; posts: number;
    voices: number; examples: { id: string | null; title: string | null; source: string | null; byline?: Byline | null }[] }[]>;
  reading_window: { days: number | null; default: number };
  story_window?: MarkxStoryWindow;
  entities_guide?: MarkxEntitiesGuide;
  entity_invariants?: MarkxEntityInvariants | null;
  holds?: MarkxHolds;
  consumers?: MarkxConsumer[];
}

export interface MarkxConsumer { feature: string; on: boolean; default: boolean; why: string; kinds: string[] }

/** A kind's tasks planned in a day past `per_day` that are not new posts' are held: asked after every other task
 *  (`low`), never (`stopped`), or as any task (`released`). */
export type MarkxHoldState = 'low' | 'stopped' | 'released';
export interface MarkxHolds {
  per_day: number | null;
  default: number;
  holds: { key: string; kind: string; day: string; state: MarkxHoldState; open: number; leased: number;
    est_usd: number | null; reason: string }[];
}

/** What must hold after every entities run. `family_org`: groups holding a product family and an org (`held`:
 * those your own merges hold together), up to 10 listed. */
export interface MarkxEntityInvariants {
  at?: string | null;
  family_org?: { count: number; held: number; clusters: { id: string; name: string | null; family: string[]; org: string[] }[] };
  error?: string;
}

export interface MarkxSamplePrecision { right: number; wrong: number; missed: number; labelled: number; precision: number | null }

/** The story window: the owner's days (null: everything), the window in force, how far back the backfill
 *  reached, and the old stories' precision that keeps "everything". */
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

export interface MarkxEntitiesGuide {
  guide: string;
  chars: number;
  rule: boolean;
  default: string;
  arms: { guide: string; chars: number; rule: boolean; ready: boolean; /** The lab's stated line. */ note?: string }[];
  labels?: MarkxMentionPrecision;
}

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

export interface MarkxSettings {
  reading_window_days: number | null;
  default: number;
  story_window_days?: number | null;
}

// ---- Labels: one tap on a Mark X News member ----

export type MarkxFlag = 'wrong_story' | 'not_about' | 'ok';

// ---- entities (the list, an entity's page, the review queue) ------------------------------------------------

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
  byline?: Byline | null;
  kind?: string | null;
  at: string | null;
  url?: string | null;
  read?: boolean;
  roles?: string[];
  /** False for a story's post that neither names the entity nor is by it. */
  about?: boolean;
  /** The 2-4 sentences around its first mention of the entity, mentions marked (`m`); null when only its title does. */
  context?: { t: string; m?: boolean }[] | null;
}

/** A Mark X story (mark x) or, for a post in none, its Mark IX story (mark ix), with every post, the original
 *  first: the entity's own earliest post (why `by`), else the root (why `origin`). */
export interface MarkxEntityStory {
  story: string;
  headline: string | null;
  voices: number;
  newest: string;
  mark?: 'x' | 'ix';
  first_at?: string;
  posts_total?: number;
  joined?: string[];
  original?: { post: string | null; url: string | null; why: 'release' | 'by' | 'origin' | 'root'; title?: string | null; stored?: string | null };
  posts: MarkxEntityPost[];
}

export interface MarkxEntityBy {
  sources: { id: string; name: string | null; kind: string | null; via: 'voice' | 'owner' }[];
  proposed: { id: string; name: string | null; kind: string | null }[];
  posts: number;
}

export type MarkxHandlePlatform = 'x' | 'github' | 'telegram' | 'bluesky' | 'hf';

export interface MarkxEntityHandles {
  known: { platform: MarkxHandlePlatform; handle: string; via: 'owner' | 'source'; display_name: string | null;
    first_seen: string | null; last_seen: string | null }[];
  posts: number;
  replies: number;
  replies_shown: boolean;
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
  flagged?: number;
}

export interface MarkxEntityLimits { stories?: number; loose?: number }

/** One line of an entity's brief, with the posts it rests on (n: the superscript) and their quotes. */
export interface MarkxBriefLine {
  thing: string;
  text: string;
  /** Shown apart from the text, never glued into it: a definition's stage and maker, a step's detail, a result's
   * figures the line does not give */
  note?: string | null;
  cites: { post: string; n: number; quote?: string | null; quotes?: string[] }[];
  sources: number;
  who?: string[];
}

/** One measure of an entity over time (one name and unit); a `dispute` value differs from another post's for
 * the same date and setting (both shown, never averaged). */
export interface MarkxNumberSeries {
  measure: string;
  unit: string | null;
  money: boolean;
  posts: number;
  disputes: number;
  points: { at: string | null; as_of: string | null; value: number; range_to: number | null; shown: string;
    setting: string | null; post: string; quote: string | null; dispute: boolean; n: number }[];
}

export interface MarkxEntityBrief {
  what: MarkxBriefLine[];
  how: MarkxBriefLine[];
  results: MarkxBriefLine[];
  points: { text: string; cites: number[] }[];
  numbers?: MarkxNumberSeries[];
  as_of: string | null;
  posts: { id: string; n: number; title: string | null; url: string | null; at: string | null; source: string | null }[];
  /** When its posts hold several things of the name, one brief a sense (the three lists above are then empty) */
  senses?: MarkxBriefSense[];
}

export interface MarkxBriefSense {
  label: string | null;
  kind: string | null;
  maker: string | null;
  post_count: number;
  what: MarkxBriefLine[];
  how: MarkxBriefLine[];
  results: MarkxBriefLine[];
  numbers?: MarkxNumberSeries[];
}

export interface MarkxEntityPage {
  brief?: MarkxEntityBrief | null;
  entity: MarkxEntityRef;
  asked: string;
  redirected: boolean;
  aliases: string[];
  maker: { id: string; name: string } | null;
  family: { id: string; name: string } | null;
  versions: { id: string; name: string; version: string | null; variant: string | null; level: string;
    settings?: { id: string; name: string; variant: string | null }[];
    builds?: { id: string; name: string; build: string }[] }[];
  posts: number;
  voices: number;
  stories: MarkxEntityStory[];
  loose: MarkxEntityPost[];
  stories_total?: number;
  loose_total?: number;
  loose_counts?: Record<'report' | 'by' | 'other' | 'mention', number>;
  by?: MarkxEntityBy;
  handles?: MarkxEntityHandles;
  sources: { id: string; name: string | null; kind: string | null; posts: number; reports: number; by?: boolean }[];
  surges: MarkxSurge[];
  accuracy: MarkxEntityAccuracy;
  queue: MarkxQueueItem[];
  published_by?: { id: string; name: string; type: string | null }[];
  published?: { id: string; name: string; type: string | null }[];
  citing?: MarkxEntityPost[];
  citing_total?: number;
  recommending_total?: number;
  published_total?: number;
  recommending?: MarkxEntityPost[];
  original?: MarkxOriginal | null;
  addresses?: { kind: 'paper' | 'code' | 'demo' | 'release' | 'package'; url: string; rule: string }[];
  cited?: { kind: 'paper' | 'code' | 'demo' | 'release'; url: string; rule: string }[];
  /** False when no post's current reading names it; `older` then lists the posts an earlier guide named it in. */
  current?: boolean;
  older?: MarkxOlderPost[];
  rabbit_hole?: MarkxRabbitHole | null;
  components?: { id: string; name: string | null; type: string | null; posts: number }[];
  timeline?: MarkxTimeline | null;
  version_line?: MarkxVersionLine | null;
  relations?: MarkxEntityRelation[];
  relations_total?: number;
}

export interface MarkxVersionStop {
  id: string;
  name: string;
  version: string | null;
  first: string | null;
  posts: number;
  current: boolean;
}
export interface MarkxVersionLine {
  family: { id: string; name: string | null };
  lines: MarkxVersionStop[][];
}
/** A relation between two things, as posts state it (out: this thing -> other; in: other -> this thing). */
export interface MarkxEntityRelation {
  relation: 'based_on' | 'released' | 'acquired' | 'part_of' | 'partnered_with' | 'leads';
  direction: 'out' | 'in';
  other: { id: string; name: string | null; type: string | null };
  since: string | null;
  posts: number;
}

export interface MarkxRabbitHole {
  /** followed / stored: you have it; feed: Follow; page: Watch page; untested: Follow (the feed finder decides). */
  sites: { url: string; host: string; state: 'followed' | 'stored' | 'feed' | 'page' | 'untested' }[];
  works: { id: string; name: string; url: string | null; kind: string | null; stored: boolean; post_id: string | null }[];
  people: { id: string; name: string }[];
  left: { sites: number; works: number };
  works_total?: number;
  missing?: number;
}

export interface MarkxOriginal {
  url: string;
  kind: 'paper' | 'release';
  /** How it was found: identifier (an arXiv id, a DOI), title, maker (its maker's own site), lookup. */
  rule: string;
  post: { id: string; title: string | null; collected: boolean } | null;
  asked: { outcome: string; at: string } | null;
}

export interface MarkxOlderPost {
  id: string;
  title: string | null;
  source: string | null;
  byline?: Byline | null;
  at: string | null;
  url: string | null;
  guide: string;
  span: string;
  now: { id: string | null; name: string; type: string | null }[];
}

export type MarkxEntityAnswer = 'same' | 'other_version' | 'different' | 'not_entity';

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
  posts: { id: string; title: string | null; source: string | null; byline?: Byline | null; at: string | null; span: string; role: string | null }[];
  group?: MarkxEntityGroup;
}

/** What `same` would do to a product family and an org: only the two names join (`only_names`), each `apart`
 * group staying apart `from` the other side; `needs_choice`: it can't (your earlier merge, or family vs org names). */
export interface MarkxQueueJoin {
  mixes: boolean;
  only_names: boolean;
  apart: { name: string; from: string }[];
  needs_choice: boolean;
}

export interface MarkxQueueItem {
  id: string;
  kind: 'alias' | 'collision' | 'rename' | 'handle';  // rename: a is the older name, b the newer; handle: a only
  a: MarkxQueueSide;
  b: MarkxQueueSide | null;
  proposal: 'same' | 'other_version' | 'different' | 'split';
  reason: string;
  confidence: number | null;
  answer: MarkxEntityAnswer | null;
  answered_at: string | null;
  created_at: string;
  join?: MarkxQueueJoin | null;
  opinion?: { by: 'haiku'; relation?: string | null; confidence: number | null; rules: string[] }
    | { by: 'rule'; rules: string[] } | null;
  /** Haiku's answer was about posts a side no longer holds, or that can't be found on it now: not shown; the
   *  next run closes the item and asks again. */
  void?: 'posts' | 'unmatched' | 'head' | null;
  flag?: { at: string; by: string; note: string | null } | null;
  evidence: {
    judge?: { relation?: string; confidence?: number; evidence?: string } | null;
    rules?: string[] | null;
    senses?: { m: number[]; what?: string }[] | null;
    mentions?: { n: number; span: string; type: string; maker: string | null }[];
    split_runs?: number | null;
    runs?: number | null;
    asked_because?: string | null;
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
  counts: { open: number; answered: Partial<Record<MarkxEntityAnswer, number>>; automatic_merges: number; automatic_undone: number;
    flagged?: number };
  accuracy: MarkxEntityAccuracy;
  next_offset?: number | null;
  view?: MarkxQueueView;
}

export type MarkxQueueView = 'flagged' | 'all';

// ---- perspectives inside a story and the story sheet ------------------------------------------------------------

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
  byline?: Byline | null;
  kind: string | null;
  at: string;
  url: string | null;
}

export interface MarkxStoryThing {
  id: string;
  name: string;
  type: string | null;
  maker: string | null;
  maker_id: string | null;
  role: string;
  posts: number;
}

export interface MarkxStoryView {
  story: { id: string; headline: string | null; first_at: string | null };
  things?: MarkxStoryThing[];
  judged: boolean;
  sheet: MarkxSheet | null;
  header: { text: string; source: 'lab' | 'owner'; labels: number };
  members: MarkxPerspectiveLine[];
  counts: { members: number; worth: number; same: number; copies: number; unjudged: number };
  posts: Record<string, MarkxStoryPost>;
  roundups?: { post: string; source: string | null; title: string | null; n: number; item: string }[];
  chain?: MarkxChain;
}

export type MarkxChainRelation = 'same_release' | 'same_event' | 'follows_up' | 'development' | 'reaction' | 'builds_on';

export interface MarkxChainLink {
  story: string;
  /** the story this link hangs on (the page's story at depth 1, a nearer link's beyond). */
  via: string;
  relation: MarkxChainRelation;
  reason: string | null;
  depth: number;
  headline: string | null;
  first_at: string | null;
}

export interface MarkxChain {
  before: MarkxChainLink[];
  after: MarkxChainLink[];
  before_more: number;
  after_more: number;
  as_of: string | null;
}

export interface MarkxRowChainLink {
  story: string;
  relation: MarkxChainRelation;
  reason: string | null;
  headline: string | null;
  first_at: string | null;
}

export interface MarkxRowChain {
  before: MarkxRowChainLink[];
  after: MarkxRowChainLink[];
  before_more: number;
  after_more: number;
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
