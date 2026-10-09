import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DECISION_KINDS,
  DECISION_LABELS,
  asRunReport,
  summarizeRunReport,
} from './runReport.ts';
import type { RunReport } from '../services/api';

function report(overrides: Partial<RunReport> = {}): RunReport {
  return {
    run_id: 'job-1',
    trigger: 'manual',
    selector: { kind: 'all' },
    force: false,
    status: 'success',
    started_at: '2026-10-09T10:00:00+00:00',
    finished_at: '2026-10-09T10:01:05+00:00',
    sources_considered: 78,
    sources_fetched: 12,
    sources_failed: 0,
    decisions: { fetch_due: 12, skip_not_due: 63, skip_unavailable: 3 },
    posts_fetched: 240,
    posts_inserted: 48,
    posts_updated: 9,
    posts_failed: 0,
    failures: [],
    post_failures: [],
    inserted_by_source: [],
    enrichment: null,
    ...overrides,
  };
}

test('DECISION_LABELS covers every DecisionKind with a human label', () => {
  assert.deepEqual(
    [...DECISION_KINDS].sort(),
    [
      'fetch_due', 'fetch_forced', 'fetch_new_source', 'fetch_retry',
      'skip_backoff', 'skip_disabled', 'skip_not_due', 'skip_unavailable',
    ],
  );
  for (const kind of DECISION_KINDS) {
    const label = DECISION_LABELS[kind];
    assert.equal(typeof label, 'string');
    assert.ok(label.length > 0, kind);
    assert.ok(!label.includes('_'), `${kind} label is not a raw enum: ${label}`);
  }
});

test('success: the headline is the new-post count; lines say what was fetched and deferred', () => {
  const summary = summarizeRunReport(report());
  assert.equal(summary.tone, 'completion');
  assert.equal(summary.headline, '48 new posts');
  assert.ok(summary.lines.some((line) => line === 'Fetched 12 of 78 sources'), summary.lines.join(' | '));
  assert.ok(summary.lines.some((line) => line.includes('63 not due yet')), summary.lines.join(' | '));
  assert.ok(summary.lines.some((line) => line.includes('3 unavailable')), summary.lines.join(' | '));
});

test('success: pluralisation and thousands separators (1 new post, 12,847 new posts)', () => {
  assert.equal(summarizeRunReport(report({ posts_inserted: 1 })).headline, '1 new post');
  assert.equal(summarizeRunReport(report({ posts_inserted: 12847 })).headline, '12,847 new posts');
  assert.equal(summarizeRunReport(report({ posts_inserted: 0 })).headline, 'No new posts');
});

test('partial: a warning that names the failure count next to the new posts', () => {
  const summary = summarizeRunReport(report({
    status: 'partial',
    sources_failed: 2,
    failures: [
      { source_id: 'a', display_name: 'A', stage: 'fetch', error: 'HTTP 503' },
      { source_id: 'b', display_name: 'B', stage: 'save', error: 'deadlock' },
    ],
  }));
  assert.equal(summary.tone, 'warning');
  assert.equal(summary.headline, '48 new posts, 2 sources failed');
});

test('failed: an error headline', () => {
  const summary = summarizeRunReport(report({ status: 'failed', sources_fetched: 1, sources_failed: 1, posts_inserted: 0 }));
  assert.equal(summary.tone, 'error');
  assert.equal(summary.headline, 'Fetch failed');
});

test('nothing_due: says nothing was due, not "0 new posts"', () => {
  const summary = summarizeRunReport(report({
    status: 'nothing_due', sources_fetched: 0, posts_inserted: 0, decisions: { skip_not_due: 78 },
  }));
  assert.equal(summary.tone, 'completion');
  assert.equal(summary.headline, 'Nothing was due');
  assert.ok(summary.lines.some((line) => line.includes('78 not due yet')));
});

test('skipped_busy: another run holds the run lock', () => {
  const summary = summarizeRunReport(report({ status: 'skipped_busy', sources_considered: 0, sources_fetched: 0, posts_inserted: 0, decisions: {} }));
  assert.equal(summary.tone, 'warning');
  assert.equal(summary.headline, 'Skipped: another run is in progress');
});

test('a forced run says so', () => {
  const summary = summarizeRunReport(report({ force: true, decisions: { fetch_forced: 78 }, sources_fetched: 78 }));
  assert.ok(summary.lines.some((line) => line.includes('forced')), summary.lines.join(' | '));
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
  assert.equal(parsed?.posts_inserted, 48);
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
  assert.deepEqual(parsed?.decisions, {});
  assert.equal(parsed?.posts_updated, 0);
});
