/**
 * The sample sites the studio's frames render (Design Studio D4): a realistic
 * one for the normal states, and the break-ui worst case. Both are built from
 * the fixture files the tests use (`components/reader/fixtures.ts`,
 * `components/ops/fixtures.ts`, `components/connections/fixtures.ts`), so the
 * studio shows what the tests assert. Dates are relative to `now`.
 */
import type { FeedItem, Folder, JobRun, SchedulerConfig, SourceHealthRow } from '../../services/api';
import { feedFixture, feedItem, worstFeedItems } from '../../components/reader/fixtures';
import { healthRow, runReport, worstHealthRows, worstRunReport } from '../../components/ops/fixtures';
import { demoCredentials } from '../../components/connections/fixtures';
import type { Site } from './site';

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function at(now: Date, offsetMs: number): string {
  return new Date(now.getTime() + offsetMs).toISOString();
}

export function folder(id: string, name: string, sort_order: number): Folder {
  return { id, name, sort_order, kind: 'track' };
}

/** The tracks of the realistic site; `f-robotics` has sources but no posts yet (the empty scope). */
export const TRACKS = {
  ai: folder('f-ai', 'AI engineering', 0),
  research: folder('f-research', 'Research papers', 1),
  ar: folder('f-ar', 'AR glasses', 2),
  robotics: folder('f-robotics', 'Robotics', 3),
} as const;

interface NamedSource {
  id: string;
  name: string;
  platform: string;
  kind: string;
  tracks: Folder[];
}

/** The sources posts come from, in the realistic site. */
const NAMED: NamedSource[] = [
  { id: 's-simon', name: 'Simon Willison’s Weblog', platform: 'rss', kind: 'generic_rss', tracks: [TRACKS.ai] },
  { id: 's-anthropic', name: 'Anthropic News', platform: 'rss', kind: 'generic_rss', tracks: [TRACKS.ai] },
  { id: 's-latent', name: 'Latent Space', platform: 'substack', kind: 'substack', tracks: [TRACKS.ai] },
  { id: 's-hn', name: 'Hacker News: Front Page', platform: 'rss', kind: 'generic_rss', tracks: [] },
  { id: 's-llama', name: 'r/LocalLLaMA', platform: 'reddit', kind: 'generic_rss', tracks: [TRACKS.ai] },
  { id: 's-newz', name: 'ai_newz', platform: 'telegram', kind: 'telegram_mtproto', tracks: [TRACKS.ai] },
  { id: 's-arxiv-cl', name: 'arXiv cs.CL', platform: 'rss', kind: 'generic_rss', tracks: [TRACKS.research] },
  { id: 's-arxiv-lg', name: 'arXiv cs.LG', platform: 'rss', kind: 'generic_rss', tracks: [TRACKS.research] },
  { id: 's-papers', name: 'Two Minute Papers', platform: 'youtube', kind: 'youtube_channel', tracks: [TRACKS.research] },
  { id: 's-roadtovr', name: 'Road to VR', platform: 'rss', kind: 'generic_rss', tracks: [TRACKS.ar] },
  { id: 's-uploadvr', name: 'UploadVR', platform: 'rss', kind: 'generic_rss', tracks: [TRACKS.ar] },
  { id: 's-verge', name: 'The Verge', platform: 'rss', kind: 'generic_rss', tracks: [TRACKS.ar] },
  { id: 's-ieee-robots', name: 'IEEE Spectrum Robotics', platform: 'rss', kind: 'generic_rss', tracks: [TRACKS.robotics] },
];

