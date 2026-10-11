import { describe, expect, it } from 'vitest';

import { healthRow } from '../ops/fixtures';
import {
  UNASSIGNED_KEY,
  filterSources,
  groupSources,
  kindLabel,
  rangeIds,
  readSourcesView,
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
  healthRow({ source_id: 'tg', display_name: 'ai_newz', platform: 'telegram', status: 'unavailable', folders: [] }),
  healthRow({ source_id: 'off', display_name: 'Road to VR', status: 'disabled', enabled: false, folders: [ar] }),
];

describe('readSourcesView / writeSourcesView', () => {
  it('defaults to track grouping, no search, no status', () => {
    expect(readSourcesView(new URLSearchParams(''))).toEqual({ q: '', status: null, group: 'track', sort: 'status' });
  });

  it('maps the old ?tab=health to status grouping and keeps its ?status= filter', () => {
    expect(readSourcesView(new URLSearchParams('tab=health&status=error'))).toEqual({ q: '', status: 'error', group: 'status', sort: 'status' });
  });

  it('an explicit group wins over the legacy tab; unknown values fall back', () => {
    expect(readSourcesView(new URLSearchParams('tab=health&group=platform')).group).toBe('platform');
    expect(readSourcesView(new URLSearchParams('group=nope&status=bogus&sort=nope'))).toEqual({ q: '', status: null, group: 'track', sort: 'status' });
    expect(readSourcesView(new URLSearchParams('status=enabled&sort=posts'))).toMatchObject({ status: 'enabled', sort: 'posts' });
  });

  it('writes only non-default values, drops the legacy tab and keeps other params', () => {
    const next = writeSourcesView(new URLSearchParams('tab=health&data=worst'), { q: 'simon', status: null, group: 'track', sort: 'status' });
    expect(next.toString()).toBe('data=worst&q=simon');
    expect(writeSourcesView(new URLSearchParams(''), { q: ' ', status: 'due', group: 'status', sort: 'name' }).toString()).toBe('status=due&group=status&sort=name');
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
  it('by track: every track in order (empty ones too), then the unassigned, a source in two tracks in both', () => {
    const groups = groupSources(rows, 'track', [ai, ar, empty]);
    expect(groups.map((g) => [g.label, g.rows.map((r) => r.source_id)])).toEqual([
      ['AI engineering', ['flaky', 'simon']],
      ['AR glasses', ['flaky', 'off']],
      ['Empty track', []],
      ['Not in a track', ['tg']],
    ]);
    expect(groups[0].folderId).toBe('f-ai');
    expect(groups[3].key).toBe(UNASSIGNED_KEY);
  });

  it('drops empty tracks when asked (a search is on) and an empty unassigned group always', () => {
    const groups = groupSources(rows.slice(0, 2), 'track', [ai, empty], { keepEmpty: false });
    expect(groups.map((g) => g.label)).toEqual(['AI engineering']);
  });

  it('a source whose only track is unknown counts as unassigned', () => {
    const groups = groupSources([healthRow({ source_id: 'x', folders: [{ id: 'gone', name: 'Gone' }] })], 'track', []);
    expect(groups.map((g) => g.label)).toEqual(['Not in a track']);
  });

  it('by status: worst first, empty statuses dropped', () => {
    expect(groupSources(rows, 'status').map((g) => g.label)).toEqual(['Backoff', 'Unavailable', 'Scheduled', 'Disabled']);
  });

  it('by platform and none', () => {
    expect(groupSources(rows, 'platform').map((g) => [g.label, g.rows.length])).toEqual([['RSS', 3], ['Telegram', 1]]);
    const all = groupSources(rows, 'none');
    expect(all).toHaveLength(1);
    expect(all[0].rows.map((r) => r.source_id)).toEqual(['flaky', 'tg', 'simon', 'off']);
  });
});

describe('sortSources', () => {
  const now = Date.now();
  const ago = (h: number) => new Date(now - h * 3_600_000).toISOString();
  const list = [
    healthRow({ source_id: 'b', display_name: 'Bravo', stored_posts: 5, last_success_at: ago(1) }),
    healthRow({ source_id: 'a', display_name: 'alpha', stored_posts: 50, last_success_at: ago(48), status: 'error' }),
    healthRow({ source_id: 'c', display_name: 'Charlie', stored_posts: 5, last_success_at: null }),
  ];
  const ids = (sort: Parameters<typeof sortSources>[1]) => sortSources(list, sort).map((r) => r.source_id);

  it('status puts the worst first; name is A to Z, case-insensitive', () => {
    expect(ids('status')[0]).toBe('a');
    expect(ids('name')).toEqual(['a', 'b', 'c']);
  });

  it('last success puts the stalest first (never fetched on top); posts the most first, ties by name', () => {
    expect(ids('success')).toEqual(['c', 'a', 'b']);
    expect(ids('posts')).toEqual(['a', 'b', 'c']);
  });

  it('applies inside every group', () => {
    expect(groupSources(list, 'none', [], { sort: 'posts' })[0].rows.map((r) => r.source_id)).toEqual(['a', 'b', 'c']);
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
