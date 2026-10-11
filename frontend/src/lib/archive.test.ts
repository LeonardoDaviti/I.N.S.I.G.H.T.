import test from 'node:test';
import assert from 'node:assert/strict';

import {
  archiveCeiling,
  archivePresets,
  archiveResultLine,
  clampDesired,
  defaultDesired,
  describeAvailable,
  describeRate,
} from './archive.ts';

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
  assert.equal(unmeasured.figure, 'not checked yet');
  assert.match(unmeasured.note ?? '', /Plan/);
});

test('the ceiling is the known available count, never an unknown one', () => {
  assert.equal(archiveCeiling(1722, 'exact'), 1722);
  assert.equal(archiveCeiling(250, 'listing_cap'), 250);
  assert.equal(archiveCeiling(null, 'exact'), null);
  assert.equal(archiveCeiling(5000, 'unknown'), null);
});

test('presets stop below the ceiling and end with all of it', () => {
  assert.deepEqual(archivePresets(1722), [
    { label: '100', value: 100 },
    { label: '500', value: 500 },
    { label: 'All 1,722', value: 1722 },
  ]);
  assert.deepEqual(archivePresets(250), [{ label: '100', value: 100 }, { label: 'All 250', value: 250 }]);
  assert.deepEqual(archivePresets(100), [{ label: 'All 100', value: 100 }]);
  assert.deepEqual(archivePresets(null).map((p) => p.value), [100, 500, 1000]);
});

test('the wanted count is a whole number clamped to what is available', () => {
  assert.equal(clampDesired(900, 250), 250);
  assert.equal(clampDesired(0, 250), 1);
  assert.equal(clampDesired(12.7, null), 12);
  assert.equal(clampDesired(Number.NaN, 250), 1);
  assert.equal(clampDesired(50_000, null), 10_000);
});

test('the default asks for 500 or everything, whichever is less', () => {
  assert.equal(defaultDesired(1722), 500);
  assert.equal(defaultDesired(126), 126);
  assert.equal(defaultDesired(null), 100);
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
