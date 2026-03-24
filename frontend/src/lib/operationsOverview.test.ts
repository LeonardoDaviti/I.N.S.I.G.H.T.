import test from 'node:test';
import assert from 'node:assert/strict';

import { compactOperationsOverview } from './operationsOverview.ts';

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
