import test from 'node:test';
import assert from 'node:assert/strict';

import { FOLLOW_LABELS, UNFOLLOWABLE, archiveLine, canArchive, missingReason, originReason, pageFollow, rowNotes, untitledLine } from './discover.ts';
import type { MissingOrigins, SuggestedSource } from '../services/api';

const NOW = new Date('2026-10-31T12:00:00Z');
const SUGGESTION: SuggestedSource = {
  key: 'qwen.ai', url: 'https://qwen.ai', voices: 8, voice_names: [], article_count: 7, link_count: 7, articles: [], origins: 7,
};
const MISSING: MissingOrigins = {
  source_id: 's1', name: 'OpenAI News', places: ['openai.com/index'], origins: 37, since: '2026-10-23T17:00:00Z', older: 36,
  origin_stories: [],
};

test('a site your stories start from says how many', () => {
  assert.equal(originReason(SUGGESTION), 'Started 7 of your stories');
});

test('a section of a site you follow names what you follow and the section', () => {
  assert.equal(originReason({ ...SUGGESTION, key: 'anthropic.com/news', origins: 14, follows: ['anthropic.com/research'] }),
    'You follow anthropic.com/research; /news started 14 of your stories');
  assert.equal(originReason({ ...SUGGESTION, key: 'huggingface.co', origins: 39, follows: ['huggingface.co/blog'] }),
    'You follow huggingface.co/blog; huggingface.co started 39 of your stories');
});

test('a followed source missing its origins says how many are older than its first post', () => {
  // Issue 0109: pages it lacks, not stories.
  assert.equal(missingReason(MISSING, NOW),
    "37 pages at openai.com/index where your stories started aren't in it, 36 from before its first post (Oct 23)");
  assert.equal(missingReason({ ...MISSING, older: 37 }, NOW),
    "37 pages at openai.com/index where your stories started aren't in it, all from before its first post (Oct 23)");
  assert.equal(missingReason({ ...MISSING, name: 'Anthropic research', places: ['anthropic.com/research'], origins: 1, older: 0 }, NOW),
    "1 page at anthropic.com/research where your stories started isn't in it");
});

test('an untitled line names its site and section, a tweet its account, never the address (issue 0080)', () => {
  assert.equal(untitledLine('https://www.example.com/blog/a-long-slug-here'), 'example.com · blog');
  assert.equal(untitledLine('https://example.com/2026/10/a-story'), 'example.com', 'a date is no section');
  assert.equal(untitledLine('https://example.com/ru-RU/index/a-story'), 'example.com · index', 'a language before it');
  assert.equal(untitledLine('https://example.com/a-page'), 'example.com', 'the root: the site alone');
  assert.equal(untitledLine('https://x.com/SomeOne/status/2111872584338018562'), 'a post by @SomeOne');
});

test('a missing row follows its archive (issue 0080)', () => {
  assert.equal(archiveLine(MISSING), null, 'no archive yet');
  // Issue 0109: the row's pages are those still missing; the stored ones have left it.
  assert.equal(archiveLine({ ...MISSING, stored: 3, archive: { state: 'running', found: 3 } }), 'Archive running · 3 found so far, 37 to go');
  assert.equal(archiveLine({ ...MISSING, stored: 3, archive: { state: 'finished', found: 3 } }), "Archive finished · 37 of these pages aren't in its archive");
});

test('a row says what was stored, a stopped feed and a section it does not watch (issue 0109)', () => {
  assert.deepEqual(rowNotes({ ...MISSING, stored: 36 }, NOW), ['36 now stored; their stories join at the next story run']);
  assert.deepEqual(rowNotes({ ...MISSING, stopped: '2024-11-11T00:00:00Z', archivable: 0 }, NOW),
    ["Its feed stopped (Nov 11 ’24): an archive can't reach these pages"]);
  assert.deepEqual(rowNotes({ ...MISSING, watches: { prefix: '/resources/articles/', not: ['/blog'] }, archivable: 1 }, NOW),
    ['It watches /resources/articles/, not /blog']);
  assert.equal(canArchive(MISSING), true);
  assert.equal(canArchive({ ...MISSING, archivable: 0 }), false);
  assert.equal(canArchive({ ...MISSING, archive: { state: 'finished', found: 1 } }), false);
});

test('the follow test labels, and the two that sink', () => {
  assert.deepEqual(Object.values(FOLLOW_LABELS),
    ['Feed found', 'Page watching', 'Headlines only', 'Blocks readers', 'A feed, but not of these pages']);
  assert.deepEqual([...UNFOLLOWABLE], ['headlines', 'blocked', 'other_feed']);
});

test('a Pages row follows its section or its account, never the bare domain (v10.15 c3)', () => {
  // The server's address first.
  assert.deepEqual(pageFollow({ url: 'https://acme.example.org/blog/2026/a-post', follow_url: 'https://acme.example.org/blog/' }),
    { url: 'https://acme.example.org/blog/', label: 'Follow section…' });
  assert.deepEqual(pageFollow({ url: 'https://x.com/acme_lab/status/1900000000000000101', follow_url: 'https://x.com/acme_lab' }),
    { url: 'https://x.com/acme_lab', label: 'Follow @acme_lab…' });
  // An older server: worked out here.
  assert.deepEqual(pageFollow({ url: 'https://x.com/acme_lab/status/1900000000000000101' }),
    { url: 'https://x.com/acme_lab', label: 'Follow @acme_lab…' });
  assert.deepEqual(pageFollow({ url: 'https://t.me/acme_channel/42' }), { url: 'https://t.me/acme_channel', label: 'Follow @acme_channel…' });
  assert.deepEqual(pageFollow({ url: 'https://example.org/news/research/an-essay?ref=x', follow_url: null }),
    { url: 'https://example.org/news/research/', label: 'Follow section…' });
  assert.deepEqual(pageFollow({ url: 'https://example.org/an-essay' }), { url: 'https://example.org/', label: 'Follow site…' });
  // A platform's page that names no account: nothing to follow, never the platform's home.
  assert.equal(pageFollow({ url: 'https://www.youtube.com/watch?v=abcdefghijk' }), null);
});
