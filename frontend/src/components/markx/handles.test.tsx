import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import MarkXEntityPage from '../../pages/MarkXEntityPage';
import MarkXEntities from './MarkXEntities';
import type { MarkxEntityPage, MarkxEntityQueue, MarkxEntityRef, MarkxQueueItem } from '../../services/markx';
import { makeFakeApi as makeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const makeFakeApi = (methods: Record<string, unknown>) => makeApi(methods as Parameters<typeof makeApi>[0]);
const now = new Date().toISOString();
const entity: MarkxEntityRef = { id: 'e1', name: 'Ivo Kestrel', type: 'person', maker: null, level: 'thing', version: null, variant: null,
  size: null, build: null, status: 'provisional', family: null };

// Issue 0168: a person's handles on the page (with an old one's months), the replies to them hidden until asked, and
// the owner's handle question in the review queue.
const page: MarkxEntityPage = {
  entity, asked: 'e1', redirected: false, aliases: ['Ivo Kestrel'], maker: null, family: null, versions: [], posts: 3,
  voices: 3, accuracy: { merges: 'm', surges: 's', collisions: 'c' }, queue: [], surges: [], current: true, stories: [],
  loose: [{ id: 'l1', title: 'He said it ships', source: 'Round-up', at: now, roles: ['source'] }],
  loose_counts: { report: 0, by: 0, other: 1, mention: 0 },
  sources: [],
  handles: { known: [
    { platform: 'x', handle: 'ikestrel', via: 'owner', display_name: 'Ivo Kestrel', first_seen: null, last_seen: null },
    { platform: 'x', handle: 'ivo_old', via: 'owner', display_name: 'Ivo Kestrel', first_seen: '2023-01-04T00:00:00Z',
      last_seen: '2024-03-02T00:00:00Z' }], posts: 1, replies: 2, replies_shown: false },
};

describe('a person’s handles (0168)', () => {
  it('lists the handles, an old one with its months, and shows the replies when asked', async () => {
    const getMarkxEntity = vi.fn().mockResolvedValue(page);
    renderWithProviders(<Routes><Route path="/markx/entities/:entityId" element={<MarkXEntityPage />} /></Routes>,
      { api: makeFakeApi({ getMarkxEntity }), route: '/markx/entities/e1' });
    const section = await screen.findByRole('region', { name: 'Ivo Kestrel\'s handles' });
    expect(within(section).getByRole('heading')).toHaveTextContent('Handles · 1 post cite them');
    expect(section).toHaveTextContent('@ikestrel (X)');
    expect(section).toHaveTextContent('@ivo_old (X, 2023-01 to 2024-03)');
    expect(getMarkxEntity).toHaveBeenCalledWith('e1');
    fireEvent.click(within(section).getByRole('button', { name: 'show 2 replies to them' }));
    await waitFor(() => expect(getMarkxEntity).toHaveBeenCalledWith('e1', undefined, true));
  });
});

describe('a handle question (0168)', () => {
  it('asks whether the handle is theirs, shows the pairs, and answers yes as same', async () => {
    const item: MarkxQueueItem = {
      id: 'q9', kind: 'handle', proposal: 'same', reason: 'second_handle', confidence: 1, answer: null, answered_at: null,
      created_at: now, join: null,
      evidence: { platform: 'x', handle: 'ivo_old', display: 'Ivo Kestrel', pairs: 3, total: 3,
        first: '2023-01-04T00:00:00Z', last: '2024-03-02T00:00:00Z', alias_of: ['ikestrel'] },
      a: { ...entity, root: 'e1', posts: [] }, b: null,
    };
    const queue: MarkxEntityQueue = { open: [item], answered: [], merges: [],
      accuracy: { merges: 'm', surges: 's', collisions: 'c' },
      counts: { open: 1, answered: {}, automatic_merges: 0, automatic_undone: 0 } };
    const answerMarkxEntity = vi.fn().mockResolvedValue({ answer: 'same' });
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue({ window_days: 30, total: 0, queue: 1, accuracy: queue.accuracy, items: [] }),
      getMarkxEntityQueue: vi.fn().mockResolvedValue(queue), answerMarkxEntity }) });
    expect(await screen.findByText(/Is @ivo_old Ivo Kestrel’s X handle\?/)).toBeInTheDocument();
    expect(screen.getByText('3 posts write “Ivo Kestrel (@ivo_old)” · 2023-01 to 2024-03 · their other handle @ikestrel'))
      .toBeInTheDocument();
    const buttons = screen.getByRole('group', { name: 'Your answer' });
    expect(within(buttons).getAllByRole('button').map((b) => b.textContent)).toEqual(['yes, theirs', 'no']);
    fireEvent.click(within(buttons).getByRole('button', { name: 'yes, theirs' }));
    await waitFor(() => expect(answerMarkxEntity).toHaveBeenCalledWith('q9', 'same'));
  });
});
