import test from 'node:test';
import assert from 'node:assert/strict';

import { platformAccount } from './platformAccount.ts';

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
