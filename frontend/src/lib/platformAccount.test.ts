import test from 'node:test';
import assert from 'node:assert/strict';

import { isPlatformHost, pageAccount, platformAccount } from './platformAccount.ts';

test('a platform account is its platform and the value its template takes (issue 0109 B2)', () => {
  assert.deepEqual(platformAccount('https://x.com/writer_x'), { platform: 'x', value: 'writer_x' });
  assert.deepEqual(platformAccount('twitter.com/Writer_X/'), { platform: 'x', value: 'Writer_X' });
  assert.deepEqual(platformAccount('https://t.me/sample_channel'), { platform: 'telegram', value: 'sample_channel' });
  assert.deepEqual(platformAccount('https://t.me/s/sample_channel'), { platform: 'telegram', value: 'sample_channel' });
  assert.deepEqual(platformAccount('https://www.youtube.com/@SampleChannel'), { platform: 'youtube', value: '@SampleChannel' });
  assert.deepEqual(platformAccount('youtube.com/channel/UCabc123'), { platform: 'youtube', value: 'channel/UCabc123' });
  assert.deepEqual(platformAccount('https://old.reddit.com/r/samplesub'), { platform: 'reddit', value: 'samplesub' });
});

test('a site, a post or a kind of page on a platform is no account', () => {
  for (const address of ['https://x.com', 'https://x.com/writer_x/status/1900000000000000101', 'https://x.com/search?q=a',
    'https://x.com/i/lists/1', 'https://t.me/sample_channel/101', 'https://youtube.com/watch?v=abcdefghijk',
    'https://reddit.com/r/samplesub/comments/abc/x', 'https://reddit.com/u/someone', 'https://openai.com/news',
    'https://xx.com/writer']) {
    assert.equal(platformAccount(address), null, address);
  }
});

test('a platform page is followed by the account it sits under (v10.15 c3)', () => {
  assert.deepEqual(pageAccount('https://twitter.com/writer_x/status/1900000000000000101'), { url: 'https://x.com/writer_x', label: '@writer_x' });
  assert.deepEqual(pageAccount('https://t.me/sample_channel/101'), { url: 'https://t.me/sample_channel', label: '@sample_channel' });
  assert.deepEqual(pageAccount('https://t.me/s/sample_channel/101'), { url: 'https://t.me/sample_channel', label: '@sample_channel' });
  assert.deepEqual(pageAccount('https://www.youtube.com/@SampleChannel/videos'), { url: 'https://www.youtube.com/@SampleChannel', label: '@SampleChannel' });
  assert.deepEqual(pageAccount('https://old.reddit.com/r/samplesub/comments/abc/x'), { url: 'https://www.reddit.com/r/samplesub', label: 'r/samplesub' });
  for (const address of ['https://x.com/i/status/1', 'https://youtube.com/watch?v=abcdefghijk', 'https://example.org/blog/a-post']) {
    assert.equal(pageAccount(address), null, address);
  }
  assert.equal(isPlatformHost('https://www.youtube.com/watch?v=abc'), true);
  assert.equal(isPlatformHost('https://example.org/x'), false);
});
