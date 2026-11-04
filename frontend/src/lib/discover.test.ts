import test from 'node:test';
import assert from 'node:assert/strict';

import { FOLLOW_LABELS, UNFOLLOWABLE, archiveLine, missingReason, originReason, untitledLine } from './discover.ts';
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
  assert.equal(missingReason(MISSING, NOW),
    "37 of your stories started at openai.com/index pages it doesn't hold, 36 from before its first post (Oct 23)");
  assert.equal(missingReason({ ...MISSING, older: 37 }, NOW),
    "37 of your stories started at openai.com/index pages it doesn't hold, all from before its first post (Oct 23)");
  assert.equal(missingReason({ ...MISSING, name: 'Anthropic research', places: ['anthropic.com/research'], origins: 6, older: 0 }, NOW),
    "6 of your stories started at anthropic.com/research pages it doesn't hold");
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
  assert.equal(archiveLine({ ...MISSING, archive: { state: 'running', found: 3 } }), 'Archive running · 3 of 37 found so far');
  assert.equal(archiveLine({ ...MISSING, archive: { state: 'finished', found: 3 } }), "Archive finished · 34 of these pages aren't in its archive");
  assert.equal(archiveLine({ ...MISSING, archive: { state: 'finished', found: 37 } }), 'Archive finished');
});

test('the follow test labels, and the two that sink', () => {
  assert.deepEqual(Object.values(FOLLOW_LABELS), ['Feed found', 'Page watching', 'Headlines only', 'Blocks readers']);
  assert.deepEqual([...UNFOLLOWABLE], ['headlines', 'blocked']);
});
