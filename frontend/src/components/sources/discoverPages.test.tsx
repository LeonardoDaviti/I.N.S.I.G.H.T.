import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import DiscoverPages, { pageLine } from './DiscoverPages';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { DiscoverPage } from '../../services/api';

const essay: DiscoverPage = {
  url: 'https://essays.example.com/2026/10/an-essay', title: 'An essay about the release', site: 'essays.example.com',
  hide_key: 'page:essays.example.com/2026/10/an-essay', video: false, first_linked_at: '2026-10-08T09:00:00Z', voices: 3,
  readable: true, stories: [{ url: 'https://essays.example.com/2026/10/an-essay', title: 'An essay', voices: 3, stored: false }],
};

function setup(pages: DiscoverPage[], api: Record<string, unknown> = {}) {
  const onFollow = vi.fn();
  renderWithProviders(<DiscoverPages pages={pages} onFollow={onFollow} />, { api: makeFakeApi(api) });
  return { onFollow };
}

describe('DiscoverPages (issue 0113)', () => {
  it('lists an entity original (0138 D1): the thing it is the original of, with its sources', () => {
    setup([{ ...essay, url: 'https://arxiv.org/abs/2611.01234', title: null, site: 'arxiv.org', stories: [], voices: 2,
      hide_key: 'page:arxiv.org/abs/2611.01234', entity: { id: 'e1', name: 'The Nimbus Paper' }, voice_names: ['Channel A', 'Channel B'] }]);
    expect(screen.getByRole('link', { name: 'The Nimbus Paper' })).toHaveAttribute('href', '/markx/entities/e1');
    expect(screen.getByText(/which 2 of your sources wrote about \(Channel A, Channel B\)/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save page' })).toBeInTheDocument();
  });

  it('lists a page with its site, its story and the three actions', () => {
    setup([essay]);
    expect(screen.getByText('An essay about the release')).toBeInTheDocument();
    expect(screen.getByText('A story of 3 sources starts here')).toBeInTheDocument();
    for (const name of ['Save page', 'Follow site…', 'Hide']) expect(screen.getByRole('button', { name })).toBeInTheDocument();
  });

  it('says a walled page probably can’t be read, and a video has nothing to save', () => {
    expect(pageLine({ ...essay, readable: false })).toContain('probably can’t be read');
    setup([{ ...essay, video: true }]);
    expect(screen.queryByRole('button', { name: 'Save page' })).not.toBeInTheDocument();
    expect(pageLine({ ...essay, tweet: true })).toContain('a tweet');
  });

  it('Save page saves through the save path and the row goes', async () => {
    const savePage = vi.fn().mockResolvedValue({ success: true, status: 'saved' });
    setup([essay], { savePage });
    fireEvent.click(screen.getByRole('button', { name: 'Save page' }));
    await waitFor(() => expect(screen.queryByText('An essay about the release')).not.toBeInTheDocument());
    expect(savePage).toHaveBeenCalledWith(essay.url, essay.title, expect.anything());
  });

  it('Hide hides that page by its key, Follow site… follows its site', async () => {
    const hideSuggestedSource = vi.fn().mockResolvedValue({ success: true });
    const { onFollow } = setup([essay], { hideSuggestedSource });
    fireEvent.click(screen.getByRole('button', { name: 'Follow site…' }));
    expect(onFollow).toHaveBeenCalledWith('https://essays.example.com');
    fireEvent.click(screen.getByRole('button', { name: 'Hide' }));
    await waitFor(() => expect(hideSuggestedSource).toHaveBeenCalledWith(essay.hide_key));
  });

  it('says so when there is nothing to save', () => {
    setup([]);
    expect(screen.getByText('No pages to save')).toBeInTheDocument();
  });
});
