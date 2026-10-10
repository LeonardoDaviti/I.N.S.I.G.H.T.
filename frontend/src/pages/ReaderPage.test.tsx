import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import ReaderPage from './ReaderPage';
import { feedItem, feedPage } from '../components/reader/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { healthResponse, healthRow } from '../components/ops/fixtures';
import { feedCursorFor } from '../lib/feedContext';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import { apiService, type Api } from '../services/api';

const ID = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;

function base(methods: Partial<Record<keyof Api, unknown>>) {
  return makeFakeApi({
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [] }),
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([])),
    getPostDetail: vi.fn().mockResolvedValue({ success: true, post: { id: 'x' } }),
    ...methods,
  });
}

function render(api: Api, route?: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<ReaderPage />} />
      <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
    </Routes>,
    { api, route },
  );
}

// sonner's toast calls setPointerCapture on press; jsdom has no pointer capture.
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.hasPointerCapture = () => false;
}

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('ReaderPage', () => {
  it('opens on the unread main feed', async () => {
    const getFeed = vi.fn().mockResolvedValue(feedPage([feedItem({ id: ID(1) })]));
    render(base({ getFeed, getUnreadCounts: vi.fn().mockResolvedValue({ total: 1, by_source: {}, by_folder: {} }) }));
    await screen.findAllByRole('article');
    expect(getFeed).toHaveBeenCalledWith(expect.objectContaining({ scope: 'all', filter: 'unread' }));
    expect(screen.getByRole('radio', { name: 'Unread' })).toHaveAttribute('aria-checked', 'true');
  });

  it('a rising unread count shows the "N new posts" pill; the list only changes when it is clicked', async () => {
    const user = userEvent.setup();
    const getFeed = vi.fn()
      .mockResolvedValueOnce(feedPage([feedItem({ id: ID(1), title: 'Old post' })]))
      .mockResolvedValueOnce(feedPage([feedItem({ id: ID(2), title: 'Brand new post' }), feedItem({ id: ID(1), title: 'Old post' })]));
    const getUnreadCounts = vi.fn()
      .mockResolvedValueOnce({ total: 10, by_source: {}, by_folder: {} })
      .mockResolvedValue({ total: 13, by_source: {}, by_folder: {} });
    const { queryClient } = render(base({ getFeed, getUnreadCounts }));
    await screen.findByText('Old post');
    await waitFor(() => expect(getUnreadCounts).toHaveBeenCalledTimes(1));

    // A finished ingestion run invalidates only ['unread-counts'] (useIngestionRun).
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ['unread-counts'] }); });

    const pill = await screen.findByRole('button', { name: /3 new posts/ });
    expect(screen.queryByText('Brand new post')).not.toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(getFeed).toHaveBeenCalledTimes(1);

    await user.click(pill);
    expect(await screen.findByText('Brand new post')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /new posts/ })).not.toBeInTheDocument();
  });

  it('Shift+A asks first, marks read through the selection, and the toast Undo restores them', async () => {
    const user = userEvent.setup();
    const items = [feedItem({ id: ID(1), title: 'One' }), feedItem({ id: ID(2), title: 'Two' }), feedItem({ id: ID(3), title: 'Three' })];
    const markReadThrough = vi.fn().mockResolvedValue({ success: true, updated: 2, ids: [ID(1), ID(2)] });
    const setPostsRead = vi.fn().mockResolvedValue({ success: true, updated: 2 });
    render(base({
      getFeed: vi.fn().mockResolvedValue(feedPage(items)),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 3, by_source: {}, by_folder: {} }),
      markReadThrough,
      setPostsRead,
    }));
    await screen.findAllByRole('article');
    await user.keyboard('jj');
    await user.keyboard('{Shift>}A{/Shift}');

    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('2 posts');
    expect(markReadThrough).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', { name: 'Mark read' }));

    expect(markReadThrough).toHaveBeenCalledWith('all', feedCursorFor(items[1]), feedCursorFor(items[0]));
    expect(await screen.findByText('Marked 2 posts as read', { selector: '[data-title]' })).toBeInTheDocument();
    await waitFor(() => expect(document.getElementById('reader-live-region')).toHaveTextContent('Marked 2 posts as read'));
    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(setPostsRead).toHaveBeenCalledWith([ID(1), ID(2)], false));
  });

  it('the filter switch changes the query; window focus does not refetch the feed', async () => {
    const user = userEvent.setup();
    const getFeed = vi.fn().mockResolvedValue(feedPage([feedItem({ id: ID(1) })]));
    render(base({ getFeed, getUnreadCounts: vi.fn().mockResolvedValue({ total: 1, by_source: {}, by_folder: {} }) }));
    await screen.findAllByRole('article');
    window.dispatchEvent(new Event('focus'));
    document.dispatchEvent(new Event('visibilitychange'));
    expect(getFeed).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('radio', { name: 'Starred' }));
    await waitFor(() => expect(getFeed).toHaveBeenLastCalledWith(expect.objectContaining({ filter: 'starred' })));
  });

  it('says ingestion has stopped instead of "all caught up" when nothing was fetched for a day', async () => {
    const twoDaysAgo = new Date(Date.now() - 48 * 3_600_000).toISOString();
    render(base({
      getFeed: vi.fn().mockResolvedValue(feedPage([])),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 0, by_source: {}, by_folder: {} }),
      getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([healthRow({ source_id: 's1', last_attempt_at: twoDaysAgo, last_success_at: twoDaysAgo })])),
    }));
    const notice = await screen.findByTestId('reader-ingestion-stopped');
    expect(notice).toHaveTextContent(/not running/i);
    expect(notice).toHaveTextContent(/last fetch was 2d ago/);
    expect(await screen.findByText(/No new posts: ingestion has stopped/)).toBeInTheDocument();
    expect(screen.queryByText(/all caught up/i)).toBeNull();
  });

  it('a recent fetch keeps the calm "all caught up"', async () => {
    render(base({
      getFeed: vi.fn().mockResolvedValue(feedPage([])),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 0, by_source: {}, by_folder: {} }),
      getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([healthRow({ source_id: 's1', last_attempt_at: new Date().toISOString() })])),
    }));
    expect(await screen.findByText(/all caught up/i)).toBeInTheDocument();
    expect(screen.queryByTestId('reader-ingestion-stopped')).toBeNull();
  });

  it('offers no fetch: fetching is an ingestion job, not part of reading', async () => {
    const user = userEvent.setup();
    const fetchSourceNow = vi.fn();
    const runIngestionCycle = vi.fn();
    render(base({
      getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ id: ID(1) })])),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 1, by_source: {}, by_folder: {} }),
      fetchSourceNow, runIngestionCycle,
    }));
    await screen.findAllByRole('article');
    expect(screen.queryByRole('button', { name: /fetch/i })).toBeNull();
    await user.keyboard('f');
    expect(fetchSourceNow).not.toHaveBeenCalled();
    expect(runIngestionCycle).not.toHaveBeenCalled();
    await user.keyboard('?');
    const dialog = await screen.findByRole('dialog', { name: /keyboard shortcuts/i });
    expect(within(dialog).queryByText(/fetch/i)).toBeNull();
  });

  it('an empty source says there are no posts yet and links quietly to Sources', async () => {
    render(base({
      getFeed: vi.fn().mockResolvedValue(feedPage([])),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 0, by_source: {}, by_folder: {} }),
    }), `/read/source/${ID(7)}?filter=all`);
    expect(await screen.findByText('No posts here yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sources/i })).toHaveAttribute('href', `/settings/sources?source=${ID(7)}`);
    expect(screen.queryByRole('button', { name: /fetch/i })).toBeNull();
  });
});

