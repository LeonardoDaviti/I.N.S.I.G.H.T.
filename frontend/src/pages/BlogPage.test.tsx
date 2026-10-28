import { describe, expect, it } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes, useLocation } from 'react-router-dom';

import BlogPage from './BlogPage';
import { POSTS } from '../blog/posts';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderBlog(route: string) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/blog" element={<BlogPage />} />
        <Route path="/blog/:slug" element={<BlogPage />} />
      </Routes>
      <Where />
    </>,
    { api: makeFakeApi({}), route },
  );
}

describe('/blog', () => {
  it('lists every post, newest first, linking to its page', () => {
    renderBlog('/blog');
    const links = screen.getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual(POSTS.map((p) => `/blog/${p.slug}`));
    expect(links[0]).toHaveTextContent(POSTS[0].title);
  });

  it('an unknown post goes back to the list', async () => {
    renderBlog('/blog/nope');
    expect(await screen.findByRole('heading', { name: 'Blog' })).toBeInTheDocument();
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/blog$/);
  });
});

describe('/blog/junior-to-senior', () => {
  it('renders the article with its figures, each labelled for screen readers', async () => {
    renderBlog('/blog/junior-to-senior');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('From junior to senior');
    expect(await screen.findByRole('heading', { name: /A layer “to be safe”/ })).toBeInTheDocument();
    const figures = screen.getAllByRole('img');
    expect(figures).toHaveLength(9);
    for (const figure of figures) expect(figure).toHaveAccessibleName();
  });

  it('keeps its first date and says when it was updated, with the two new parts', async () => {
    renderBlog('/blog/junior-to-senior');
    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement;
    expect(header).toHaveTextContent('11 October 2026 · updated 28 October 2026 · 39 min read');
    expect(await screen.findByRole('heading', { name: /How an issue moves now/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /How fast we ship, and is that good\?/ })).toBeInTheDocument();
  });

  it('the quiz checks an answer, explains it, and resets for another try', async () => {
    renderBlog('/blog/junior-to-senior');
    const item = (await screen.findAllByRole('group'))[0].closest('li') as HTMLElement;
    const check = within(item).getByRole('button', { name: 'Check' });
    expect(check).toBeDisabled();

    fireEvent.click(within(item).getByLabelText('An HTTP 500 server error'));
    fireEvent.click(check);
    expect(within(item).getByRole('status')).toHaveTextContent('Not quite.');

    fireEvent.click(within(item).getByRole('button', { name: 'Try again' }));
    fireEvent.click(within(item).getByLabelText('An HTTP 200 success response'));
    fireEvent.click(within(item).getByRole('button', { name: 'Check' }));
    expect(within(item).getByRole('status')).toHaveTextContent('Right.');
  });
});
