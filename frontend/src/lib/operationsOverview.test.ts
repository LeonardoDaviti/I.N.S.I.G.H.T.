import test from 'node:test';
import assert from 'node:assert/strict';

import { compactJobRun, compactOperationsOverview, jobLabel, normalizeSourceHealth } from './operationsOverview.ts';

test('compactOperationsOverview trims oversized job payloads for the mission feed', () => {
  const compacted = compactOperationsOverview({
    success: true,
    jobs: [
      {
        id: 'job-1',
        job_type: 'vertical_briefing_source',
        status: 'success',
        trigger: 'manual',
        payload: {
          posts: {
            count: 40,
            sample_ids: ['a', 'b', 'c', 'd', 'e', 'f'],
          },
          tracks: [
            { id: 'track-1', title: 'One', timeline: [{ date: '2026-03-24' }] },
            { id: 'track-2', title: 'Two', timeline: [{ date: '2026-03-24' }] },
            { id: 'track-3', title: 'Three', timeline: [{ date: '2026-03-24' }] },
            { id: 'track-4', title: 'Four', timeline: [{ date: '2026-03-24' }] },
            { id: 'track-5', title: 'Five', timeline: [{ date: '2026-03-24' }] },
          ],
          events: [
            { at: '1', message: 'one' },
            { at: '2', message: 'two' },
            { at: '3', message: 'three' },
            { at: '4', message: 'four' },
            { at: '5', message: 'five' },
            { at: '6', message: 'six' },
            { at: '7', message: 'seven' },
          ],
        },
      },
    ],
  });

  const payload = compacted.jobs?.[0]?.payload;
  assert.ok(payload);
  assert.deepEqual(payload?.posts, {
    count: 40,
    sample_ids: ['a', 'b', 'c', { truncated_items: 3 }],
  });
  assert.deepEqual(payload?.tracks, [
    { id: 'track-1', title: 'One', timeline: [{ date: '2026-03-24' }] },
    { id: 'track-2', title: 'Two', timeline: [{ date: '2026-03-24' }] },
    { truncated_items: 3 },
  ]);
  assert.equal(payload?.events?.length, 4);
  assert.deepEqual(payload?.events?.[3], { truncated_items: 4 });
});

test('compactOperationsOverview leaves the new source_health {summary, rows} shape untouched', () => {
  const rows = Array.from({ length: 8 }, (_, i) => ({ source_id: `s${i}`, display_name: `S${i}`, status: 'error' }));
  const compacted = compactOperationsOverview({
    success: true,
    jobs: [],
    source_health: {
      summary: { due_now: 1, deferred: 2, backoff: 3, unavailable: 4, errors: 5 },
      rows: rows as never,
    },
  });
  assert.equal(compacted.source_health?.rows.length, 8);
  assert.deepEqual(compacted.source_health?.summary, { due_now: 1, deferred: 2, backoff: 3, unavailable: 4, errors: 5 });
});

test('normalizeSourceHealth accepts the new shape and degrades the Mark VIII array or nothing to an empty summary', () => {
  const summary = { due_now: 1, deferred: 0, backoff: 0, unavailable: 0, errors: 0 };
  assert.deepEqual(normalizeSourceHealth({ summary, rows: [] }), { summary, rows: [] });
  const empty = { summary: { due_now: 0, deferred: 0, backoff: 0, unavailable: 0, errors: 0 }, rows: [] };
  assert.deepEqual(normalizeSourceHealth(undefined), empty);
  assert.deepEqual(normalizeSourceHealth([{ source_id: 'old' }]), empty);
});

test('compactJobRun keeps an ingestion_run run report whole so RunReportSummary can render it', () => {
  const failures = Array.from({ length: 6 }, (_, i) => ({ source_id: `s${i}`, display_name: `S${i}`, stage: 'fetch', error: 'boom' }));
  const job = {
    id: 'job-2',
    job_type: 'ingestion_run',
    status: 'failed',
    trigger: 'manual',
    payload: {
      status: 'partial',
      posts_inserted: 3,
      failures,
      inserted_by_source: failures.map((f) => ({ source_id: f.source_id, display_name: f.display_name, inserted: 1 })),
      events: Array.from({ length: 30 }, (_, i) => ({ at: String(i), message: `e${i}` })),
    },
  };
  const summary = compactJobRun(job, 'summary');
  assert.equal(summary.payload?.failures.length, 6);
  assert.equal(summary.payload?.inserted_by_source.length, 6);
  // events are still trimmed: they are the noisy part
  assert.ok((summary.payload?.events.length ?? 0) < 30);
});

test('jobLabel prefers the backend job_label, then a local label, then the raw type', () => {
  assert.equal(jobLabel({ job_type: 'ingestion_run', job_label: 'Ingestion run' }), 'Ingestion run');
  assert.equal(jobLabel({ job_type: 'ingestion_run' }), 'Ingestion run');
  assert.equal(jobLabel({ job_type: 'scheduler_cycle' }), 'Daily work');
  assert.equal(jobLabel({ job_type: 'something_new' }), 'Something new');
});
