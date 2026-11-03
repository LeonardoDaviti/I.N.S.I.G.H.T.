import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import FeedList from './FeedList';
// The feed's dialogs are lazy chunks (the reader's JS budget). Imported with the file, they
// open in the same turn instead of racing findBy against their first transform.
import './ShortcutHelp';
import '../ops/ConfirmDialog';
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
        <Route path="/" element={<FeedList scope="all" filter="unread" view="stream" {...props} />} />
        <Route path="/posts/:postId" element={<LocationProbe />} />
        <Route path="/read/:scopeKind/:scopeId" element={<LocationProbe />} />
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
    // The time column, and below `sm` the meta line, which takes the column's place (issue 0073).
    const [column, meta] = within(fresh).getAllByText(clock(new Date(iso(2))));
    expect(column).toHaveClass('max-sm:hidden');
    expect(meta).toHaveClass('sm:hidden');
    expect(within(oldOne).getAllByText(clock(old))).toHaveLength(2);
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

  it('a post started but not finished shows a thin progress line, and says how far (issue 0030)', async () => {
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([
      feedItem({ id: ID(1), title: 'Started', resume_block: 16, resume_blocks: 40 }),
      feedItem({ id: ID(2), title: 'Barely started', resume_block: 1, resume_blocks: 40 }),
      feedItem({ id: ID(3), title: 'Not started' }),
    ])) });
    const [started, barely, untouched] = await screen.findAllByRole('article');
    const line = started.querySelector<HTMLElement>('[data-reading-progress]');
    expect(line).not.toBeNull();
    expect(line).toHaveAttribute('aria-hidden', 'true');
    expect(line!.firstElementChild).toHaveStyle({ width: '40%' });
    expect(within(started).getByText('40% read')).toHaveClass('sr-only');
    expect(barely.querySelector('[data-reading-progress]')).toBeNull();
    expect(untouched.querySelector('[data-reading-progress]')).toBeNull();
  });

  it('on a phone the title takes the row: the time joins the meta line, counts, a reading bar and a note take lines of their own (issue 0073)', async () => {
    const now = new Date();
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([
      feedItem({ id: ID(1), title: 'Anthropic S-1', source_display_name: 'Hacker News', counts: { points: 1675, comments: 1628 },
        reading_minutes: 4, resume_block: 16, resume_blocks: 40, sort_at: now.toISOString(), published_at: '2025-09-14T00:00:00Z' }),
      feedItem({ id: ID(2), title: 'Plain post', reading_minutes: 2 }),
    ])) });
    const [hn, plain] = await screen.findAllByRole('article');
    // Below `sm` the row is a grid: the title across it, the actions beside the meta and excerpt lines.
    expect(hn).toHaveClass('max-sm:grid');
    expect(hn.querySelector('h3')).toHaveClass('max-sm:col-span-full');
    expect(within(hn).getByRole('button', { name: 'Mark read' }).parentElement).toHaveClass('max-sm:col-start-2', 'max-sm:row-span-2');
    const lines = (row: HTMLElement) => Array.from(row.querySelector('h3 + p')!.children)
      .filter((child) => !child.classList.contains('sr-only')).map((line) => line.textContent);
    // Source · time · length; then the counts with the length and its bar; then the note. A line never starts on a dot.
    expect(lines(hn)).toEqual([expect.stringMatching(/^Hacker News·Today, \d\d:\d\d$/), '·1,675 points · 1,628 comments·4 min read·40% read', '·published Sep 14 ’25']);
    const dots = hn.querySelectorAll('h3 + p [aria-hidden="true"]');
    expect(Array.from(dots).filter((dot) => dot.textContent === '·').map((dot) => dot.classList.contains('max-sm:hidden')))
      .toEqual([false, true, false, false, true]);
    expect(lines(plain)).toEqual([expect.stringMatching(/·[^·]*\d\d:\d\d·2 min read$/)]);
  });

  it('a changed page says what changed, a page new to you when it was published (issue 0039)', async () => {
    const now = new Date();
    const update = { at: now.toISOString(), words: 9000, words_added: 1400, words_removed: 0, sections_added: 2, sections_removed: 0 };
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([
      feedItem({ id: ID(1), title: 'Changed essay', sort_at: now.toISOString(), published_at: '2019-05-17T00:00:00Z', update }),
      feedItem({ id: ID(2), title: 'Found late', sort_at: now.toISOString(), published_at: '2025-09-14T00:00:00Z' }),
      feedItem({ id: ID(3), title: 'Plain post' }),
    ])) });
    const row = async (title: string) => (await screen.findByRole('link', { name: title })).closest('article') as HTMLElement;
    expect(within(await row('Changed essay')).getByText('updated +2 sections, +1,400 words')).toBeInTheDocument();
    expect(within(await row('Found late')).getByText('published Sep 14 ’25')).toBeInTheDocument();
    expect((await row('Plain post')).querySelector('[data-page-note]')).toBeNull();
  });

  it('coming back from a post selects and focuses the post read last', async () => {
    rememberSelection(ID(2));
    setup();
    const articles = await screen.findAllByRole('article');
    await waitFor(() => expect(articles[1]).toHaveAttribute('aria-current', 'true'));
    expect(document.activeElement).toBe(articles[1]);
  });

  it('renders one article per item with two links each: the title and the source', async () => {
    setup();
    const articles = await screen.findAllByRole('article');
    expect(articles).toHaveLength(3);
    for (const article of articles) expect(within(article).getAllByRole('link')).toHaveLength(2);
  });

  it('the source name opens the reader on that source, without opening or marking the post (issue 0019)', async () => {
    const user = userEvent.setup();
    const setPostsRead = vi.fn().mockResolvedValue({ success: true });
    setup({ setPostsRead });
    const [first] = await screen.findAllByRole('article');
    const sourceId = items()[0].source_id;
    const source = within(first).getByRole('link', { name: 'Simon Willison’s Weblog' });
    expect(source).toHaveAttribute('href', `/read/source/${sourceId}`);
    await user.click(source);
    expect((await screen.findByTestId('location')).textContent).toBe(`/read/source/${sourceId}`);
    expect(setPostsRead).not.toHaveBeenCalled();
  });

  it('a row has one read toggle, the circle, and one save: Read later unread, Keep once read, also when selected (issues 0019, 0022)', async () => {
    const user = userEvent.setup();
    const now = new Date().toISOString();
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([
      feedItem({ id: ID(1), title: 'Unread one' }),
      feedItem({ id: ID(2), title: 'Read one', read_at: now }),
      feedItem({ id: ID(3), title: 'Read, still in Later', read_at: now, later_at: now }),
      feedItem({ id: ID(4), title: 'Unread, kept before', starred_at: now }),
    ])) });
    await screen.findAllByRole('article');
    await user.keyboard('j');
    const rows = screen.getAllByRole('article');
    expect(rows[0]).toHaveAttribute('aria-current', 'true');
    const labels = (row: HTMLElement) => within(row).getAllByRole('button').map((b) => b.getAttribute('aria-label'));
    expect(labels(rows[0])).toEqual(['Mark read', 'Read later']);
    expect(labels(rows[1])).toEqual(['Mark unread', 'Keep']);
    // A save already on keeps its button, so it can be undone by hand.
    expect(labels(rows[2])).toEqual(['Mark unread', 'Read later', 'Keep']);
    expect(labels(rows[3])).toEqual(['Mark read', 'Read later', 'Keep']);
    expect(within(rows[2]).getByText('In Later')).toBeInTheDocument();
    expect(within(rows[3]).getByText('Kept')).toBeInTheDocument();
  });

  it('l puts the selected row in Later and again takes it out', async () => {
    const user = userEvent.setup();
    const setPostsLater = vi.fn().mockResolvedValue({ success: true });
    setup({ setPostsLater, getUnreadCounts: vi.fn().mockResolvedValue({ total: 3, by_source: {}, by_folder: {} }) });
    await screen.findAllByRole('article');
    await user.keyboard('jl');
    const first = () => screen.getAllByRole('article')[0];
    expect(within(first()).getByRole('button', { name: 'Read later' })).toHaveAttribute('aria-pressed', 'true');
    expect(setPostsLater).toHaveBeenCalledWith([ID(1)], true);
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Saved for later'));
    await user.keyboard('l');
    expect(setPostsLater).toHaveBeenLastCalledWith([ID(1)], false);
    expect(within(first()).getByRole('button', { name: 'Read later' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('m finishes a post: marked read, it leaves Later (issue 0022)', async () => {
    const user = userEvent.setup();
    const setPostsRead = vi.fn().mockResolvedValue({ success: true });
    setup({ setPostsRead, getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ id: ID(1), later_at: new Date().toISOString() })])) });
    await screen.findAllByRole('article');
    await user.keyboard('jm');
    expect(setPostsRead).toHaveBeenCalledWith([ID(1)], true);
    const row = screen.getAllByRole('article')[0];
    expect(within(row).queryByText('In Later')).toBeNull();
    expect(within(row).getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual(['Mark unread', 'Keep']);
  });

  it('the Later list has no day headers and refuses mark read up to here', async () => {
    const user = userEvent.setup();
    setup({}, { filter: 'later' });
    await screen.findAllByRole('article');
    expect(document.querySelectorAll('[data-day-header]')).toHaveLength(0);
    await user.keyboard('j{Shift>}A{/Shift}');
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Mark read up to here does not work in Later.'));
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('History refuses mark read up to here, and comes back fresh with what you just opened (issue 0052)', async () => {
    const user = userEvent.setup();
    const read = new Date().toISOString();
    const getFeed = vi.fn().mockResolvedValue(feedPage(items().map((item) => ({ ...item, read_at: read }))));
    const { api, queryClient, unmount } = setup({ getFeed }, { filter: 'history' });
    await screen.findAllByRole('article');
    expect(document.querySelectorAll('[data-day-header]').length).toBeGreaterThan(0);
    await user.keyboard('j{Shift>}A{/Shift}');
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Mark read up to here does not work in History.'));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(getFeed).toHaveBeenCalledTimes(1);

    // Coming back to History (a post read meanwhile) loads it again; other lists keep their cache.
    unmount();
    renderWithProviders(<LiveRegionProvider><FeedList scope="all" filter="history" view="stream" /></LiveRegionProvider>, { api, queryClient });
    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(2));
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

  it('o opens the selected post with ?ctx= and marks it read, keeping it in Later (opening is not finishing)', async () => {
    const user = userEvent.setup();
    const setPostsRead = vi.fn().mockResolvedValue({ success: true });
    setup({ setPostsRead });
    await screen.findAllByRole('article');
    await user.keyboard('jjo');
    const location = await screen.findByTestId('location');
    expect(location.textContent).toBe(`/posts/${ID(2)}?ctx=${encodeURIComponent('all:unread:')}`);
    expect(setPostsRead).toHaveBeenCalledWith([ID(2)], true, { keepLater: true });
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

  it('s keeps the selected row, unread or read, through the row button state', async () => {
    const user = userEvent.setup();
    const setPostStarred = vi.fn().mockResolvedValue({ success: true });
    setup({ setPostStarred });
    await screen.findAllByRole('article');
    await user.keyboard('js');
    const first = screen.getAllByRole('article')[0];
    expect(within(first).getByRole('button', { name: 'Keep' })).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Kept'));
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
  it('a story shows once: "covered by" opens its other posts, each opening as a post (issue 0050)', async () => {
    const user = userEvent.setup();
    const story = {
      id: ID(1), voices: 3,
      sources: [{ id: 's1', name: 'Anthropic News' }, { id: 's2', name: 'Simon Willison' }, { id: 's3', name: 'https://tg.i-c-a.su/rss/denissexy?limit=50' }],
      posts: [
        { id: ID(7), title: 'My notes on the model', url: 'https://simonwillison.net/x', source_id: 's2', source_display_name: 'Simon Willison',
          platform: 'rss', sort_at: '2026-10-01T12:00:00Z', published_at: null, read_at: null, role: 'report' as const },
        { id: ID(8), title: 'Вышел новый Claude', url: 'https://t.me/denissexy/1', source_id: 's3', source_display_name: 'https://tg.i-c-a.su/rss/denissexy?limit=50',
          platform: 'rss', sort_at: '2026-10-01T13:00:00Z', published_at: null, read_at: '2026-10-01T14:00:00Z', role: 'share' as const },
      ],
    };
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ id: ID(1), title: 'Introducing the model', story })])) });
    const toggle = await screen.findByRole('button', { name: 'covered by 3 · Anthropic News, Simon Willison, +1' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const list = document.querySelector('[data-story-posts]') as HTMLElement;
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('Simon Willison·My notes on the model'),
      expect.stringContaining('@denissexy·Вышел новый Claude· share'),
    ]);
    await user.click(within(list).getByRole('link', { name: 'My notes on the model' }));
    expect(screen.getByTestId('location')).toHaveTextContent(`/posts/${ID(7)}`);
  });
  it('a story is a tree: what came from the lead indented, an outside origin first (issue 0064)', async () => {
    const user = userEvent.setup();
    const post = (n: number, name: string, title: string, hour: number, parent: string | null, reason: 'citation' | 'address' | 'copy') => ({
      id: ID(n), title, url: `https://x.test/${n}`, source_id: `s${n}`, source_display_name: name, platform: 'rss',
      sort_at: `2026-10-26T${hour}:00:00Z`, published_at: null, read_at: null, role: 'report' as const, parent_id: parent, parent_reason: reason,
    });
    // GPT-6.1 Terra: OpenAI's own post leads; HN's row of its address and two citers under it; LessWrong under Simon.
    const terra = {
      id: ID(1), voices: 4, first: ID(1), parent_id: null, parent_reason: null, origin: null,
      sources: [{ id: 's1', name: 'OpenAI News' }, { id: 's2', name: 'Hacker News' }, { id: 's3', name: 'data_secrets' }, { id: 's4', name: 'Simon Willison' }],
      posts: [post(2, 'Hacker News', 'GPT-6.1 Terra', 18, ID(1), 'address'), post(3, 'data_secrets', 'Вышла GPT-6.1 Terra', 19, ID(1), 'citation'),
        post(4, 'Simon Willison', 'GPT-6.1 Terra notes', 23, ID(1), 'citation'), post(5, 'Lesswrong', 'AI #192', 23, ID(4), 'citation')],
    };
    // Claude Fable 5: the origin is Anthropic's page, linked by 3; this row is one of its citers.
    const fable = {
      id: ID(9), voices: 3, first: null, parent_id: null, parent_reason: 'citation' as const,
      origin: { url: 'https://www.anthropic.com/news/claude-fable-5-mythos-5', title: 'Claude Fable 5', linked_by: 3 },
      sources: [{ id: 's9', name: 'ai_newz' }, { id: 's10', name: 'denissexy' }],
      posts: [post(10, 'denissexy', 'Вышла новая модель', 17, null, 'citation')],
    };
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([
      feedItem({ id: ID(1), title: 'Introducing GPT-6.1 Terra', story: terra }),
      feedItem({ id: ID(9), title: 'Вышел Claude 5 Fable', source_display_name: 'ai_newz', sort_at: '2026-10-26T16:00:00Z', story: fable }),
    ])) });
    await user.click(await screen.findByRole('button', { name: /^covered by 4/ }));
    await user.click(screen.getByRole('button', { name: /^covered by 3/ }));
    const [terraList, fableList] = Array.from(document.querySelectorAll('[data-story-posts]')) as HTMLElement[];
    const lines = (list: HTMLElement) => within(list).getAllByRole('listitem').map((li) => `${li.dataset.depth} ${li.textContent?.split('·')[0]}`);
    expect(lines(terraList)).toEqual(['0 Hacker News', '0 data_secrets', '0 Simon Willison', '1 Lesswrong']);
    expect(lines(fableList)).toEqual(['0 anthropic.com', '1 ai_newz', '1 denissexy']);
    expect(within(fableList).getAllByRole('listitem')[1]).toHaveTextContent(/· this post$/);
    expect(within(fableList).getByRole('link', { name: 'Claude Fable 5' })).toHaveAttribute('href',
      '/save?url=https%3A%2F%2Fwww.anthropic.com%2Fnews%2Fclaude-fable-5-mythos-5&title=Claude+Fable+5');
  });
  it('a thread is one row, "Thread · 3 posts", its replies in order; a repost says who reposted it, from whom (issue 0066)', async () => {
    const user = userEvent.setup();
    const reply = (n: number, title: string, parent: string) => ({
      id: ID(n), title, url: `https://nitter.local/badlogicgames/status/${n}`, source_id: 'bg', source_display_name: 'badlogicgames',
      platform: 'rss', sort_at: '2026-10-27T08:52:39Z', published_at: null, read_at: null, role: 'report' as const,
      parent_id: parent, parent_reason: 'thread' as const, text: title,
    });
    const thread = {
      id: ID(1), voices: 1, first: ID(1), parent_id: null, parent_reason: null, origin: null, thread: true,
      sources: [{ id: 'bg', name: 'badlogicgames' }],
      posts: [reply(2, 'pretty joyless now. guess i switch to gardening.', ID(1)), reply(3, 'there will remain some niche holdouts', ID(2))],
    };
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([
      feedItem({ id: ID(1), title: 'software is dead. sad.', source_display_name: 'badlogicgames', story: thread }),
      feedItem({ id: ID(5), title: 'how i work with agents in 2026.', source_display_name: 'steipete',
        repost: { by: [], author: 'badlogicgames' } }),
    ])) });
    const toggle = await screen.findByRole('button', { name: 'Thread · 3 posts' });
    // On a phone a story's line may take two lines, so the names show (issue 0073).
    expect(within(toggle).getByText('Thread · 3 posts')).toHaveClass('truncate', 'max-sm:line-clamp-2', 'max-sm:whitespace-normal');
    await user.click(toggle);
    const list = document.querySelector('[data-story-posts]') as HTMLElement;
    expect(within(list).getAllByRole('listitem').map((li) => `${li.dataset.depth} ${li.textContent?.split('·')[1]}`))
      .toEqual([expect.stringMatching(/^0 pretty joyless now/), expect.stringMatching(/^0 there will remain/)]);
    const [, repost] = screen.getAllByRole('article');
    // The source once (issue 0070), the repost's line beside it from `sm` up, under it on a phone (issue 0073).
    expect(repost.textContent?.match(/steipete/g)).toHaveLength(1);
    expect(within(repost).getByText('↻ from @badlogicgames')).toHaveClass('sm:order-1');
    expect(within(repost).getByText('4 min read')).toHaveClass('sm:order-2');
  });
  it('a story names the roundups that mention it, who reposted a tweet, and on a phone a deep line its parent (issue 0068)', async () => {
    const user = userEvent.setup();
    const post = (n: number, name: string, title: string, parent: string, extra = {}) => ({
      id: ID(n), title, url: `https://x.test/${n}`, source_id: `s${n}`, source_display_name: name, platform: 'rss',
      sort_at: `2026-10-26T1${n}:00:00Z`, published_at: null, read_at: null, role: 'report' as const, parent_id: parent,
      parent_reason: 'citation' as const, ...extra,
    });
    // Ghostty leaves GitHub: mitchellh.com's post (read) is the origin; @steipete's tweet (reposted) and Mat Duggan's row
    // under it, Andrew Nesbitt's "A GitHub for maintainers" under Duggan.
    const ghostty = {
      id: ID(1), voices: 4, first: ID(1), parent_id: ID(1), parent_reason: 'citation' as const, origin: null,
      sources: [{ id: 's1', name: 'mitchellh.com' }, { id: 's2', name: 'steipete' }, { id: 's3', name: 'Mat Duggan' }, { id: 's4', name: 'Andrew Nesbitt' }],
      posts: [{ ...post(1, 'mitchellh.com', 'Ghostty is leaving GitHub', ''), parent_id: null, parent_reason: null },
        post(2, 'steipete', 'ghostty is leaving github', ID(1), { reposted_by: ['steipete', 'badlogicgames'] }),
        post(4, 'Andrew Nesbitt', 'A GitHub for maintainers', ID(3))],
      roundups: [{ id: ID(7), title: 'AI #192: Anthropic Is Going Public', source_display_name: 'Lesswrong' },
        { id: ID(8), title: 'not much happened today', source_display_name: 'Smol' }],
    };
    setup({ getFeed: vi.fn().mockResolvedValue(feedPage([
      feedItem({ id: ID(3), title: 'GitHub is not your home', source_display_name: 'Mat Duggan', sort_at: '2026-10-26T13:00:00Z', story: ghostty }),
    ])) });
    await user.click(await screen.findByRole('button', { name: /^covered by 4/ }));
    const list = document.querySelector('[data-story-posts]') as HTMLElement;
    const items = within(list).getAllByRole('listitem');
    expect(items.map((li) => li.textContent?.split('·')[0])).toEqual(
      ['mitchellh.com', 'steipete', '↻ reposted by @steipete, @badlogicgames', 'Mat Duggan', '↳ Mat DugganAndrew Nesbitt']);
    expect(items.map((li) => li.dataset.depth)).toEqual(['0', '1', '1', '1', '2']);
    expect(items[4]).toHaveClass('pl-2', 'sm:pl-8');
    expect(within(items[4]).getByText('↳ Mat Duggan')).toHaveClass('sm:hidden');
    const roundups = screen.getByText(/^Also in roundups:/);
    expect(roundups).toHaveTextContent('Also in roundups: Lesswrong, Smol');
    expect(within(roundups).getByRole('link', { name: 'Lesswrong' })).toHaveAttribute('href', `/posts/${ID(7)}`);
    expect(within(list).queryByText('Lesswrong')).toBeNull();
  });
});
