import test from 'node:test';
import assert from 'node:assert/strict';

import { newsLine, newsWords } from './news.ts';

const story = (names: string[]) => ({ id: 's', voices: names.length, posts: [], sources: names.map((name, i) => ({ id: String(i), name })) });

test('newsWords says what a News score is made of, leaving out what is zero (issue 0051)', () => {
  assert.equal(newsWords({ reports: 4, shares: 1, mentions: 1 }), '4 sources · 1 share · in 1 roundup');
  assert.equal(newsWords({ reports: 1, shares: 2, mentions: 0 }), '1 source · 2 shares');
  assert.equal(newsWords({ reports: 0, shares: 2, mentions: 3 }), '2 shares · in 3 roundups');
});

test('newsLine adds who covered it, the first reporter first', () => {
  const news = { part: 'recent' as const, first_at: '2026-10-01T00:00:00Z', reports: 3, shares: 0, mentions: 0, score: 3 };
  assert.equal(newsLine(news, story(['Road to VR', 'UploadVR', 'Engadget'])), '3 sources · Road to VR, UploadVR, +1');
});
