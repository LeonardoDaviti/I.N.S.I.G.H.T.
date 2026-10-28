import { describe, expect, it } from 'vitest';

import { healthRow } from '../ops/fixtures';
import {
  UNASSIGNED_KEY,
  brokenNote,
  filterSources,
  groupSources,
  kindLabel,
  nextSort,
  rangeIds,
  readSourcesView,
  rowFact,
  sortSources,
  stepActive,
  visibleRowKeys,
  writeSourcesView,
} from './sourceList';

const ai = { id: 'f-ai', name: 'AI engineering' };
const ar = { id: 'f-ar', name: 'AR glasses' };
const empty = { id: 'f-empty', name: 'Empty track' };

const rows = [
  healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog', folders: [ai] }),
  healthRow({ source_id: 'flaky', display_name: 'Flaky Feed', status: 'backoff', folders: [ai, ar] }),
  healthRow({ source_id: 'tg', display_name: 'ai_newz', platform: 'telegram', kind: 'telegram_mtproto', status: 'unavailable', folders: [] }),
  healthRow({ source_id: 'off', display_name: 'Road to VR', status: 'disabled', enabled: false, folders: [ar] }),
];

describe('readSourcesView / writeSourcesView', () => {
  const defaults = { q: '', status: null, group: 'none', sort: 'status', dir: 'desc' };

  it('defaults to the flat list, worst status first, no search, no status', () => {
    expect(readSourcesView(new URLSearchParams(''))).toEqual(defaults);
  });

  it('maps the old ?tab=health to the flat list and keeps its ?status= filter', () => {
    expect(readSourcesView(new URLSearchParams('tab=health&status=error'))).toEqual({ ...defaults, status: 'error' });
  });

  it('retired and unknown values fall back to the defaults', () => {
    expect(readSourcesView(new URLSearchParams('group=status&sort=success&dir=asc'))).toEqual({ ...defaults, dir: 'asc' });
    expect(readSourcesView(new URLSearchParams('group=nope&status=bogus&sort=nope&dir=up'))).toEqual(defaults);
    // Group by Platform became Group by Kind (issue 0027): an old link groups by kind.
    expect(readSourcesView(new URLSearchParams('tab=health&group=platform')).group).toBe('kind');
  });

  it('a column without a direction takes its own', () => {
    expect(readSourcesView(new URLSearchParams('sort=name'))).toMatchObject({ sort: 'name', dir: 'asc' });
    expect(readSourcesView(new URLSearchParams('sort=added'))).toMatchObject({ sort: 'added', dir: 'desc' });
    expect(readSourcesView(new URLSearchParams('sort=lastPost&dir=asc'))).toMatchObject({ sort: 'lastPost', dir: 'asc' });
  });

  it('writes only non-default values, drops the legacy tab and keeps other params', () => {
    const next = writeSourcesView(new URLSearchParams('tab=health&data=worst'), { q: 'simon', status: null, group: 'none', sort: 'status', dir: 'desc' });
    expect(next.toString()).toBe('data=worst&q=simon');
    expect(writeSourcesView(new URLSearchParams(''), { q: ' ', status: 'due', group: 'track', sort: 'added', dir: 'desc' }).toString())
      .toBe('status=due&group=track&sort=added');
    expect(writeSourcesView(new URLSearchParams(''), { q: '', status: null, group: 'kind', sort: 'name', dir: 'desc' }).toString())
      .toBe('group=kind&sort=name&dir=desc');
  });

  it('round-trips every view', () => {
    const view = { q: 'ai', status: 'enabled', group: 'track', sort: 'posts', dir: 'asc' } as const;
    expect(readSourcesView(writeSourcesView(new URLSearchParams(''), view))).toEqual(view);
  });
});

describe('nextSort (a header click)', () => {
  it('a new column starts in its own direction; the active one reverses', () => {
    expect(nextSort({ sort: 'status', dir: 'desc' }, 'added')).toEqual({ sort: 'added', dir: 'desc' });
    expect(nextSort({ sort: 'added', dir: 'desc' }, 'added')).toEqual({ sort: 'added', dir: 'asc' });
    expect(nextSort({ sort: 'added', dir: 'asc' }, 'added')).toEqual({ sort: 'added', dir: 'desc' });
    expect(nextSort({ sort: 'added', dir: 'asc' }, 'name')).toEqual({ sort: 'name', dir: 'asc' });
  });
});

