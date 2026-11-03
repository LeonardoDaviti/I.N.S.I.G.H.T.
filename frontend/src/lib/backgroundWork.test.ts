import test from 'node:test';
import assert from 'node:assert/strict';

import { backgroundWorkBusy, backgroundWorkLines } from './backgroundWork.ts';
import type { BackgroundWorkResponse } from '../services/api';

const NOW = new Date('2026-10-31T12:00:00Z');
const RUN = {
  computed_at: '2026-10-31T11:48:00Z', seconds: 4.77, full: false, posts: 5018, stories: 86, news: 90, classics: 175,
  links_filled: 0,
};

function work(overrides: Partial<BackgroundWorkResponse> = {}): BackgroundWorkResponse {
  return {
    success: true,
    stories: { running: false, last_run: RUN },
    search: { total: 41689, pending: 0 },
    links: { total: 41689, pending: 0 },
    ...overrides,
  };
}

test('all done: the last run with its counts, the index up to date, every link read', () => {
  const [stories, search, links] = backgroundWorkLines(work(), NOW);
  assert.deepEqual(stories, {
    key: 'stories', label: 'Stories', status: 'ok', word: 'done',
    details: ['Last run 12m ago, took 5s · next run: after the next fetch run',
      '5,018 posts grouped · 86 stories · 90 News stories, last 30 days · 175 Classics'],
  });
  assert.deepEqual([search.status, search.word], ['ok', 'up to date']);
  assert.deepEqual([links.status, links.word], ['ok', 'all read']);
  assert.equal(backgroundWorkBusy(work()), false);
});

test('right after an update: re-indexing and reading links count up, the story job runs', () => {
  const after = work({
    stories: { running: true, last_run: RUN },
    search: { total: 41689, pending: 29689 },
    links: { total: 41689, pending: 40489 },
  });
  const [stories, search, links] = backgroundWorkLines(after, NOW);
  assert.deepEqual([stories.status, stories.word, stories.details],
    ['running', 'building stories, News and Classics now', ['Last run 12m ago, took 5s']]);
  assert.deepEqual([search.status, search.word], ['running', 're-indexing 12,000 of 41,689']);
  assert.deepEqual([links.status, links.word], ['running', 'reading 1,200 of 41,689']);
  assert.equal(backgroundWorkBusy(after), true);
});

test('never run: the story job runs after the next fetch run', () => {
  const [stories] = backgroundWorkLines(work({ stories: { running: false, last_run: null } }), NOW);
  assert.deepEqual(stories, { key: 'stories', label: 'Stories', status: 'scheduled', word: 'not run yet',
    details: ['Runs after the next fetch run'] });
  assert.deepEqual(backgroundWorkLines(work({ stories: { running: true, last_run: null } }), NOW)[0].details, [],
    'the first run, running');
});

test('a run that recorded no counts still reads, and odd numbers stay in range', () => {
  const [stories, search] = backgroundWorkLines(work({
    stories: { running: false, last_run: { computed_at: '2026-10-30T12:00:00Z' } },
    search: { total: 10, pending: 25 },
  }), NOW);
  assert.deepEqual(stories.details, ['Last run 1d ago · next run: after the next fetch run']);
  assert.equal(search.word, 're-indexing 0 of 10');
  assert.equal(backgroundWorkBusy(undefined), false);
});

test('new rules regroup every post in batches: the line says how far, and that the old stories show till then', () => {
  const [stories] = backgroundWorkLines(work({ stories: { running: false, last_run: { ...RUN, rebuild: { done: 12000, total: 41689 } } } }), NOW);
  assert.deepEqual([stories.status, stories.word], ['running', 'regrouping every post by new rules, 12,000 of 41,689']);
  assert.equal(stories.details[0], 'Until it is done the stories made by the old rules are shown');
});
