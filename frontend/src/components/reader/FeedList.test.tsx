import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import FeedList from './FeedList';
import { LiveRegionProvider } from './LiveRegion';
import { feedItem, feedPage } from './fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { resetStoredChoices, SHORTCUTS_KEY } from '../../hooks/useShortcutPreference';
import { ApiError } from '../../lib/apiError';
import { rememberSelection } from '../../lib/readerSelection';
import type { Api } from '../../services/api';

const ID = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;

function items() {
  return [
    feedItem({ id: ID(1), title: 'First post' }),
    feedItem({ id: ID(2), title: '', excerpt: 'A post with no text to take a title from' }),
    feedItem({ id: ID(3), title: 'Third post', media_thumb: 'https://img.example/thumb.jpg' }),
  ];
}

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="location">{location.pathname + location.search}</p>;
}

function setup(methods: Partial<Record<keyof Api, unknown>> = {}, props: Partial<Parameters<typeof FeedList>[0]> = {}) {
  const api = makeFakeApi({
    getFeed: vi.fn().mockResolvedValue(feedPage(items())),
    getPostDetail: vi.fn().mockResolvedValue({ success: true, post: { id: 'x' } }),
    ...methods,
  });
  const utils = renderWithProviders(
    <LiveRegionProvider>
      <Routes>
        <Route path="/" element={<FeedList scope="all" filter="unread" view="stream" density="comfortable" {...props} />} />
        <Route path="/posts/:postId" element={<LocationProbe />} />
      </Routes>
    </LiveRegionProvider>,
    { api },
  );
  return { api, ...utils };
}

const liveRegion = () => document.getElementById('reader-live-region') as HTMLElement;

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
  rememberSelection('');
});

