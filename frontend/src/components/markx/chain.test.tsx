import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import MarkXStoryPage from '../../pages/MarkXStoryPage';
import { StoryChain } from './MarkXChain';
import type { MarkxChain, MarkxChainLink, MarkxStoryView } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

/** Issue 0219, invented names: a story's chain on its page (what led to it, what followed), typed and explained. */
const link = (story: string, headline: string, extra: Partial<MarkxChainLink> = {}): MarkxChainLink => ({
  story, via: 'weights', relation: 'same_release', reason: 'The launch, then its weights a week later.', depth: 1,
  headline, first_at: '2026-11-02T10:00:00Z', ...extra,
});
const CHAIN: MarkxChain = {
  before: [link('launch', 'Vantor releases Orbit 2 Small'),
    link('teaser', 'Orbit 2 Small is coming', { depth: 2, via: 'launch', first_at: '2026-10-30T09:00:00Z', reason: null })],
  after: [link('ranking', 'Orbit 2 Small ranks fourth on the arena', { first_at: '2026-11-12T08:00:00Z',
    reason: 'Its arena ranking, days after the weights.' })],
  before_more: 0, after_more: 2, as_of: null,
};

describe('the chain view (0219)', () => {
  it('shows what led to the story and what followed, each link typed with its reason', () => {
    renderWithProviders(<StoryChain chain={CHAIN} />, { api: makeFakeApi({}) });
    const block = screen.getByRole('region', { name: 'Chain' });
    expect(within(block).getByRole('heading', { level: 2 })).toHaveTextContent('Chain');
    const rows = within(block).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('2026-11-02Vantor releases Orbit 2 Small · earlier in this release');
    expect(rows[0]).toHaveTextContent('The launch, then its weights a week later.');
    expect(within(rows[0]).getByRole('link')).toHaveAttribute('href', '/markx/stories/launch');
    expect(rows[1]).toHaveTextContent('Orbit 2 Small is coming · earlier in this release · via a linked story');
    expect(rows[2]).toHaveTextContent('Orbit 2 Small ranks fourth on the arena · later in this release');
    expect(within(block).getByText('Led to it')).toBeInTheDocument();
    expect(within(block).getByText('Followed')).toBeInTheDocument();
    expect(within(block).getByText('+2 more')).toBeInTheDocument();
  });

  it('is not shown without a link, and says the date it was read as of', () => {
    const { unmount } = renderWithProviders(<StoryChain chain={{ ...CHAIN, before: [], after: [] }} />,
      { api: makeFakeApi({}) });
    expect(screen.queryByRole('region', { name: 'Chain' })).toBeNull();
    unmount();
    renderWithProviders(<StoryChain chain={{ ...CHAIN, as_of: '2026-11-05T00:00:00Z' }} />, { api: makeFakeApi({}) });
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Chain · as of 2026-11-05');
  });

  it('sits on the story page', async () => {
    const view: MarkxStoryView = {
      story: { id: 'weights', headline: "Vantor opens Orbit 2 Small's weights", first_at: '2026-11-09T10:00:00Z' },
      judged: false, sheet: null, header: { text: 'Experimental.', source: 'lab', labels: 0 }, members: [],
      counts: { members: 0, worth: 0, same: 0, copies: 0, unjudged: 0 }, posts: {}, chain: CHAIN,
    };
    renderWithProviders(
      <Routes><Route path="/markx/stories/:storyId" element={<MarkXStoryPage />} /></Routes>,
      { api: makeFakeApi({ getMarkxStory: vi.fn().mockResolvedValue(view) }), route: '/markx/stories/weights' },
    );
    const block = await screen.findByRole('region', { name: 'Chain' });
    expect(within(block).getAllByRole('listitem')).toHaveLength(3);
  });
});
