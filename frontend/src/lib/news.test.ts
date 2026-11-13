import test from 'node:test';
import assert from 'node:assert/strict';

import { inNewsParts, newsLine, newsPart, newsWords, scopeRoleWords } from './news.ts';
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
  const gemini = { ...story(['News from Google', 'Google DeepMind News', '_modelnotes', 'epsilon_ok', 'data_whispers']), voices: 4 };
  const news = { part: 'earlier' as const, first_at: '2026-10-28T17:00:00Z', reports: 4, shares: 1, mentions: 0, score: 4 };
  assert.equal(newsLine(news, gemini), '4 sources (1 share) · News from Google, Google DeepMind News, +2');
  assert.equal(coveredBy(gemini), 'covered by 4 · News from Google, Google DeepMind News, +2');
});

test('newsLine adds who covered it, the first reporter first', () => {
  const news = { part: 'recent' as const, first_at: '2026-10-01T00:00:00Z', reports: 3, shares: 0, mentions: 0, score: 3 };
  assert.equal(newsLine(news, story(['Road to VR', 'UploadVR', 'Engadget'])), '3 sources · Road to VR, UploadVR, +1');
});

test('a source page row says the source part first; nothing when the API sends none (issue 0077)', () => {
  const news = { part: 'recent' as const, first_at: '2026-10-01T00:00:00Z', reports: 2, shares: 0, mentions: 0, score: 2 };
  const two = story(['Source A', 'Source B']);
  assert.equal(newsLine({ ...news, scope_role: 'origin' }, two), 'Started it · 2 sources · Source A, Source B');
  assert.equal(newsLine({ ...news, scope_role: 'report' }, two), 'Covered · 2 sources · Source A, Source B');
  assert.equal(newsLine({ ...news, scope_role: null }, two), '2 sources · Source A, Source B');
  assert.equal(scopeRoleWords({ scope_role: 'share' }), 'Shared');
  assert.equal(scopeRoleWords({ scope_role: 'mention' }), 'Mentioned');
  assert.equal(scopeRoleWords({}), null);
  assert.equal(scopeRoleWords({ scope_role: 'something-new' }), null);
});

test('News parts: the last 48 hours, this week since Monday, then a part per earlier week (issue 0077)', () => {
  // Wednesday 4 Nov 2026, local time: this week began Monday 2 Nov.
  const now = new Date(2026, 10, 4, 12);
  const at = (month: number, day: number, hour = 12) => new Date(2026, month, day, hour).toISOString();
  const earlier = (first_at: string) => ({ part: 'earlier' as const, first_at });
  assert.equal(newsPart({ part: 'recent', first_at: at(10, 3) }, now).label, 'Last 48 hours');
  assert.equal(newsPart(earlier(at(10, 2, 0)), now).label, 'This week');
  assert.equal(newsPart(earlier(at(10, 1, 23)), now).label, 'Week of 26 Oct');
  assert.equal(newsPart(earlier(at(9, 26, 0)), now).label, 'Week of 26 Oct');
  assert.equal(newsPart(earlier(at(9, 14)), now).label, 'Week of 12 Oct');
  // The week of 5 Oct is the fourth before this one, across a clock change in many zones.
  assert.equal(newsPart(earlier(at(9, 5)), now).rank, 5);
  // Another year says its year.
  assert.equal(newsPart(earlier(new Date(2025, 11, 31).toISOString()), new Date(2026, 0, 6)).label, 'Week of 29 Dec 2025');
});

test('inNewsParts keeps the API order (score) inside each part, the newest part first (issue 0077)', () => {
  const now = new Date(2026, 10, 4, 12);
  const row = (id: string, part: 'recent' | 'earlier', month: number, day: number) => ({ id, news: { part, first_at: new Date(2026, month, day, 12).toISOString() } });
  // As the API sends them: by score across the 30 days.
  const rows = [row('old-high', 'earlier', 9, 14), row('week-high', 'earlier', 10, 2), row('new', 'recent', 10, 4),
    row('last-week', 'earlier', 9, 28), row('old-low', 'earlier', 9, 13), row('week-low', 'earlier', 10, 3)];
  assert.deepEqual(inNewsParts(rows, now).map((r) => r.id), ['new', 'week-high', 'week-low', 'last-week', 'old-high', 'old-low']);
});