describe('filterSources', () => {
  it('searches names, platform and track names, case and accent insensitive', () => {
    expect(filterSources(rows, { q: 'SIMON', status: null }).map((r) => r.source_id)).toEqual(['simon']);
    expect(filterSources(rows, { q: 'telegram', status: null }).map((r) => r.source_id)).toEqual(['tg']);
    expect(filterSources(rows, { q: 'ar glasses', status: null }).map((r) => r.source_id)).toEqual(['flaky', 'off']);
  });

  it('status error means failing (error or backoff) and combines with the search', () => {
    expect(filterSources(rows, { q: '', status: 'error' }).map((r) => r.source_id)).toEqual(['flaky']);
    expect(filterSources(rows, { q: 'simon', status: 'error' })).toEqual([]);
  });

  it('enabled keeps every source that is on, whatever its status', () => {
    expect(filterSources(rows, { q: '', status: 'enabled' }).map((r) => r.source_id)).toEqual(['simon', 'flaky', 'tg']);
    expect(filterSources(rows, { q: '', status: 'disabled' }).map((r) => r.source_id)).toEqual(['off']);
  });
});

describe('groupSources', () => {
  it('by track: every track in order (empty ones too), then the untracked without a header, a source in two tracks in both', () => {
    const groups = groupSources(rows, 'track', [ai, ar, empty]);
    expect(groups.map((g) => [g.label, g.rows.map((r) => r.source_id)])).toEqual([
      ['AI engineering', ['flaky', 'simon']],
      ['AR glasses', ['flaky', 'off']],
      ['Empty track', []],
      ['Other sources', ['tg']],
    ]);
    expect(groups.map((g) => Boolean(g.headless))).toEqual([false, false, false, true]);
    expect(groups[0].folderId).toBe('f-ai');
    expect(groups[3].key).toBe(UNASSIGNED_KEY);
  });

  it('drops empty tracks when asked (a search is on) and an empty untracked group always', () => {
    const groups = groupSources(rows.slice(0, 2), 'track', [ai, empty], { keepEmpty: false });
    expect(groups.map((g) => g.label)).toEqual(['AI engineering']);
  });

  it('a source whose only track is unknown counts as untracked', () => {
    const groups = groupSources([healthRow({ source_id: 'x', folders: [{ id: 'gone', name: 'Gone' }] })], 'track', []);
    expect(groups.map((g) => g.key)).toEqual([UNASSIGNED_KEY]);
  });

  it('by kind (a subreddit read as a feed and one read as Reddit are apart), and none: one headless list', () => {
    expect(groupSources(rows, 'kind').map((g) => [g.label, g.rows.length])).toEqual([['RSS', 3], ['Telegram', 1]]);
    const reddit = healthRow({ source_id: 'r', platform: 'rss', kind: 'reddit_subreddit' });
    expect(groupSources([...rows, reddit], 'kind').map((g) => g.label)).toEqual(['Reddit', 'RSS', 'Telegram']);
    const all = groupSources(rows, 'none');
    expect(all).toHaveLength(1);
    expect(all[0].headless).toBe(true);
    expect(all[0].rows.map((r) => r.source_id)).toEqual(['flaky', 'tg', 'simon', 'off']);
  });
});

describe('sortSources', () => {
  const now = Date.now();
  const ago = (h: number) => new Date(now - h * 3_600_000).toISOString();
  const list = [
    healthRow({ source_id: 'b', display_name: 'Bravo', kind: 'youtube_channel', stored_posts: 5, last_post_at: ago(1), created_at: ago(500) }),
    healthRow({ source_id: 'a', display_name: 'alpha', kind: 'generic_rss', stored_posts: 50, last_post_at: ago(48), created_at: ago(2), status: 'error' }),
    healthRow({ source_id: 'c', display_name: 'Charlie', kind: 'generic_rss', stored_posts: 5, last_post_at: null, created_at: ago(90) }),
  ];
  const ids = (sort: Parameters<typeof sortSources>[1], dir?: Parameters<typeof sortSources>[2]) =>
    sortSources(list, sort, dir).map((r) => r.source_id);

  it('each column in its own direction by default, ties by name', () => {
    expect(ids('name')).toEqual(['a', 'b', 'c']);
    expect(ids('kind')).toEqual(['a', 'c', 'b']);
    expect(ids('posts')).toEqual(['a', 'b', 'c']);
    expect(ids('lastPost')).toEqual(['b', 'a', 'c']);
    expect(ids('added')).toEqual(['a', 'c', 'b']);
    expect(ids('status')[0]).toBe('a');
  });

  it('each column reversed, ties still by name', () => {
    expect(ids('name', 'desc')).toEqual(['c', 'b', 'a']);
    expect(ids('kind', 'desc')).toEqual(['b', 'a', 'c']);
    expect(ids('posts', 'asc')).toEqual(['b', 'c', 'a']);
    expect(ids('lastPost', 'asc')).toEqual(['c', 'a', 'b']);
    expect(ids('added', 'asc')).toEqual(['b', 'c', 'a']);
    // Only the status order reverses: the two healthy sources stay A to Z.
    expect(ids('status', 'asc')).toEqual(['b', 'c', 'a']);
  });

  it('worst status first, then A to Z within a status, never by the next fetch', () => {
    // On the server a just-fetched source (next fetch furthest away) sank to the end of Scheduled.
    const scheduled = [
      healthRow({ source_id: 'hn', display_name: 'Hacker News', status: 'deferred', next_due_at: ago(-1) }),
      healthRow({ source_id: 'arena', display_name: 'arena.ai', status: 'deferred', next_due_at: ago(-24) }),
      healthRow({ source_id: 'jg', display_name: 'Jeff Geerling', status: 'deferred', next_due_at: ago(-5) }),
      healthRow({ source_id: 'bad', display_name: 'Zed', status: 'error', consecutive_failures: 1 }),
    ];
    expect(sortSources(scheduled, 'status', 'desc').map((r) => r.source_id)).toEqual(['bad', 'arena', 'hn', 'jg']);
  });

  it('applies inside every group', () => {
    expect(groupSources(list, 'none', [], { sort: 'added', dir: 'asc' })[0].rows.map((r) => r.source_id)).toEqual(['b', 'c', 'a']);
  });
});

