import test from 'node:test';
import assert from 'node:assert/strict';

import {
  HEALTH_STATUS_ORDER,
  backoffLabel,
  effectiveHealthStatus,
  filterHealthRows,
  formatDue,
  cadenceLine,
  parseOverrideHours,
  withEffectiveStatus,
} from './sourceSchedule.ts';
import type { SourceHealthRow } from '../services/api';

const NOW = new Date('2026-10-09T12:00:00Z');
const HOUR = 3_600_000;

function iso(offsetMs: number): string {
  return new Date(NOW.getTime() + offsetMs).toISOString();
}

function row(overrides: Partial<SourceHealthRow> = {}): SourceHealthRow {
  return {
    source_id: 'id',
    display_name: 'Source',
    platform: 'rss',
    kind: 'generic_rss',
    enabled: true,
    in_main_digest: true,
    folders: [],
    stored_posts: 10,
    last_post_at: null,
    created_at: iso(-40 * 24 * HOUR),
    backlog_posts: null,
    mean_gap_hours: 30,
    interval_hours: 12,
    interval_basis: 'tier',
    override_hours: null,
    next_due_at: iso(3 * HOUR),
    would_fetch_now: false,
    decision: 'skip_not_due',
    decision_detail: null,
    status: 'deferred',
    last_attempt_at: null,
    last_success_at: null,
    last_outcome: null,
    last_fetched_posts: null,
    last_error: null,
    last_error_at: null,
    consecutive_failures: 0,
    next_retry_at: null,
    dormant: false,
    ...overrides,
  };
}

test('formatDue: future, overdue, due now, unknown', () => {
  assert.equal(formatDue(iso(3 * HOUR), NOW), 'in 3h');
  assert.equal(formatDue(iso(5 * 24 * HOUR), NOW), 'in 5d');
  assert.equal(formatDue(iso(25 * 60_000), NOW), 'in 25m');
  assert.equal(formatDue(iso(-2 * HOUR), NOW), 'overdue 2h');
  assert.equal(formatDue(iso(-20_000), NOW), 'due now');
  assert.equal(formatDue(null, NOW), '—');
  assert.equal(formatDue('not a date', NOW), '—');
});

test('backoffLabel: retry countdown, dormant, retry due, none', () => {
  assert.equal(
    backoffLabel(row({ consecutive_failures: 2, next_retry_at: iso(3 * HOUR), status: 'backoff' }), NOW),
    'retry in 3h',
  );
  assert.equal(
    backoffLabel(row({ consecutive_failures: 9, next_retry_at: iso(5 * 24 * HOUR), dormant: true, status: 'backoff' }), NOW),
    'dormant · retry in 5d',
  );
  assert.equal(
    backoffLabel(row({ consecutive_failures: 1, next_retry_at: iso(-HOUR), status: 'error' }), NOW),
    'retry due',
  );
  assert.equal(backoffLabel(row(), NOW), null);
});

test('cadenceLine says how often and why, in plain words (issue 0027)', () => {
  assert.equal(cadenceLine(row({ interval_hours: 24, interval_basis: 'probation' })),
    'Fetched every 1d (new source, until it has 3 dated posts)');
  assert.equal(cadenceLine(row({ interval_hours: 6, interval_basis: 'override' })), 'Fetched every 6h (your own setting)');
  assert.equal(cadenceLine(row({ interval_hours: 4, interval_basis: 'tier', mean_gap_hours: 8 })),
    'Fetched every 4h (it posts about every 8h)');
  assert.equal(cadenceLine(row({ interval_hours: 3, interval_basis: 'backlog_guard' })),
    'Fetched every 3h (often enough to catch every post its feed lists)');
  assert.equal(cadenceLine(row({ interval_hours: 168, interval_basis: 'profile_floor' })),
    'Fetched every 7d (the least wait for its kind)');
  for (const basis of ['probation', 'override', 'tier', 'backlog_guard', 'profile_floor'] as const) {
    assert.doesNotMatch(cadenceLine(row({ interval_hours: 5, interval_basis: basis })), /probation|tier|guard|floor|override/i);
  }
});


