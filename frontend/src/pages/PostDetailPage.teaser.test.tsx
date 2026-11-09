import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';

import { baseApi, renderPost, rssPost } from './PostDetailPage.testkit';
import { resetStoredChoices } from '../hooks/useShortcutPreference';

// A teaser (issue 0140): a post left as its feed's summary says so under its text, why, and links the page.

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('PostDetailPage teaser line', () => {
  it('says Summary only, why, and opens the page', async () => {
    renderPost(baseApi(rssPost({ teaser_reason: 'its page needs a script to show the article' })));
    await screen.findByRole('article', { name: 'Post content' });
    expect(document.querySelector('[data-teaser]')?.textContent)
      .toBe('Summary only · its page needs a script to show the article · Open the page ↗');
    const link = screen.getByRole('link', { name: 'Open the page ↗' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.getAttribute('href')).toBeTruthy();
  });

  it('says nothing for a post read in full or whole', async () => {
    renderPost(baseApi(rssPost({ teaser_reason: null })));
    await screen.findByRole('article', { name: 'Post content' });
    expect(document.querySelector('[data-teaser]')).toBeNull();
  });
});
