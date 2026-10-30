import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';

import { baseApi, renderPost, rssPost } from './PostDetailPage.testkit';
import { resetStoredChoices } from '../hooks/useShortcutPreference';

// Background (issue 0051): a post that links a classic says so, in one quiet line under it.

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('PostDetailPage Background', () => {
  it('names each classic the post builds on, a stored one in the reader, an outside one as a link', async () => {
    renderPost(baseApi(rssPost({ background: [
      { url: 'https://arxiv.org/abs/2001.08361', post_id: null, title: 'Scaling Laws for Neural Language Models', voices: 3 },
      { url: 'https://anthropic.com/news/golden-gate-claude', post_id: '00000000-0000-4000-8000-0000000000aa', title: 'Golden Gate Claude', voices: 2 },
    ] })));
    await screen.findByRole('article', { name: 'Post content' });
    const lines = [...document.querySelectorAll('[data-background] p')].map((p) => p.textContent);
    expect(lines).toEqual([
      'Builds on: Scaling Laws for Neural Language Models · cited by 3 of your sources',
      'Builds on: Golden Gate Claude · cited by 2 of your sources',
    ]);
    expect(screen.getByRole('link', { name: /Scaling Laws for Neural Language Models/ })).toHaveAttribute('href', 'https://arxiv.org/abs/2001.08361');
    expect(screen.getByRole('link', { name: 'Golden Gate Claude' })).toHaveAttribute('href', '/posts/00000000-0000-4000-8000-0000000000aa');
  });

  it('says nothing when the post links no classic', async () => {
    renderPost(baseApi(rssPost({ background: [] })));
    await screen.findByRole('article', { name: 'Post content' });
    expect(document.querySelector('[data-background]')).toBeNull();
    expect(screen.queryByText(/Builds on/)).not.toBeInTheDocument();
  });
});
