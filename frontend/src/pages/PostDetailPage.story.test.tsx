import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import PostDetailPage from './PostDetailPage';
import { POST_ID, baseApi, rssPost } from './PostDetailPage.testkit';
import { makeFakeApi } from '../test/fakeApi';
import { makeTestQueryClient, renderWithProviders } from '../test/render';
import { postKey } from '../hooks/usePost';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import type { Api, FeedStory, Post, PostDetailResponse } from '../services/api';

// The post page knows what INSIGHT has: "Covered by" at the end (issue 0055).

const LAB = '00000000-0000-4000-8000-0000000000a1';
const CHANNEL = '00000000-0000-4000-8000-0000000000a2';
const TAKE = '00000000-0000-4000-8000-0000000000a3';

function story(overrides: Partial<FeedStory> = {}): FeedStory {
  return {
    id: LAB, voices: 3, first: LAB,
    sources: [{ id: 's1', name: 'Anthropic News' }, { id: 's2', name: '@data_secrets' }, { id: 's3', name: 'Simon Willison' }],
    posts: [
      { id: LAB, title: 'Introducing Kimi K3.1 Pro', url: 'https://a.test/kimi', source_id: 's1', source_display_name: 'Anthropic News',
        platform: 'rss', sort_at: '2026-10-23T08:00:00+00:00', published_at: '2026-10-23T08:00:00+00:00', read_at: '2026-10-23T09:00:00+00:00', role: 'report' },
      { id: CHANNEL, title: 'Вышла Kimi K3.1', url: 'https://t.me/data_secrets/10204', source_id: 's2', source_display_name: '@data_secrets',
        platform: 'telegram', sort_at: '2026-10-23T10:00:00+00:00', published_at: '2026-10-23T10:00:00+00:00', read_at: null, role: 'share' },
    ],
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="location">{location.pathname}</p>;
}

function renderPage(api: Api, queryClient = makeTestQueryClient()) {
  renderWithProviders(
    <>
      <Routes>
        <Route path="/posts/:postId" element={<PostDetailPage />} />
      </Routes>
      <LocationProbe />
    </>,
    { api, route: `/posts/${POST_ID}`, queryClient },
  );
  return queryClient;
}

function byId(posts: Record<string, Post>) {
  return makeFakeApi({
    getPostDetail: vi.fn((id: string) => Promise.resolve({ success: true, post: posts[id], reader_state: null })),
    recordPostOpen: vi.fn().mockResolvedValue({ success: true }),
    recordPostReadingSession: vi.fn().mockResolvedValue({ success: true }),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 0, by_source: {}, by_folder: {} }),
  });
}

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('PostDetailPage covered by (issue 0055)', () => {
  it('lists the story\'s other posts at the end: source, title, share, first, and which are read', async () => {
    renderPage(baseApi(rssPost({ story: story() })));
    await screen.findByRole('article', { name: 'Post content' });
    const block = screen.getByRole('region', { name: 'Covered by' });
    expect(block).toHaveTextContent(/^Covered by 3/);
    const rows = within(block).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toMatch(/^Anthropic News·Introducing Kimi K3\.1 Pro· first/);
    expect(rows[1].textContent).toMatch(/^@data_secrets·Вышла Kimi K3\.1· share.*Unread$/);
    expect(within(rows[0]).getByRole('link')).toHaveClass('text-fg-2');
    expect(within(rows[1]).getByRole('link')).toHaveClass('font-medium');
    // It comes after the text.
    const article = screen.getByRole('article', { name: 'Post content' });
    expect(article.compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('says so when this post was first', async () => {
    renderPage(baseApi(rssPost({ story: story({ first: POST_ID }) })));
    expect(await screen.findByRole('region', { name: 'Covered by' })).toHaveTextContent(/^Covered by 3 · this post was first/);
  });

  it('each entry opens that post in INSIGHT', async () => {
    const user = userEvent.setup();
    renderPage(byId({
      [POST_ID]: rssPost({ story: story() }),
      [CHANNEL]: rssPost({ id: CHANNEL, title: 'Вышла Kimi K3.1', story: null }),
    }));
    const block = await screen.findByRole('region', { name: 'Covered by' });
    await user.click(within(block).getByRole('link', { name: 'Вышла Kimi K3.1' }));
    expect(screen.getByTestId('location')).toHaveTextContent(`/posts/${CHANNEL}`);
    expect(await screen.findByRole('heading', { level: 1, name: 'Вышла Kimi K3.1' })).toBeInTheDocument();
  });

  it('a post opened here reads as read in a cached post\'s list', async () => {
    const queryClient = makeTestQueryClient();
    const other: PostDetailResponse = { success: true, post: rssPost({ id: TAKE, story: story({
      posts: [{ ...story().posts[1], id: POST_ID, read_at: null }],
    }) }), reader_state: null };
    queryClient.setQueryData(postKey(TAKE), other);
    renderPage(baseApi(rssPost()), queryClient);
    await screen.findByRole('article', { name: 'Post content' });
    await waitFor(() => {
      const cached = queryClient.getQueryData<PostDetailResponse>(postKey(TAKE));
      expect(cached?.post?.story?.posts[0].read_at).toBeTruthy();
    });
  });

  it('shows nothing when the post is in no story', async () => {
    renderPage(baseApi(rssPost({ story: null })));
    await screen.findByRole('article', { name: 'Post content' });
    expect(screen.queryByRole('region', { name: 'Covered by' })).toBeNull();
    expect(screen.queryByText(/Covered by/)).toBeNull();
  });
});
