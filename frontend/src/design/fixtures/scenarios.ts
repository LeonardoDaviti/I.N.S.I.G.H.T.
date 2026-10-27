/**
 * The state matrix (Design Studio D4, D5): for each page doc and each state its
 * `meta` block lists, the app URL a frame opens and the fixture routes that
 * answer its API calls. The coverage test fails when a doc lists a state that
 * has no scenario here. A few states beyond the docs' lists (the reader's track
 * and source scopes, keyboard help, a dialog) exist for the Wall.
 */
import type { FixtureRoute } from '../frame/transport';
import { pending, serverError } from '../frame/transport';
import type { FrameDriver } from '../frame/driver';
import type { CredentialsResponse } from '../../services/api';
import { credentials, publicView, substackView, telegramView } from '../../components/connections/fixtures';
import { runReport } from '../../components/ops/fixtures';
import { siteRoutes, type Site } from './site';
import { HOUR, MINUTE, TRACKS, at, sourceId, ingestionJob, manyTracks, normalSite, scheduler, worstSite } from './sites';
import { postStateDetail } from './posts';

export interface FrameScenario {
  page: string;
  state: string;
  /** One line for the studio: what this state shows. */
  label: string;
  /** The app URL the frame renders, e.g. `/read/folder/<id>`. */
  url: string;
  /** The routes that answer this state's API calls, first match wins. */
  routes: (now: Date) => FixtureRoute[];
  /** The viewport width this state is about (the narrow top bar), when it has one. */
  width?: number;
  /** Steps after the page renders, for states no URL reaches. */
  setup?: (frame: FrameDriver) => Promise<void>;
  /** False for states the Wall uses that no page doc lists. */
  documented: boolean;
}

/** The break-ui error: a 500 whose message is far longer than a line. */
export const LONG_ERROR = 'Internal Server Error: psycopg.OperationalError: connection to server at "db" (172.18.0.3), '
  + 'port 5432 failed: FATAL: remaining connection slots are reserved for non-replication superuser connections. '
  + 'The request was retried 3 times over 12.4 seconds before giving up; see the backend log for the full traceback.';

