import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AddSourceModal from './AddSourceModal';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api, FeedFinding, PageWatchPreview } from '../services/api';

const feed = (url: string, title: string): FeedFinding => ({ success: true, status: 'feed', feeds: [{ url, title }] });
const ANSWERS: Record<string, FeedFinding> = {
  'borretti.me': { success: true, status: 'found', feeds: [{ url: 'https://borretti.me/feed.xml', title: 'Fernando Borretti' }] },
  'simonwillison.net': { success: true, status: 'found', feeds: [
    { url: 'https://simonwillison.net/atom/everything/', title: 'Everything' },
    { url: 'https://simonwillison.net/atom/entries/', title: 'Entries' },
  ] },
  'https://gwern.net': { success: true, status: 'direct', feeds: [] },
  'https://www.anthropic.com/news': { success: true, status: 'none', feeds: [] },
  'https://js-shell.example/': { success: true, status: 'none', feeds: [] },
  'https://new.example/feed.xml': feed('https://new.example/feed.xml', 'New'),
};
const PREVIEWS: Record<string, PageWatchPreview> = {
  'https://www.anthropic.com/news': { success: true, prefix: '/news/', found: 12, sitemap: false, items: [{ url: 'https://www.anthropic.com/news/a', title: 'A', published_at: null }] },
  'https://js-shell.example/': { success: true, prefix: '/', found: 0, sitemap: false, items: [] },
};

function setup(overrides: Partial<Record<keyof Api, unknown>> = {}, existingAddresses: string[] = []) {
  const methods = {
    findFeed: vi.fn((url: string): Promise<FeedFinding> => Promise.resolve(ANSWERS[url] ?? { success: true, status: 'none', feeds: [] })),
    previewPageWatch: vi.fn((url: string) => Promise.resolve(PREVIEWS[url] ?? { success: true, prefix: '/', found: 0, items: [] })),
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [{ id: 'f-ai', name: 'AI engineering', sort_order: 0 }] }),
    addSource: vi.fn((payload: { handle_or_url: string }): Promise<{ success: boolean; source_id?: string; error?: string }> => Promise.resolve({ success: true, source_id: `id:${payload.handle_or_url}` })),
    createFolder: vi.fn().mockResolvedValue({ success: true, folder: { id: 'f-new', name: 'Imported' } }),
    addSourceToFolder: vi.fn().mockResolvedValue({ success: true }),
  };
  const api = { ...methods, ...overrides } as typeof methods;
  const onAddMany = vi.fn();
  const onClose = vi.fn();
  renderWithProviders(
    <AddSourceModal existingAddresses={existingAddresses} onClose={onClose} onAdd={vi.fn()} onAddMany={onAddMany} />,
    { api: makeFakeApi(api) },
  );
  return { api, onAddMany, onClose };
}

const dialog = () => screen.getByRole('dialog');
const openSeveral = async () => {
  await userEvent.click(within(dialog()).getByRole('button', { name: 'Add several…' }));
  return within(dialog()).getByLabelText(/^Addresses/);
};
const paste = async (text: string) => {
  const box = await openSeveral();
  fireEvent.change(box, { target: { value: text } });
  await userEvent.click(within(dialog()).getByRole('button', { name: 'Find feeds' }));
};
const rowOf = (address: string) => screen.getByTestId(`several-row:${address}`);
const tickOf = (address: string) => within(rowOf(address)).getByRole('checkbox');

