import test from 'node:test';
import assert from 'node:assert/strict';

import { jobLabel, normalizeSourceHealth } from './operationsOverview.ts';

test('normalizeSourceHealth accepts the new shape and degrades the Mark VIII array or nothing to an empty summary', () => {
  const summary = { due_now: 1, deferred: 0, backoff: 0, unavailable: 0, errors: 0 };
  assert.deepEqual(normalizeSourceHealth({ summary, rows: [] }), { summary, rows: [] });
  const empty = { summary: { due_now: 0, deferred: 0, backoff: 0, unavailable: 0, errors: 0 }, rows: [] };
  assert.deepEqual(normalizeSourceHealth(undefined), empty);
  assert.deepEqual(normalizeSourceHealth([{ source_id: 'old' }]), empty);
});

test('jobLabel prefers the backend job_label, then a local label, then the raw type', () => {
  assert.equal(jobLabel({ job_type: 'ingestion_run', job_label: 'Ingestion run' }), 'Ingestion run');
  assert.equal(jobLabel({ job_type: 'ingestion_run' }), 'Ingestion run');
  assert.equal(jobLabel({ job_type: 'scheduler_cycle' }), 'Daily work');
  assert.equal(jobLabel({ job_type: 'something_new' }), 'Something new');
});
