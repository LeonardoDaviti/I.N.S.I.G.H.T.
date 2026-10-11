import { Suspense } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { Route, Routes, useLocation, useNavigationType } from 'react-router-dom';

import { AppRoutes } from './App';
import { makeFakeApi } from './test/fakeApi';
import { renderWithProviders } from './test/render';

// The pages are stand-ins: these tests are about which route renders, not the pages.
vi.mock('./pages/ReaderPage', () => ({ default: () => <Where page="reader" /> }));
vi.mock('./pages/SourcesConfig', () => ({ default: () => <Where page="sources" /> }));
vi.mock('./pages/PostDetailPage', () => ({ default: () => <Where page="post" /> }));

function Where({ page }: { page: string }) {
  const location = useLocation();
  const how = useNavigationType();
  return <p data-testid="where">{`${page} at ${location.pathname}${location.search} (${how})`}</p>;
}

function renderRoutes(route: string) {
  return renderWithProviders(
    <Suspense fallback={null}>
      <Routes><Route path="*" element={<AppRoutes />} /></Routes>
    </Suspense>,
    { api: makeFakeApi({}), route },
  );
}

/** The analysis pages retired in issue 0005. */
const RETIRED_ROUTES = [
  '/briefing',
  '/briefing/topics',
  '/briefing/vertical',
  '/briefing/vertical/source/s1',
  '/stories',
  '/inbox',
  '/experts',
  '/tracks',
];

describe('routes', () => {
  it.each(RETIRED_ROUTES)('%s lands on the feed, replacing the history entry', async (route) => {
    renderRoutes(route);
    expect(await screen.findByTestId('where')).toHaveTextContent('reader at / (REPLACE)');
  });

  it('a track opens the reader scoped to it, replacing the history entry', async () => {
    renderRoutes('/tracks/t1');
    expect(await screen.findByTestId('where')).toHaveTextContent('reader at /read/folder/t1 (REPLACE)');
  });

  it('a track link keeps the reader params and drops the old time window', async () => {
    renderRoutes('/tracks/t%201?days=7&filter=all&view=by_source');
    expect(await screen.findByTestId('where')).toHaveTextContent('reader at /read/folder/t%201?filter=all&view=by_source (REPLACE)');
  });

  it.each([
    ['/', 'reader at /'],
    ['/posts/p1', 'post at /posts/p1'],
    ['/settings/sources?tab=health', 'sources at /settings/sources?tab=health'],
  ])('%s still renders', async (route, text) => {
    renderRoutes(route);
    expect(await screen.findByTestId('where')).toHaveTextContent(`${text} (POP)`);
  });

  it.each([
    ['/ingestion', '/settings/sources?tab=ingestion'],
    ['/ingestion/main', '/settings/sources?tab=ingestion'],
    ['/ingestion/jobs', '/settings/sources?tab=ingestion&sub=jobs'],
    ['/ingestion/missions?job=j1', '/settings/sources?tab=ingestion&sub=jobs&job=j1'],
    ['/ingestion/logs', '/settings/sources?tab=ingestion&sub=logs'],
    ['/ingestion/archive', '/settings/sources?tab=ingestion&sub=archive'],
  ])('%s moves to the sources ingestion tab, replacing the history entry', async (route, target) => {
    renderRoutes(route);
    expect(await screen.findByTestId('where')).toHaveTextContent(`sources at ${target} (REPLACE)`);
  });
});
