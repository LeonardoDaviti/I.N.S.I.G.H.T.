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
import { credentials, substackView, telegramView } from '../../components/connections/fixtures';
import { runReport } from '../../components/ops/fixtures';
import { siteRoutes, type Site } from './site';
import { HOUR, MINUTE, TRACKS, at, backgroundWork, sourceId, ingestionJob, manyTracks, normalSite, scheduler, worstSite } from './sites';
import { postStateDetail } from './posts';
import { storyTreeItems, xItems } from './storyTrees';

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

/** Issue 0139, Mark X on: two entity cards (one long), a Russian post only Mark X's English reading matched, and a
 *  post its own words matched. */
function markxSearch(now: Date) {
  const [own, ...rest] = normalSite(now).items;
  const russian = {
    ...rest[0], id: 'mx-0139-ru', title: 'Трёхмерные модели для дизайнеров: библиотека, с которой модели тратят меньше токенов',
    excerpt: 'Вышла библиотека на Python: модели пишут трёхмерные объекты кодом.',
    snippet: [{ text: 'Acme released widget3d, a Python ', mark: false }, { text: '3D', mark: true },
      { text: '-modeling ', mark: false }, { text: 'library', mark: true }, { text: ' built for language models', mark: false }],
    snippet_from: 'markx' as const,
  };
  const mine = { ...own, title: 'A 3D library for robot simulation', snippet: [{ text: 'A ', mark: false }, { text: '3D', mark: true },
    { text: ' ', mark: false }, { text: 'library', mark: true }, { text: ' for robot simulation, open source.', mark: false }] };
  return {
    success: true, items: [russian, mine], next_cursor: null,
    entities: [
      { id: 'e-widget3d', name: 'widget3d', type: 'software', maker: 'Acme', posts: 4, voices: 2 },
      { id: 'e-long', name: 'A Very Long Three-Dimensional Modelling Library Name That Keeps Going', type: 'software', maker: null, posts: 1, voices: 1 },
    ],
  };
}

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
  { page: 'reader', state: 'search', label: 'Search results in the Main feed, the words marked', url: '/search?q=prompt&scope=all', routes: site(normalSite), documented: true },
  { page: 'reader', state: 'search-history', label: 'History searched: only what you opened, last open first', url: '/search?q=the&filter=history', routes: site(normalSite), documented: true },
  {
    page: 'reader', state: 'search-markx', label: 'Mark X on: entity cards above the results; a Russian post found by its English reading, its line marked Mark X',
    url: '/search?q=3D%20library', documented: true,
    routes: (now) => [{ path: '/api/search', respond: () => markxSearch(now) }, ...siteRoutes(normalSite(now))],
  },
  { page: 'reader', state: 'search-empty', label: 'No posts match, narrowed: Search everything', url: '/search?q=quantum%20knitting&scope=all&days=7', routes: site(normalSite), documented: true },
  { page: 'reader', state: 'history', label: 'Show history: what you opened, by the day you opened it', url: '/?filter=history', routes: (now) => withSite(now, (s) => {
    // The read posts, opened over the last few days, some long after they were published.
    let k = 0;
    return { ...s, items: s.items.map((item) => (item.read_at ? { ...item, read_at: at(now, -(0.4 + 9 * k++) * HOUR) } : item)) };
  }), documented: true },
  { page: 'reader', state: 'history-empty', label: 'Show history, nothing opened yet', url: '/?filter=history', routes: (now) => withSite(now, (s) => ({ ...s, items: s.items.map((item) => ({ ...item, read_at: null })) })), documented: true },
  {
    page: 'reader', state: 'story', label: 'Three stories open as trees: an origin post, an outside page as the origin, a deep line', url: '/', documented: true,
    routes: (now) => withSite(now, (s) => ({ ...s, items: [...storyTreeItems(now), ...s.items] })),
    setup: async (frame) => {
      await frame.click('button[aria-controls$="-story"]', /covered by 4 · OpenAI/);
      await frame.click('button[aria-controls$="-story"]', /covered by 4 · ai_dispatch/);
      await frame.click('button[aria-controls$="-story"]', /covered by 4 · mitchellh/);
    },
  },
  {
    page: 'reader', state: 'thread', label: 'An X thread as one row, open; a repost says who reposted it, from whom', url: '/', documented: true,
    routes: (now) => withSite(now, (s) => ({ ...s, items: [...xItems(now), ...s.items] })),
    setup: async (frame) => {
      await frame.click('button[aria-controls$="-story"]', /Thread · 7 posts/);
    },
  },
  { page: 'reader', state: 'track', label: 'Scoped to one track', url: `/read/folder/${TRACKS.ai.id}`, routes: site(normalSite), documented: false },
  { page: 'reader', state: 'source', label: 'Scoped to one source', url: `/read/source/${sourceId('s-simon')}`, routes: site(normalSite), documented: false },

  // ---- post ----
  { page: 'post', state: 'article', label: 'A text post: byline, title, prose', url: '/posts/p-article', routes: postRoutes('article'), documented: true },
  { page: 'post', state: 'media', label: 'Video, then images of three shapes', url: '/posts/p-media', routes: postRoutes('media'), documented: true },
  { page: 'post', state: 'long-title', label: 'A title of several lines and the worst body', url: '/posts/p-long-title', routes: postRoutes('long-title'), documented: true },
  { page: 'post', state: 'headings', label: 'h1–h6, lists, quote, table and code', url: '/posts/p-headings', routes: postRoutes('headings'), documented: true },
  { page: 'post', state: 'missing-title', label: 'A Telegram post with no title', url: '/posts/p-missing-title', routes: postRoutes('missing-title'), documented: true },
  { page: 'post', state: 'teaser', label: 'The feed’s summary only: why, and the page', url: '/posts/p-teaser', routes: postRoutes('teaser'), documented: true },
  { page: 'post', state: 'story', label: 'Covered by 4 at the end; a link to a stored post opens it here', url: '/posts/p-story', routes: postRoutes('story'), documented: true },
  { page: 'post', state: 'thread', label: 'An X thread read in order after its first post', url: '/posts/p-bg', routes: postRoutes('thread'), documented: true },
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
    )),
  },
  {
    page: 'sources', state: 'connections-unset', label: 'Nothing set', url: '/settings/sources?tab=connections', documented: true,
    routes: connections(() => credentials(substackView(), telegramView())),
  },
  {
    page: 'sources', state: 'connections-expired', label: 'A failing test and a lapsed session', url: '/settings/sources?tab=connections', documented: true,
    routes: connections((now) => credentials(
      substackView({ test: tested(now, false, 'substack.com answered 401 Unauthorized: the session cookie has expired; copy a fresh substack.sid') }, SET),
      telegramView({ apiSet: true, session: false }),
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
  {
    page: 'sources', state: 'archive-coverage', label: 'A feed measured by the smart archiver: stored of ~the site, how, why not the rest',
    url: `/settings/sources?tab=ingestion&sub=archive&source=${sourceId('s-simon')}`, routes: site(normalSite), documented: true,
  },
  {
    page: 'sources', state: 'source-discoveries', label: 'The source sheet: what this source discovered',
    url: `/settings/sources?source=${sourceId('s-simon')}`, routes: site(normalSite), documented: true,
  },
  { page: 'sources', state: 'ingestion-logs', label: 'Logs: the application log tail', url: '/settings/sources?tab=ingestion&sub=logs', routes: site(normalSite), documented: true },
  { page: 'sources', state: 'ingestion', label: 'The ingestion tab: scheduler and the last run', url: '/settings/sources?tab=ingestion', routes: site(normalSite), documented: false },
  {
    page: 'sources', state: 'background-after-update', label: 'Background work right after an update: re-indexing, reading links, building stories',
    url: '/settings/sources?tab=ingestion', documented: true,
    routes: (now) => withSite(now, (s) => ({ ...s, background: backgroundWork(now, { afterUpdate: true }) })),
  },
  {
    page: 'sources', state: 'background-done', label: 'Background work all done: the last story run and its counts',
    url: '/settings/sources?tab=ingestion', documented: true,
    routes: (now) => withSite(now, (s) => ({ ...s, background: backgroundWork(now) })),
  },
  {
    page: 'sources', state: 'background-never', label: 'Background work on a new install: stories not run yet',
    url: '/settings/sources?tab=ingestion', documented: true,
    routes: (now) => withSite(now, (s) => ({ ...s, background: { ...backgroundWork(now), stories: { running: false, last_run: null } } })),
  },

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
  {
    // Issue 0060, modeled on claude.com (2026-10-31): Follow… from Discover starts where the links point.
    page: 'sources', state: 'follow-where-linked', label: 'Follow… from Discover: every page with the linked articles it holds',
    url: '/settings/sources?tab=discover', routes: (now) => [...followWhereLinked(now), ...siteRoutes(normalSite(now))], documented: false,
    setup: async (frame) => {
      await frame.click('button', /Follow…/);
      await frame.find('[role="dialog"] input[type="radio"]');
    },
  },
  {
    // Issue 0065, modeled on the lab copy (2026-10-31): the sources your stories start from first.
    page: 'sources', state: 'discover-origins', label: 'Discover: where your stories start, and what a source you follow misses',
    url: '/settings/sources?tab=discover', routes: (now) => [...discoverOrigins(), ...siteRoutes(normalSite(now))], documented: true,
  },
];

/** Discover on the lab copy (issue 0065): origins first, a section of a site you follow, an archive offer. */
function discoverOrigins(): FixtureRoute[] {
  const story = (url: string, title: string | null, voices: number) => ({ url, title, voices, stored: false });
  const article = (url: string, title: string | null, linked_by: string[]) => ({ url, title, linked_by });
  const voices = ['dennis_it', 'Simon Willison', 'data_whispers', 'ai_dispatch', 'seeall_notes', 'Lesswrong', 'Epoch AI'];
  return [{
    path: '/api/sources/suggested',
    respond: () => ({
      success: true,
      archives: [{
        source_id: 's-openai-news', name: 'OpenAI News', places: ['openai.com/index'], origins: 37,
        since: '2026-10-23T17:00:00Z', older: 36,
        origin_stories: [story('https://openai.com/index/gpt-6-astra', null, 9),
          story('https://openai.com/index/hugging-face-incident-and-the-road-ahead', null, 8),
          story('https://openai.com/index/introducing-gpt-5-5', 'GPT-5.5 is out', 7)],
      }, {
        source_id: 's-anthropic-research', name: 'Anthropic Research', places: ['anthropic.com/research'], origins: 6,
        since: '2025-04-18T00:00:00Z', older: 0,
        origin_stories: [story('https://anthropic.com/research/ecdsa-curve-origins', null, 2),
          story('https://anthropic.com/research/self-replicating-ai', null, 2)],
      }],
      suggestions: [{
        key: 'anthropic.com/news', url: 'https://anthropic.com/news', voices: 23, voice_names: voices, article_count: 16, link_count: 16,
        classics: 0, origins: 16, follows: ['anthropic.com/research'],
        origin_stories: [story('https://anthropic.com/news/claude-fable-5-mythos-5', 'Claude Fable 5', 13),
          story('https://anthropic.com/news/fable-mythos-access', 'U.S. Government Directs Anthropic to Shut Down Fable 5 and Mythos 5 Models on National Security Grounds', 12),
          story('https://anthropic.com/news/claude-sonnet-5', null, 5)],
        articles: [article('https://anthropic.com/news/claude-fable-5-mythos-5', 'Claude Fable 5', voices)],
      }, {
        key: 'qwen.ai', url: 'https://qwen.ai', voices: 8, voice_names: voices.slice(0, 5), article_count: 7, link_count: 7, classics: 0,
        origins: 7,
        origin_stories: [story('https://qwen.ai/blog?id=qwen3.8-flash-next', null, 3), story('https://qwen.ai/blog?id=qwen-image-2.1', null, 2)],
        articles: [article('https://qwen.ai/blog?id=qwen3.8-flash-next', null, voices.slice(0, 3))],
      }, {
        key: 'github.com/openai', url: 'https://github.com/openai', voices: 10, voice_names: voices, article_count: 5, link_count: 5,
        classics: 0, origins: 5,
        origin_stories: [story('https://github.com/openai/math', null, 5), story('https://github.com/openai/PrimeGaps186', null, 2)],
        articles: [article('https://github.com/openai/math', null, voices.slice(0, 5))],
      }, {
        key: 'reuters.com', url: 'https://reuters.com', voices: 42, voice_names: voices, article_count: 356, link_count: 364, classics: 1,
        origins: 0, articles: [article('https://reuters.com/world/europe/openai-agents-hijacked-german-website-2026-09-04', null, voices)],
      }, {
        key: 'x.com/elonmusk', url: 'https://x.com/elonmusk', voices: 21, voice_names: voices, article_count: 98, link_count: 99,
        classics: 0, origins: 0, articles: [article('https://x.com/elonmusk/status/2111872584338018562', null, voices.slice(0, 4))],
      }],
      unnamed: [{ place: 'youtube.com/watch', origins: 9 }],
    }),
  }, mainSourceMissing(), officialNone()];
}

/** Discover's "main source missing" (issue 0170): a section to follow, with its event and what its test found. */
/** Issue 0196: Discover's official channels section, in Shadow with nothing found yet. */
function officialNone(): FixtureRoute {
  return {
    path: '/api/official',
    respond: () => ({ success: true, mode: 'shadow', cap: 5, added_today: 0, counts: {}, events: {}, rows: [] }),
  };
}

function mainSourceMissing(rows = true): FixtureRoute {
  const event = {
    story: 'story-widget-5', headline: 'Acme ships Widget 5 with a longer context', event_type: 'model_release', voices: 4,
    first_at: '2026-10-27T10:00:00Z',
    own_page: { url: 'https://acme.example/blog/widget-5', how: 'held', held_by: ['Link Aggregator'] },
    posts: [{ id: 'p-1', title: 'Widget 5 is out', source: 'Channel A', source_id: 's-a', url: 'https://t.me/channel_a/101', at: null }],
  };
  return {
    path: '/api/discover/main-source',
    respond: () => ({
      success: true, checked: 141, events: rows ? 1 : 0, within_days: 30, total: rows ? 1 : 0,
      rows: rows ? [{
        key: 'main:acme.example/blog/', kind: 'missing', actor: { id: 'e-acme', name: 'Acme' }, source: null,
        channel: { key: 'acme.example/blog/', kind: 'site', platform: 'site', url: 'https://acme.example/blog', prefix: '/blog/' },
        events: [event], latest: event.first_at,
        test: { label: 'page', holds: 1, of: 1, feeds: [], pages: [], preview: { prefix: '/blog/', found: 12, items: [] }, at: '2026-10-28T09:00:00Z' },
      }] : [],
    }),
  };
}

/** Discover suggesting claude.com, and what Follow… finds there (issue 0060). */
function followWhereLinked(now: Date): FixtureRoute[] {
  const site = 'https://claude.com';
  const posts = ['Introducing routines in Claude Code', 'Agent view in Claude Code', 'Cowork is now Claude',
    'The AI-native SDLC playbook', 'Organization skills and directory'];
  const items = (prefix: string) => posts.map((title, n) => ({
    url: `${site}${prefix}${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`, title, published_at: at(now, -(n + 1) * 26 * HOUR),
  }));
  const page = (path: string, found: number) => ({ url: `${site}${path.replace(/\/$/, '')}`, prefix: path, found, sitemap: true, items: items(path), holds: 21 });
  return [
    mainSourceMissing(false),
    officialNone(),
    {
      path: '/api/sources/suggested',
      respond: () => ({
        success: true,
        suggestions: [{
          key: 'claude.com', url: site, voices: 6, voice_names: ['Simon Willison', 'Latent Space', 'Import AI'],
          article_count: 24, link_count: 31, classics: 0,
          articles: items('/blog/').map((item) => ({ url: item.url, title: item.title, linked_by: ['Simon Willison'] })),
        }],
      }),
    },
    {
      method: 'POST', path: '/api/sources/find-feed',
      respond: () => ({
        success: true, status: 'none', feeds: [], homepage: true, linked: 24, start: `${site}/blog`,
        pages: [page('/resources/articles/', 273), page('/resources/', 546)],
      }),
    },
  ];
}

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
      { source_id: sourceId('s-newz'), display_name: 'ai_dispatch', stage: 'connector', error: 'FloodWaitError: A wait of 1260 seconds is required (caused by GetHistoryRequest)' },
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
