import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import MarkXStoryPage from '../../pages/MarkXStoryPage';
import { StoryThings } from './MarkXEntities';
import type { MarkxStoryThing, MarkxStoryView } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

/** Issue 0250, invented names: a story page's things, each one click from its entity page. */
const THINGS: MarkxStoryThing[] = [
  { id: 'vexa-kestrel', name: 'Vexa (Kestrel)', type: 'model', maker: 'Kestrel', maker_id: 'kestrel', role: 'subject', posts: 4 },
  { id: 'kestrel', name: 'Kestrel', type: 'org', maker: null, maker_id: null, role: 'actor', posts: 3 },
  { id: 'orbit', name: 'Orbit', type: 'model', maker: 'Vantor', maker_id: 'vantor', role: 'compared', posts: 1 },
];

describe('things in this story (0250)', () => {
  it('lists the things in the order the server ranks them, each a link to its entity page', () => {
    renderWithProviders(<StoryThings things={THINGS} />, { api: makeFakeApi({}) });
    const block = screen.getByRole('region', { name: 'Things in this story' });
    const rows = within(block).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Vexa (Kestrel) · model · by Kestrel · what it is about · 4 posts');
    expect(within(rows[0]).getByRole('link')).toHaveAttribute('href', '/markx/entities/vexa-kestrel');
    expect(rows[1]).toHaveTextContent('Kestrel · org · acts in it · 3 posts');
    expect(rows[2]).toHaveTextContent('Orbit · model · by Vantor · compared');
    expect(rows[2]).not.toHaveTextContent('post');
  });

  it('is not shown without a thing', () => {
    renderWithProviders(<StoryThings things={[]} />, { api: makeFakeApi({}) });
    expect(screen.queryByRole('region', { name: 'Things in this story' })).toBeNull();
  });

  it('sits on the story page, under the headline', async () => {
    const view: MarkxStoryView = {
      story: { id: 's1', headline: 'Kestrel opens Vexa to developers', first_at: '2026-11-09T10:00:00Z' },
      things: THINGS, judged: false, sheet: null, header: { text: 'Experimental.', source: 'lab', labels: 0 },
      members: [], counts: { members: 0, worth: 0, same: 0, copies: 0, unjudged: 0 }, posts: {},
    };
    renderWithProviders(
      <Routes><Route path="/markx/stories/:storyId" element={<MarkXStoryPage />} /></Routes>,
      { api: makeFakeApi({ getMarkxStory: vi.fn().mockResolvedValue(view) }), route: '/markx/stories/s1' },
    );
    const block = await screen.findByRole('region', { name: 'Things in this story' });
    expect(within(block).getByRole('link', { name: 'Vexa (Kestrel)' })).toHaveAttribute('href', '/markx/entities/vexa-kestrel');
  });
});
