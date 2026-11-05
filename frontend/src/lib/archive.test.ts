import test from 'node:test';
import assert from 'node:assert/strict';

import type { ArchivePlan } from '../services/api';
import { archiveResultLine, describeAvailable, describePlan, describeRate } from './archive.ts';

test('an exact count is the figure, with nothing to qualify', () => {
  assert.deepEqual(describeAvailable({ available: 1722, basis: 'exact', stored: 25 }), { figure: '1,722', note: null });
});

test('an upper bound and an estimate say so in the figure and the note', () => {
  const upper = describeAvailable({ available: 11639, basis: 'upper_bound', stored: 112 });
  assert.equal(upper.figure, 'up to 11,639');
  assert.match(upper.note ?? '', /newest post number/);
  const estimate = describeAvailable({ available: 2400, basis: 'estimate', stored: 0 });
  assert.equal(estimate.figure, 'about 2,400');
});

test('a listing cap and a feed window explain why older posts are out of reach', () => {
  const capped = describeAvailable({ available: 250, basis: 'listing_cap', stored: 0 });
  assert.equal(capped.figure, '250 reachable');
  assert.match(capped.note ?? '', /listings stop/);
  const feed = describeAvailable({ available: 503, basis: 'feed_window', stored: 25 });
  assert.equal(feed.figure, '503 in the feed');
  assert.match(feed.note ?? '', /nothing older/);
});

test('an unknown total is never a number the source did not give', () => {
  assert.deepEqual(describeAvailable({ available: null, basis: 'unknown', stored: 0 }), {
    figure: 'not reported',
    note: 'This source does not report a total; the archive pages back until it runs out.',
  });
  assert.equal(describeAvailable({ available: null, basis: 'unknown', stored: 40 }).figure, 'at least 40');
});

test('a source that reports a total but was never measured says so', () => {
  const unmeasured = describeAvailable({ available: null, basis: 'exact', stored: 3 });
  assert.equal(unmeasured.figure, '—');
  assert.match(unmeasured.note ?? '', /Plan/);
});

const plan = (over: Partial<ArchivePlan> = {}): ArchivePlan => ({
  available_posts: 2300,
  older_posts: 2180,
  estimated_pages: 109,
  estimated_seconds: 1080,
  current_stored_posts: 120,
  oldest_published_at: '2025-03-03T12:00:00Z',
  continues_from: '2025-03-03T12:00:00Z',
  resume: false,
  resume_available: false,
  ...over,
});

test('the plan says what is stored, where the archive continues, and how much is older', () => {
  assert.equal(describePlan(plan(), '~18m'),
    'You have 120 posts, back to 3 Mar 2025. The archive continues from there: about 2,180 older posts · ~18m');
});

test('a source that reports no size is planned with its size unknown', () => {
  assert.equal(describePlan(plan({ older_posts: null, estimated_pages: null, estimated_seconds: null }), null),
    'You have 120 posts, back to 3 Mar 2025. The archive continues from there · size unknown');
});

test('a resume, a source that cannot jump and an empty source say where they start', () => {
  assert.match(describePlan(plan({ resume: true, continues_from: null, checkpoint: { collected_posts: 80 } }), null),
    /resumes from its checkpoint \(80 posts collected so far\): about 2,180 older posts$/);
  assert.match(describePlan(plan({ continues_from: null }), null), /starts at the newest post: about 2,180 older posts$/);
  assert.equal(describePlan(plan({ current_stored_posts: 0, oldest_published_at: null, continues_from: null, older_posts: 2300 }), null),
    'Nothing is stored yet. The archive starts at the newest post: about 2,300 posts');
  assert.equal(describePlan(plan({ older_posts: 0 }), null), 'You have 120 posts, back to 3 Mar 2025. Nothing older to fetch.');
});

test('rate limits read as pauses', () => {
  assert.equal(describeRate({ page_delay_seconds: 5, batch_size: 10, batch_cooldown_seconds: 30 }), '5s between pages, 30s every 10 pages');
  assert.equal(describeRate({ page_delay_seconds: 1 }), '1s between pages');
  assert.equal(describeRate({ page_delay_seconds: 0 }), 'no pause between pages');
  assert.equal(describeRate(null), null);
});

test('an archive result reads as counts, leaving out what was not recorded', () => {
  assert.equal(
    archiveResultLine({ posts_fetched: 500, posts_inserted: 475, posts_updated: 25, pages_fetched: 25, stored_posts: 500 }),
    '500 posts fetched, 475 new, 25 updated · 25 pages · 500 stored',
  );
  assert.equal(archiveResultLine({ posts_fetched: 1, posts_inserted: 1, pages_fetched: 1 }), '1 post fetched, 1 new · 1 page');
  assert.equal(archiveResultLine({}), null);
});
