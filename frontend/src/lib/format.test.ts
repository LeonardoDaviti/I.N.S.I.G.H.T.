import test from 'node:test';
import assert from 'node:assert/strict';

import { middleTruncate, plural } from './format.ts';

test('plural and middleTruncate', () => {
  assert.equal(plural(1, 'source'), '1 source');
  assert.equal(plural(12847, 'post'), '12,847 posts');
  assert.equal(middleTruncate('abcdefghij', 7), 'abc…hij');
});
