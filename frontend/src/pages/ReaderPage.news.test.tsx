import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import ReaderPage from './ReaderPage';
// News and Classics are lazy chunks (the reader's JS budget); imported here so they render in one turn.
import '../components/reader/NewsList';
import '../components/reader/ClassicsList';
import { feedItem, feedPage } from '../components/reader/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { healthResponse } from '../components/ops/fixtures';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import type { Api, Classic, FeedItem, NewsScore } from '../services/api';

// News and Classics (issue 0051): two views next to the Main feed, of the Main feed or a track.

const ID = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;
const FOLDER = '00000000-0000-4000-8000-0000000000f1';

function base(methods: Partial<Record<keyof Api, unknown>>) {
  return makeFakeApi({
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [{ id: FOLDER, name: 'XR', source_count: 2 }] }),
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([])),
    getOperationsOverview: vi.fn().mockResolvedValue({ success: true, jobs: [] }),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 4, by_source: {}, by_folder: {} }),
    getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ id: ID(9) })])),
    ...methods,
  });
}

function render(api: Api, route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<ReaderPage />} />
      <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
      <Route path="/posts/:postId" element={<p>the post page</p>} />
    </Routes>,
    { api, route },
  );
}

function story(id: string, title: string, news: Partial<NewsScore>, names: string[]): FeedItem {
  return feedItem({
    id, title,
    story: { id, voices: names.length, sources: names.map((name, n) => ({ id: `s${n}`, name })), posts: [] },
    news: { part: 'recent', first_at: new Date().toISOString(), reports: 1, shares: 0, mentions: 0, score: 1, ...news },
  });
}