/** What each source posts about, newest first: realistic titles of ordinary length. */
const TITLES: Record<string, string[]> = {
  's-simon': ['Prompt caching is now generally available', 'Notes on running a local model on a laptop for a week', 'A quick look at structured outputs in practice'],
  's-anthropic': ['Introducing Claude Opus 5.5', 'How we evaluate agentic coding at scale'],
  's-latent': ['The state of AI engineering, autumn edition', 'Why evals are the new unit tests'],
  's-hn': ['Show HN: A tiny SQLite extension for vector search', 'The hidden cost of microservices, ten years later', 'Ask HN: What are you reading this month?'],
  's-llama': ['Benchmarks: 70B quantised models on a single consumer GPU', 'Fine-tuning a 3B model for function calling'],
  's-newz': ['New open-weights model tops the multilingual leaderboard', 'A short thread on mixture-of-experts routing'],
  's-arxiv-cl': ['Scaling Laws for Sparse Mixture-of-Experts Language Models', 'Long-context retrieval without positional interpolation'],
  's-arxiv-lg': ['A Simple Baseline for Test-Time Compute', 'On the Stability of Low-Precision Training'],
  's-papers': ['This AI makes realistic cloth in real time'],
  's-roadtovr': ['Hands-on: the lightest AR glasses yet', 'Display makers race to microLED at scale'],
  's-uploadvr': ['Developer kit for the new waveguide glasses ships'],
  's-verge': ['Smart glasses are finally getting good batteries'],
};

function realisticItems(now: Date): FeedItem[] {
  const items: FeedItem[] = [];
  let n = 0;
  for (let round = 0; round < 3; round += 1) {
    for (const source of NAMED) {
      const title = TITLES[source.id]?.[round];
      if (!title) continue;
      n += 1;
      const ageMs = (n * 2.3 + round * 9) * HOUR;
      items.push(feedItem({
        id: `p-${source.id.slice(2)}-${round + 1}`,
        title,
        excerpt: `${title}. A short excerpt of the opening paragraph, as the feed row shows it in comfortable density.`,
        url: `https://example.org/${source.id.slice(2)}/${round + 1}`,
        source_id: source.id,
        source_display_name: source.name,
        platform: source.platform,
        sort_at: at(now, -ageMs),
        published_at: at(now, -ageMs),
        read_at: n % 4 === 0 ? at(now, -HOUR) : null,
        starred_at: n % 7 === 0 ? at(now, -2 * HOUR) : null,
        reading_minutes: source.platform === 'youtube' ? null : 2 + (n % 9),
        duration_seconds: source.platform === 'youtube' ? 5 * 60 + 41 : null,
      }, now));
    }
  }
  return items.sort((a, b) => b.sort_at.localeCompare(a.sort_at));
}

/** Filler names for a dense source list: what a 90-source install looks like. */
const DENSE_NAMES = [
  'Stratechery', 'Import AI', 'The Gradient', 'Ahead of AI', 'Interconnects', 'One Useful Thing', 'Lil’Log',
  'Chip Huyen', 'Eugene Yan', 'Hamel Husain', 'Jay Alammar', 'Sebastian Raschka', 'Andrej Karpathy', 'Distill',
  'BAIR Blog', 'Google DeepMind Blog', 'OpenAI News', 'Meta AI Blog', 'Hugging Face Blog', 'PyTorch Blog',
  'r/MachineLearning', 'r/singularity', 'r/virtualreality', 'r/robotics', 'arXiv cs.CV', 'arXiv cs.RO',
  'arXiv cs.AI', 'arXiv stat.ML', 'Yannic Kilcher', 'AI Explained', 'Machine Learning Street Talk', 'Lex Fridman',
  'MKBHD', 'Tested', 'Linus Tech Tips', 'Mixed News', 'XR Today', 'Auganix', 'The Robot Report', 'Robohub',
];

function denseRows(now: Date): SourceHealthRow[] {
  const trackCycle = [[TRACKS.ai], [TRACKS.research], [TRACKS.ar], [TRACKS.robotics], [], [TRACKS.ai, TRACKS.research]];
  return Array.from({ length: 80 }, (_, i) => {
    const name = DENSE_NAMES[i % DENSE_NAMES.length] + (i >= DENSE_NAMES.length ? ` (${['weekly', 'mirror'][i % 2]})` : '');
    const failing = i % 23 === 5;
    const backoff = i % 29 === 11;
    const disabled = i % 31 === 17;
    return healthRow({
      source_id: `s-dense-${i + 1}`,
      display_name: name,
      platform: i % 9 === 0 ? 'youtube' : i % 7 === 0 ? 'reddit' : 'rss',
      kind: i % 9 === 0 ? 'youtube_channel' : 'generic_rss',
      folders: trackCycle[i % trackCycle.length],
      stored_posts: 20 + ((i * 37) % 900),
      enabled: !disabled,
      ...(disabled ? { status: 'disabled', decision: 'skip_disabled' as const, next_due_at: null } : {}),
      ...(failing ? { status: 'error', decision: 'fetch_retry' as const, last_outcome: 'error', last_error: 'HTTP 404 Not Found', consecutive_failures: 1 } : {}),
      ...(backoff ? {
        status: 'backoff', decision: 'skip_backoff' as const, last_outcome: 'error', last_error: 'HTTP 429 Too Many Requests',
        consecutive_failures: 3, next_retry_at: at(now, 5 * HOUR),
      } : {}),
    }, now);
  });
}

