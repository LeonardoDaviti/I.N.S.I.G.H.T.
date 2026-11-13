import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AddSourceModal from './AddSourceModal';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { FeedFinding, PageOffer } from '../services/api';

// The server's Telegram bridge (issue 0135): asked only when the Telegram template is chosen.
const bridge = vi.hoisted(() => vi.fn<() => Promise<string | null>>());
vi.mock('../services/api', async (actual) => ({ ...(await actual<typeof import('../services/api')>()), telegramBridge: bridge }));

// stripe.com's home page would follow /customers/ (557 links, 0 articles); its /blog had 269
// dated articles (2026-10-28).
const offer = (url: string, prefix: string, found: number): PageOffer => ({
  url, prefix, found, sitemap: false,
  items: [{ url: `${url}/post`, title: `A post from ${prefix}`, published_at: '2026-10-12T00:00:00+00:00' }],
});
const BLOG = offer('https://pay.example/blog', '/blog/', 269);
const PRESS = offer('https://pay.example/press', '/press/', 12);

function setup(finding: FeedFinding) {
  const api = {
    findFeed: vi.fn().mockResolvedValue(finding),
    previewPageWatch: vi.fn().mockResolvedValue({ success: true, prefix: '/customers/', found: 557, sitemap: false,
      items: [{ url: 'https://pay.example/customers/acme', title: 'Acme', published_at: null }] }),
  };
  const onAdd = vi.fn();
  renderWithProviders(<AddSourceModal onClose={vi.fn()} onAdd={onAdd} />, { api: makeFakeApi(api) });
  return { api, onAdd };
}

const dialog = () => screen.getByRole('dialog');
const typeHome = async () => {
  await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'pay.example');
};

