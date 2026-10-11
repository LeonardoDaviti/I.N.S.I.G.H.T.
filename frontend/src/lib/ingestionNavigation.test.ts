import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ingestionSubViewHref,
  normalizeIngestionSubView,
  normalizeIngestionTab,
  sourcesIngestionHref,
} from './ingestionNavigation.ts';

test('normalizeIngestionTab falls back to main for empty or unknown values', () => {
  assert.equal(normalizeIngestionTab(), 'main');
  assert.equal(normalizeIngestionTab(''), 'main');
  assert.equal(normalizeIngestionTab('unknown'), 'main');
});

test('normalizeIngestionTab keeps supported tab keys', () => {
  assert.equal(normalizeIngestionTab('archive'), 'archive');
  assert.equal(normalizeIngestionTab('missions'), 'missions');
  assert.equal(normalizeIngestionTab('logs'), 'logs');
});

test('normalizeIngestionTab opens the jobs tab for /ingestion/jobs', () => {
  assert.equal(normalizeIngestionTab('jobs'), 'missions');
});

test('sourcesIngestionHref lands each old tab on a view the ingestion tab has', () => {
  assert.equal(sourcesIngestionHref(), '/settings/sources?tab=ingestion');
  assert.equal(sourcesIngestionHref('main'), '/settings/sources?tab=ingestion');
  assert.equal(sourcesIngestionHref('missions'), '/settings/sources?tab=ingestion&sub=jobs');
  assert.equal(sourcesIngestionHref('jobs'), '/settings/sources?tab=ingestion&sub=jobs');
  assert.equal(sourcesIngestionHref('archive'), '/settings/sources?tab=ingestion&sub=archive');
  assert.equal(sourcesIngestionHref('logs'), '/settings/sources?tab=ingestion&sub=logs');
});

test('sourcesIngestionHref carries the query across but not a stale tab or sub', () => {
  assert.equal(
    sourcesIngestionHref('missions', '?job=j-1&tab=x&sub=logs'),
    '/settings/sources?tab=ingestion&sub=jobs&job=j-1',
  );
});

test('the ingestion tab has an overview, archive, jobs and logs; anything else is the overview', () => {
  assert.equal(normalizeIngestionSubView('archive'), 'archive');
  assert.equal(normalizeIngestionSubView('logs'), 'logs');
  assert.equal(normalizeIngestionSubView('jobs'), 'jobs');
  assert.equal(normalizeIngestionSubView('missions'), 'overview');
  assert.equal(normalizeIngestionSubView(null), 'overview');
  assert.equal(ingestionSubViewHref('overview'), '?tab=ingestion');
  assert.equal(ingestionSubViewHref('logs'), '?tab=ingestion&sub=logs');
});
