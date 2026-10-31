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

// The post page knows what INSIGHT has: "Covered by" at the end (issue 0055), and links to
// stored posts that open here, with ↗ for the original (issue 0057).

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

describe('PostDetailPage covered by, as a tree (issue 0064)', () => {
  const depths = (block: HTMLElement) => within(block).getAllByRole('listitem').map((li) => [li.dataset.depth, li.textContent]);

  it('the origin first, this post in its place, what came from it indented under it', async () => {
    const [lab, channel] = story().posts;
    renderPage(baseApi(rssPost({ title: 'My notes on Kimi K3.1', story: story({
      parent_id: LAB, parent_reason: 'citation',
      posts: [{ ...lab, parent_id: null, parent_reason: null }, { ...channel, parent_id: POST_ID, parent_reason: 'citation' }],
    }) })));
    const block = await screen.findByRole('region', { name: 'Covered by' });
    expect(depths(block)).toEqual([
      ['0', expect.stringMatching(/^Anthropic News·Introducing Kimi K3\.1 Pro· first/)],
      ['1', expect.stringMatching(/·My notes on Kimi K3\.1· this post$/)],
      ['2', expect.stringMatching(/^↳ simonwillison\.net@data_secrets·Вышла Kimi K3\.1· share/)],   // on a phone: its parent, not more indent (0068)
    ]);
    expect(within(block).getAllByRole('listitem')[1]).toHaveAttribute('aria-current', 'true');
    expect(within(within(block).getAllByRole('listitem')[1]).queryByRole('link')).toBeNull();
  });

  it('an outside page as the origin opens in Save any page', async () => {
    const user = userEvent.setup();
    const [lab, channel] = story().posts;
    renderPage(baseApi(rssPost({ story: story({
      first: null, parent_id: null, parent_reason: 'citation',
      origin: { url: 'https://www.kimi.com/blog/kimi-k3-1', title: 'Kimi K3.1 Pro tech blog', linked_by: 8 },
      posts: [{ ...lab, parent_id: null, parent_reason: 'citation' }, { ...channel, parent_id: LAB, parent_reason: 'copy' }],
    }) })));
    const block = await screen.findByRole('region', { name: 'Covered by' });
    expect(depths(block).map(([depth, text]) => [depth, text?.split('·')[0]])).toEqual([
      ['0', 'kimi.com'], ['1', 'simonwillison.net'], ['1', 'Anthropic News'], ['2', '↳ Anthropic News@data_secrets'],
    ]);
    expect(within(block).getAllByRole('listitem')[0]).toHaveTextContent(/^kimi\.com·Kimi K3\.1 Pro tech bloglinked by 8$/);
    await user.click(within(block).getByRole('link', { name: 'Kimi K3.1 Pro tech blog' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/save');
  });
});

describe('PostDetailPage links to stored posts (issue 0057)', () => {
  const html = '<p>See <a href="https://t.me/data_secrets/9951">the earlier post</a> and '
    + '<a href="https://openai.com/index/securing">OpenAI\'s post</a>.</p>';

  it('a link to a stored post opens it in INSIGHT; ↗ beside it opens the original', async () => {
    const user = userEvent.setup();
    renderPage(byId({
      [POST_ID]: rssPost({ content_html: html, internal_links: { 'https://t.me/data_secrets/9951': TAKE } }),
      [TAKE]: rssPost({ id: TAKE, title: 'Ноам Браун заявил', content_html: '<p>Earlier.</p>' }),
    }));
    const article = await screen.findByRole('article', { name: 'Post content' });
    const inside = within(article).getByRole('link', { name: 'the earlier post' });
    expect(inside).toHaveAttribute('href', `/posts/${TAKE}`);
    expect(inside).not.toHaveAttribute('target');
    const original = within(article).getByRole('link', { name: 'Open the original' });
    expect(original).toHaveAttribute('href', 'https://t.me/data_secrets/9951');
    expect(original).toHaveAttribute('target', '_blank');
    // A page INSIGHT doesn't have works as before.
    const outside = within(article).getByRole('link', { name: "OpenAI's post" });
    expect(outside).toHaveAttribute('href', 'https://openai.com/index/securing');
    expect(outside).toHaveAttribute('target', '_blank');
    expect(within(article).getAllByRole('link', { name: 'Open the original' })).toHaveLength(1);

    await user.click(inside);
    expect(screen.getByTestId('location')).toHaveTextContent(`/posts/${TAKE}`);
    expect(await screen.findByRole('heading', { level: 1, name: 'Ноам Браун заявил' })).toBeInTheDocument();
  });

  it('without internal links every link leaves as before', async () => {
    renderPage(baseApi(rssPost({ content_html: html })));
    const article = await screen.findByRole('article', { name: 'Post content' });
    expect(within(article).getByRole('link', { name: 'the earlier post' })).toHaveAttribute('target', '_blank');
    expect(within(article).queryByRole('link', { name: 'Open the original' })).toBeNull();
  });
});

describe('PostDetailPage threads and reposts (issue 0066)', () => {
  const reply = (n: number, text: string, parent: string) => ({
    id: `00000000-0000-4000-8000-00000000010${n}`, title: text, url: `https://nitter.local/badlogicgames/status/${n}`,
    source_id: 'bg', source_display_name: 'badlogicgames', platform: 'rss', sort_at: `2026-10-27T08:5${n}:00+00:00`,
    published_at: null, read_at: null, role: 'report' as const, parent_id: parent, parent_reason: 'thread' as const, text,
  });

  it('a thread reads in order after its first post, and is not listed again (issue 0070)', async () => {
    const first = reply(1, 'pretty joyless now.\n\nguess i switch to gardening.', POST_ID);
    const second = reply(2, 'there will remain some niche holdouts', first.id);
    const thread = story({ voices: 1, thread: true, sources: [{ id: 'bg', name: 'badlogicgames' }], posts: [second, first] });
    renderPage(baseApi(rssPost({ title: 'software is dead. sad.', story: thread })));
    await screen.findByRole('article', { name: 'Post content' });
    const read = screen.getByRole('region', { name: 'Thread' });
    expect(read.querySelectorAll('p')[0].textContent).toBe('pretty joyless now.\n\nguess i switch to gardening.');
    expect(read.querySelectorAll('p')[1].textContent).toBe('there will remain some niche holdouts');
    expect(within(read).getAllByRole('link')[1]).toHaveAttribute('href', `/posts/${second.id}`);
    expect(screen.queryByRole('region', { name: 'Covered by' })).toBeNull();
  });

  it('opened at a reply, the thread lists what came before it; a reply quoting the thread shows no card (issue 0070)', async () => {
    const second = { ...reply(2, 'Its out guys.', POST_ID), html: '<p>Its out guys.</p>', quotes_above: true };
    const root = { ...reply(0, 'software is dead. sad.', ''), parent_id: null, parent_reason: null };
    const thread = story({ voices: 1, thread: true, sources: [{ id: 'bg', name: 'badlogicgames' }], posts: [root, second] });
    renderPage(baseApi(rssPost({ title: 'pretty joyless now.', story: { ...thread, parent_id: root.id, parent_reason: 'thread' } })));
    await screen.findByRole('article', { name: 'Post content' });
    const read = screen.getByRole('region', { name: 'Thread' });
    expect(read).toHaveTextContent(/^Its out guys\.↩ quotes the post above ·/);
    const listed = screen.getByRole('region', { name: 'Covered by' });
    expect(listed).toHaveTextContent('software is dead. sad.');
    expect(listed).not.toHaveTextContent('Its out guys.');
  });

  it('a repost in a story names its author, and its reposter once (issue 0070)', async () => {
    const repost = { ...reply(3, 'We are announcing three new discoveries', ''), parent_id: null, parent_reason: null,
      source_display_name: 'sama', role: 'share' as const, repost: { by: [], author: 'danintheory' } };
    renderPage(baseApi(rssPost({ story: story({ posts: [repost] }) })));
    await screen.findByRole('article', { name: 'Post content' });
    const line = within(screen.getByRole('region', { name: 'Covered by' })).getByText('@danintheory').closest('li');
    expect(line).toHaveTextContent(/^@danintheory·We are announcing three new discoveries· ↻ sama/);
    expect(line).not.toHaveTextContent('share');
  });

  it('a repost says who reposted it, and its author', async () => {
    renderPage(baseApi(rssPost({ title: 'how i work with agents in 2026.', repost: { by: [], author: 'badlogicgames' } })));
    await screen.findByRole('article', { name: 'Post content' });
    expect(screen.getByText('↻ from @badlogicgames')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Thread' })).toBeNull();
  });
});

describe('PostDetailPage: what reading v9.9 would show (issue 0068)', () => {
  it('a thread reply reads as a post: its link is a link, a stored post opens here, its picture shows through the cache', async () => {
    const reply = {
      id: '00000000-0000-4000-8000-000000000201', title: 'see this', url: 'https://nitter.local/badlogicgames/status/2',
      source_id: 'bg', source_display_name: 'badlogicgames', platform: 'rss', sort_at: '2026-10-27T08:52:00+00:00',
      published_at: null, read_at: null, role: 'report' as const, parent_id: POST_ID, parent_reason: 'thread' as const, text: 'see this',
      html: '<p>see <a href="https://blog.test/post">this post</a> and <a href="https://example.com/x">that</a></p>'
        + '<img src="https://nitter.local/pic/media%2Fgiraffe.jpg" alt="a giraffe" />',
      internal_links: { 'https://blog.test/post': TAKE },
    };
    const thread = story({ voices: 1, thread: true, sources: [{ id: 'bg', name: 'badlogicgames' }], posts: [reply] });
    renderPage(baseApi(rssPost({ title: 'software is dead. sad.', story: thread })));
    await screen.findByRole('article', { name: 'Post content' });
    const read = screen.getByRole('region', { name: 'Thread' });
    expect(within(read).getByRole('link', { name: 'this post' })).toHaveAttribute('href', `/posts/${TAKE}`);
    expect(within(read).getByRole('link', { name: 'that' })).toHaveAttribute('href', 'https://example.com/x');
    expect(within(read).getByRole('img', { name: 'a giraffe' })).toHaveAttribute('src',
      `/api/media?post=${reply.id}&url=${encodeURIComponent('https://nitter.local/pic/media%2Fgiraffe.jpg')}`);
  });

  it('under the tree: who reposted a tweet, and the roundups that mention the story, each opening it', async () => {
    const tweet = { ...story().posts[1], reposted_by: ['steipete', 'badlogicgames'] };
    renderPage(baseApi(rssPost({ story: story({ posts: [story().posts[0], tweet], roundups: [
      { id: TAKE, title: 'AI #192: Anthropic Is Going Public', source_display_name: 'Lesswrong' },
      { id: CHANNEL, title: 'not much happened today', source_display_name: 'Smol' },
    ] }) })));
    const covered = await screen.findByRole('region', { name: 'Covered by' });
    expect(within(covered).getByText('↻ reposted by @steipete, @badlogicgames')).toBeInTheDocument();
    expect(within(covered).getByText(/^Also in roundups:/)).toHaveTextContent('Also in roundups: Lesswrong, Smol');
    expect(within(covered).getByRole('link', { name: 'Lesswrong' })).toHaveAttribute('href', `/posts/${TAKE}`);
  });
});
