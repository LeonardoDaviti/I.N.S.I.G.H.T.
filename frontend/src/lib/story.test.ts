import test from 'node:test';
import assert from 'node:assert/strict';

import { coveredBy, suggestionReason } from './story.ts';

const story = (names: string[]) => ({ id: 's', voices: names.length, posts: [], sources: names.map((name, i) => ({ id: String(i), name })) });

test('coveredBy names two sources, then counts the rest', () => {
  assert.equal(coveredBy(story(['Anthropic', 'Simon Willison'])), 'covered by 2 · Anthropic, Simon Willison');
  assert.equal(coveredBy(story(['Anthropic', 'Simon Willison', 'https://tg.i-c-a.su/rss/denissexy?limit=50', 'B'])),
    'covered by 4 · Anthropic, Simon Willison, +2');
});

test('suggestionReason says how many of your sources link it, who, and how many articles', () => {
  assert.equal(suggestionReason({
    key: 'metr.org', url: 'https://metr.org', voices: 1, article_count: 1, link_count: 1, voice_names: ['Simon Willison'], articles: [],
  }), 'linked by 1 of your sources (Simon Willison) · 1 article');
});
