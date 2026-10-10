import test from 'node:test';
import assert from 'node:assert/strict';

import { foldForSearch, matchesSource, queryWords } from './sourceSearch.ts';

const source = (overrides = {}) => ({ name: 'Café Tech', label: 'Café Tech', url: 'https://cafe.example.com/feed', kind: 'generic_rss', platform: 'rss', ...overrides });

test('folds case and diacritics', () => {
  assert.equal(foldForSearch('  Ünïcödé  ÉTÉ '), 'unicode ete');
  assert.equal(foldForSearch('generic_rss'), 'generic rss');
});

test('matches name, label, URL and kind, case- and diacritic-insensitively', () => {
  assert.equal(matchesSource(source(), queryWords('CAFE')), true);
  assert.equal(matchesSource(source(), queryWords('café')), true);
  assert.equal(matchesSource(source(), queryWords('example.com')), true);
  assert.equal(matchesSource(source(), queryWords('generic_rss')), true);
  assert.equal(matchesSource(source({ name: 'https://www.reddit.com/r/LocalLLaMA/.rss', label: 'r/LocalLLaMA', url: null }), queryWords('localllama')), true);
});

test('needs every word, in any order', () => {
  assert.equal(matchesSource(source(), queryWords('tech cafe')), true);
  assert.equal(matchesSource(source(), queryWords('tech telegram')), false);
});

test('an empty query matches everything', () => {
  assert.equal(matchesSource(source(), queryWords('   ')), true);
});
