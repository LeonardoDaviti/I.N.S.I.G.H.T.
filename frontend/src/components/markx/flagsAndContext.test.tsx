import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import MarkXEntities, { EntityPostLine } from './MarkXEntities';
import MarkXEntityPage from '../../pages/MarkXEntityPage';
import type { MarkxEntityPage, MarkxEntityQueue, MarkxEntityRef, MarkxQueueItem } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

/** Issue 0222, invented names: the owner is asked only what Claude flagged; the whole queue is the operator's,
 * collapsed; an answer about posts a side no longer holds is never shown; each post shows its mention in context. */
const now = new Date().toISOString();
const ref = (id: string, name: string): MarkxEntityRef => ({
  id, name, type: 'software', maker: null, level: 'thing', version: null, variant: null, size: null, build: null,
  status: 'provisional', family: null,
});
const ACCURACY = { merges: 'automatic merges 97.6% right (lab)', surges: 'surges 91% (lab)', collisions: 'splits 55% (lab)' };
const item = (id: string, extra: Partial<MarkxQueueItem> = {}): MarkxQueueItem => ({
  id, kind: 'alias', proposal: 'same', reason: 'below_bar', confidence: 0.86, answer: null, answered_at: null, created_at: now,
  evidence: { judge: { relation: 'same', confidence: 0.86, evidence: 'One tool, two spellings.' } },
  opinion: { by: 'haiku', relation: 'same', confidence: 0.86, rules: [] },
  a: { ...ref('e1', 'Kestrel Coder'), root: 'e1', posts: [] }, b: { ...ref('e2', 'Kestrel Coder CLI'), root: 'e2', posts: [] },
  ...extra,
});
const queue = (open: MarkxQueueItem[], counts: Partial<MarkxEntityQueue['counts']> = {}): MarkxEntityQueue => ({
  open, answered: [], accuracy: ACCURACY, merges: [],
  counts: { open: 17262, answered: {}, automatic_merges: 0, automatic_undone: 0, flagged: open.length, ...counts },
});
const LIST = { window_days: 30, total: 0, queue: 17262, flagged: 1, accuracy: ACCURACY, items: [] };

describe('the owner sees only flags (issue 0222)', () => {
  it('lists the flagged items by default and asks for the whole queue only when the operator opens it', async () => {
    const flagged = item('q1', { flag: { at: now, by: 'claude', note: 'A plugin, not the tool itself.' } });
    const getMarkxEntityQueue = vi.fn(async (_limit?: number, view?: string) =>
      (view === 'all' ? queue([flagged, item('q2'), item('q3')]) : queue([flagged])));
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue(LIST), getMarkxEntityQueue }) });
    expect(await screen.findByText(/Flagged for you: 1/)).toBeInTheDocument();
    expect(screen.queryByText(/To review/)).not.toBeInTheDocument();
    expect(screen.getAllByRole('group', { name: 'Your answer' })).toHaveLength(1);
    expect(screen.getByText('flagged for you').closest('p')).toHaveTextContent('A plugin, not the tool itself.');
    expect(getMarkxEntityQueue.mock.calls.every((c) => c[1] === 'flagged')).toBe(true);
    await userEvent.click(screen.getByText(/Operator view: the whole queue \(17,262 open items\)/));
    await waitFor(() => expect(screen.getAllByRole('group', { name: 'Your answer' })).toHaveLength(4));
    expect(getMarkxEntityQueue).toHaveBeenCalledWith(50, 'all');
  });

  it('says nothing is flagged when nothing is', async () => {
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue(LIST), getMarkxEntityQueue: vi.fn(async () => queue([])) }) });
    expect(await screen.findByText(/Nothing flagged for you/)).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Your answer' })).not.toBeInTheDocument();
  });

  it('never shows an answer about posts a side no longer holds', async () => {
    const stale = item('q1', { void: 'posts', opinion: null, confidence: null, evidence: { judge: null },
      flag: { at: now, by: 'claude', note: null } });
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue(LIST), getMarkxEntityQueue: vi.fn(async () => queue([stale])) }) });
    expect(await screen.findByText(/about posts these names no longer hold/)).toHaveAttribute('data-void', 'posts');
    expect(screen.queryByText(/Haiku says/)).not.toBeInTheDocument();
    expect(screen.queryByText(/band/)).not.toBeInTheDocument();
  });
});

describe('a post shows its mention in context (issue 0222)', () => {
  it('marks the mention under the post’s link', () => {
    renderWithProviders(<ul><EntityPostLine post={{ id: 'p1', title: 'Weekly notes', source: 'Example Blog', at: now,
      context: [{ t: 'Then ' }, { t: 'Kestrel Coder', m: true }, { t: ' got hooks. The end.' }] }} /></ul>, { api: makeFakeApi({}) });
    const context = screen.getByText(/got hooks/).closest('p');
    expect(context).toHaveTextContent('Then Kestrel Coder got hooks. The end.');
    const mark = within(context as HTMLElement).getByText('Kestrel Coder');
    expect(mark.tagName).toBe('MARK');
    expect(screen.getByRole('link', { name: 'Weekly notes' })).toBeInTheDocument();
    // 0233 (0225 #28): a quote one step in under the post's line, never at the line's own indent
    const quote = context?.closest('[data-context]');
    expect(quote?.tagName).toBe('BLOCKQUOTE');
    expect(quote).toHaveClass('ml-4', 'border-l-2', 'pl-2');
    expect(quote?.contains(screen.getByRole('link', { name: 'Weekly notes' }))).toBe(false);
  });

  it('shows the title alone when only the title names it', () => {
    renderWithProviders(<ul><EntityPostLine post={{ id: 'p1', title: 'Kestrel Coder ships', source: 'Example Blog', at: now,
      context: null }} /></ul>, { api: makeFakeApi({}) });
    expect(document.querySelector('[data-context]')).toBeNull();
  });

  it('collapses the entity page’s unflagged questions and old stories to check into the operator’s view', async () => {
    const PAGE: MarkxEntityPage = {
      entity: ref('e1', 'Kestrel Coder'), asked: 'e1', redirected: false, aliases: ['Kestrel Coder'], maker: null, family: null,
      versions: [], posts: 1, voices: 1, accuracy: ACCURACY, surges: [], stories: [],
      queue: [item('q1', { flag: { at: now, by: 'claude', note: 'Check this one.' } }), item('q2')],
      sample: [{ story: 's1', first_at: now, answer: null }],
      loose: [{ id: 'p1', title: 'Weekly notes', source: 'Example Blog', at: now, roles: ['subject'], read: false, about: true,
        context: [{ t: 'Then ' }, { t: 'Kestrel Coder', m: true }, { t: ' got hooks.' }] }],
      sources: [{ id: 's1', name: 'Example Blog', kind: 'site', posts: 1, reports: 1 }],
    } as MarkxEntityPage;
    renderWithProviders(
      <Routes><Route path="/markx/entities/:entityId" element={<MarkXEntityPage />} /></Routes>,
      { api: makeFakeApi({ getMarkxEntity: vi.fn().mockResolvedValue(PAGE) }), route: '/markx/entities/e1' });
    const mine = await screen.findByRole('region', { name: 'Flagged for you' });
    expect(within(mine).getAllByRole('group', { name: 'Your answer' })).toHaveLength(1);
    expect(screen.getByText(/Operator view: 1 open question about it/).closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText(/Operator view: 1 old story offered to check/).closest('details')).not.toHaveAttribute('open');
    const about = screen.getByRole('region', { name: 'About Kestrel Coder' });
    expect(within(about).getByText('Kestrel Coder').tagName).toBe('MARK');
  });
});
