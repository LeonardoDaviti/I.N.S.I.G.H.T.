import test from 'node:test';
import assert from 'node:assert/strict';

import { citedBy, classicTitle } from './classics.ts';

test('citedBy names who cited a classic and when, three then a count (issue 0051)', () => {
  const at = (month: string) => `${month}-15T12:00:00Z`;
  assert.equal(citedBy({ citers: [{ name: 'Simon Willison', at: at('2025-08') }] }), 'Simon Willison, Aug 2025');
  assert.equal(citedBy({ citers: ['A', 'B', 'C', 'D', 'E'].map((name) => ({ name, at: at('2026-03') })) }),
    'A, Mar 2026 · B, Mar 2026 · C, Mar 2026 · +2');
});

test('classicTitle is the title, else the address without its scheme', () => {
  assert.equal(classicTitle({ title: 'The Bitter Lesson', url: 'https://incompleteideas.net/IncIdeas/BitterLesson.html' }), 'The Bitter Lesson');
  assert.equal(classicTitle({ title: null, url: 'https://www.arxiv.org/abs/2001.08361' }), 'arxiv.org/abs/2001.08361');
});
