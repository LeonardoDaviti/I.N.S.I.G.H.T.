import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import SearchPage from './SearchPage';
import ReaderPage from './ReaderPage';
import { feedItem, feedPage } from '../components/reader/fixtures';
import { healthResponse, healthRow } from '../components/ops/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import type { Api } from '../services/api';

const SOURCE = '00000000-0000-4000-8000-000000000001';
const POST = '00000000-0000-4000-8000-000000000042';

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
        <Route path="/search" element={<SearchPage />} />
        <Route path="/posts/:postId" element={<p>post page</p>} />
      </Routes>
      <Where />
    </>,
    { api, route },
  );
}

function api(searchPosts = vi.fn().mockResolvedValue(feedPage([]))) {
  return {
    searchPosts,
    api: makeFakeApi({
      searchPosts,
      getFeed: vi.fn().mockResolvedValue(feedPage([])),
      getFolders: vi.fn().mockResolvedValue({ success: true, folders: [] }),
      getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([healthRow({ source_id: SOURCE, display_name: 'Simon Willison’s Weblog' })])),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 0, by_source: {}, by_folder: {} }),
      getOperationsOverview: vi.fn().mockResolvedValue({ success: true, jobs: [] }),
      setPostsRead: vi.fn().mockResolvedValue({ success: true, updated: 1, ids: [POST] }),
    }),
  };
}

const where = () => screen.getByTestId('where').textContent;
const lastSearch = (searchPosts: ReturnType<typeof vi.fn>) => searchPosts.mock.calls.at(-1)?.[0];

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('search (issue 0040)', () => {
  it('the reader toolbar field searches what is on screen: its scope, and Later when shown', async () => {
    const user = userEvent.setup();
    const { api: fake, searchPosts } = api();
    render(fake, `/read/source/${SOURCE}?filter=later`);
    const field = await screen.findByRole('searchbox', { name: /^Search / });
    await user.type(field, '  mcp servers {Enter}');

    expect(where()).toBe(`/search?q=mcp+servers&scope=source%3A${SOURCE}&filter=later`);
    expect(await screen.findByRole('button', { name: /Simon Willison/ })).toHaveAttribute('aria-pressed', 'true');
    expect(lastSearch(searchPosts)).toMatchObject({ q: 'mcp servers', scope: `source:${SOURCE}`, filter: 'later', order: 'newest' });
  });

  it('an empty field searches nothing', async () => {
    const user = userEvent.setup();
    render(api().api, '/');
    await user.type(await screen.findByRole('searchbox', { name: 'Search Main feed' }), '   {Enter}');
    expect(where()).toBe('/');
  });

  it('a result row: title, source, date and the matching line with its words marked; it opens as a post', async () => {
    const user = userEvent.setup();
    const item = feedItem({
      id: POST, title: 'Weekly links',
      snippet: [{ text: 'One link was about ', mark: false }, { text: 'Tailscale', mark: true }, { text: ' on a phone.', mark: false }],
    });
    const { api: fake } = api(vi.fn().mockResolvedValue(feedPage([item])));
    render(fake, '/search?q=tailscale');

    const row = await screen.findByRole('article', { name: 'Weekly links' });
    expect(within(row).getByText('Tailscale', { selector: 'mark' })).toBeInTheDocument();
    expect(row.querySelector('[data-snippet]')).toHaveTextContent('One link was about Tailscale on a phone.');
    expect(within(row).getByRole('link', { name: /Simon Willison/ })).toBeInTheDocument();
    expect(row.querySelector('time')).not.toBeNull();
    expect(within(row).queryByText(item.excerpt)).toBeNull();
    expect(screen.getByRole('feed', { name: 'Search results' })).toBeInTheDocument();

    await user.click(within(row).getByRole('link', { name: 'Weekly links' }));
    expect(where()).toBe(`/posts/${POST}`);
  });

  it('a row matched by its title alone shows its excerpt', async () => {
    const item = feedItem({ id: POST, title: 'Tailscale notes', snippet: null });
    render(api(vi.fn().mockResolvedValue(feedPage([item]))).api, '/search?q=tailscale');
    const row = await screen.findByRole('article', { name: 'Tailscale notes' });
    expect(within(row).getByText(item.excerpt)).toBeInTheDocument();
    expect(row.querySelector('mark')).toBeNull();
  });

  it('chips: the scope searched from comes off; Later, Kept and a date narrow; the order changes', async () => {
    const user = userEvent.setup();
    const { api: fake, searchPosts } = api(vi.fn().mockResolvedValue(feedPage([feedItem({ id: POST })])));
    render(fake, '/search?q=robots&scope=all');
    await screen.findByRole('article');
    expect(lastSearch(searchPosts)).toMatchObject({ q: 'robots', scope: 'all' });

    await user.click(screen.getByRole('button', { name: 'Main feed' }));
    expect(where()).toBe('/search?q=robots');
    expect(screen.queryByRole('button', { name: 'Main feed' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Later' }));
    expect(screen.getByRole('button', { name: 'Later' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Kept' }));
    expect(screen.getByRole('button', { name: 'Later' })).toHaveAttribute('aria-pressed', 'false');
    await user.click(screen.getByRole('button', { name: 'Last month' }));
    await user.click(within(screen.getByRole('radiogroup', { name: 'Order' })).getByRole('radio', { name: 'Best match' }));

    expect(where()).toBe('/search?q=robots&filter=starred&days=30&order=best');
    await screen.findByRole('article');
    expect(lastSearch(searchPosts)).toMatchObject({ q: 'robots', scope: null, filter: 'starred', days: 30, order: 'best' });

    await user.click(screen.getByRole('button', { name: 'Last month' }));
    expect(where()).toBe('/search?q=robots&filter=starred&order=best');
  });

  it('a rail link narrows the search to that track or source', async () => {
    render(api().api, '/search?q=robots');
    const rail = (await screen.findAllByRole('navigation', { name: 'Main feed, tracks and sources' }))[0];
    expect(within(rail).getByRole('link', { name: /Main feed/ })).toHaveAttribute('href', '/search?q=robots&scope=all');
  });

  it('empty: says no post matches, names the chips and offers Search everything', async () => {
    const user = userEvent.setup();
    const { api: fake, searchPosts } = api();
    render(fake, '/search?q=quantum%20knitting&scope=all&days=7');

    expect(await screen.findByText('No posts match “quantum knitting”')).toBeInTheDocument();
    expect(screen.getByText('In Main feed · Last week')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Search everything' }));

    expect(where()).toBe('/search?q=quantum+knitting');
    expect(await screen.findByText('No posts match “quantum knitting”')).toBeInTheDocument();
    expect(lastSearch(searchPosts)).toMatchObject({ scope: null, days: null, filter: 'all' });
    expect(screen.queryByRole('button', { name: 'Search everything' })).toBeNull();
    expect(screen.getByText('Try other words, or fewer of them.')).toBeInTheDocument();
  });

  it('before any words: the field waits, focused, and nothing is searched', async () => {
    const { api: fake, searchPosts } = api();
    render(fake, '/search');
    expect(await screen.findByRole('searchbox', { name: 'Search posts' })).toHaveFocus();
    expect(screen.getByText(/Word forms count in English and Russian/)).toBeInTheDocument();
    expect(searchPosts).not.toHaveBeenCalled();
  });
});
