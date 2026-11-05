import test from 'node:test';
import assert from 'node:assert/strict';

import { waitingLine } from './archiveWaiting.ts';

test('a waiting archive says whose limit it waits for and when it continues, in the reader\'s time', () => {
  const until = '2026-11-05T13:05:00Z';
  assert.equal(waitingLine({ host: 'bridge.example', until }, new Date('2026-11-05T13:00:00Z'), 'UTC'),
    "Waiting for bridge.example's limit: continues at 13:05");
  assert.equal(waitingLine({ host: 'bridge.example', until }, new Date('2026-11-05T13:00:00Z'), 'Asia/Dubai'),
    "Waiting for bridge.example's limit: continues at 17:05");
  assert.equal(waitingLine({ host: 'bridge.example', until }, new Date('2026-11-05T13:06:00Z'), 'UTC'),
    "Waiting for bridge.example's limit: continues shortly", 'its time has come: the scheduler takes it up');
  assert.equal(waitingLine({ host: 'bridge.example', until, reason: 'timeout' }, new Date('2026-11-05T13:00:00Z'), 'UTC'),
    'Waiting for bridge.example to answer: continues at 13:05');
});
