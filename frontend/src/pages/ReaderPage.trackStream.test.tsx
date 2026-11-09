// v10.12.1: a topic track's Stream lists only the posts in the track (the server decides; the reader asks with
// all_sources=1 for every post of its sources), the toolbar counts its own unread items, a quiet line says how many of
// its sources' posts are still being judged, and the switch "All posts from its sources" is kept in the URL. A plain
// folder has no switch. Synthetic data.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import ReaderPage from './ReaderPage';
import { feedItem, feedPage } from '../components/reader/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { healthResponse } from '../components/ops/fixtures';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import { trackCountsApi } from '../hooks/useTrackCounts';
import type { Api } from '../services/api';

const TOPIC = '00000000-0000-4000-8000-0000000000f1';
const PLAIN = '00000000-0000-4000-8000-0000000000f2';

function base() {
  return makeFakeApi({
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [
      { id: TOPIC, name: 'Local setups', source_count: 2 }, { id: PLAIN, name: 'Agentic News', source_count: 3 }] }),
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([])),
    getOperationsOverview: vi.fn().mockResolvedValue({ success: true, jobs: [] }),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 4, by_source: {}, by_folder: { [TOPIC]: 1321, [PLAIN]: 5 } }),
    getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ id: '00000000-0000-4000-8000-000000000009' })])),
    getMarkxOn: vi.fn().mockResolvedValue({ on: true }),
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
        <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
      </Routes>
      <Where />
    </>,
    { api, route },
  );
}

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
  vi.restoreAllMocks();
  vi.spyOn(trackCountsApi, 'counts').mockResolvedValue({ by_track: { [TOPIC]: { unread: 12, discover: 7, count: 19, waiting: 40 } } });
});

const allSourcesSwitch = () => screen.findByRole('switch', { name: 'All posts from its sources' });

describe('a topic track lists only its posts (v10.12.1)', () => {
  it('Stream: its items, its own count, the waiting line; the switch lists every post of its sources', async () => {
    const api = base();
    render(api, `/read/folder/${TOPIC}?view=stream`);
    const toggle = await allSourcesSwitch();
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect((await screen.findAllByText('12 unread')).length).toBeGreaterThan(0);
    expect(screen.getByTestId('reader-track-waiting')).toHaveTextContent('40 posts from its sources are still being judged');
    await vi.waitFor(() => expect(api.getFeed).toHaveBeenCalled());
    expect(vi.mocked(api.getFeed).mock.calls.every(([params]) => !params.allSources)).toBe(true);

    await userEvent.click(toggle);
    expect(screen.getByTestId('where').textContent).toBe(`/read/folder/${TOPIC}?view=stream&all_sources=1`);
    expect(await allSourcesSwitch()).toHaveAttribute('aria-checked', 'true');
    await vi.waitFor(() => expect(vi.mocked(api.getFeed).mock.calls.some(([params]) => params.allSources === true)).toBe(true));
    expect((await screen.findAllByText('1,321 unread')).length).toBeGreaterThan(0);
    expect(screen.queryByTestId('reader-track-waiting')).toBeNull();
  });

  it('the switch is kept in the URL', async () => {
    const api = base();
    render(api, `/read/folder/${TOPIC}?view=stream&all_sources=1`);
    expect(await allSourcesSwitch()).toHaveAttribute('aria-checked', 'true');
    await vi.waitFor(() => expect(vi.mocked(api.getFeed).mock.calls.some(([params]) => params.allSources === true)).toBe(true));
  });

  it('mark read up to here asks for the list shown: its items, or every post with the switch on', async () => {
    const user = userEvent.setup();
    const ID = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;
    const items = [feedItem({ id: ID(1), title: 'One' }), feedItem({ id: ID(2), title: 'Two' })];
    const markReadThrough = vi.fn().mockResolvedValue({ success: true, updated: 2, ids: [ID(1), ID(2)] });
    for (const [search, all] of [['?view=stream', false], ['?view=stream&all_sources=1', true]] as const) {
      markReadThrough.mockClear();
      const api = base();
      api.getFeed = vi.fn().mockResolvedValue(feedPage(items));
      api.markReadThrough = markReadThrough;
      const { unmount } = render(api, `/read/folder/${TOPIC}${search}`);
      await screen.findAllByRole('article');
      await user.keyboard('jj');
      await user.keyboard('{Shift>}A{/Shift}');
      await user.click(await screen.findByRole('button', { name: 'Mark read' }));
      const args = [`folder:${TOPIC}`, expect.any(String), expect.any(String), ...(all ? [true] : [])];
      expect(markReadThrough).toHaveBeenCalledWith(...args);
      unmount();
    }
  });

  it('a plain folder has no switch and lists its sources’ posts', async () => {
    const api = base();
    render(api, `/read/folder/${PLAIN}`);
    await vi.waitFor(() => expect(api.getFeed).toHaveBeenCalled());
    expect((await screen.findAllByText('5 unread')).length).toBeGreaterThan(0);
    expect(screen.queryByRole('switch', { name: 'All posts from its sources' })).toBeNull();
    expect(screen.queryByTestId('reader-track-waiting')).toBeNull();
  });
});
