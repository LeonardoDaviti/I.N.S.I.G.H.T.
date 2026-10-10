import test from 'node:test';
import assert from 'node:assert/strict';

import { displayPostTitle } from './postTitle.ts';

test('displayPostTitle: a cut title becomes the full first line of the text', () => {
  const content = 'Update claude-api skill: Claude Opus 5.5 default, Claude Sonnet 5.5, build-eval and hillclimb guides (#1930)\n\n* Update the skill';
  assert.equal(
    displayPostTitle('Update claude-api skill: Claude Opus 5.5 default, Claude Sonnet 5.5, …', content),
    'Update claude-api skill: Claude Opus 5.5 default, Claude Sonnet 5.5, build-eval and hillclimb guides (#1930)',
  );
  assert.equal(displayPostTitle('A long post...', 'A long post that goes on\nmore'), 'A long post that goes on');
});

test('displayPostTitle: a whole title, or text that does not start with it, stays', () => {
  assert.equal(displayPostTitle('2026 in LLMs (so far)', 'On Friday I gave the closing keynote.'), '2026 in LLMs (so far)');
  assert.equal(displayPostTitle('Wait for it…', 'Something else entirely'), 'Wait for it…');
  assert.equal(displayPostTitle('Wait for it…', 'Wait for it…'), 'Wait for it…');
  assert.equal(displayPostTitle('', 'text'), 'Untitled post');
  assert.equal(displayPostTitle(null, null), 'Untitled post');
});

test('displayPostTitle: a very long first line is capped', () => {
  const line = `Start ${'x'.repeat(600)}`;
  const shown = displayPostTitle('Start x…', line);
  assert.equal(Array.from(shown).length, 301);
  assert.ok(shown.endsWith('…'));
});
