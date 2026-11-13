import test from 'node:test';
import assert from 'node:assert/strict';

import { bylineName, bylineText, carried, carriedLine } from './byline.ts';

// Issue 0185: one formatter for who wrote a post, via whom, quoting whom. Synthetic names only.
const own = { author: null, via: 'Example Feed', quoting: null };
const repost = { author: '@acme', via: 'Example Feed', quoting: null };
const forward = { author: 'Acme News', via: 'Example Channel', quoting: null };
const quote = { author: null, via: 'Example Feed', quoting: '@other' };

test('bylineText names the writer and the feed that carried it', () => {
  assert.equal(bylineText(own), 'Example Feed');
  assert.equal(bylineText(repost), '@acme via Example Feed');
  assert.equal(bylineText(forward), 'Acme News via Example Channel');
  assert.equal(bylineText(quote), 'Example Feed, quoting @other');
  assert.equal(bylineText({ ...repost, quoting: '@other' }), '@acme via Example Feed, quoting @other');
  // No byline (an older server): the source name, made readable.
  assert.equal(bylineText(null, 'https://nitter.local/someone/rss'), '@someone');
  assert.equal(bylineText(undefined, 'Example Feed'), 'Example Feed');
});

test('bylineName is the writer, else the feed (a story line)', () => {
  assert.equal(bylineName({ byline: repost, source_display_name: 'Example Feed' }), '@acme');
  assert.equal(bylineName({ byline: own, source_display_name: 'Example Feed' }), 'Example Feed');
  assert.equal(bylineName({ source_display_name: 'Example Feed' }), 'Example Feed');
  assert.equal(carried({ byline: forward }), true);
  assert.equal(carried({ byline: quote }), false);
});

test('carriedLine: who else reposted it, from whom, quoting whom (issues 0066, 0070, 0185)', () => {
  assert.equal(carriedLine({ byline: repost, repost: { by: ['fan_a'], author: 'acme' } }), '↻ @fan_a, from @acme');
  assert.equal(carriedLine({ byline: repost, repost: { by: ['fan_a', 'fan_b'], author: 'acme' } }), '↻ @fan_a, @fan_b, from @acme');
  assert.equal(carriedLine({ byline: repost }), '↻ from @acme');
  assert.equal(carriedLine({ byline: forward }), '↻ from Acme News');
  assert.equal(carriedLine({ byline: quote }), 'quoting @other');
  assert.equal(carriedLine({ byline: { ...repost, quoting: '@other' } }), '↻ from @acme, quoting @other');
  assert.equal(carriedLine({ byline: own }), null);
  assert.equal(carriedLine({}), null);
});
