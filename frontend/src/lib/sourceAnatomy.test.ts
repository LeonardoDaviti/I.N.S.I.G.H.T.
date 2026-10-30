import test from 'node:test';
import assert from 'node:assert/strict';

import type { SourceAnatomyRow, SourceGives } from '../services/api';
import {
  DEFAULT_ANATOMY_SORT,
  anatomyName,
  conditionalCell,
  fullTextCell,
  lastFetchCell,
  nextAnatomySort,
  scheduleCell,
  sortAnatomy,
  watchCell,
} from './sourceAnatomy.ts';

const NOW = new Date('2026-10-30T12:00:00Z');
const gives = (over: Partial<SourceGives> = {}): SourceGives => ({ posts: 0, read: 0, stories: 0, first: 0, classics: 0, links: 0, ...over });

function row(id: string, over: Partial<SourceAnatomyRow> = {}): SourceAnatomyRow {
  return {
    source_id: id, display_name: id, address: `https://${id}.example/feed`, platform: 'rss', enabled: true,
    kind: 'feed', full_text: 'feed', watch_changes: null, watched_pages: 0, validators: false,
    status: 'deferred', interval_hours: 6, interval_basis: 'tier', next_due_at: '2026-10-30T14:00:00Z',
    last_attempt_at: '2026-10-30T09:00:00Z', last_outcome: 'healthy', last_error: null, last_error_at: null,
    recent: gives(), all: gives(), ...over,
  };
}

const ids = (rows: SourceAnatomyRow[]) => rows.map((r) => r.source_id);

test('the default order is the most posts in the window, then all time, then the name', () => {
  const rows = [
    row('b', { recent: gives({ posts: 5 }), all: gives({ posts: 5 }) }),
    row('a', { recent: gives({ posts: 5 }), all: gives({ posts: 5 }) }),
    row('c', { recent: gives({ posts: 5 }), all: gives({ posts: 90 }) }),
    row('d', { recent: gives({ posts: 40 }) }),
  ];
  assert.deepEqual(DEFAULT_ANATOMY_SORT, { sort: 'posts', dir: 'desc' });
  assert.deepEqual(ids(sortAnatomy(rows, 'posts', 'desc')), ['d', 'c', 'a', 'b']);
  assert.deepEqual(ids(sortAnatomy(rows, 'posts', 'asc')), ['a', 'b', 'c', 'd']);
});

test('every column sorts; ties fall back to the name', () => {
  const a = row('a', { kind: 'telegram', full_text: 'on', watch_changes: true, validators: null, interval_hours: 24,
    last_attempt_at: '2026-10-29T12:00:00Z', recent: gives({ stories: 3, first: 1, classics: 0, links: 9, read: 2 }) });
  const b = row('b', { kind: 'feed', full_text: 'off', watch_changes: false, validators: true, interval_hours: 1,
    last_attempt_at: null, recent: gives({ stories: 1, first: 2, classics: 4, links: 1, read: 0 }) });
  const c = row('c', { kind: 'saved', full_text: 'on', interval_hours: 1, last_attempt_at: '2026-10-30T11:00:00Z' });
  const rows = [c, b, a];
  assert.deepEqual(ids(sortAnatomy(rows, 'name', 'asc')), ['a', 'b', 'c']);
  assert.deepEqual(ids(sortAnatomy(rows, 'kind', 'asc')), ['b', 'c', 'a']);          // Feed, Saved, Telegram
  assert.deepEqual(ids(sortAnatomy(rows, 'fullText', 'asc')), ['a', 'c', 'b']);      // on, on, off
  assert.deepEqual(ids(sortAnatomy(rows, 'watch', 'asc')), ['a', 'b', 'c']);         // on, off, cannot
  assert.deepEqual(ids(sortAnatomy(rows, 'conditional', 'asc')), ['b', 'c', 'a']);   // yes, no, cannot
  assert.deepEqual(ids(sortAnatomy(rows, 'schedule', 'asc')), ['b', 'a', 'c']);      // Saved is never fetched: last
  assert.deepEqual(ids(sortAnatomy(rows, 'lastFetch', 'desc')), ['c', 'a', 'b']);    // never fetched last
  assert.deepEqual(ids(sortAnatomy(rows, 'stories', 'desc')), ['a', 'b', 'c']);
  assert.deepEqual(ids(sortAnatomy(rows, 'first', 'desc')), ['b', 'a', 'c']);
  assert.deepEqual(ids(sortAnatomy(rows, 'classics', 'desc')), ['b', 'a', 'c']);
  assert.deepEqual(ids(sortAnatomy(rows, 'links', 'desc')), ['a', 'b', 'c']);
  assert.deepEqual(ids(sortAnatomy(rows, 'read', 'desc')), ['a', 'b', 'c']);
});

test('pressing a column starts it in its own direction; again reverses it', () => {
  assert.deepEqual(nextAnatomySort({ sort: 'posts', dir: 'desc' }, 'name'), { sort: 'name', dir: 'asc' });
  assert.deepEqual(nextAnatomySort({ sort: 'name', dir: 'asc' }, 'name'), { sort: 'name', dir: 'desc' });
  assert.deepEqual(nextAnatomySort({ sort: 'name', dir: 'asc' }, 'links'), { sort: 'links', dir: 'desc' });
});

test('a source without a name of its own is named from its address', () => {
  assert.equal(anatomyName({ display_name: null, address: 'https://tg.i-c-a.su/rss/denissexy?limit=50' }), '@denissexy');
  assert.equal(anatomyName({ display_name: 'Road to VR', address: 'https://www.roadtovr.com/feed/' }), 'Road to VR');
});

test('the cells say how it is read in a word, with what it means on hover', () => {
  assert.equal(fullTextCell({ full_text: 'feed' }).text, 'in feed');
  assert.equal(fullTextCell({ full_text: 'off' }).text, 'off');
  assert.equal(watchCell({ watch_changes: null, watched_pages: 0 }).text, '—');
  assert.equal(watchCell({ watch_changes: true, watched_pages: 3 }).title, 'Watches 3 pages for changes');
  assert.equal(conditionalCell({ validators: true }).text, 'yes');
  assert.equal(conditionalCell({ validators: null }).text, '—');
  assert.equal(scheduleCell(row('a'), NOW).text, '6h');
  assert.match(scheduleCell(row('a'), NOW).title, /next in 2h/);
  assert.equal(scheduleCell(row('a', { enabled: false }), NOW).text, 'off');
  assert.equal(scheduleCell(row('a', { kind: 'saved' }), NOW).text, '—');
  assert.equal(lastFetchCell(row('a'), NOW).text, '3h');
  assert.equal(lastFetchCell(row('a', { last_outcome: 'error', last_error: 'HTTP 404' }), NOW).text, 'failed 3h: HTTP 404');
  assert.equal(lastFetchCell(row('a', { last_attempt_at: null }), NOW).text, '—');
});