describe('a home page with no feed offers its blog (issue 0041)', () => {
  it('offers the page with the most articles; following it asks nothing more and adds it under the pasted name', async () => {
    const { api, onAdd } = setup({ success: true, status: 'none', feeds: [], homepage: true, pages: [BLOG, PRESS] });
    await typeHome();
    await userEvent.click(await within(dialog()).findByRole('button', { name: 'Follow pay.example/blog: 269 articles' }));

    expect(within(dialog()).getByText('Following pay.example/blog')).toBeInTheDocument();
    expect(within(dialog()).getByText('Found 269 articles under /blog/')).toBeInTheDocument();
    expect(within(dialog()).getByText('A post from /blog/')).toBeInTheDocument();
    expect(within(dialog()).getByLabelText(/^Path/)).toHaveValue('/blog/');
    expect(api.previewPageWatch).not.toHaveBeenCalled();

    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add source' }));
    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    expect(onAdd.mock.calls[0][0]).toMatchObject({
      handle_or_url: 'https://pay.example/blog', display_name: 'pay.example', page_watch: { prefix: '/blog/' } });
  });

  it('the other candidates are behind "Other pages on this site"', async () => {
    const { onAdd } = setup({ success: true, status: 'none', feeds: [], homepage: true, pages: [BLOG, PRESS] });
    await typeHome();
    await within(dialog()).findByRole('button', { name: 'Follow pay.example/blog: 269 articles' });
    await userEvent.click(within(dialog()).getByText('Other pages on this site'));
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Follow pay.example/press: 12 articles' }));

    expect(within(dialog()).getByText('Found 12 articles under /press/')).toBeInTheDocument();
    // The blog moves behind "Other pages", so it can be chosen again.
    expect(within(dialog()).getByRole('button', { name: 'Follow pay.example/blog: 269 articles' })).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add source' }));
    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    expect(onAdd.mock.calls[0][0]).toMatchObject({ handle_or_url: 'https://pay.example/press', page_watch: { prefix: '/press/' } });
  });

  it('no blog page with articles: the home page is the last resort, with a plain warning', async () => {
    const { api, onAdd } = setup({ success: true, status: 'none', feeds: [], homepage: true, pages: [] });
    await typeHome();
    const warning = 'This is the site\'s homepage: it may pick up product pages, not articles.';
    expect(await within(dialog()).findByText(warning)).toBeInTheDocument();
    expect(within(dialog()).queryByText('Other pages on this site')).not.toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Follow this page instead' }));

    expect(await within(dialog()).findByText('Found 557 articles under /customers/')).toBeInTheDocument();
    expect(within(within(dialog()).getByTestId('page-watch')).getByText(warning)).toBeInTheDocument();
    expect(api.previewPageWatch).toHaveBeenCalledWith('pay.example', undefined);
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add source' }));
    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    expect(onAdd.mock.calls[0][0]).toMatchObject({ handle_or_url: 'https://pay.example', display_name: '' });
  });

  it('a section address is followed as it is, without the warning', async () => {
    const { api } = setup({ success: true, status: 'none', feeds: [], homepage: false, pages: [] });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'pay.example/news');
    await userEvent.click(await within(dialog()).findByRole('button', { name: 'Follow this page instead' }));
    await within(dialog()).findByText('Found 557 articles under /customers/');
    expect(api.previewPageWatch).toHaveBeenCalledWith('pay.example/news', undefined);
    expect(within(dialog()).queryByText(/This is the site's homepage/)).not.toBeInTheDocument();
  });
});

// claude.com from Discover (2026-10-31): its home page offered /resources/ (546 articles); 21 of
// the 24 claude.com articles your sources linked are under /blog/, now /resources/articles/.
describe('findings ranked by the articles your sources linked (issue 0060)', () => {
  const ARTICLES = { ...offer('https://lab.example/resources/articles', '/resources/articles/', 273), holds: 21 };
  const RESOURCES = { ...offer('https://lab.example/resources', '/resources/', 546), holds: 21 };
  const NEWS = { ...offer('https://lab.example/news', '/news/', 40), holds: 0 };

  it('lists every page with what it holds, the best already chosen and previewed', async () => {
    const { api, onAdd } = setup({ success: true, status: 'none', feeds: [], homepage: true, linked: 24,
      start: 'https://lab.example/blog', pages: [ARTICLES, RESOURCES, NEWS] });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'lab.example');

    const best = await within(dialog()).findByRole('radio', { name: /lab\.example\/resources\/articles.*273 articles/ });
    expect(best).toBeChecked();
    expect(within(dialog()).getAllByText('Holds 21 of the 24 articles your sources linked')).toHaveLength(2);
    expect(within(dialog()).getByText('Holds 0 of the 24 articles your sources linked')).toBeInTheDocument();
    expect(within(dialog()).getByText('Following lab.example/resources/articles')).toBeInTheDocument();
    expect(within(dialog()).getByText('Found 273 articles under /resources/articles/')).toBeInTheDocument();
    expect(within(dialog()).queryByText('Other pages on this site')).not.toBeInTheDocument();
    expect(api.previewPageWatch).not.toHaveBeenCalled();

    await userEvent.click(within(dialog()).getByRole('radio', { name: /lab\.example\/news/ }));
    expect(within(dialog()).getByText('Found 40 articles under /news/')).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /lab\.example\/resources\/articles/ }));
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add source' }));
    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    expect(onAdd.mock.calls[0][0]).toMatchObject({ handle_or_url: 'https://lab.example/resources/articles',
      display_name: 'lab.example', page_watch: { prefix: '/resources/articles/' } });
  });

  it('feeds say what they hold, the one holding the most chosen', async () => {
    setup({ success: true, status: 'found', homepage: false, linked: 5, start: null, pages: [],
      feeds: [{ url: 'https://lab.example/writing/feed', title: 'Writing', holds: 4 },
        { url: 'https://lab.example/podcast.xml', title: 'Podcast', holds: 1 }] });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'lab.example/writing');
    expect(await within(dialog()).findByRole('radio', { name: /Writing/ })).toBeChecked();
    expect(within(dialog()).getByText('Holds 4 of the 5 articles your sources linked')).toBeInTheDocument();
    expect(within(dialog()).getByText('Holds 1 of the 5 articles your sources linked')).toBeInTheDocument();
  });

  it('one feed found says what it holds', async () => {
    setup({ success: true, status: 'found', homepage: false, linked: 1, start: 'https://lab.example/blog', pages: [],
      feeds: [{ url: 'https://lab.example/blog/feed', title: 'Lab blog', holds: 1 }] });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'lab.example');
    expect(await within(dialog()).findByText('Holds the article your sources linked')).toBeInTheDocument();
  });

  it('a site your sources never linked offers its pages as before', async () => {
    setup({ success: true, status: 'none', feeds: [], homepage: true, linked: 0, start: null, pages: [BLOG, PRESS] });
    await typeHome();
    expect(await within(dialog()).findByRole('button', { name: 'Follow pay.example/blog: 269 articles' })).toBeInTheDocument();
    expect(within(dialog()).queryByRole('radio')).not.toBeInTheDocument();
    expect(within(dialog()).queryByText(/your sources linked/)).not.toBeInTheDocument();
  });
});

