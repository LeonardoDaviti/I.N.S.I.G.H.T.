// v10.12.1: a track that is a topic (Mark X on) opens on Topic unless the URL names a view, and the rail counts its
// unread items plus its Discover suggestions; a plain folder opens on Stream with its sources' count. Synthetic data.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import ReaderPage from './ReaderPage';
import '../components/tracks/TrackTopic';
import { feedItem, feedPage } from '../components/reader/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { healthResponse } from '../components/ops/fixtures';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import { trackCountsApi } from '../hooks/useTrackCounts';
import { tracksApi, type TrackPage } from '../services/tracks';
import type { Api } from '../services/api';

const TOPIC = '00000000-0000-4000-8000-0000000000f1';
const PLAIN = '00000000-0000-4000-8000-0000000000f2';

function base(on: boolean) {
  return makeFakeApi({
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [
      { id: TOPIC, name: 'Local setups', source_count: 0 }, { id: PLAIN, name: 'Agentic News', source_count: 3 }] }),
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([])),
    getOperationsOverview: vi.fn().mockResolvedValue({ success: true, jobs: [] }),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 4, by_source: {}, by_folder: { [PLAIN]: 5 } }),
    getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ id: '00000000-0000-4000-8000-000000000009' })])),
    getMarkxOn: on ? vi.fn().mockResolvedValue({ on: true }) : vi.fn().mockRejectedValue(new Error('Not Found')),
  });
}

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function render(api: Api, route: string) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/" element={<ReaderPage />} />
        <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
      </Routes>
      <Where />
    </>,
    { api, route },
  );
}

const TOPIC_PAGE: TrackPage = {
  track: { id: TOPIC, name: 'Local setups', kind: 'track', topic: true, description: 'Cheap local AI setups', excludes: null, sources: [] },
  sections: [], discover: [], counts: {}, calibration: null, suggestions: [], examples: { in: [], out: [] }, subtopics: [],
  footer: null, prefilter: null,
};

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
  vi.restoreAllMocks();
  vi.spyOn(trackCountsApi, 'counts').mockResolvedValue({ by_track: { [TOPIC]: { unread: 2, discover: 7, count: 9 } } });
  vi.spyOn(tracksApi, 'page').mockResolvedValue(TOPIC_PAGE);
});

const viewChoice = async () => screen.findByRole('radiogroup', { name: 'View' });

describe('a topic track opens on Topic (v10.12.1)', () => {
  it('opens on Topic, and Stream is one click away', async () => {
    const api = base(true);
    render(api, `/read/folder/${TOPIC}`);
    const view = await viewChoice();
    expect(await within(view).findByRole('radio', { name: 'Topic' })).toHaveAttribute('aria-checked', 'true');
    await vi.waitFor(() => expect(tracksApi.page).toHaveBeenCalledWith(TOPIC));
    expect(api.getFeed).not.toHaveBeenCalled();
    await userEvent.click(within(view).getByRole('radio', { name: 'Stream' }));
    expect(within(view).getByRole('radio', { name: 'Stream' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByTestId('where').textContent).toBe(`/read/folder/${TOPIC}?view=stream`);
    await userEvent.click(within(view).getByRole('radio', { name: 'Topic' }));
    expect(screen.getByTestId('where').textContent).toBe(`/read/folder/${TOPIC}`);
  });

  it('a view the URL names wins', async () => {
    render(base(true), `/read/folder/${TOPIC}?view=news`);
    const view = await viewChoice();
    await within(view).findByRole('radio', { name: 'Topic' });
    expect(within(view).getByRole('radio', { name: 'News' })).toHaveAttribute('aria-checked', 'true');
  });

  it('a plain folder opens on Stream, with its sources’ count in the rail; the topic track counts items and Discover', async () => {
    render(base(true), `/read/folder/${PLAIN}`);
    const view = await viewChoice();
    await within(view).findByRole('radio', { name: 'Topic' });
    expect(within(view).getByRole('radio', { name: 'Stream' })).toHaveAttribute('aria-checked', 'true');
    const rail = await screen.findByRole('navigation', { name: 'Main feed, tracks and sources' });
    expect(await within(rail).findByRole('link', { name: /Local setups.*9 unread/ })).toBeInTheDocument();
    expect(within(rail).getByRole('link', { name: /Agentic News.*5 unread/ })).toBeInTheDocument();
  });

  it('with Mark X off: Stream, no topic counts asked', async () => {
    render(base(false), `/read/folder/${TOPIC}`);
    const view = await viewChoice();
    await new Promise((r) => setTimeout(r, 20));
    expect(within(view).getByRole('radio', { name: 'Stream' })).toHaveAttribute('aria-checked', 'true');
    expect(trackCountsApi.counts).not.toHaveBeenCalled();
  });
});
