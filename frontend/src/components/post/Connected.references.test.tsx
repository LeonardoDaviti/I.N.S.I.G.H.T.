import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';

import Connected from './Connected';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { PostConnectedReferences } from '../../services/api';

// A full text's reference list (issue 0137 B8): its links are not Outside rows but a folded "References" group.

const POST = '00000000-0000-4000-8000-000000000003';

function answer(overrides: Partial<PostConnectedReferences> = {}): PostConnectedReferences {
  return { success: true, earlier: [], later: [], outside: [], more: { earlier: 0, later: 0, outside: 0 }, ...overrides };
}

function renderIt(data: PostConnectedReferences) {
  renderWithProviders(<Connected postId={POST} />, {
    api: makeFakeApi({ getPostConnected: vi.fn().mockResolvedValue(data) }), route: `/posts/${POST}`,
  });
}

describe('references in Connected (issue 0137)', () => {
  it('lists them folded under References with their count, each opening its page', async () => {
    renderIt(answer({ references: [
      { url: 'https://doi.example/10.1000/a', address: 'https://doi.example/10.1000/a', host: 'doi.example', title: 'doi' },
      { url: 'https://papers.example/b', address: 'https://papers.example/b', host: 'papers.example', title: null },
    ] }));
    const group = await screen.findByLabelText('References');
    expect(group).not.toHaveAttribute('open');
    expect(group).toHaveTextContent('References· 2');
    expect(within(group).getByRole('link', { name: /doi/ })).toHaveAttribute('href', 'https://doi.example/10.1000/a');
    expect(within(group).getByRole('link', { name: /papers\.example\/b/ })).toHaveAttribute('href', 'https://papers.example/b');
  });

  it('shows nothing for a post with no references, or from an older server', async () => {
    const { container } = renderWithProviders(<Connected postId={POST} />, {
      api: makeFakeApi({ getPostConnected: vi.fn().mockResolvedValue(answer({ references: [] })) }), route: `/posts/${POST}`,
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.querySelector('[data-connected]')).toBeNull();
  });
});
