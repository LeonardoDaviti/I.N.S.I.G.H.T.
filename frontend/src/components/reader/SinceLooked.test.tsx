import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import SinceLooked from './SinceLooked';
import type { FeedItem, SinceLooked as Since } from '../../services/api';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const row = (id: string, title: string, voices: number) =>
  ({ id, title, story: { id, voices, sources: [], posts: [] } } as unknown as FeedItem);

const DATA: Since = {
  look: new Date(Date.now() - 3 * 3600_000).toISOString(), first: false,
  news: {
    counts: { new: 1, changed: 1 },
    new: [row('a', 'Vexa 3 released', 4)],
    changed: [{ ...row('b', 'Tessel 2 preview', 3), since: { voices: ['Bench Blog', 'Lab Notes'], lines: [{ id: 'c', title: 'Tessel 2 benchmarks', source: 'Bench Blog' }] } }],
  },
  tracks: [{ id: 't1', name: 'Local Setups', since: '', new: 2, also: 1, lines: [{ text: 'Tessel 2 on a 24 GB card', kind: 'setup', sources: 2, post: 'd' }] }],
};

describe('Since you looked (0271, invented rows)', () => {
  it('lists the new rows, the changed rows with who joined, each track, then moves the look once', async () => {
    const lookSince = vi.fn().mockResolvedValue({ before: DATA.look, now: new Date().toISOString() });
    renderWithProviders(<SinceLooked />, { api: makeFakeApi({ getSince: vi.fn().mockResolvedValue(DATA), lookSince }) });
    expect(await screen.findByText('Vexa 3 released')).toBeInTheDocument();
    expect(screen.getByText('New in News (1)')).toBeInTheDocument();
    expect(screen.getByText('Changed (1)')).toBeInTheDocument();
    expect(screen.getByText(/\+ Bench Blog, Lab Notes/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Tessel 2 benchmarks' })).toHaveAttribute('href', '/posts/c');
    expect(screen.getByRole('link', { name: 'Local Setups' })).toBeInTheDocument();
    expect(screen.getByText('(3 new)', { exact: false })).toBeInTheDocument();
    await waitFor(() => expect(lookSince).toHaveBeenCalledTimes(1));
  });

  it('says when nothing is new', async () => {
    const empty: Since = { ...DATA, news: { counts: { new: 0, changed: 0 }, new: [], changed: [] }, tracks: [] };
    renderWithProviders(<SinceLooked />, { api: makeFakeApi({ getSince: vi.fn().mockResolvedValue(empty), lookSince: vi.fn().mockResolvedValue({}) }) });
    expect(await screen.findByText(/^Nothing new since you looked/)).toBeInTheDocument();
  });
});