function namedRows(now: Date): SourceHealthRow[] {
  return NAMED.map((source, i) => healthRow({
    source_id: source.id,
    display_name: source.name,
    platform: source.platform,
    kind: source.kind,
    folders: source.tracks.map(({ id, name }) => ({ id, name })),
    stored_posts: 120 + i * 53,
    last_success_at: at(now, -(i + 1) * HOUR),
    ...(source.id === 's-newz' ? {
      status: 'backoff', decision: 'skip_backoff' as const, last_outcome: 'error', consecutive_failures: 2,
      last_error: 'FloodWaitError: A wait of 1260 seconds is required', next_retry_at: at(now, 2 * HOUR),
    } : {}),
  }, now));
}

export function scheduler(now: Date, overrides: Partial<SchedulerConfig> = {}): SchedulerConfig {
  return {
    interval_hours: 24,
    sync_sources_each_cycle: true,
    generate_daily_briefing: false,
    generate_topic_briefing: false,
    ingest_tick_minutes: 60,
    state: { last_tick_at: at(now, -12 * MINUTE), next_tick_at: at(now, 48 * MINUTE) },
    ...overrides,
  };
}

export function ingestionJob(now: Date, report = runReport(), overrides: Partial<JobRun> = {}): JobRun {
  return {
    id: 'job-latest',
    job_type: 'ingestion_run',
    job_label: 'Ingestion run',
    status: report.status === 'success' ? 'completed' : 'failed',
    trigger: 'scheduler',
    message: report.summary ?? null,
    payload: report as unknown as Record<string, unknown>,
    started_at: at(now, -13 * MINUTE),
    finished_at: at(now, -12 * MINUTE),
    ...overrides,
  };
}

/** The realistic site: 13 sources with posts, 80 more in a dense list, four tracks, a healthy scheduler. */
export function normalSite(now: Date = new Date()): Site {
  return {
    config: { analysis_enabled: false },
    items: realisticItems(now),
    folders: Object.values(TRACKS),
    health: [...namedRows(now), ...denseRows(now)],
    credentials: demoCredentials(now),
    jobs: [ingestionJob(now)],
    scheduler: scheduler(now),
  };
}

/** Tracks for ⌘K's worst case: 44, with long, RTL, CJK and emoji names. */
export function manyTracks(): Folder[] {
  const names = [
    'Policy & regulation (EU, DE, FR, NL, PL, CZ) — the long-running reading list nobody finishes',
    'الذكاء الاصطناعي والسياسات العامة',
    '人工智能前沿',
    'Нейросети и машинное обучение',
    '🚀 Launch day',
    'Q',
  ];
  return Array.from({ length: 44 }, (_, i) => folder(
    `f-many-${i + 1}`,
    i < names.length ? names[i] : `Track ${i + 1}: ${['Robotics', 'Chips', 'Energy', 'Biotech'][i % 4]} and adjacent reading`,
    i,
  ));
}

/** The break-ui worst case: the catalog's feed rows, then 1,000 more, the worst sources, many tracks, a partial run. */
export function worstSite(now: Date = new Date()): Site {
  const huge = feedFixture('huge', now).stream.flatMap((pageOfItems) => pageOfItems.items);
  const health = worstHealthRows(now);
  const worstFolders = health.flatMap((row) => row.folders);
  const unique = [...new Map(worstFolders.map((f) => [f.id, f])).values()];
  return {
    config: { analysis_enabled: false },
    items: [...worstFeedItems(now), ...huge],
    folders: [...unique.map((f, i) => folder(f.id, f.name, i)), ...manyTracks()],
    health,
    credentials: demoCredentials(now),
    jobs: [ingestionJob(now, worstRunReport())],
    scheduler: scheduler(now),
  };
}

export { DAY, HOUR, MINUTE, at };