describe('FeedList', () => {
  it('under day headers the row shows its time of day, not the header date again; source names are derived', async () => {
    const now = Date.now();
    const iso = (hoursAgo: number) => new Date(now - hoursAgo * 3_600_000).toISOString();
    const old = new Date(now - 12 * 24 * 3_600_000);
    setup({
      getFeed: vi.fn().mockResolvedValue(feedPage([
        feedItem({ id: ID(1), title: 'Fresh', sort_at: iso(2), published_at: iso(2) }),
        feedItem({ id: ID(2), title: 'Old one', sort_at: old.toISOString(), published_at: old.toISOString(), source_display_name: 'https://github.com/anthropics/claude-code/commits.atom' }),
        feedItem({ id: ID(3), title: 'Old two', sort_at: old.toISOString(), published_at: old.toISOString(), source_display_name: 'https://rss.arxiv.org/rss/cs.CL' }),
      ])),
    });
    const [fresh, oldOne] = await screen.findAllByRole('article');
    const clock = (date: Date) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date);
    expect(within(fresh).getByText(clock(new Date(iso(2))))).toBeInTheDocument();
    expect(within(oldOne).getByText(clock(old))).toBeInTheDocument();
    const shortDate = old.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    expect(within(oldOne).queryByText(shortDate)).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+[hd] ago/)).not.toBeInTheDocument();
    // The day headers are drawn for the eye only: the ARIA feed owns articles, and
    // each row reads its day out with its time.
    const headers = Array.from(document.querySelectorAll('[data-day-header]'));
    expect(headers).toHaveLength(2);
    expect(headers[1]).toHaveTextContent(shortDate);
    expect(headers[1]).toHaveAttribute('aria-hidden', 'true');
    expect(Array.from(screen.getByRole('feed').children).every((child) => child.tagName === 'ARTICLE' || child.hasAttribute('data-day-header'))).toBe(true);
    expect(oldOne.querySelector('time')).toHaveTextContent(`${shortDate}, ${clock(old)}`);
    expect(screen.getByText('anthropics/claude-code')).toBeInTheDocument();
    expect(screen.getByText('arXiv cs.CL')).toBeInTheDocument();
    expect(screen.queryByText(/github\.com|rss\.arxiv/)).not.toBeInTheDocument();
  });

  it('numbers the articles for the feed; the set size is unknown while more pages can load', async () => {
    setup({ getFeed: vi.fn().mockResolvedValue({ ...feedPage(items()), next_cursor: 'more' }) });
    const articles = await screen.findAllByRole('article');
    expect(articles.map((a) => a.getAttribute('aria-posinset'))).toEqual(['1', '2', '3']);
    expect(articles.every((a) => a.getAttribute('aria-setsize') === '-1')).toBe(true);
  });

  it('marks unread rows with the unread dot', async () => {
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([
      feedItem({ id: ID(1), title: 'Unread one', read_at: null }),
      feedItem({ id: ID(2), title: 'Read one', read_at: new Date().toISOString() }),
    ])) });
    const [unread, read] = await screen.findAllByRole('article');
    expect(unread.querySelector('[data-glyph="unread"]')).not.toBeNull();
    expect(read.querySelector('[data-glyph="unread"]')).toBeNull();
  });

  it('coming back from a post selects and focuses the post read last', async () => {
    rememberSelection(ID(2));
    setup();
    const articles = await screen.findAllByRole('article');
    await waitFor(() => expect(articles[1]).toHaveAttribute('aria-current', 'true'));
    expect(document.activeElement).toBe(articles[1]);
  });

  it('renders one article per item with exactly one link each', async () => {
    setup();
    const articles = await screen.findAllByRole('article');
    expect(articles).toHaveLength(3);
    for (const article of articles) expect(within(article).getAllByRole('link')).toHaveLength(1);
  });

  it('an item the API gives no title reads "Untitled post"; thumbnails load lazily', async () => {
    setup();
    expect(await screen.findByRole('link', { name: 'Untitled post' })).toBeInTheDocument();
    const img = document.querySelector('article img') as HTMLImageElement;
    expect(img).toHaveAttribute('loading', 'lazy');
    expect(img).toHaveAttribute('decoding', 'async');
  });

  it('j/k move aria-current, the roving tabIndex and DOM focus', async () => {
    const user = userEvent.setup();
    setup();
    const articles = await screen.findAllByRole('article');
    expect(articles.map((a) => a.tabIndex)).toEqual([0, -1, -1]);

    await user.keyboard('j');
    expect(articles[0]).toHaveAttribute('aria-current', 'true');
    expect(document.activeElement).toBe(articles[0]);

    await user.keyboard('j');
    expect(articles[1]).toHaveAttribute('aria-current', 'true');
    expect(articles[0]).not.toHaveAttribute('aria-current');
    expect(articles.map((a) => a.tabIndex)).toEqual([-1, 0, -1]);
    expect(document.activeElement).toBe(articles[1]);

    await user.keyboard('k');
    expect(document.activeElement).toBe(articles[0]);
  });

  it('o opens the selected post with ?ctx= and marks it read', async () => {
    const user = userEvent.setup();
    const setPostsRead = vi.fn().mockResolvedValue({ success: true });
    setup({ setPostsRead });
    await screen.findAllByRole('article');
    await user.keyboard('jjo');
    const location = await screen.findByTestId('location');
    expect(location.textContent).toBe(`/posts/${ID(2)}?ctx=${encodeURIComponent('all:unread:')}`);
    expect(setPostsRead).toHaveBeenCalledWith([ID(2)], true);
  });

  it('m marks read optimistically and announces it', async () => {
    const user = userEvent.setup();
    let resolve: (v: unknown) => void = () => {};
    const setPostsRead = vi.fn().mockReturnValue(new Promise((r) => { resolve = r; }));
    setup({ setPostsRead });
    await screen.findAllByRole('article');
    await user.keyboard('jm');
    // Optimistic: the row flips before the request settles.
    const first = screen.getAllByRole('article')[0];
    expect(within(first).getByRole('button', { name: 'Mark unread' })).toBeInTheDocument();
    expect(setPostsRead).toHaveBeenCalledWith([ID(1)], true);
    await act(async () => { resolve({ success: true }); });
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Marked as read'));
  });

  it('m rolls back when the request fails and announces the error', async () => {
    const user = userEvent.setup();
    const setPostsRead = vi.fn().mockRejectedValue(new ApiError(500, 'Could not update read state. Check the backend logs.'));
    setup({ setPostsRead });
    await screen.findAllByRole('article');
    await user.keyboard('jm');
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Could not update read state'));
    const first = screen.getAllByRole('article')[0];
    expect(within(first).getByRole('button', { name: 'Mark read' })).toBeInTheDocument();
  });

  it('s toggles the star through the row button state', async () => {
    const user = userEvent.setup();
    const setPostStarred = vi.fn().mockResolvedValue({ success: true });
    setup({ setPostStarred });
    await screen.findAllByRole('article');
    await user.keyboard('js');
    const first = screen.getAllByRole('article')[0];
    expect(within(first).getByRole('button', { name: 'Star' })).toHaveAttribute('aria-pressed', 'true');
    expect(setPostStarred).toHaveBeenCalledWith(ID(1), true);
  });

  it('with shortcuts switched off, j does nothing and ? still opens help', async () => {
    window.localStorage.setItem(SHORTCUTS_KEY, 'off');
    const user = userEvent.setup();
    setup();
    const articles = await screen.findAllByRole('article');
    await user.keyboard('j');
    expect(articles[0]).not.toHaveAttribute('aria-current');
    await user.keyboard('?');
    const dialog = await screen.findByRole('dialog', { name: /keyboard shortcuts/i });
    expect(within(dialog).getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  });

  it('the help switch turns single-key shortcuts off', async () => {
    const user = userEvent.setup();
    setup();
    const articles = await screen.findAllByRole('article');
    await user.keyboard('?');
    const dialog = await screen.findByRole('dialog', { name: /keyboard shortcuts/i });
    await user.click(within(dialog).getByRole('switch'));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await user.keyboard('j');
    expect(articles[0]).not.toHaveAttribute('aria-current');
  });

  it('j at the last item loads the next page and moves onto it', async () => {
    const user = userEvent.setup();
    const getFeed = vi.fn()
      .mockResolvedValueOnce(feedPage(items().slice(0, 2), 'CURSOR2'))
      .mockResolvedValueOnce(feedPage([items()[2]]));
    setup({ getFeed });
    await screen.findAllByRole('article');
    await user.keyboard('jjj');
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(3));
    expect(getFeed).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: 'CURSOR2' }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getAllByRole('article')[2]));
  });

  it('the empty state shows its action', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([])) }, {
      emptyTitle: 'You are all caught up',
      emptyAction: { label: 'Show all', onClick },
    });
    expect(await screen.findByText('You are all caught up')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show all' }));
    expect(onClick).toHaveBeenCalled();
  });

  it('a failed load renders the error with Retry', async () => {
    const getFeed = vi.fn()
      .mockRejectedValueOnce(new ApiError(500, 'Could not load the feed. Check the backend logs.'))
      .mockResolvedValueOnce(feedPage(items()));
    const user = userEvent.setup();
    setup({ getFeed });
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the feed');
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findAllByRole('article')).toHaveLength(3);
  });
});