describe('Add several sources (issue 0035)', () => {
  it('resolves every line through the feed finder and says what each one is', async () => {
    const { api } = setup({}, ['https://new.example/feed.xml']);
    await paste('borretti.me\nhttps://gwern.net\n\nhttps://www.anthropic.com/news\nhttps://js-shell.example/\nhttps://new.example/feed.xml\nborretti.me');
    await screen.findByText('Fernando Borretti');
    expect(within(rowOf('borretti.me')).getByText('borretti.me/feed.xml')).toBeInTheDocument();
    expect(within(rowOf('https://gwern.net')).getByText('INSIGHT reads it directly')).toBeInTheDocument();
    expect(await within(rowOf('https://www.anthropic.com/news')).findByText('No feed: follow the page (12 articles)')).toBeInTheDocument();
    expect(await within(rowOf('https://js-shell.example/')).findByText('Nothing readable')).toBeInTheDocument();
    expect(within(rowOf('https://new.example/feed.xml')).getByText('Already in your sources')).toBeInTheDocument();
    // An address already a source is not looked up; a repeated line is looked up once.
    expect(api.findFeed).not.toHaveBeenCalledWith('https://new.example/feed.xml');
    expect(api.findFeed.mock.calls.filter(([url]) => url === 'borretti.me')).toHaveLength(1);
    expect(api.previewPageWatch).toHaveBeenCalledWith('https://www.anthropic.com/news', undefined);
    expect(api.previewPageWatch).toHaveBeenCalledTimes(2);
    // Already and unreadable rows are unticked and cannot be ticked.
    expect(tickOf('https://new.example/feed.xml')).toBeDisabled();
    expect(tickOf('https://new.example/feed.xml')).not.toBeChecked();
    expect(tickOf('https://js-shell.example/')).toBeDisabled();
    expect(tickOf('borretti.me')).toBeChecked();
    expect(within(dialog()).getByRole('button', { name: 'Add 3 sources' })).toBeEnabled();
  });

  it('looks up at most four addresses at once, rows appearing as answers arrive', async () => {
    const pending: Array<(value: FeedFinding) => void> = [];
    const findFeed = vi.fn(() => new Promise<FeedFinding>((resolve) => { pending.push(resolve); }));
    setup({ findFeed });
    await paste(['a.example', 'b.example', 'c.example', 'd.example', 'e.example', 'f.example'].join('\n'));
    await waitFor(() => expect(findFeed).toHaveBeenCalledTimes(4));
    expect(screen.queryByTestId('several-row:a.example')).toBeNull();
    expect(within(dialog()).getByText('Looking for feeds… 0 of 6')).toBeInTheDocument();
    pending[0](feed('https://a.example/feed', 'A'));
    expect(await screen.findByTestId('several-row:a.example')).toBeInTheDocument();
    await waitFor(() => expect(findFeed).toHaveBeenCalledTimes(5));
    expect(within(dialog()).getByRole('button', { name: 'Add 1 source' })).toBeDisabled();
    // Stop: nothing more is asked, and what came back can be added.
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Stop' }));
    expect(within(dialog()).getByRole('button', { name: 'Add 1 source' })).toBeEnabled();
    pending[1](feed('https://b.example/feed', 'B'));
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    expect(findFeed).toHaveBeenCalledTimes(5);
    expect(screen.queryByTestId('several-row:b.example')).toBeNull();
  });

  it('a page with several feeds offers a picker; Add N adds the ticked rows and hands them over to be fetched', async () => {
    const { api, onAddMany } = setup();
    await paste('simonwillison.net\nborretti.me\nhttps://www.anthropic.com/news');
    const simon = await screen.findByTestId('several-row:simonwillison.net');
    await userEvent.click(within(simon).getByRole('radio', { name: /Entries/ }));
    await within(rowOf('https://www.anthropic.com/news')).findByText('No feed: follow the page (12 articles)');
    await userEvent.click(tickOf('borretti.me'));
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add 2 sources' }));
    await waitFor(() => expect(onAddMany).toHaveBeenCalled());
    expect(api.addSource).toHaveBeenCalledTimes(2);
    expect(api.addSource.mock.calls[0][0]).toEqual({
      platform: 'rss', handle_or_url: 'https://simonwillison.net/atom/entries/', display_name: 'Entries', fetch_delay_seconds: 1,
    });
    expect(api.addSource.mock.calls[1][0]).toEqual({
      platform: 'rss', handle_or_url: 'https://www.anthropic.com/news', display_name: '', fetch_delay_seconds: 1, page_watch: { prefix: '/news/' },
    });
    expect(onAddMany).toHaveBeenCalledWith([
      { id: 'id:https://simonwillison.net/atom/entries/', name: 'Entries', address: 'https://simonwillison.net/atom/entries/' },
      { id: 'id:https://www.anthropic.com/news', name: '', address: 'https://www.anthropic.com/news' },
    ], true);
    expect(api.addSourceToFolder).not.toHaveBeenCalled();
  });

  it('one track for all: an existing one, or a new one created first', async () => {
    const { api } = setup();
    await paste('borretti.me\nhttps://gwern.net');
    await screen.findByText('INSIGHT reads it directly');
    const track = within(dialog()).getByLabelText(/Track for all/);
    await waitFor(() => expect(within(track).getByRole('option', { name: 'AI engineering' })).toBeInTheDocument());
    await userEvent.selectOptions(track, 'f-ai');
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add 2 sources' }));
    await waitFor(() => expect(api.addSourceToFolder).toHaveBeenCalledTimes(2));
    expect(api.addSourceToFolder).toHaveBeenCalledWith('f-ai', 'id:https://borretti.me/feed.xml');
    expect(api.createFolder).not.toHaveBeenCalled();
  });

  it('a failed add stays in the table with its error; the others are handed over', async () => {
    const addSource = vi.fn((payload: { handle_or_url: string }) => Promise.resolve(payload.handle_or_url === 'https://gwern.net'
      ? { success: false, error: 'Source already exists' }
      : { success: true, source_id: 'b1' }));
    const { onAddMany } = setup({ addSource });
    await paste('borretti.me\nhttps://gwern.net');
    await screen.findByText('INSIGHT reads it directly');
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add 2 sources' }));
    await waitFor(() => expect(onAddMany).toHaveBeenCalledWith([expect.objectContaining({ id: 'b1' })], false));
    expect(within(rowOf('https://gwern.net')).getByText('Could not add: Source already exists')).toBeInTheDocument();
    expect(within(rowOf('borretti.me')).getByText('Added')).toBeInTheDocument();
    expect(tickOf('borretti.me')).toBeDisabled();
    expect(within(dialog()).getByRole('button', { name: 'Add 1 source' })).toBeEnabled();
  });

  it('an OPML file fills the box, nested outlines included, and one shared parent becomes the new track', async () => {
    const { api } = setup();
    await openSeveral();
    const opml = `<?xml version="1.0"?><opml version="2.0"><head/><body>
      <outline text="Imported"><outline text="Blogs">
        <outline text="Borretti" type="rss" xmlUrl="https://borretti.me/feed.xml"/>
      </outline><outline text="Gwern" htmlUrl="https://gwern.net"/></outline>
    </body></opml>`;
    await userEvent.upload(within(dialog()).getByLabelText('Import OPML'), new File([opml], 'feeds.opml', { type: 'text/xml' }));
    await waitFor(() => expect(within(dialog()).getByLabelText(/^Addresses/)).toHaveValue('https://borretti.me/feed.xml\nhttps://gwern.net'));
    // Nested: the nearest parent is Blogs for one and Imported for the other, so no track is suggested.
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Find feeds' }));
    await screen.findByText('INSIGHT reads it directly');
    expect(within(dialog()).getByLabelText(/Track for all/)).toHaveValue('');
    expect(api.findFeed).toHaveBeenCalledWith('https://borretti.me/feed.xml');
  });

  it('an OPML file whose outlines share one parent suggests it as a new track, and INSIGHT’s own export round-trips page watching', async () => {
    const { api } = setup({
      findFeed: vi.fn().mockResolvedValue(feed('https://borretti.me/feed.xml', 'Fernando Borretti')),
    });
    await openSeveral();
    const opml = `<?xml version="1.0"?><opml version="2.0" xmlns:insight="https://insight.local/opml"><head/><body>
      <outline text="Reading"><outline text="Borretti" type="rss" xmlUrl="https://borretti.me/feed.xml"/>
      <outline text="Anthropic News" type="rss" xmlUrl="https://www.anthropic.com/news" htmlUrl="https://www.anthropic.com/news"
        insight:displayName="Anthropic News" insight:pageWatchPrefix="/news/"/></outline>
    </body></opml>`;
    await userEvent.upload(within(dialog()).getByLabelText('Import OPML'), new File([opml], 'insight.opml', { type: 'text/xml' }));
    await waitFor(() => expect(within(dialog()).getByLabelText(/^Addresses/)).toHaveValue('https://borretti.me/feed.xml\nhttps://www.anthropic.com/news'));
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Find feeds' }));
    expect(await within(await screen.findByTestId('several-row:https://www.anthropic.com/news')).findByText('No feed: follow the page (12 articles)')).toBeInTheDocument();
    // A followed page is previewed with its path, not looked up again.
    expect(api.findFeed).not.toHaveBeenCalledWith('https://www.anthropic.com/news');
    expect(api.previewPageWatch).toHaveBeenCalledWith('https://www.anthropic.com/news', '/news/');
    expect(within(dialog()).getByLabelText(/Track for all/)).toHaveValue('new');
    expect(within(dialog()).getByLabelText('New track name')).toHaveValue('Reading');
    await screen.findByText('Fernando Borretti');
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add 2 sources' }));
    await waitFor(() => expect(api.addSourceToFolder).toHaveBeenCalledTimes(2));
    expect(api.createFolder).toHaveBeenCalledWith({ name: 'Reading' });
    expect(api.addSourceToFolder).toHaveBeenCalledWith('f-new', 'id:https://www.anthropic.com/news');
    expect(api.addSource).toHaveBeenCalledWith(expect.objectContaining({
      handle_or_url: 'https://www.anthropic.com/news', display_name: 'Anthropic News', page_watch: { prefix: '/news/' },
    }));
  });

  it('a file that is not OPML says so', async () => {
    setup();
    await openSeveral();
    await userEvent.upload(within(dialog()).getByLabelText('Import OPML'), new File(['not xml <'], 'x.opml', { type: 'text/xml' }));
    expect(await within(dialog()).findByText('This file has no OPML outlines to import.')).toBeInTheDocument();
  });

  it('Cancel closes the dialog mid-way', async () => {
    const findFeed = vi.fn(() => new Promise<FeedFinding>(() => {}));
    const { onClose } = setup({ findFeed });
    await paste('a.example');
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('a home page with no feed: its blog with the most articles, named by the pasted address; else the home page with a warning (issue 0041)', async () => {
    const blog = { url: 'https://pay.example/blog', prefix: '/blog/', found: 269, sitemap: false,
      items: [{ url: 'https://pay.example/blog/a', title: 'A', published_at: null }] };
    const findFeed = vi.fn((url: string): Promise<FeedFinding> => Promise.resolve(url === 'pay.example'
      ? { success: true, status: 'none', feeds: [], homepage: true, pages: [blog, { ...blog, url: 'https://pay.example/press', prefix: '/press/', found: 3 }] }
      : { success: true, status: 'none', feeds: [], homepage: true, pages: [] }));
    const previewPageWatch = vi.fn().mockResolvedValue({ success: true, prefix: '/customers/', found: 40, sitemap: false,
      items: [{ url: 'https://shop.example/customers/a', title: 'Acme', published_at: null }] });
    const { api, onAddMany } = setup({ findFeed, previewPageWatch });
    await paste('pay.example\nhttps://shop.example/');
    expect(await within(rowOf('pay.example')).findByText('No feed: follow pay.example/blog (269 articles)')).toBeInTheDocument();
    expect(await within(rowOf('https://shop.example/')).findByText(
      'No feed: follow the page (40 articles). This is the site\'s homepage: it may pick up product pages, not articles.')).toBeInTheDocument();
    expect(previewPageWatch).toHaveBeenCalledTimes(1);
    expect(previewPageWatch).toHaveBeenCalledWith('https://shop.example/', undefined);

    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add 2 sources' }));
    await waitFor(() => expect(onAddMany).toHaveBeenCalled());
    expect(api.addSource).toHaveBeenCalledWith(expect.objectContaining({
      handle_or_url: 'https://pay.example/blog', display_name: 'pay.example', page_watch: { prefix: '/blog/' } }));
    expect(api.addSource).toHaveBeenCalledWith(expect.objectContaining({
      handle_or_url: 'https://shop.example/', display_name: '', page_watch: { prefix: '/customers/' } }));
  });

  it('back to one source', async () => {
    setup();
    await openSeveral();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'One source' }));
    expect(within(dialog()).getByLabelText('Feed URL or handle')).toBeInTheDocument();
  });
});

describe('a template with a field shows what is already added (issue 0035)', () => {
  it('GitHub Trending: All languages, Python', async () => {
    renderWithProviders(
      <AddSourceModal
        existingAddresses={[
          'https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml',
          'https://mshibanami.github.io/GitHubTrendingRSS/daily/python.xml',
          'https://nitter.local/karpathy/rss',
        ]}
        onClose={vi.fn()}
        onAdd={vi.fn()}
      />,
      { api: makeFakeApi({}) },
    );
    await userEvent.click(within(dialog()).getByRole('button', { name: 'GitHub Trending' }));
    expect(within(dialog()).getByText('Added: All languages, Python')).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Nitter' }));
    expect(within(dialog()).getByText('Added: karpathy')).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Telegram RSS' }));
    expect(within(dialog()).queryByText(/^Added:/)).toBeNull();
    // Without onAddMany there is no several mode.
    expect(within(dialog()).queryByRole('button', { name: 'Add several…' })).toBeNull();
  });
});
