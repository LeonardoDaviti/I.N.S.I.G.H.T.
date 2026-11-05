import test from 'node:test';
import assert from 'node:assert/strict';

import { ixWords, judged, pWords, relationWords, usd, whyWords } from './markx.ts';

test('why a post is in a Mark X story, in words (issue 0086 E)', () => {
  assert.equal(whyWords({ role: 'member', reason: 'rule:citation', p: null, relation: null }), "Mark IX's rule: citation");
  assert.equal(whyWords({ role: 'member', reason: 'rule:none', p: null, relation: null }), "Mark IX's rule: first post");
  assert.equal(whyWords({ role: 'member', reason: 'judge:join', p: 0.9, relation: 'same_event' }), 'joined: Haiku: same event 0.90');
  assert.equal(whyWords({ role: 'member', reason: 'judge:pair', p: 0.65, relation: 'development' }),
    "Haiku: development 0.65, a story Mark IX doesn't have");
  assert.equal(whyWords({ role: 'digest_item', reason: 'judge:check', p: 0.1, relation: 'digest_item' }),
    'kept as a digest item (Haiku: digest item 0.10)');
  assert.equal(whyWords({ role: 'member', reason: 'merge', p: null, relation: null }), 'merged in with its story (Haiku: same event)');
  assert.equal(whyWords(null), 'not in this Mark X story');
});

test('relations, probabilities, Mark IX and cost read plainly', () => {
  assert.equal(relationWords('cant_tell'), "can't tell");
  assert.equal(relationWords('follows_up'), 'follows up');
  assert.equal(pWords(null), '');
  assert.equal(judged('different', 0.25), 'Haiku: different 0.25');
  assert.equal(ixWords(null), 'Mark IX: not in its News');
  assert.equal(ixWords({ title: 'GPT-6.1 Terra', same_row: false }), 'Mark IX: in “GPT-6.1 Terra”');
  assert.equal(ixWords({ title: 'x', same_row: true }), 'Mark IX: same row');
  assert.equal(usd(0.01234), '$0.0123');
  assert.equal(usd(1.2), '$1.20');
});