describe('a feed whose posts moved (issue 0108)', () => {
  it('offers the moved-to feed first and says where the old feed\'s posts live', async () => {
    setup({ success: true, status: 'found', homepage: false, linked: 0, start: null, pages: [],
      feeds: [{ url: 'https://www.blog.example/rss/', title: 'The Blog' },
        { url: 'https://home.example/feed.xml', title: 'Home', moved_to: 'blog.example' }] });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'home.example');
    expect(await within(dialog()).findByRole('radio', { name: /The Blog/ })).toBeChecked();
    expect(within(dialog()).getByRole('radio', { name: /Home/ })).not.toBeChecked();
    expect(within(dialog()).getByText('The posts of this feed now live at blog.example')).toBeInTheDocument();
  });
});

describe('new spheres (issue 0135)', () => {
  it('a saved search is said to be one, after the site\'s own feed', async () => {
    setup({ success: true, status: 'found', homepage: false, linked: 0, start: null, pages: [],
      feeds: [{ url: 'https://journal.example/toc.rss', title: 'Current issue' },
        { url: 'https://journal.example/feed', title: 'Keyword search for query', saved_search: true }] });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'journal.example');
    expect(await within(dialog()).findByRole('radio', { name: /Current issue/ })).toBeChecked();
    expect(within(dialog()).getByText('A saved search, not the site\'s own feed')).toBeInTheDocument();
  });

  it('refuses a feed whose items cannot be read', async () => {
    setup({ success: true, status: 'none', feeds: [], homepage: false, pages: [], refused: 'this feed has items INSIGHT can\'t read' });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'stray.example/feed');
    expect(await within(dialog()).findByText('Not added: this feed has items INSIGHT can\'t read')).toBeInTheDocument();
    expect(within(dialog()).getByRole('button', { name: 'Add source' })).toBeDisabled();
  });

  it('says why no feed was found (issue 0137)', async () => {
    setup({ success: true, status: 'none', feeds: [], homepage: false, pages: [], reason: 'blocked' });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'shut.example/journal');
    expect(await within(dialog()).findByText('No feed found: the site refused INSIGHT (blocked)')).toBeInTheDocument();
  });

  it('a bridge that did not answer is not "no bridge" (issue 0185)', async () => {
    setup({ success: true, status: 'none', feeds: [], homepage: false, pages: [], reason: 'bridge did not answer' });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'shut.example/someone');
    expect(await within(dialog()).findByText(/^No feed found: the bridge on this server did not answer/)).toBeInTheDocument();
    expect(within(dialog()).queryByText(/no bridge is set up/)).toBeNull();
  });

  it('says when only a saved search was found (issue 0137)', async () => {
    setup({ success: true, status: 'found', homepage: false, pages: [], note: 'only a saved search was found',
      feeds: [{ url: 'https://journal.example/search/rss?q=x', title: 'Keyword search', saved_search: true }] });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'journal.example');
    expect(await within(dialog()).findByText(/^Only a saved search was found/)).toBeInTheDocument();
  });

  it('a site\'s feed found for one author\'s page says so and offers to follow the page instead (issue 0137)', async () => {
    const page = offer('https://tank.example/blog/an-author', '/blog/an-author/', 4);
    const { onAdd } = setup({ success: true, status: 'found', homepage: false, pages: [], watch: page,
      feeds: [{ url: 'https://tank.example/feed', title: 'The tank', not_this_page: 'other_scope' }] });
    await userEvent.type(within(dialog()).getByLabelText('Feed URL or handle'), 'tank.example/blog/an-author');
    expect(await within(dialog()).findByText(/^Found the site's feed, not this page's/)).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Follow this page instead' }));
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add source' }));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({
      handle_or_url: 'https://tank.example/blog/an-author', page_watch: { prefix: '/blog/an-author/' } }));
  });

  it('the Telegram template builds on the server\'s bridge, and says so when there is none', async () => {
    bridge.mockResolvedValueOnce('https://tg.example');
    const first = renderWithProviders(<AddSourceModal onClose={vi.fn()} onAdd={vi.fn()} />, { api: makeFakeApi({}) });
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Telegram RSS' }));
    await userEvent.type(within(dialog()).getByLabelText(/^Channel Username/), 'achannel');
    expect(await within(dialog()).findByText('→ https://tg.example/rss/achannel?limit=50')).toBeInTheDocument();
    first.unmount();

    bridge.mockResolvedValueOnce(null);
    renderWithProviders(<AddSourceModal onClose={vi.fn()} onAdd={vi.fn()} />, { api: makeFakeApi({}) });
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Telegram RSS' }));
    expect(await within(dialog()).findByText(/No Telegram bridge is set up on this server/)).toBeInTheDocument();
    await userEvent.type(within(dialog()).getByLabelText(/^Channel Username/), 'achannel');
    expect(within(dialog()).getByRole('button', { name: 'Add source' })).toBeDisabled();
  });
});
