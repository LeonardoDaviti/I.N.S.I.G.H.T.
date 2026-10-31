import test from 'node:test';
import assert from 'node:assert/strict';

import { countsLabel, middleTruncate, plural } from './format.ts';

test('plural and middleTruncate', () => {
  assert.equal(plural(1, 'source'), '1 source');
  assert.equal(plural(12847, 'post'), '12,847 posts');
  assert.equal(middleTruncate('abcdefghij', 7), 'abc…hij');
});

test('countsLabel: a Hacker News row\'s counts (issue 0070)', () => {
  assert.equal(countsLabel({ points: 1675, comments: 1628 }), '1,675 points · 1,628 comments');
  assert.equal(countsLabel({ points: 1, comments: 0 }), '1 point · 0 comments');
});
