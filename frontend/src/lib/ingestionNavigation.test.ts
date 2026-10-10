import test from 'node:test';
import assert from 'node:assert/strict';

import {
  INGESTION_TABS,
  getIngestionTabHref,
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

test('getIngestionTabHref uses the base route for main and nested routes for other tabs', () => {
  assert.equal(getIngestionTabHref('main'), '/ingestion');
  assert.equal(getIngestionTabHref('archive'), '/ingestion/archive');
  assert.equal(getIngestionTabHref('missions'), '/ingestion/missions');
  assert.equal(getIngestionTabHref('logs'), '/ingestion/logs');
});

test('INGESTION_TABS exposes the expected user-facing order', () => {
  assert.deepEqual(
    INGESTION_TABS.map((tab) => tab.key),
    ['main', 'archive', 'missions', 'logs'],
  );
});

test('sourcesIngestionHref lands each old tab on a view the ingestion tab has', () => {
  assert.equal(sourcesIngestionHref(), '/settings/sources?tab=ingestion');
  assert.equal(sourcesIngestionHref('main'), '/settings/sources?tab=ingestion');
  assert.equal(sourcesIngestionHref('missions'), '/settings/sources?tab=ingestion&sub=jobs');
  assert.equal(sourcesIngestionHref('jobs'), '/settings/sources?tab=ingestion&sub=jobs');
  // No archive or logs view under sources: the overview, with no sub that promises one.
  assert.equal(sourcesIngestionHref('archive'), '/settings/sources?tab=ingestion');
  assert.equal(sourcesIngestionHref('logs'), '/settings/sources?tab=ingestion');
});

test('sourcesIngestionHref carries the query across but not a stale tab or sub', () => {
  assert.equal(
    sourcesIngestionHref('missions', '?job=j-1&tab=x&sub=logs'),
    '/settings/sources?tab=ingestion&sub=jobs&job=j-1',
  );
});
