import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AddSourceModal from './AddSourceModal';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { FeedFinding, PageOffer } from '../services/api';

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