// The retired track page's analysis surfaces (Design Studio D5): with analysis on,
// a folder scope carries the track briefing and the milestones rail.
describe('ReaderPage, folder scope', () => {
  const FOLDER = ID(5);
  const scoped = (analysis: boolean) => base({
    getConfig: vi.fn().mockResolvedValue({ analysis_enabled: analysis }),
    getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ id: ID(1), title: 'Claude Code ships hooks' })])),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 1, by_source: {}, by_folder: {} }),
  });

  beforeEach(() => {
    vi.spyOn(apiService, 'getMilestones').mockResolvedValue({ success: true } as never);
    vi.spyOn(apiService, 'getExperts').mockResolvedValue({ success: true, experts: [] });
  });
  afterEach(() => vi.restoreAllMocks());

  it('with analysis on, shows the track briefing and the milestones rail for that folder', async () => {
    render(scoped(true), `/read/folder/${FOLDER}`);
    await screen.findByText('Claude Code ships hooks');
    expect(await screen.findByRole('complementary', { name: 'Milestones' })).toBeInTheDocument();
    await waitFor(() => expect(apiService.getMilestones).toHaveBeenCalledWith({ folderId: FOLDER }));
    await waitFor(() => expect(apiService.getExperts).toHaveBeenCalled());
  });

  it('reading-only, a folder is just its posts: no briefing, no milestones', async () => {
    render(scoped(false), `/read/folder/${FOLDER}`);
    await screen.findByText('Claude Code ships hooks');
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole('complementary', { name: 'Milestones' })).toBeNull();
    expect(apiService.getMilestones).not.toHaveBeenCalled();
    expect(apiService.getExperts).not.toHaveBeenCalled();
  });

  it('with analysis on, a source scope adds nothing', async () => {
    render(scoped(true), `/read/source/${ID(6)}`);
    await screen.findByText('Claude Code ships hooks');
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole('complementary', { name: 'Milestones' })).toBeNull();
    expect(apiService.getMilestones).not.toHaveBeenCalled();
  });
});

// Issue 0003: the scope name is one click from where the source is managed.
describe('ReaderPage, the scope name links into Sources', () => {
  const api = () => base({
    getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ id: ID(1) })])),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 1, by_source: {}, by_folder: {} }),
  });

  it.each([
    [`/read/source/${ID(7)}`, `/settings/sources?source=${ID(7)}`],
    [`/read/folder/${ID(5)}`, `/settings/sources?track=${ID(5)}`],
  ])('%s links its name to %s', async (route, href) => {
    render(api(), route);
    const heading = await screen.findByRole('heading', { level: 1 });
    expect(within(heading).getByRole('link')).toHaveAttribute('href', href);
  });

  it('the main feed name is plain text', async () => {
    render(api());
    const heading = await screen.findByRole('heading', { level: 1 });
    expect(within(heading).queryByRole('link')).toBeNull();
  });

  it('an empty scope points at that source in Sources', async () => {
    render(base({
      getFeed: vi.fn().mockResolvedValue(feedPage([])),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 0, by_source: {}, by_folder: {} }),
    }), `/read/folder/${ID(5)}?filter=all`);
    expect(await screen.findByRole('link', { name: 'This track in Sources' })).toHaveAttribute('href', `/settings/sources?track=${ID(5)}`);
  });
});
