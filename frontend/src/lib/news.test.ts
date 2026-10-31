import test from 'node:test';
import assert from 'node:assert/strict';

import { newsLine, newsWords } from './news.ts';
import { coveredBy } from './story.ts';

const story = (names: string[]) => ({ id: 's', voices: names.length, posts: [], sources: names.map((name, i) => ({ id: String(i), name })) });

test('newsWords counts the voices, a share among them, leaving out what is zero (issues 0051, 0069)', () => {
  // Gemini 4 Carbon on the lab: 4 voices, DeepMind's copy of Google's post one share.
  assert.equal(newsWords({ shares: 1, mentions: 1 }, 4), '4 sources (1 share) · in 1 roundup');
  // Nvidia News and r/LocalLLaMA: never "1 source · 1 share".
  assert.equal(newsWords({ shares: 1, mentions: 0 }, 2), '2 sources (1 share)');
  assert.equal(newsWords({ shares: 2, mentions: 3 }, 2), '2 sources (2 shares) · in 3 roundups');
});

test('News, the feed row and the post page say one number (issue 0069)', () => {
  const gemini = { ...story(['News from Google', 'Google DeepMind News', '_philschmid', 'epsiloncorrect', 'data_secrets']), voices: 4 };
  const news = { part: 'earlier' as const, first_at: '2026-10-28T17:00:00Z', reports: 4, shares: 1, mentions: 0, score: 4 };
  assert.equal(newsLine(news, gemini), '4 sources (1 share) · News from Google, Google DeepMind News, +2');
  assert.equal(coveredBy(gemini), 'covered by 4 · News from Google, Google DeepMind News, +2');
});

test('newsLine adds who covered it, the first reporter first', () => {
  const news = { part: 'recent' as const, first_at: '2026-10-01T00:00:00Z', reports: 3, shares: 0, mentions: 0, score: 3 };
  assert.equal(newsLine(news, story(['Road to VR', 'UploadVR', 'Engadget'])), '3 sources · Road to VR, UploadVR, +1');
});