function classic(overrides: Partial<Classic>): Classic {
  return {
    url: 'https://darioamodei.com/essay/machines-of-loving-grace', post_id: null, title: 'Machines of Loving Grace',
    voices: 3, days: 414, first_at: '2025-08-10T12:00:00Z', last_at: '2026-09-28T12:00:00Z', cited_again: false,
    citers: [{ name: 'Simon Willison', at: '2025-08-12T12:00:00Z' }, { name: 'Gwern', at: '2026-03-14T12:00:00Z' }],
    read_at: null, later_at: null, ...overrides,
  };
}

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('News (issue 0051)', () => {
  it('View offers News and Classics next to the feed; News shows its parts, its score in words', async () => {
    const user = userEvent.setup();
    const getNews = vi.fn().mockResolvedValue(feedPage([
      story(ID(1), 'Meta Connect 2026 recap', { reports: 4, shares: 1, mentions: 1, score: 5 }, ['Road to VR', 'UploadVR', 'The Verge', 'Simon']),
      story(ID(2), 'Snap Specs launch', { part: 'earlier', reports: 2 }, ['Snap', 'Engadget']),
    ]));
    render(base({ getNews }), '/');
    const view = await screen.findByRole('radiogroup', { name: 'View' });
    expect(within(view).getAllByRole('radio').map((radio) => radio.textContent)).toEqual(['Stream', 'By source', 'News', 'Classics']);
    await user.click(within(view).getByRole('radio', { name: 'News' }));

    const feed = await screen.findByRole('feed', { name: 'News' });
    expect(getNews).toHaveBeenCalledWith(expect.objectContaining({ scope: 'all' }));
    expect(within(feed).getAllByRole('article').map((row) => within(row).getByRole('heading').textContent))
      .toEqual(['Meta Connect 2026 recap', 'Snap Specs launch']);
    expect(screen.getByText('Last 48 hours')).toBeInTheDocument();
    expect(screen.getByText('This week')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /4 sources \(1 share\) · in 1 roundup · Road to VR, UploadVR, \+2/ })).toBeInTheDocument();
    // News is not the unread feed: no Show, no Posts, no unread count.
    expect(screen.queryByRole('radiogroup', { name: 'Show' })).not.toBeInTheDocument();
    expect(screen.queryByRole('radiogroup', { name: 'Posts' })).not.toBeInTheDocument();
    expect(screen.queryByText('4 unread')).not.toBeInTheDocument();
  });

  it('an empty News says what fills it', async () => {
    render(base({ getNews: vi.fn().mockResolvedValue(feedPage([])) }), '/?view=news');
    expect(await screen.findByText('No News yet')).toBeInTheDocument();
    expect(screen.getByText('A story shows here when 2 or more of your sources cover it within days.')).toBeInTheDocument();
  });

  it('a track opens its own News', async () => {
    const getNews = vi.fn().mockResolvedValue(feedPage([]));
    render(base({ getNews }), `/read/folder/${FOLDER}?view=news`);
    await screen.findByText('No News yet');
    expect(getNews).toHaveBeenCalledWith(expect.objectContaining({ scope: `folder:${FOLDER}` }));
  });

  it('earlier weeks get a part each, every part in the API order (issue 0077)', async () => {
    const weeksAgo = (n: number) => new Date(Date.now() - n * 7 * 24 * 60 * 60 * 1000).toISOString();
    // As the API sends them: by score across the 30 days.
    render(base({ getNews: vi.fn().mockResolvedValue(feedPage([
      story(ID(1), 'Old and big', { part: 'earlier', first_at: weeksAgo(3), score: 9 }, ['A', 'B']),
      story(ID(2), 'New', {}, ['A', 'B']),
      story(ID(3), 'Old and small', { part: 'earlier', first_at: weeksAgo(3), score: 2 }, ['A', 'B']),
    ])) }), '/?view=news');
    const feed = await screen.findByRole('feed', { name: 'News' });
    expect(within(feed).getAllByRole('article').map((row) => within(row).getByRole('heading').textContent))
      .toEqual(['New', 'Old and big', 'Old and small']);
    expect(screen.getByText('Last 48 hours')).toBeInTheDocument();
    expect(screen.getAllByText(/^Week of \d+ \w+/)).toHaveLength(1);
  });

  it("News is Mark X's rows; the older News (Mark IX's) is one click away and back (issue 0205)", async () => {
    const user = userEvent.setup();
    const getNews = vi.fn().mockImplementation(({ mark }: { mark?: string }) => Promise.resolve(mark === 'ix'
      ? { ...feedPage([story(ID(2), 'The older row', {}, ['A', 'B'])]), mark: 'ix', fallback: false, note: null }
      : { ...feedPage([story(ID(1), 'The Mark X row', {}, ['A', 'B'])]), mark: 'x', fallback: false, note: null }));
    render(base({ getNews }), '/?view=news');
    expect(await screen.findByRole('link', { name: 'The Mark X row' })).toBeInTheDocument();
    expect(getNews).toHaveBeenCalledWith(expect.objectContaining({ scope: 'all', mark: 'main' }));
    await user.click(screen.getByRole('button', { name: 'Older News view' }));
    expect(await screen.findByRole('link', { name: 'The older row' })).toBeInTheDocument();
    expect(getNews).toHaveBeenCalledWith(expect.objectContaining({ scope: 'all', mark: 'ix' }));
    await user.click(screen.getByRole('button', { name: 'Back to News' }));
    expect(await screen.findByRole('link', { name: 'The Mark X row' })).toBeInTheDocument();
  });

  it('ranked News shows the Notable lane first and the order by coverage one click away (issue 0208)', async () => {
    const user = userEvent.setup();
    const rank = { significance: 0.95, coverage: 0.3, fit: 0, score: 0.66, event: 'new_method', effect: 4, usable: 'now' };
    const getNews = vi.fn().mockImplementation(({ order }: { order?: string }) => Promise.resolve(order === 'coverage'
      ? { ...feedPage([story(ID(1), 'The loud launch', { score: 20 }, ['A', 'B']),
          story(ID(2), 'The quiet method', { score: 3 }, ['A', 'B'])]), mark: 'x', order: 'coverage' }
      : { ...feedPage([story(ID(2), 'The quiet method', { score: 3, notable: true, rank }, ['A', 'B']),
          story(ID(1), 'The loud launch', { score: 20 }, ['A', 'B'])]), mark: 'x', order: 'ranked' }));
    render(base({ getNews }), '/?view=news');
    const feed = await screen.findByRole('feed', { name: 'News' });
    expect(within(feed).getAllByRole('article').map((row) => within(row).getByRole('heading').textContent))
      .toEqual(['The quiet method', 'The loud launch']);
    expect(screen.getByText('Notable for you')).toBeInTheDocument();
    expect(screen.getByText(/New method · usable now · 2 sources/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'By coverage' }));
    await waitFor(() => expect(getNews).toHaveBeenCalledWith(expect.objectContaining({ order: 'coverage' })));
    await waitFor(() => expect(screen.queryByText('Notable for you')).not.toBeInTheDocument());
    expect(within(screen.getByRole('feed', { name: 'News' })).getAllByRole('article')
      .map((row) => within(row).getByRole('heading').textContent)).toEqual(['The loud launch', 'The quiet method']);
    await user.click(screen.getByRole('button', { name: 'Ranked for you' }));
    expect(await screen.findByText('Notable for you')).toBeInTheDocument();
  });

  it("a row shows its expert breakdowns as Analysis, each with its author, when the API sends them (issue 0208)", async () => {
    const analysis = [{ id: ID(5), title: 'How its attention works', source: 'Example Channel', author: 'Example Channel' }];
    render(base({ getNews: vi.fn().mockResolvedValue({ ...feedPage([
      story(ID(1), 'A lab releases open weights', { analysis }, ['A', 'B']),
      story(ID(2), 'Another row', {}, ['A', 'B']),
    ]), mark: 'x', order: 'ranked' }) }), '/?view=news');
    const list = await screen.findByRole('list', { name: 'Analysis' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(list).toHaveTextContent('Analysis · Example Channel · How its attention works');
    expect(within(list).getByRole('link', { name: 'How its attention works' })).toHaveAttribute('href', `/posts/${ID(5)}`);
    expect(screen.getAllByRole('list', { name: 'Analysis' })).toHaveLength(1);   // a row with none shows none
  });

  it('when Mark X has no rows the API falls back to the older News and the page says so (issue 0205)', async () => {
    const note = 'Mark X has no News yet (a new install, or its worker has not run): this is the older News.';
    render(base({ getNews: vi.fn().mockResolvedValue({ ...feedPage([story(ID(2), 'The older row', {}, ['A', 'B'])]),
      mark: 'ix', fallback: true, note }) }), '/?view=news');
    expect(await screen.findByRole('link', { name: 'The older row' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(note);
    expect(screen.queryByRole('button', { name: 'Older News view' })).not.toBeInTheDocument();   // it is the older News
  });

  it('opening a story reads it as the feed does, on its own (no feed context)', async () => {
    const user = userEvent.setup();
    const setPostsRead = vi.fn().mockResolvedValue({ success: true, updated: 1, ids: [ID(1)] });
    render(base({ getNews: vi.fn().mockResolvedValue(feedPage([story(ID(1), 'Meta Connect 2026 recap', {}, ['A', 'B'])])),
      setPostsRead }), '/?view=news');
    const link = await screen.findByRole('link', { name: 'Meta Connect 2026 recap' });
    expect(link).toHaveAttribute('href', `/posts/${ID(1)}`);
    await user.click(link);
    await waitFor(() => expect(setPostsRead).toHaveBeenCalledWith([ID(1)], true, { keepLater: true }));
  });
});

describe('News and Classics on a source page (issue 0077)', () => {
  const SOURCE = '00000000-0000-4000-8000-0000000000a1';

  it('View on a source offers Stream / News / Classics, with no Posts choice', async () => {
    const user = userEvent.setup();
    const getNews = vi.fn().mockResolvedValue(feedPage([]));
    render(base({ getNews }), `/read/source/${SOURCE}`);
    const view = await screen.findByRole('radiogroup', { name: 'View' });
    expect(within(view).getAllByRole('radio').map((radio) => radio.textContent)).toEqual(['Stream', 'News', 'Classics']);
    expect(screen.queryByRole('radiogroup', { name: 'Posts' })).not.toBeInTheDocument();
    await user.click(within(view).getByRole('radio', { name: 'News' }));
    expect(await screen.findByText('No News from this source yet')).toBeInTheDocument();
    expect(getNews).toHaveBeenCalledWith(expect.objectContaining({ scope: `source:${SOURCE}` }));
  });

  it('a source opens its own News, each row saying its part when the API sends it', async () => {
    const getNews = vi.fn().mockResolvedValue(feedPage([
      story(ID(1), 'A launch', { scope_role: 'origin' } as Partial<NewsScore>, ['Source A', 'Source B']),
      story(ID(2), 'A recap', {}, ['Source A', 'Source B']),
    ]));
    render(base({ getNews }), `/read/source/${SOURCE}?view=news`);
    await screen.findByRole('feed', { name: 'News' });
    expect(getNews).toHaveBeenCalledWith(expect.objectContaining({ scope: `source:${SOURCE}` }));
    expect(screen.getByRole('button', { name: /^Started it · 2 sources · Source A, Source B/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^2 sources · Source A, Source B/ })).toBeInTheDocument();
  });

  it('a source with no News says why, quietly', async () => {
    render(base({ getNews: vi.fn().mockResolvedValue(feedPage([])) }), `/read/source/${SOURCE}?view=news`);
    expect(await screen.findByText('No News from this source yet')).toBeInTheDocument();
    expect(screen.getByText('News needs 2+ sources on one story.')).toBeInTheDocument();
  });

  it('a source opens its own Classics, saying its part; none is a quiet line', async () => {
    const getClassics = vi.fn().mockResolvedValue({ success: true, classics: [
      { ...classic({ citers: [{ name: 'Source A', at: '2025-08-12T12:00:00Z' }] }), scope_role: 'report' },
    ] });
    render(base({ getClassics }), `/read/source/${SOURCE}?view=classics`);
    const list = await screen.findByRole('list', { name: 'Classics' });
    // Issue 0105: a source cites a classic, it doesn't cover it.
    expect(within(list).getByRole('listitem')).toHaveTextContent('Cited it · Source A, Aug 2025');
    expect(getClassics).toHaveBeenCalledWith(expect.objectContaining({ scope: `source:${SOURCE}` }));
  });

  it('a source with no Classics says so quietly', async () => {
    render(base({ getClassics: vi.fn().mockResolvedValue({ success: true, classics: [] }) }), `/read/source/${SOURCE}?view=classics`);
    expect(await screen.findByText('No Classics from this source yet')).toBeInTheDocument();
  });

  it('By source on one source is its stream', async () => {
    const getFeed = vi.fn().mockResolvedValue(feedPage([feedItem({ id: ID(9) })]));
    const getFeedGroups = vi.fn();
    render(base({ getFeed, getFeedGroups }), `/read/source/${SOURCE}?view=by_source`);
    await waitFor(() => expect(getFeed).toHaveBeenCalledWith(expect.objectContaining({ scope: `source:${SOURCE}` })));
    expect(getFeedGroups).not.toHaveBeenCalled();
  });
});

describe('Classics (issue 0051)', () => {
  it('come a page at a time: Load more asks for the next with its cursor and appends (issue 0195)', async () => {
    const getClassics = vi.fn()
      .mockResolvedValueOnce({ success: true, classics: [classic({})], next_cursor: '100' })
      .mockResolvedValueOnce({ success: true, classics: [classic({ url: 'https://arxiv.org/abs/2001.08361', title: 'Scaling Laws' })], next_cursor: null });
    render(base({ getClassics }), '/?view=classics');
    const list = await screen.findByRole('list', { name: 'Classics' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }));
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(2));
    expect(getClassics).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: '100' }));
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('lists who cited each and when, cited again first as the API orders it', async () => {
    const getClassics = vi.fn().mockResolvedValue({ success: true, classics: [
      classic({ url: 'https://arxiv.org/abs/2001.08361', title: 'Scaling Laws for Neural Language Models', cited_again: true }),
      classic({}),
    ] });
    render(base({ getClassics }), '/?view=classics');
    const list = await screen.findByRole('list', { name: 'Classics' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows.map((row) => within(row).getByRole('heading').textContent))
      .toEqual(['Scaling Laws for Neural Language Models', 'Machines of Loving Grace']);
    expect(rows[0]).toHaveTextContent('cited again this week · Simon Willison, Aug 2025 · Gwern, Mar 2026');
    expect(rows[1]).not.toHaveTextContent('cited again');
    expect(getClassics).toHaveBeenCalledWith(expect.objectContaining({ scope: 'all' }));
  });

  it('a stored classic opens in the reader; an outside one is saved first, fetched only on click', async () => {
    const user = userEvent.setup();
    const savePage = vi.fn().mockResolvedValue({ success: true, status: 'saved', post_id: ID(7) });
    render(base({ getClassics: vi.fn().mockResolvedValue({ success: true, classics: [
      classic({ url: 'https://lab.test/news/golden-gate-claude', post_id: ID(5), title: 'Golden Gate Claude' }),
      classic({}),
    ] }), savePage }), '/?view=classics');
    expect(await screen.findByRole('link', { name: 'Golden Gate Claude' })).toHaveAttribute('href', `/posts/${ID(5)}`);
    expect(savePage).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Machines of Loving Grace' }));
    expect(savePage).toHaveBeenCalledWith('https://darioamodei.com/essay/machines-of-loving-grace', 'Machines of Loving Grace',
      expect.objectContaining({ onFetching: expect.any(Function) }));
    expect(await screen.findByText('the post page')).toBeInTheDocument();
  });

  it('Later saves it and puts it in Later; Hide takes it away for good', async () => {
    const user = userEvent.setup();
    const savePage = vi.fn().mockResolvedValue({ success: true, status: 'saved', post_id: ID(7) });
    const setPostsLater = vi.fn().mockResolvedValue({ success: true, updated: 1, ids: [ID(7)] });
    const hideClassic = vi.fn().mockResolvedValue({ success: true });
    render(base({ getClassics: vi.fn().mockResolvedValue({ success: true, classics: [classic({})] }), savePage, setPostsLater,
      hideClassic }), '/?view=classics');
    await user.click(await screen.findByRole('button', { name: 'Read later' }));
    await waitFor(() => expect(setPostsLater).toHaveBeenCalledWith([ID(7)], true));
    expect(await screen.findByRole('button', { name: 'Read later' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Hide' }));
    expect(hideClassic).toHaveBeenCalledWith('https://darioamodei.com/essay/machines-of-loving-grace');
    await waitFor(() => expect(document.querySelector('[data-classic]')).toBeNull());
  });

  it('nothing yet says what makes a classic', async () => {
    render(base({ getClassics: vi.fn().mockResolvedValue({ success: true, classics: [] }) }), '/?view=classics');
    expect(await screen.findByText('No classics yet')).toBeInTheDocument();
  });
});
