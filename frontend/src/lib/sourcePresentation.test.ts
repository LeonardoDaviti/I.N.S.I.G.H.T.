import test from 'node:test';
import assert from 'node:assert/strict';

import {
  filterSourceGroups,
  getSourceAvatarModel,
  getSourceDisplayName,
} from './sourcePresentation.ts';

test('getSourceAvatarModel uses a favicon service for RSS URLs', () => {
  const model = getSourceAvatarModel({
    id: 'rss-karpathy',
    platform: 'rss',
    handle_or_url: 'https://karpathy.bearblog.dev',
    display_name: 'karpathy',
  });

  assert.equal(model.displayName, 'karpathy');
  assert.equal(model.fallback, 'KA');
  assert.ok(model.faviconUrl);
  assert.match(model.faviconUrl!, /google\.com\/s2\/favicons/);
  assert.match(model.faviconUrl!, /karpathy\.bearblog\.dev/);
});

test('getSourceAvatarModel falls back to initials for non-url community sources', () => {
  const model = getSourceAvatarModel({
    id: 'reddit-local-llama',
    platform: 'reddit',
    handle_or_url: 'r/LocalLLaMA',
    display_name: 'r/LocalLLaMA',
  });

  assert.equal(model.displayName, 'r/LocalLLaMA');
  assert.equal(model.faviconUrl, null);
  assert.equal(model.fallback, 'LL');
});

test('filterSourceGroups keeps only matching sources when a query targets a source', () => {
  const result = filterSourceGroups(
    [
      {
        platform: 'reddit',
        totalCount: 313,
        sources: [
          { id: '1', platform: 'reddit', handle_or_url: 'Unsloth', display_name: 'Unsloth', post_count: 263 },
          { id: '2', platform: 'reddit', handle_or_url: 'r/LocalLLaMA', display_name: 'r/LocalLLaMA', post_count: 50 },
        ],
      },
      {
        platform: 'rss',
        totalCount: 5779,
        sources: [
          { id: '3', platform: 'rss', handle_or_url: 'https://karpathy.bearblog.dev', display_name: 'karpathy', post_count: 503 },
        ],
      },
    ],
    'llama',
  );

  assert.equal(result.length, 1);
  assert.equal(result[0].platform, 'reddit');
  assert.equal(result[0].sources.length, 1);
  assert.equal(result[0].sources[0].display_name, 'r/LocalLLaMA');
});

test('filterSourceGroups keeps a whole platform visible when the query matches the platform name', () => {
  const result = filterSourceGroups(
    [
      {
        platform: 'reddit',
        totalCount: 313,
        sources: [
          { id: '1', platform: 'reddit', handle_or_url: 'Unsloth', display_name: 'Unsloth', post_count: 263 },
          { id: '2', platform: 'reddit', handle_or_url: 'r/LocalLLaMA', display_name: 'r/LocalLLaMA', post_count: 50 },
        ],
      },
    ],
    'reddit',
  );

  assert.equal(result.length, 1);
  assert.equal(result[0].sources.length, 2);
});

test('getSourceDisplayName compacts raw URL labels for UI display', () => {
  const displayName = getSourceDisplayName({
    id: 'seangoedecke-feed',
    platform: 'rss',
    handle_or_url: 'https://www.seangoedecke.com/rss.xml',
    display_name: 'https://www.seangoedecke.com/rss.xml',
  });

  assert.equal(displayName, 'seangoedecke.com/rss.xml');
});
