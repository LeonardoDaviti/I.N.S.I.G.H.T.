import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import MarkXStoryPage from '../../pages/MarkXStoryPage';
import { RowChain, StoryChain } from './MarkXChain';
import type { MarkxChain, MarkxChainLink, MarkxRowChain, MarkxStoryView } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

/** Issues 0219 and 0267, invented names: a story's Earlier and Later on its page, typed and explained. */
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

describe('Earlier and later (0219, 0267)', () => {
  it('shows the stories before and after, in date order, each with its relation in words and its reason', () => {
    renderWithProviders(<StoryChain chain={CHAIN} />, { api: makeFakeApi({}) });
    const block = screen.getByRole('region', { name: 'Earlier and later' });
    expect(within(block).getByRole('heading', { level: 2 })).toHaveTextContent('Earlier and later');
    const rows = within(block).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('2026-10-30Orbit 2 Small is coming · earlier in this release · via a linked story');
    expect(rows[1]).toHaveTextContent('2026-11-02Vantor releases Orbit 2 Small · earlier in this release');
    expect(rows[1]).toHaveTextContent('The launch, then its weights a week later.');
    expect(within(rows[1]).getByRole('link')).toHaveAttribute('href', '/markx/stories/launch');
    expect(rows[2]).toHaveTextContent('Orbit 2 Small ranks fourth on the arena · later in this release');
    expect(within(block).getByText('Earlier')).toBeInTheDocument();
    expect(within(block).getByText('Later')).toBeInTheDocument();
    expect(within(block).getByText('+2 more')).toBeInTheDocument();
  });

  it('is not shown without a link, and says the date it was read as of', () => {
    const { unmount } = renderWithProviders(<StoryChain chain={{ ...CHAIN, before: [], after: [] }} />,
      { api: makeFakeApi({}) });
    expect(screen.queryByRole('region', { name: 'Earlier and later' })).toBeNull();
    unmount();
    renderWithProviders(<StoryChain chain={{ ...CHAIN, as_of: '2026-11-05T00:00:00Z' }} />, { api: makeFakeApi({}) });
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Earlier and later · as of 2026-11-05');
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
    const block = await screen.findByRole('region', { name: 'Earlier and later' });
    expect(within(block).getAllByRole('listitem')).toHaveLength(3);
  });

  it('a News row says its Earlier and Later in one plain line each', () => {
    const row: MarkxRowChain = {
      before: [{ story: 'teaser', relation: 'same_release', reason: null, headline: 'Orbit 2 Small is coming',
        first_at: '2026-10-30T09:00:00Z' }],
      after: [{ story: 'ranking', relation: 'same_release', reason: 'Its ranking.', headline: 'Orbit 2 Small ranks fourth',
        first_at: '2026-11-12T08:00:00Z' }],
      before_more: 0, after_more: 1,
    };
    renderWithProviders(<RowChain chain={row} />, { api: makeFakeApi({}) });
    const lines = within(screen.getByRole('list', { name: 'Earlier and later' })).getAllByRole('listitem');
    expect(lines.map((l) => l.textContent)).toEqual([
      'Earlier: Orbit 2 Small is coming · 2026-10-30 · earlier in this release',
      'Later: Orbit 2 Small ranks fourth · 2026-11-12 · later in this release',
      '+1 more on the story page',
    ]);
    expect(within(lines[1]).getByRole('link')).toHaveAttribute('href', '/markx/stories/ranking');
  });

  it('a News row with none says nothing', () => {
    renderWithProviders(<RowChain chain={null} />, { api: makeFakeApi({}) });
    expect(screen.queryByRole('list', { name: 'Earlier and later' })).toBeNull();
  });
});
