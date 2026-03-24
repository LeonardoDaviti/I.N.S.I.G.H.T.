import test from 'node:test';
import assert from 'node:assert/strict';

import {
  INGESTION_TABS,
  getIngestionTabHref,
  normalizeIngestionTab,
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
