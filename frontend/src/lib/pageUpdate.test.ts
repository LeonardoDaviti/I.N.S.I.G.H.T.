import test from 'node:test';
import assert from 'node:assert/strict';

import { lateFind, pageState, updateChanges, updateLine } from './pageUpdate.ts';

const update = { at: '2026-11-03T09:00:00Z', words: 9000, words_added: 1400, words_removed: 30, sections_added: 2, sections_removed: 0 };

test('an update in words', () => {
  assert.equal(updateChanges(update), '+2 sections, +1,400 words');
  assert.equal(updateChanges({ ...update, sections_added: 0, words_added: 10, words_removed: 300 }), '−300 words');
  assert.equal(updateChanges({ ...update, sections_added: 0, sections_removed: 1, words_added: 0, words_removed: 0 }), '−1 section');
  assert.equal(updateLine(update, new Date('2026-11-20T00:00:00Z')), 'Updated Nov 3: +2 sections, +1,400 words');
});

test('a late find is a row sorted days after its date, never an update', () => {
  assert.equal(lateFind({ sort_at: '2026-10-28T10:00:00Z', published_at: '2025-09-14T00:00:00Z' }), true);
  assert.equal(lateFind({ sort_at: '2026-10-28T10:00:00Z', published_at: '2026-10-27T10:00:00Z' }), false);
  assert.equal(lateFind({ sort_at: '2026-10-28T10:00:00Z', published_at: '2025-09-14T00:00:00Z', update }), false);
  assert.equal(lateFind({ sort_at: '2026-10-28T10:00:00Z', published_at: null }), false);
});

test('what a page states about itself', () => {
  const state = pageState({ modified: '2026-06-23', status: 'finished', confidence: 'highly likely', page_update: update },
    '2025-09-14T00:00:00Z');
  assert.equal(state.modified, '2026-06-23T00:00:00.000Z');
  assert.deepEqual(state.notes, ['finished', 'highly likely']);
  assert.equal(state.update?.words_added, 1400);
  assert.equal(pageState({ modified: '2025-09-14T08:00:00Z' }, '2025-09-14T00:00:00Z').modified, null);
  assert.deepEqual(pageState(null, null), { modified: null, notes: [], update: null });
});