const site = (build: (now: Date) => Site) => (now: Date) => siteRoutes(build(now));
/** Every read waits forever. */
const loading = () => [{ path: /^\/api\//, respond: () => pending() }];
/** Every read fails with the long message. */
const failing = () => [{ path: /^\/api\//, respond: () => serverError(LONG_ERROR) }];

function withSite(now: Date, change: (site: Site) => Site): FixtureRoute[] {
  return siteRoutes(change(normalSite(now)));
}

function postRoutes(state: string) {
  return (now: Date) => {
    const detail = postStateDetail(state, now);
    return [{ path: '/api/posts/item/:postId', respond: () => detail }, ...siteRoutes(normalSite(now))];
  };
}

function connections(build: (now: Date) => CredentialsResponse) {
  return (now: Date) => withSite(now, (s) => ({ ...s, credentials: build(now) }));
}

const SET = { set: true, last4: 'a3f9', source: 'db' as const, updated_at: '2026-10-10T08:00:00Z' };
const tested = (now: Date, ok: boolean, message: string) => ({ ok, message, tested_at: at(now, -10 * MINUTE) });

const SCENARIOS: FrameScenario[] = [
  // ---- reader ----
  { page: 'reader', state: 'normal', label: 'Unread rows under day headers', url: '/', routes: site(normalSite), documented: true },
  {
    page: 'reader', state: 'empty', label: 'Nothing unread: all caught up', url: '/', documented: true,
    routes: (now) => withSite(now, (s) => ({ ...s, items: s.items.map((item) => ({ ...item, read_at: item.read_at ?? at(now, -HOUR) })) })),
  },
  { page: 'reader', state: 'empty-scope', label: 'A track with no posts yet', url: `/read/folder/${TRACKS.robotics.id}`, routes: site(normalSite), documented: true },
  { page: 'reader', state: 'loading', label: 'Skeleton rows; the rail says Loading…', url: '/', routes: loading, documented: true },
  { page: 'reader', state: 'error', label: 'Could not load the feed, with Retry', url: '/', routes: failing, documented: true },
  { page: 'reader', state: 'worst', label: 'Long, unbroken, RTL and CJK titles; 1,000+ items', url: '/', routes: site(worstSite), documented: true },
  { page: 'reader', state: 'track', label: 'Scoped to one track', url: `/read/folder/${TRACKS.ai.id}`, routes: site(normalSite), documented: false },
  { page: 'reader', state: 'source', label: 'Scoped to one source', url: `/read/source/${sourceId('s-simon')}`, routes: site(normalSite), documented: false },

  // ---- post ----
  { page: 'post', state: 'article', label: 'A text post: byline, title, prose', url: '/posts/p-article', routes: postRoutes('article'), documented: true },
  { page: 'post', state: 'media', label: 'Video, then images of three shapes', url: '/posts/p-media', routes: postRoutes('media'), documented: true },
  { page: 'post', state: 'long-title', label: 'A title of several lines and the worst body', url: '/posts/p-long-title', routes: postRoutes('long-title'), documented: true },
  { page: 'post', state: 'headings', label: 'h1–h6, lists, quote, table and code', url: '/posts/p-headings', routes: postRoutes('headings'), documented: true },
  { page: 'post', state: 'missing-title', label: 'A Telegram post with no title', url: '/posts/p-missing-title', routes: postRoutes('missing-title'), documented: true },
  { page: 'post', state: 'loading', label: 'The skeleton in the post column', url: '/posts/p-article', routes: loading, documented: true },
  { page: 'post', state: 'error', label: 'The post failed to load', url: '/posts/p-article', routes: failing, documented: true },

  // ---- sources ----
  { page: 'sources', state: 'dense', label: '93 sources in one list, some failing or in backoff', url: '/settings/sources', routes: site(normalSite), documented: true },
  {
    page: 'sources', state: 'search-no-hits', label: 'No sources match', url: '/settings/sources?q=quantum%20knitting', routes: site(normalSite), documented: true,
  },
  {
    page: 'sources', state: 'bulk-selection', label: 'Three rows checked, the bulk bar showing', url: '/settings/sources', routes: site(normalSite), documented: true,
    setup: async (frame) => {
      for (const slug of ['s-simon', 's-anthropic', 's-latent']) await frame.click(`li[data-source-id="${sourceId(slug)}"] input[type="checkbox"]`);
    },
  },
  { page: 'sources', state: 'source-sheet', label: 'The source sheet, open', url: `/settings/sources?source=${sourceId('s-newz')}`, routes: site(normalSite), documented: true },
  {
    page: 'sources', state: 'connections-set', label: 'Every provider working', url: '/settings/sources?tab=connections', documented: true,
    routes: connections((now) => credentials(
      substackView({ test: tested(now, true, 'Read the newest paid post of The Kaitchup in full') }, SET),
      telegramView({ apiSet: true, session: true, test: tested(now, true, 'Signed in as @owner') }),
      publicView('reddit'),
      publicView('youtube'),
    )),
  },
  {
    page: 'sources', state: 'connections-unset', label: 'Nothing set', url: '/settings/sources?tab=connections', documented: true,
    routes: connections(() => credentials(substackView(), telegramView(), publicView('reddit'), publicView('youtube'))),
  },
  {
    page: 'sources', state: 'connections-expired', label: 'A failing test and a lapsed session', url: '/settings/sources?tab=connections', documented: true,
    routes: connections((now) => credentials(
      substackView({ test: tested(now, false, 'substack.com answered 401 Unauthorized: the session cookie has expired; copy a fresh substack.sid') }, SET),
      telegramView({ apiSet: true, session: false }),
      publicView('reddit'),
      publicView('youtube'),
    )),
  },
  {
    page: 'sources', state: 'ingestion-partial-failure', label: 'The last run: some sources failed', url: '/settings/sources?tab=ingestion', documented: true,
    routes: (now) => withSite(now, (s) => ({ ...worstSiteJobs(s, now) })),
  },
  {
    page: 'sources', state: 'scheduler-stopped', label: 'The scheduler has not ticked for 9 hours', url: '/settings/sources?tab=ingestion', documented: true,
    routes: (now) => withSite(now, (s) => ({
      ...s,
      scheduler: scheduler(now, { state: { last_tick_at: at(now, -9 * HOUR), next_tick_at: at(now, -8 * HOUR) } }),
    })),
  },

  {
    page: 'sources', state: 'ingestion-archive', label: 'Archive: the catalog, one channel picked for a backfill',
    url: `/settings/sources?tab=ingestion&sub=archive&source=${sourceId('s-papers')}`, routes: site(normalSite), documented: true,
  },
  { page: 'sources', state: 'ingestion-logs', label: 'Logs: the application log tail', url: '/settings/sources?tab=ingestion&sub=logs', routes: site(normalSite), documented: true },
  { page: 'sources', state: 'ingestion', label: 'The ingestion tab: scheduler and the last run', url: '/settings/sources?tab=ingestion', routes: site(normalSite), documented: false },

  // ---- shell ----
  {
    page: 'shell', state: 'switcher', label: '⌘K open over the feed', url: '/', routes: site(normalSite), documented: false,
    setup: async (frame) => {
      await frame.find('a', /Prompt caching/);
      await frame.press({ key: 'k', ctrlKey: true });
      await frame.find('[role="listbox"]');
    },
  },
  {
    page: 'shell', state: 'switcher-many-tracks', label: '⌘K with 44 tracks, long and RTL names', url: '/', documented: true,
    routes: (now) => withSite(now, (s) => ({ ...s, folders: [...s.folders, ...manyTracks()] })),
    setup: async (frame) => {
      await frame.find('a', /Prompt caching/);
      await frame.press({ key: 'k', ctrlKey: true });
      await frame.find('[role="listbox"]');
    },
  },
  { page: 'shell', state: 'narrow-topbar', label: 'The top bar at 320px', url: '/', width: 320, routes: site(normalSite), documented: true },
  {
    page: 'shell', state: 'keyboard-help', label: 'Keyboard help (?) over the feed', url: '/', routes: site(normalSite), documented: false,
    setup: async (frame) => {
      await frame.find('a', /Prompt caching/);
      await frame.press({ key: '?', shiftKey: true });
      await frame.find('[role="dialog"]');
    },
  },
  // ---- blog ----
  { page: 'blog', state: 'index', label: 'Every post, newest first', url: '/blog', routes: site(normalSite), documented: true },
  { page: 'blog', state: 'article', label: 'A post with figures, code and the quiz', url: '/blog/junior-to-senior', routes: site(normalSite), documented: true },
  { page: 'blog', state: 'unknown', label: 'An unknown slug lands on the list', url: '/blog/no-such-post', routes: site(normalSite), documented: true },
  {
    page: 'shell', state: 'dialog', label: 'A dialog open: Add source', url: '/settings/sources', routes: site(normalSite), documented: false,
    setup: async (frame) => {
      await frame.click('button', /Add source/);
      await frame.find('[role="dialog"]');
    },
  },
];

/** A partial run with failures as the newest ingestion job. */
function worstSiteJobs(s: Site, now: Date): Site {
  const report = runReport({
    status: 'partial',
    sources_considered: 93,
    sources_fetched: 14,
    sources_failed: 3,
    sources_with_new: 9,
    posts_inserted: 41,
    failures: [
      { source_id: sourceId('s-newz'), display_name: 'ai_newz', stage: 'connector', error: 'FloodWaitError: A wait of 1260 seconds is required (caused by GetHistoryRequest)' },
      { source_id: 's-dense-6', display_name: 'Lil’Log', stage: 'fetch', error: LONG_ERROR },
      { source_id: 's-dense-35', display_name: 'Linus Tech Tips', stage: 'save', error: 'deadlock detected' },
    ],
  });
  return { ...s, jobs: [ingestionJob(now, report), ...s.jobs.map((job) => ({ ...job, id: 'job-earlier' }))] };
}

export function frameScenarios(page?: string): FrameScenario[] {
  return page ? SCENARIOS.filter((scenario) => scenario.page === page) : [...SCENARIOS];
}

export function frameScenario(page: string, state: string): FrameScenario | undefined {
  return SCENARIOS.find((scenario) => scenario.page === page && scenario.state === state);
}
