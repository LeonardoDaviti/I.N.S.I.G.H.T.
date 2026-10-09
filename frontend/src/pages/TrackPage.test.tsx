import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import TrackPage from './TrackPage';
import { apiService, type Post } from '../services/api';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';

const TRACK = 'f8571844-1065-4d96-85b5-1dfd9dc7b111';

function post(id: string, title: string): Post {
  return {
    id, title, url: `https://example.com/${id}`, platform: 'rss', source_display_name: 'Simon Willison’s Weblog',
    published_at: new Date(Date.now() - 3 * 24 * 3_600_000).toISOString(),
  } as Post;
}

function renderTrack(route = `/tracks/${TRACK}`) {
  return renderWithProviders(
    <Routes><Route path="/tracks/:trackId" element={<TrackPage />} /></Routes>,
    { api: makeFakeApi({}), route },
  );
}

beforeEach(() => {
  vi.spyOn(apiService, 'getMilestones').mockResolvedValue({ success: true } as never);
  vi.spyOn(apiService, 'getExperts').mockResolvedValue({ success: true, experts: [] });
});
afterEach(() => vi.restoreAllMocks());

describe('TrackPage', () => {
  it('renders the track on Mark IX parts: back to tracks, a track chip, rows that link to the post', async () => {
    vi.spyOn(apiService, 'getFolderPosts').mockResolvedValue({
      success: true,
      folder: { id: TRACK, name: 'Agentic News', kind: 'track', exclude_from_main_digest: true } as never,
      source_count: 1,
      total: 2,
      posts: [post('p1', 'Claude Code ships hooks'), post('p2', 'مراجعة النماذج اللغوية')],
    });
    renderTrack();
    expect(await screen.findByRole('heading', { level: 1, name: /Agentic News/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to tracks' })).toHaveAttribute('href', '/tracks');
    expect(screen.getByText('track')).toBeInTheDocument();
    expect(screen.getByText(/1 source · 2 posts · hidden from the main digest/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Claude Code ships hooks/ })).toHaveAttribute('href', '/posts/p1');
    expect(screen.getByText('مراجعة النماذج اللغوية')).toHaveAttribute('dir', 'auto');
  });

  it('the time window is a slash radio group in the URL', async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(apiService, 'getFolderPosts').mockResolvedValue({ success: true, posts: [], total: 0, source_count: 2 });
    renderTrack();
    const group = await screen.findByRole('radiogroup', { name: 'Time window' });
    expect(within(group).getByRole('radio', { name: 'all' })).toHaveAttribute('aria-checked', 'true');
    await user.click(within(group).getByRole('radio', { name: '7d' }));
    expect(within(group).getByRole('radio', { name: '7d' })).toHaveAttribute('aria-checked', 'true');
    expect(spy).toHaveBeenLastCalledWith(TRACK, expect.objectContaining({ days: 7 }));
  });

  it('a failed load is the monochrome error state with a retry', async () => {
    vi.spyOn(apiService, 'getFolderPosts').mockResolvedValue({ success: false, posts: [], error: 'Track not found' });
    renderTrack();
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('Track not found')).toBeInTheDocument();
    expect(within(alert).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
