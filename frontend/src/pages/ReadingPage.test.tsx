import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import ReadingPage from './ReadingPage';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { readingApi, type ReadingSummary } from '../services/reading';

const SUMMARY: ReadingSummary = {
  days: 7,
  since: '2026-11-19T10:00:00Z',
  posts: [
    { day: '2026-11-26', post_id: 'p1', at: '2026-11-26T09:15:00Z', title: 'A model ships', source_id: 's1', source: 'Example Blog',
      active_seconds: 250, open_seconds: 900, depth: 0.82, source_opened: true, tracks: [{ id: 't1', name: 'AI' }] },
    { day: '2026-11-25', post_id: 'p2', at: '2026-11-25T20:00:00Z', title: 'An older read', source_id: 's1', source: 'Example Blog',
      active_seconds: null, open_seconds: 40, depth: null, source_opened: false, tracks: [] },
  ],
  posts_total: 2,
  by_source: [{ id: 's1', name: 'Example Blog', posts: 2, active_seconds: 250, originals_opened: 1 }],
  by_track: [{ id: 't1', name: 'AI', posts: 1, active_seconds: 250, originals_opened: 1 }],
  by_story: [{ id: 'st1', name: 'A model ships', posts: 1, active_seconds: 250, originals_opened: 1 }],
  seen_by_source: [{ id: 's1', name: 'Example Blog', seen: 12, opened: 2 }],
  seen_by_track: [{ id: 't1', name: 'AI', seen: 5, opened: 1 }],
};

function renderPage() {
  return renderWithProviders(<Routes><Route path="/reading" element={<ReadingPage />} /></Routes>,
    { api: makeFakeApi({}), route: '/reading' });
}

afterEach(() => vi.restoreAllMocks());

describe('ReadingPage', () => {
  it('lists the posts opened by day with active time, depth and the original, then the totals and what was seen', async () => {
    const summary = vi.spyOn(readingApi, 'summary').mockResolvedValue(SUMMARY);
    renderPage();
    expect(await screen.findByRole('heading', { level: 1, name: 'Your reading' })).toBeInTheDocument();
    expect(summary).toHaveBeenCalledWith(7);

    const first = (await screen.findAllByRole('link', { name: 'A model ships' }))[0].closest('tr')!;
    expect(first).toHaveTextContent('4m 10s');
    expect(first).toHaveTextContent('82%');
    expect(first).toHaveTextContent('opened');
    const older = screen.getByRole('link', { name: 'An older read' }).closest('tr')!;
    expect(older).toHaveTextContent('40s open');   // an old session: its open time, said so

    const seen = screen.getByRole('table', { name: 'Seen by source' });
    expect(within(seen).getByRole('row', { name: /Example Blog/ })).toHaveTextContent(/12\s*2\s*10/);
    expect(screen.getByRole('table', { name: 'Story' })).toHaveTextContent('A model ships');
    expect(screen.getByText(/2 posts opened/)).toBeInTheDocument();
  });

  it('asks for 30 days and all time', async () => {
    const user = userEvent.setup();
    const summary = vi.spyOn(readingApi, 'summary').mockResolvedValue(SUMMARY);
    renderPage();
    await screen.findByRole('table', { name: 'Source' });
    await user.click(screen.getByRole('radio', { name: '30 days' }));
    await user.click(screen.getByRole('radio', { name: 'All time' }));
    expect(summary.mock.calls.map((c) => c[0])).toEqual([7, 30, 'all']);
  });
});
