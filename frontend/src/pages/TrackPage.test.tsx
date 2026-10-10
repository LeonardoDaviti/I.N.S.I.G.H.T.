import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import TrackPage from './TrackPage';
import { apiService, type Post } from '../services/api';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { runReport } from '../components/ops/fixtures';

const TRACK = 'f8571844-1065-4d96-85b5-1dfd9dc7b111';

function post(id: string, title: string): Post {
  return {
    id, title, url: `https://example.com/${id}`, platform: 'rss', source_display_name: 'Simon Willison’s Weblog',
    published_at: new Date(Date.now() - 3 * 24 * 3_600_000).toISOString(),
  } as Post;
}

function renderTrack(route = `/tracks/${TRACK}`, api = makeFakeApi({})) {
  return renderWithProviders(
    <Routes><Route path="/tracks/:trackId" element={<TrackPage />} /></Routes>,
    { api, route },
  );
}

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

const page = (posts: Post[]) => ({ success: true as const, folder: { id: TRACK, name: 'Agentic News', kind: 'track' } as never, source_count: 1, total: posts.length, posts });

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

  it('an older response that lands last does not replace the newer window', async () => {
    const user = userEvent.setup();
    const all = deferred<ReturnType<typeof page>>();
    vi.spyOn(apiService, 'getFolderPosts').mockImplementation((_id, opts) => (
      opts?.days === 7 ? Promise.resolve(page([post('w', 'This week only')])) : all.promise
    ));
    renderTrack();
    const group = await screen.findByRole('radiogroup', { name: 'Time window' });
    await user.click(within(group).getByRole('radio', { name: '7d' }));
    expect(await screen.findByText('This week only')).toBeInTheDocument();

    all.resolve(page([post('old', 'Everything, late')]));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText('Everything, late')).toBeNull();
    expect(screen.getByText('This week only')).toBeInTheDocument();
  });

  it('Fetch this track reloads with the window chosen while it ran', async () => {
    const user = userEvent.setup();
    const report = deferred<unknown>();
    const spy = vi.spyOn(apiService, 'getFolderPosts').mockResolvedValue(page([post('p1', 'Claude Code ships hooks')]));
    renderTrack(`/tracks/${TRACK}`, makeFakeApi({ fetchFolderNow: vi.fn().mockReturnValue(report.promise) }));
    await screen.findByText('Claude Code ships hooks');

    await user.click(screen.getByRole('button', { name: /Fetch this track/ }));
    await user.click(within(screen.getByRole('radiogroup', { name: 'Time window' })).getByRole('radio', { name: '30d' }));
    report.resolve(runReport({ posts_inserted: 3, selector: { kind: 'folder', id: TRACK } }));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(3));
    expect(spy).toHaveBeenLastCalledWith(TRACK, expect.objectContaining({ days: 30 }));
  });
});
