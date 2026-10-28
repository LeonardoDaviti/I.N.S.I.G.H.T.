import test from 'node:test';
import assert from 'node:assert/strict';

import { READING_DEFAULTS, READING_SIZES, readingStyle, SERIF_STACK } from './readingSettings.ts';

test('the default sets no variable, so the post reads as before', () => {
  assert.equal(readingStyle(READING_DEFAULTS), undefined);
});

test('each setting sets only its own variables', () => {
  assert.deepEqual(readingStyle({ ...READING_DEFAULTS, font: 'serif' }), { '--reading-font': SERIF_STACK });
  assert.deepEqual(readingStyle({ ...READING_DEFAULTS, size: '5' }), { '--reading-scale': '1.25' });
  assert.deepEqual(readingStyle({ ...READING_DEFAULTS, size: '1' }), { '--reading-scale': '0.9' });
  assert.deepEqual(readingStyle({ ...READING_DEFAULTS, width: 'wide' }), { '--reading-column': '52rem', '--reading-measure': '84ch' });
  assert.deepEqual(readingStyle({ ...READING_DEFAULTS, width: 'narrow' }), { '--reading-column': '36rem', '--reading-measure': '58ch' });
});

test('five sizes around today, the middle one today', () => {
  assert.deepEqual(READING_SIZES.map((size) => size.label), ['90%', '95%', '100%', '110%', '125%']);
  assert.equal(READING_SIZES[2].value, READING_DEFAULTS.size);
});
