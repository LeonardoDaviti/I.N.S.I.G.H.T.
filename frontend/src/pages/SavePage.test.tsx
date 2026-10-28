import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import SavePage from './SavePage';
import type { SavedPage } from '../services/api';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { bookmarkletCode, siteOf } from '../lib/savePage';
import { DESTINATIONS, filterDestinations } from '../components/layout/navigation';

const ARTICLE = 'https://www.example.com/2026/10/an-essay';

function renderSave(route: string, answer: Partial<SavedPage> = {}, extra: Record<string, unknown> = {}) {
  const savePage = vi.fn().mockResolvedValue({ success: true, status: 'saved', post_id: 'p1', title: 'An essay',
    source_id: 's1', readable: true, reason: null, feed: null, ...answer });
  const api = makeFakeApi({ savePage, ...extra });
  renderWithProviders(<Routes><Route path="/save" element={<SavePage />} /></Routes>, { api, route });
  return { savePage, api };
}

const fromBookmarklet = `/save?url=${encodeURIComponent(ARTICLE)}&title=${encodeURIComponent('An essay | Example')}`;

describe('/save from the bookmarklet', () => {
  it('shows the page and saves only on Save, a POST with its address and title', async () => {
    const { savePage } = renderSave(fromBookmarklet);
    expect(screen.getByRole('heading', { name: 'Save to INSIGHT' })).toBeInTheDocument();
    expect(screen.getByText('An essay | Example')).toBeInTheDocument();
    expect(screen.getByText('example.com')).toBeInTheDocument();
    expect(savePage).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(savePage).toHaveBeenCalledWith(ARTICLE, 'An essay | Example');
    expect(await screen.findByText('Saved to INSIGHT')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Read it' })).toHaveAttribute('href', '/posts/p1');
    expect(screen.getByRole('link', { name: 'Saved' })).toHaveAttribute('href', '/read/source/s1');
    // A save goes to Later (issue 0022, owner's decision).
    expect(screen.getByRole('link', { name: 'Read it' }).parentElement).toHaveTextContent('An essay is in Saved and in Later, unread. Read it');
    expect(screen.getByRole('link', { name: 'Later' })).toHaveAttribute('href', '/?filter=later');
    expect(screen.getByRole('button', { name: 'Close tab' })).toBeInTheDocument();
  });

  it('a page already stored is not saved again: it links to the post', async () => {
    renderSave(fromBookmarklet, { status: 'already', post_id: 'p0', title: 'An essay', readable: undefined });
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Already in INSIGHT')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Read it' })).toHaveAttribute('href', '/posts/p0');
    expect(screen.getByRole('link', { name: 'Read it' }).parentElement).toHaveTextContent('An essay. It’s in Later. Read it');
    expect(screen.getByRole('link', { name: 'Later' })).toHaveAttribute('href', '/?filter=later');
  });

  it('a page that could not be read is saved with its title and says so', async () => {
    renderSave(fromBookmarklet, { readable: false, reason: 'HTTP 403' });
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Saved, without its text')).toBeInTheDocument();
    expect(screen.getByText(/couldn’t be read as an article \(HTTP 403\)/)).toBeInTheDocument();
  });

  it('offers the site’s feed and follows it through Add source', async () => {
    const addSource = vi.fn().mockResolvedValue({ success: true, source_id: 'f1' });
    const fetchSourceNow = vi.fn(() => new Promise(() => {}));
    renderSave(fromBookmarklet, { feed: { url: 'https://example.com/feed.xml', title: 'Example' } }, { addSource, fetchSourceNow });
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('This site has a feed. Follow it?')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Follow' }));
    expect(addSource).toHaveBeenCalledWith({ platform: 'rss', handle_or_url: 'https://example.com/feed.xml', display_name: 'Example' });
    expect(await screen.findByText('Following Example')).toBeInTheDocument();
    await waitFor(() => expect(fetchSourceNow).toHaveBeenCalledWith('f1', expect.anything()));
  });

  it('an error is shown and Save can be pressed again', async () => {
    renderSave(fromBookmarklet, { success: false, error: 'Only an http or https page can be saved' });
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Only an http or https page can be saved')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
  });
});

describe('/save from ⌘K', () => {
  it('takes a pasted address and saves it on Enter', async () => {
    const { savePage } = renderSave('/save');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Page address'), `${ARTICLE}{Enter}`);
    expect(savePage).toHaveBeenCalledWith(ARTICLE, undefined);
    expect(await screen.findByText('Saved to INSIGHT')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save another page' }));
    expect(screen.getByLabelText('Page address')).toHaveValue('');
  });

  it('shows the bookmarklet to drag to the bookmarks bar', () => {
    renderSave('/save');
    const link = screen.getByText('Save to INSIGHT', { selector: 'a' });
    expect(link.getAttribute('href')).toBe(bookmarkletCode(window.location.origin));
  });

  it('is a ⌘K entry', () => {
    const entry = DESTINATIONS.find((item) => item.id === 'save-page');
    expect(entry).toMatchObject({ label: 'Save a page…', to: '/save' });
    expect(filterDestinations('bookmark').map((item) => item.id)).toContain('save-page');
  });
});

describe('the bookmarklet', () => {
  it('opens the save page of this INSIGHT in a new tab with the page’s address and title', () => {
    const code = bookmarkletCode('http://insight.local:5173/');
    expect(code.startsWith('javascript:')).toBe(true);
    const opened: unknown[][] = [];
    const fakeWindow = { open: (...args: unknown[]) => opened.push(args) };
    const fakeLocation = { href: 'https://a.example/x?y=1&z=2' };
    const fakeDocument = { title: 'A & B' };
    new Function('window', 'location', 'document', code.slice('javascript:'.length))(fakeWindow, fakeLocation, fakeDocument);
    expect(opened).toEqual([[
      `http://insight.local:5173/save?url=${encodeURIComponent(fakeLocation.href)}&title=${encodeURIComponent('A & B')}`,
      '_blank',
      'noopener',
    ]]);
  });

  it('names a page by its site', () => {
    expect(siteOf('https://www.example.com/a')).toBe('example.com');
    expect(siteOf('example.org/b')).toBe('example.org');
  });
});
