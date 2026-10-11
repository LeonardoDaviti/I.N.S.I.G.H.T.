import test from 'node:test';
import assert from 'node:assert/strict';

import { jobLabel } from './operationsOverview.ts';

test('jobLabel prefers the backend job_label, then a local label, then the raw type', () => {
  assert.equal(jobLabel({ job_type: 'ingestion_run', job_label: 'Ingestion run' }), 'Ingestion run');
  assert.equal(jobLabel({ job_type: 'ingestion_run' }), 'Ingestion run');
  assert.equal(jobLabel({ job_type: 'scheduler_cycle' }), 'Daily work');
  assert.equal(jobLabel({ job_type: 'something_new' }), 'Something new');
});