describe('row columns', () => {
  it('names the kind, falling back to the platform', () => {
    expect(kindLabel({ kind: 'youtube_channel', platform: 'youtube' })).toBe('YouTube');
    expect(kindLabel({ kind: 'telegram_rss', platform: 'rss' })).toBe('Telegram RSS');
    expect(kindLabel({ kind: 'something_new', platform: 'telegram' })).toBe('Telegram');
  });
});

describe('rangeIds (shift-click)', () => {
  const keys = ['g1/a', 'g1/b', 'g2/a', 'g2/c'].map((key) => ({ key, id: key.split('/')[1] }));

  it('spans anchor to target in either direction, one id per source', () => {
    expect(rangeIds(keys, 'g1/b', 'g2/c')).toEqual(['b', 'a', 'c']);
    expect(rangeIds(keys, 'g2/c', 'g1/a')).toEqual(['a', 'b', 'c']);
  });

  it('without a visible anchor it is just the target', () => {
    expect(rangeIds(keys, null, 'g1/b')).toEqual(['b']);
    expect(rangeIds(keys, 'gone/x', 'g1/b')).toEqual(['b']);
    expect(rangeIds(keys, 'g1/a', 'gone/x')).toEqual([]);
  });
});

describe('keyboard walk', () => {
  const groups = groupSources(rows, 'track', [ai, ar]);

  it('skips collapsed groups and keeps one key per group and source', () => {
    const keys = visibleRowKeys(groups, new Set(['track:f-ai']));
    expect(keys.map((k) => k.key)).toEqual(['track:f-ar/flaky', 'track:f-ar/off', `${UNASSIGNED_KEY}/tg`]);
  });

  it('j/k step and clamp; from nothing j starts at the top, k at the bottom', () => {
    const keys = ['a', 'b', 'c'];
    expect(stepActive(keys, null, 1)).toBe('a');
    expect(stepActive(keys, null, -1)).toBe('c');
    expect(stepActive(keys, 'a', 1)).toBe('b');
    expect(stepActive(keys, 'c', 1)).toBe('c');
    expect(stepActive(keys, 'a', -1)).toBe('a');
    expect(stepActive([], 'a', 1)).toBeNull();
  });
});

describe('the source doctor note (issue 0036)', () => {
  const now = new Date('2026-10-28T09:00:00Z');
  const broken = { status: 'backoff' as const, consecutive_failures: 3, doctor_looked_at: '2026-10-28T08:00:00Z' };
  const feed = { kind: 'feed' as const, url: 'https://arena.ai/blog/feed.xml', title: 'Arena blog', found: null, prefix: null };

  it('says a replacement was found, or that none was', () => {
    expect(rowFact(healthRow({ ...broken, replacement: feed }, now), now)).toBe('Broken: replacement found');
    expect(rowFact(healthRow({ ...broken, replacement: null }, now), now)).toBe('Broken: no replacement found');
  });

  it('says nothing of the kind before the doctor looked, or for a source that is off', () => {
    expect(brokenNote(healthRow({ status: 'backoff', consecutive_failures: 1 }, now))).toBeNull();
    expect(rowFact(healthRow({ ...broken, replacement: feed, enabled: false }, now), now)).toBe('off');
  });
});
