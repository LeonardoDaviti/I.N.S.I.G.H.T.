import test from 'node:test';
import assert from 'node:assert/strict';

import { asRunReport, summarizeRunReport } from './runReport.ts';
import type { RunReport } from '../services/api';

function report(overrides: Partial<RunReport> = {}): RunReport {
  return {
    run_id: 'job-1',
    status: 'success',
    sources_considered: 78,
    sources_fetched: 12,
    sources_failed: 0,
    sources_with_new: 5,
    posts_inserted: 34,
    posts_failed: 0,
    failures: [],
    inserted_by_source: [],
    ...overrides,
  };
}

const headline = (overrides: Partial<RunReport>) => summarizeRunReport(report(overrides)).headline;

test('the headline says what the run delivered: new posts and from how many sources', () => {
  const summary = summarizeRunReport(report());
  assert.equal(summary.tone, 'completion');
  assert.equal(summary.headline, '34 new posts from 5 sources');
  assert.deepEqual(summary.lines, [], 'no zero or bookkeeping lines');
  assert.equal(headline({ posts_inserted: 1, sources_with_new: 1 }), '1 new post from 1 source');
  assert.equal(headline({ posts_inserted: 12847, sources_with_new: 1200 }), '12,847 new posts from 1,200 sources');
});

test('an old stored report without sources_with_new counts its per-source list', () => {
  const inserted_by_source = [
    { source_id: 'a', display_name: 'A', inserted: 3 },
    { source_id: 'b', display_name: 'B', inserted: 1 },
  ];
  assert.equal(headline({ sources_with_new: undefined, posts_inserted: 4, inserted_by_source }), '4 new posts from 2 sources');
});

test('a run that fetched but found nothing new says how many sources it checked', () => {
  assert.equal(headline({ posts_inserted: 0, sources_with_new: 0 }), 'Nothing new: 12 sources checked');
  assert.equal(headline({ posts_inserted: 0, sources_with_new: 0, sources_fetched: 1 }), 'Nothing new: 1 source checked');
});

test('failures: the count of failed sources, after the new posts when there are any', () => {
  const partial = summarizeRunReport(report({ status: 'partial', sources_failed: 3 }));
  assert.equal(partial.tone, 'warning');
  assert.equal(partial.headline, '34 new posts from 5 sources, 3 sources failed');
  const failed = summarizeRunReport(report({ status: 'failed', sources_fetched: 3, sources_failed: 3, posts_inserted: 0, sources_with_new: 0 }));
  assert.equal(failed.tone, 'error');
  assert.equal(failed.headline, '3 sources failed');
});

test('posts that could not be saved are the one line under the headline', () => {
  assert.deepEqual(summarizeRunReport(report({ status: 'partial', posts_failed: 2 })).lines, ['2 posts could not be saved']);
});

test('nothing due and a busy run have their own headlines', () => {
  assert.equal(headline({ status: 'nothing_due', sources_fetched: 0, posts_inserted: 0 }), 'Nothing was due');
  const busy = summarizeRunReport(report({ status: 'skipped_busy' }));
  assert.equal(busy.tone, 'warning');
  assert.equal(busy.headline, 'Skipped: another run is in progress');
});

test('asRunReport accepts a job payload and drops the compaction sentinels from its lists', () => {
  const payload = {
    ...report(),
    events: [{ at: 'x', message: 'started' }],
    failures: [
      { source_id: 'a', display_name: 'A', stage: 'fetch', error: 'boom' },
      { truncated_items: 4 },
    ],
  };
  const parsed = asRunReport(payload);
  assert.ok(parsed);
  assert.equal(parsed?.failures.length, 1);
  assert.equal(parsed?.posts_inserted, 34);
});

test('asRunReport rejects payloads that are not run reports', () => {
  assert.equal(asRunReport(null), null);
  assert.equal(asRunReport({ success: false, error: 'Ingestion run failed: boom' }), null);
  assert.equal(asRunReport({ status: 'success' }), null);
});

test('asRunReport fills missing optional lists so the UI never reads undefined', () => {
  const minimal = { status: 'success', posts_inserted: 2, sources_considered: 1, sources_fetched: 1 };
  const parsed = asRunReport(minimal);
  assert.ok(parsed);
  assert.deepEqual(parsed?.failures, []);
  assert.deepEqual(parsed?.inserted_by_source, []);
  assert.equal(parsed?.posts_failed, 0);
});

test('asRunReport keeps only what the report shows: an old report\'s enrichment and decisions are dropped', () => {
  const parsed = asRunReport({
    run_id: 'r', status: 'nothing_due', posts_inserted: 0, sources_considered: 222,
    decisions: { skip_not_due: 213, skip_backoff: 9 }, enrichment: { skipped: 'analysis off' },
    summary: '0 due, 222 deferred, 0 failed; 0 new posts',
  });
  assert.ok(parsed);
  for (const key of ['enrichment', 'decisions', 'summary']) assert.equal(key in parsed, false, key);
  assert.equal(summarizeRunReport(parsed).headline, 'Nothing was due');
});
