import test from 'node:test';
import assert from 'node:assert/strict';

import { proxiedImage } from './mediaProxy.ts';

test('proxiedImage: an http(s) image of a post goes through /api/media', () => {
  assert.equal(
    proxiedImage('p-1', 'https://telegram.local/media/chan/1/a.jpg?x=1&y=2'),
    '/api/media?post=p-1&url=https%3A%2F%2Ftelegram.local%2Fmedia%2Fchan%2F1%2Fa.jpg%3Fx%3D1%26y%3D2',
  );
});

test('proxiedImage: data: URLs, a missing post id and no URL are left alone', () => {
  assert.equal(proxiedImage('p-1', 'data:image/svg+xml;utf8,<svg/>'), 'data:image/svg+xml;utf8,<svg/>');
  assert.equal(proxiedImage(undefined, 'https://a.test/x.jpg'), 'https://a.test/x.jpg');
  assert.equal(proxiedImage('p-1', null), undefined);
});
