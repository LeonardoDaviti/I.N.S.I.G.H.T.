import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';

import { baseApi, renderPost, rssPost } from './PostDetailPage.testkit';
import { resetStoredChoices } from '../hooks/useShortcutPreference';

// An aggregator's page (0280): the header names the page's site, the feed as "via", and links the thread before any
// fetch. Synthetic data only.

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('PostDetailPage header for an aggregator page', () => {
  it('reads "curiousbits.example via <feed>" and links the discussion', async () => {
    renderPost(baseApi(rssPost({
      byline: { author: 'curiousbits.example', via: 'Hacker News', quoting: null },
      discussion: { name: 'Hacker News', url: 'https://news.ycombinator.com/item?id=1', total: null },
    })));
    await screen.findByRole('article', { name: 'Post content' });
    const header = document.querySelector('header')!;
    expect(header.querySelector('[data-page-site]')?.textContent).toBe('curiousbits.example');
    expect(header.textContent).toContain('curiousbits.examplevia');
    expect(header.textContent).not.toContain('↻');
    const link = screen.getByRole('link', { name: 'Discussion on Hacker News' });
    expect(link.getAttribute('href')).toBe('https://news.ycombinator.com/item?id=1');
  });

  it('shows neither for a feed\'s own post', async () => {
    renderPost(baseApi(rssPost({ discussion: null })));
    await screen.findByRole('article', { name: 'Post content' });
    expect(document.querySelector('[data-page-site]')).toBeNull();
    expect(document.querySelector('[data-discussion-link]')).toBeNull();
  });
});
