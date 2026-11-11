import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXEntities from './MarkXEntities';
import { EntityInvariants } from './MarkXOverview';
import type { MarkxEntityQueue, MarkxEntityRef, MarkxQueueItem } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

/** 0164 A and C, invented names: the card shows each name's group and what `same` would do; the overview warns. */
const now = new Date().toISOString();
const ref = (id: string, name: string, extra: Partial<MarkxEntityRef> = {}): MarkxEntityRef => ({
  id, name, type: 'model', maker: null, level: 'thing', version: null, variant: null, size: null, build: null,
  status: 'provisional', family: null, ...extra,
});
const ACCURACY = { merges: 'automatic merges 97.6% right (lab)', surges: 'surges 91% (lab)', collisions: 'splits 55% (lab)' };

const item = (join: MarkxQueueItem['join']): MarkxQueueItem => ({
  id: 'q1', kind: 'alias', proposal: 'same', reason: 'type', confidence: 0.97, answer: null, answered_at: null,
  created_at: now, evidence: { judge: { relation: 'same', confidence: 0.97, evidence: 'The family and its account.' } }, join,
  a: { ...ref('e1', 'Vela', { level: 'family' }), root: 'e1', posts: [],
    group: { root: 'e1', name: 'Vela', type: 'model', size: 1, names: ['Vela'], more: 0, sides: { family: ['Vela'], org: [] } } },
  b: { ...ref('e2', 'Zentra Vela', { type: 'org' }), root: 'e9', posts: [],
    group: { root: 'e9', name: 'Zentra AI', type: 'org', size: 3, names: ['Zentra AI', 'Zentra', 'Zentra Vela'], more: 0,
      sides: { family: ['Zentra Vela'], org: ['Zentra', 'Zentra AI'] } } },
});
const queue = (it: MarkxQueueItem): MarkxEntityQueue => ({
  open: [it], answered: [], accuracy: ACCURACY, merges: [],
  counts: { open: 1, answered: {}, automatic_merges: 0, automatic_undone: 0 },
});

describe('Mark X entity guards (issue 0164)', () => {
  it('shows the group a name is in and says same joins only the two names', async () => {
    const answerMarkxEntity = vi.fn().mockResolvedValue({ answer: 'same', result: 'joined_names' });
    const it = item({ mixes: true, only_names: true, apart: [{ name: 'Zentra AI', from: 'Vela' }], needs_choice: false });
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue({ window_days: 30, total: 0, queue: 1, accuracy: ACCURACY, items: [] }),
      getMarkxEntityQueue: vi.fn().mockResolvedValue(queue(it)), answerMarkxEntity }) });
    expect(await screen.findByText('part of: Zentra AI (Zentra, Zentra Vela)')).toBeInTheDocument();
    expect(screen.queryByText(/part of: Vela/)).not.toBeInTheDocument();      // its own group: no line
    expect(screen.getByRole('note')).toHaveTextContent('Same joins only these two names; Zentra AI stays apart from Vela.');
    const buttons = screen.getByRole('group', { name: 'Your answer' });
    expect(within(buttons).getAllByRole('button').map((b) => b.textContent))
      .toEqual(['same', 'other version', 'different', 'not an entity']);   // the card's buttons are kept
    await userEvent.click(within(buttons).getByRole('button', { name: 'same' }));
    await waitFor(() => expect(answerMarkxEntity).toHaveBeenCalledWith('q1', 'same'));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('says why an answer was not applied when the owner’s own merge holds the name there', async () => {
    const message = '“Zentra Vela” is held with Zentra AI by your own earlier merge.';
    const answerMarkxEntity = vi.fn().mockResolvedValue({ answer: 'same', result: 'needs_choice', message });
    const it = item({ mixes: true, only_names: false, apart: [{ name: 'Zentra AI', from: 'Vela' }], needs_choice: true });
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue({ window_days: 30, total: 0, queue: 1, accuracy: ACCURACY, items: [] }),
      getMarkxEntityQueue: vi.fn().mockResolvedValue(queue(it)), answerMarkxEntity }) });
    expect(await screen.findByRole('note')).toHaveTextContent(/your own earlier merge/);
    await userEvent.click(screen.getByRole('button', { name: 'same' }));
    expect(await screen.findByRole('status')).toHaveTextContent(`Not applied: ${message}`);
  });

  it('shows no warning when same mixes nothing', async () => {
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue({ window_days: 30, total: 0, queue: 1, accuracy: ACCURACY, items: [] }),
      getMarkxEntityQueue: vi.fn().mockResolvedValue(queue(item(null))) }) });
    expect(await screen.findByText('part of: Zentra AI (Zentra, Zentra Vela)')).toBeInTheDocument();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('warns on the overview when a group holds a product family and an org, and says nothing when none does', () => {
    const { unmount } = renderWithProviders(<EntityInvariants state={{ family_org: { count: 2, held: 1, clusters: [
      { id: 'c1', name: 'Zentra AI', family: ['Vela', 'Zentra Vela'], org: ['Zentra', 'Zentra AI'] }] } }} />,
    { api: makeFakeApi({}) });
    const alert = screen.getByRole('alert', { name: 'Entity invariant' });
    expect(alert).toHaveTextContent('2 entity groups hold both a product family and an org (1 group held together by your own merges)');
    expect(within(alert).getByRole('link', { name: 'Zentra AI' })).toHaveAttribute('href', '/markx/entities/c1');
    expect(alert).toHaveTextContent('family Vela, Zentra Vela · org Zentra, Zentra AI');
    unmount();
    renderWithProviders(<EntityInvariants state={{ family_org: { count: 0, held: 0, clusters: [] } }} />, { api: makeFakeApi({}) });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
