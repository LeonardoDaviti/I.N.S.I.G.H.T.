import test from 'node:test';
import assert from 'node:assert/strict';

import { citedBy, classicRoleWords, classicTitle } from './classics.ts';

test('citedBy names who cited a classic and when, three then a count (issue 0051)', () => {
  const at = (month: string) => `${month}-15T12:00:00Z`;
  assert.equal(citedBy({ citers: [{ name: 'Simon Willison', at: at('2025-08') }] }), 'Simon Willison, Aug 2025');
  assert.equal(citedBy({ citers: ['A', 'B', 'C', 'D', 'E'].map((name) => ({ name, at: at('2026-03') })) }),
    'A, Mar 2026 · B, Mar 2026 · C, Mar 2026 · +2');
});

test('citedBy names a Reddit author in its subreddit, as the API sends it on that source\'s page (issue 0105)', () => {
  const at = (month: string) => `${month}-15T12:00:00Z`;
  assert.equal(citedBy({ citers: [{ name: 'u/alice', place: 'r/sub', at: at('2026-02') }, { name: 'Source B', at: at('2026-03') }] }),
    'u/alice in r/sub, Feb 2026 · Source B, Mar 2026');
});

test('a classic on a source\'s page: "Started it" for its own page, "Cited it" for a page it cites (issue 0105)', () => {
  assert.equal(classicRoleWords({ scope_role: 'origin' }), 'Started it');
  assert.equal(classicRoleWords({ scope_role: 'report' }), 'Cited it');
  assert.equal(classicRoleWords({ scope_role: null }), null);
  assert.equal(classicRoleWords({}), null);
  assert.equal(classicRoleWords({ scope_role: 'something-new' }), null);
});

test('classicTitle is the title, else the address without its scheme', () => {
  assert.equal(classicTitle({ title: 'The Bitter Lesson', url: 'https://incompleteideas.net/IncIdeas/BitterLesson.html' }), 'The Bitter Lesson');
  assert.equal(classicTitle({ title: null, url: 'https://www.arxiv.org/abs/2001.08361' }), 'arxiv.org/abs/2001.08361');
});
