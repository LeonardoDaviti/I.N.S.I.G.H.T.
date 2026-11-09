// 0145: a track, while Mark X is on, offers View Topic; the Main feed and a source never do. Synthetic data only.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import ReaderPage from './ReaderPage';
import '../components/tracks/TrackTopic';
import { feedItem, feedPage } from '../components/reader/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { healthResponse } from '../components/ops/fixtures';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import { tracksApi, type TrackPage } from '../services/tracks';
import type { Api } from '../services/api';

const FOLDER = '00000000-0000-4000-8000-0000000000f1';

function base(on: boolean, methods: Partial<Record<keyof Api, unknown>> = {}) {
  return makeFakeApi({
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [{ id: FOLDER, name: 'Prints', source_count: 2 }] }),
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([])),
    getOperationsOverview: vi.fn().mockResolvedValue({ success: true, jobs: [] }),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 4, by_source: {}, by_folder: {} }),
    getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ id: '00000000-0000-4000-8000-000000000009' })])),
    getMarkxOn: on ? vi.fn().mockResolvedValue({ on: true }) : vi.fn().mockRejectedValue(new Error('Not Found')),
    ...methods,
  });
}

function render(api: Api, route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<ReaderPage />} />
      <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
    </Routes>,
    { api, route },
  );
}

const FOLDER_PAGE: TrackPage = {
  track: { id: FOLDER, name: 'Prints', kind: 'track', topic: false, description: null, excludes: null, sources: [] },
  sections: [], discover: [], counts: {}, calibration: null, suggestions: [], examples: { in: [], out: [] }, subtopics: [],
  footer: null, prefilter: null,
};

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('View Topic (issue 0145)', () => {
  it('a track offers Topic while Mark X is on, and opens it', async () => {
    const page = vi.spyOn(tracksApi, 'page').mockResolvedValue(FOLDER_PAGE);
    render(base(true), `/read/folder/${FOLDER}`);
    const view = await screen.findByRole('radiogroup', { name: 'View' });
    await within(view).findByRole('radio', { name: 'Topic' });
    await userEvent.click(within(view).getByRole('radio', { name: 'Topic' }));
    expect(await screen.findByText('This track is a folder of sources')).toBeInTheDocument();
    expect(page).toHaveBeenCalledWith(FOLDER);
    expect(screen.queryByRole('radiogroup', { name: 'Show' })).not.toBeInTheDocument();
  });

  it('the Main feed never offers it', async () => {
    render(base(true), '/');
    const view = await screen.findByRole('radiogroup', { name: 'View' });
    expect(within(view).queryByRole('radio', { name: 'Topic' })).toBeNull();
  });

  it('a track while Mark X is off', async () => {
    render(base(false), `/read/folder/${FOLDER}`);
    const view = await screen.findByRole('radiogroup', { name: 'View' });
    await new Promise((r) => setTimeout(r, 20));
    expect(within(view).getAllByRole('radio').map((r) => r.textContent)).toEqual(['Stream', 'By source', 'News', 'Classics']);
  });
});
