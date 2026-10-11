import { Suspense } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { Route, Routes, useLocation, useNavigationType } from 'react-router-dom';

import { AppRoutes } from './App';
import { makeFakeApi } from './test/fakeApi';
import { renderWithProviders } from './test/render';

// The pages are stand-ins: these tests are about which route renders, not the pages.
vi.mock('./pages/ReaderPage', () => ({ default: () => <Where page="reader" /> }));
vi.mock('./pages/DailyBriefing', () => ({ default: () => <Where page="briefing" /> }));
vi.mock('./pages/VerticalBriefingPage', () => ({ default: () => <Where page="vertical briefing" /> }));
vi.mock('./pages/StoriesExplorerPage', () => ({ default: () => <Where page="stories" /> }));
vi.mock('./pages/AnalystInboxPage', () => ({ default: () => <Where page="inbox" /> }));
vi.mock('./pages/ExpertsPage', () => ({ default: () => <Where page="experts" /> }));
vi.mock('./pages/IngestionControl', () => ({ default: () => <Where page="ingestion" /> }));
vi.mock('./pages/SourcesConfig', () => ({ default: () => <Where page="sources" /> }));
vi.mock('./pages/PostDetailPage', () => ({ default: () => <Where page="post" /> }));

function Where({ page }: { page: string }) {
  const location = useLocation();
  const how = useNavigationType();
  return <p data-testid="where">{`${page} at ${location.pathname}${location.search} (${how})`}</p>;
}

function renderRoutes(route: string, analysis: boolean | null) {
  const api = makeFakeApi({
    getConfig: analysis === null
      ? vi.fn().mockRejectedValue(new Error('Not Found'))
      : vi.fn().mockResolvedValue({ analysis_enabled: analysis }),
  });
  return renderWithProviders(
    <Suspense fallback={null}>
      <Routes><Route path="*" element={<AppRoutes />} /></Routes>
    </Suspense>,
    { api, route },
  );
}

const ANALYSIS_ROUTES: Array<[string, string]> = [
  ['/briefing', 'briefing'],
  ['/briefing/topics', 'briefing'],
  ['/briefing/vertical', 'vertical briefing'],
  ['/briefing/vertical/source/s1', 'vertical briefing'],
  ['/stories', 'stories'],
  ['/inbox', 'inbox'],
  ['/experts', 'experts'],
  ['/tracks', 'experts'],
];

describe('routes, analysis off (reading-only)', () => {
  it.each(ANALYSIS_ROUTES)('%s lands on the feed, replacing the history entry', async (route) => {
    renderRoutes(route, false);
    expect(await screen.findByTestId('where')).toHaveTextContent('reader at / (REPLACE)');
  });

  it('a track opens the reader scoped to it, replacing the history entry', async () => {
    renderRoutes('/tracks/t1', false);
    expect(await screen.findByTestId('where')).toHaveTextContent('reader at /read/folder/t1 (REPLACE)');
  });

  it('a track link keeps the reader params and drops the old time window', async () => {
    renderRoutes('/tracks/t%201?days=7&filter=all&view=by_source', false);
    expect(await screen.findByTestId('where')).toHaveTextContent('reader at /read/folder/t%201?filter=all&view=by_source (REPLACE)');
  });

  it.each([
    ['/', 'reader at /'],
    ['/posts/p1', 'post at /posts/p1'],
    ['/settings/sources?tab=health', 'sources at /settings/sources?tab=health'],
  ])('%s still renders', async (route, text) => {
    renderRoutes(route, false);
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
    renderRoutes(route, false);
    expect(await screen.findByTestId('where')).toHaveTextContent(`sources at ${target} (REPLACE)`);
  });

  it('with no runtime answer, the build flag (off in tests) decides', async () => {
    renderRoutes('/stories', null);
    expect(await screen.findByTestId('where')).toHaveTextContent('reader at / (REPLACE)');
  });
});

describe('routes, analysis on', () => {
  it.each(ANALYSIS_ROUTES)('%s renders %s', async (route, page) => {
    renderRoutes(route, true);
    expect(await screen.findByTestId('where')).toHaveTextContent(`${page} at ${route} (POP)`);
  });

  it('a track opens the reader scoped to it too', async () => {
    renderRoutes('/tracks/t1?days=30', true);
    expect(await screen.findByTestId('where')).toHaveTextContent('reader at /read/folder/t1 (REPLACE)');
  });

  it.each(['/ingestion', '/ingestion/jobs'])('%s still renders the ingestion page', async (route) => {
    renderRoutes(route, true);
    expect(await screen.findByTestId('where')).toHaveTextContent(`ingestion at ${route} (POP)`);
  });

  it('the runtime value wins over the build flag: a deep link waits for it instead of bouncing', async () => {
    let answer: (value: { analysis_enabled: boolean }) => void = () => {};
    const api = makeFakeApi({ getConfig: vi.fn().mockReturnValue(new Promise((resolve) => { answer = resolve; })) });
    renderWithProviders(
      <Suspense fallback={null}><Routes><Route path="*" element={<AppRoutes />} /></Routes></Suspense>,
      { api, route: '/stories' },
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText(/reader at/)).toBeNull();
    answer({ analysis_enabled: true });
    expect(await screen.findByTestId('where')).toHaveTextContent('stories at /stories (POP)');
  });
});