test('filterHealthRows: "error" means failing (error or backoff), like the "N source errors" chip', () => {
  const rows = [
    row({ source_id: 'e', status: 'error', consecutive_failures: 1 }),
    row({ source_id: 'b', status: 'backoff', consecutive_failures: 2 }),
    row({ source_id: 'u', status: 'unavailable' }),
    row({ source_id: 'd', status: 'deferred' }),
  ];
  assert.deepEqual(filterHealthRows(rows, 'error').map((r) => r.source_id), ['e', 'b']);
  assert.deepEqual(filterHealthRows(rows, 'backoff').map((r) => r.source_id), ['b']);
  assert.deepEqual(filterHealthRows(rows, 'unavailable').map((r) => r.source_id), ['u']);
  assert.deepEqual(filterHealthRows(rows, null).map((r) => r.source_id), ['e', 'b', 'u', 'd']);
  assert.deepEqual(filterHealthRows(rows, 'nonsense').map((r) => r.source_id), ['e', 'b', 'u', 'd']);
});

test('parseOverrideHours validates the override the API accepts (null or 1..2160)', () => {
  assert.deepEqual(parseOverrideHours(''), { ok: true, value: null });
  assert.deepEqual(parseOverrideHours('  '), { ok: true, value: null });
  assert.deepEqual(parseOverrideHours('6'), { ok: true, value: 6 });
  assert.deepEqual(parseOverrideHours('1.5'), { ok: true, value: 1.5 });
  assert.deepEqual(parseOverrideHours('2160'), { ok: true, value: 2160 });
  for (const bad of ['0', '0.5', '2161', '3000', 'abc', '-4', '6h', 'Infinity', 'NaN']) {
    const result = parseOverrideHours(bad);
    assert.equal(result.ok, false, bad);
  }
});

test('effectiveHealthStatus: a failed last attempt is failing, or backoff while a retry is scheduled', () => {
  const failed = { last_outcome: 'error' as const, last_error: 'HTTP 429', last_error_at: iso(-HOUR), last_success_at: iso(-48 * HOUR) };
  assert.equal(effectiveHealthStatus(row({ status: 'due', ...failed }), NOW), 'error');
  assert.equal(effectiveHealthStatus(row({ status: 'deferred', ...failed, next_retry_at: iso(2 * HOUR) }), NOW), 'backoff');
  assert.equal(effectiveHealthStatus(row({ status: 'due', ...failed, next_retry_at: iso(-HOUR) }), NOW), 'error');
  // Healthy sources keep their schedule status, even with an older error on record.
  assert.equal(effectiveHealthStatus(row({ status: 'due', last_outcome: 'healthy', last_error: 'old' }), NOW), 'due');
  assert.equal(effectiveHealthStatus(row({ status: 'deferred' }), NOW), 'deferred');
  // Without an outcome, an error newer than the last success counts.
  assert.equal(effectiveHealthStatus(row({ status: 'due', last_error: 'x', last_error_at: iso(-HOUR), last_success_at: iso(-2 * HOUR) }), NOW), 'error');
  assert.equal(effectiveHealthStatus(row({ status: 'due', last_error: 'x', last_error_at: iso(-2 * HOUR), last_success_at: iso(-HOUR) }), NOW), 'due');
  // Disabled and unavailable pass through.
  assert.equal(effectiveHealthStatus(row({ status: 'disabled', ...failed }), NOW), 'disabled');
  assert.equal(effectiveHealthStatus(row({ status: 'unavailable', ...failed }), NOW), 'unavailable');
});

test('withEffectiveStatus derives each row status, so failing rows count as failing', () => {
  const input = [
    row({ status: 'due', last_outcome: 'error', last_error: 'HTTP 429' }),
    row({ status: 'due' }),
    row({ status: 'deferred' }),
    row({ status: 'unavailable' }),
    row({ status: 'backoff' }),
  ];
  const rows = withEffectiveStatus(input, NOW);
  assert.deepEqual(rows.map((r) => r.status), ['error', 'due', 'deferred', 'unavailable', 'backoff']);
  assert.equal(rows[1], input[1]);
});
