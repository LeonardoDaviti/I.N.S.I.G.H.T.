import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import MarkXEntities from './MarkXEntities';
import MarkXEntityPage from '../../pages/MarkXEntityPage';
import type { MarkxEntityList, MarkxEntityPage, MarkxEntityQueue, MarkxEntityRef, MarkxQueueItem } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const now = new Date().toISOString();
const ref = (id: string, name: string, extra: Partial<MarkxEntityRef> = {}): MarkxEntityRef => ({
  id, name, type: 'model', maker: 'Acme', level: 'version', version: '5', variant: null, size: null, build: null,
  status: 'provisional', family: null, ...extra,
});
const ACCURACY = { merges: 'automatic merges 97.6% right (lab)', surges: 'surges 91% (lab)', collisions: 'splits 55% (lab)' };

const ITEM: MarkxQueueItem = {
  id: 'q1', kind: 'alias', proposal: 'same', reason: 'below_bar', confidence: 0.86, answer: null, answered_at: null,
  created_at: now, evidence: { judge: { relation: 'same', confidence: 0.86, evidence: 'One tool, two spellings.' } },
  a: { ...ref('e1', 'Kestrel Coder', { type: 'software', version: null }), root: 'e1',
    posts: [{ id: 'p1', title: 'Kestrel Coder ships', source: 'Example Blog', at: now, span: 'Kestrel Coder', role: 'subject' }] },
  b: { ...ref('e2', 'Kestrel Coder CLI', { type: 'software', version: null }), root: 'e2',
    posts: [{ id: 'p2', title: 'The CLI is out', source: 'Example Channel', at: now, span: 'Kestrel Coder CLI', role: 'subject' }] },
};
const QUEUE: MarkxEntityQueue = {
  open: [ITEM], answered: [], accuracy: ACCURACY,
  merges: [{ id: 'r1', from: { id: 'e3', name: 'DeepKestrel' }, to: { id: 'e4', name: 'Deep Kestrel' }, by: 'rule:squash',
    automatic: true, at: now, undone_at: null, confidence: 0.97 }],
  counts: { open: 1, answered: {}, automatic_merges: 1, automatic_undone: 0 },
};
const LIST: MarkxEntityList = {
  window_days: 30, total: 2, queue: 1, accuracy: ACCURACY,
  items: [
    { ...ref('e5', 'Nimbus 5'), voices: 4, posts: 6, reports: 5, mentions: 1, last_at: now, last_seen: 'today',
      stories: [{ id: 's1', headline: 'Acme releases Nimbus 5' }],
      newest: [{ id: 'p3', title: 'Nimbus 5 benchmarks', source: 'Example News', at: now, read: true },
        { id: 'p4', title: 'Nimbus 5 is here', source: 'Example Wire', at: now, read: false }],
      surges: [{ day: now.slice(0, 10), voices: 4, posts: 6, via: [] }] },
    { ...ref('e6', 'Acme', { type: 'org', maker: null, level: 'thing', version: null }), voices: 2, posts: 2, reports: 1,
      mentions: 1, last_at: now, last_seen: '3 days ago', stories: [], newest: [], surges: [] },
  ],
};

describe('Mark X entities (issue 0119 A3)', () => {
  it('is one list ranked like News, read posts kept and dimmed, with the queue and the measured accuracy', async () => {
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue(LIST), getMarkxEntityQueue: vi.fn().mockResolvedValue(QUEUE) }) });
    const list = await screen.findByRole('region', { name: 'Entities' });
    const names = within(list).getAllByRole('link').map((a) => a.textContent).filter((t) => t === 'Nimbus 5' || t === 'Acme');
    expect(names).toEqual(['Nimbus 5', 'Acme']);
    expect(within(list).getByText(/last seen today/)).toBeInTheDocument();
    expect(within(list).queryByText(/Today/)).not.toBeInTheDocument();          // no Today/Week split
    const read = within(list).getByText('Nimbus 5 benchmarks').closest('li');
    expect(read).toHaveAttribute('data-read', 'true');                         // read: still there, marked
    expect(within(list).getByText('surging')).toBeInTheDocument();
    expect(screen.getByText(/97.6%/)).toBeInTheDocument();
    expect(await screen.findByText(/To review: 1/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Nimbus 5' })).toHaveAttribute('href', '/markx/entities/e5');
  });

  it('answers a queue item in one tap and undoes a merge from the history', async () => {
    const answerMarkxEntity = vi.fn().mockResolvedValue({ answer: 'same' });
    const undoMarkxMerge = vi.fn().mockResolvedValue({ undone: 'r1' });
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue(LIST), getMarkxEntityQueue: vi.fn().mockResolvedValue(QUEUE),
      answerMarkxEntity, undoMarkxMerge }) });
    const item = await screen.findByRole('group', { name: 'Your answer' });
    expect(within(item).getAllByRole('button').map((b) => b.textContent)).toEqual(['same', 'other version', 'different', 'not an entity']);
    expect(screen.getByText(/Haiku: One tool/)).toBeInTheDocument();
    await userEvent.click(within(item).getByRole('button', { name: 'same' }));
    await waitFor(() => expect(answerMarkxEntity).toHaveBeenCalledWith('q1', 'same'));
    await userEvent.click(screen.getByText(/1 automatic merge/));
    await userEvent.click(screen.getByRole('button', { name: 'undo' }));
    await waitFor(() => expect(undoMarkxMerge).toHaveBeenCalledWith('r1'));
  });

  it('opens an entity page: every post by story, the loose ones last, sources and versions', async () => {
    const PAGE: MarkxEntityPage = {
      entity: ref('e5', 'Nimbus 5', { family: { id: 'f1', name: 'Nimbus' } }), asked: 'e5', redirected: false,
      aliases: ['Nimbus 5', 'Nimbus V5'], maker: null, family: { id: 'f1', name: 'Nimbus' },
      versions: [{ id: 'e7', name: 'Nimbus 5.1', version: '5.1', variant: null, level: 'version' },
        { id: 'e5', name: 'Nimbus 5', version: '5', variant: null, level: 'version' }],
      posts: 3, voices: 2, accuracy: ACCURACY, queue: [], surges: [],
      stories: [{ story: 's1', headline: 'Acme releases Nimbus 5', voices: 2, newest: now,
        posts: [{ id: 'p3', title: 'Nimbus 5 benchmarks', source: 'Example News', at: now, roles: ['subject'], read: true }] }],
      loose: [{ id: 'p9', title: 'A list of models', source: 'Example Wire', at: now, roles: ['mention'], read: false }],
      sources: [{ id: 's1', name: 'Example News', kind: 'site', posts: 2, reports: 2 }],
    };
    const getMarkxEntity = vi.fn().mockResolvedValue(PAGE);
    renderWithProviders(
      <Routes><Route path="/markx/entities/:entityId" element={<MarkXEntityPage />} /></Routes>,
      { api: makeFakeApi({ getMarkxEntity }), route: '/markx/entities/e5' });
    expect(await screen.findByRole('heading', { name: 'Nimbus 5' })).toBeInTheDocument();
    expect(getMarkxEntity).toHaveBeenCalledWith('e5');
    expect(screen.getByRole('link', { name: 'Nimbus 5.1' })).toHaveAttribute('href', '/markx/entities/e7');
    expect(screen.getByRole('region', { name: 'Acme releases Nimbus 5' })).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'In no story' })).getByText(/mention/)).toBeInTheDocument();
    expect(screen.getByText(/also written Nimbus V5/)).toBeInTheDocument();
  });
});

describe('the entity queue, measured (issue 0130 A)', () => {
  const band = (id: string, b: string, conf: number, extra: Record<string, unknown> = {}) => ({
    ...ITEM, id, confidence: conf, band: b, evidence: { ...ITEM.evidence, ...extra } }) as MarkxQueueItem;
  const Q2: MarkxEntityQueue = {
    ...QUEUE, counts: { ...QUEUE.counts, open: 3 },
    open: [
      band('q1', '>=0.90', 0.92, { reasons: ['maker_unstated'] }),
      band('q2', '0.85-0.90', 0.87, { second: { relation: 'part', confidence: 0.8, evidence: 'A plugin of it.' }, disagree: true }),
      band('q3', '<0.80', 0.7, { second_asked: true }),
    ],
  };

  it('shows each item’s band, filters by band, and marks a second opinion that disagrees', async () => {
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue(LIST), getMarkxEntityQueue: vi.fn().mockResolvedValue(Q2) }) });
    const bands = await screen.findByRole('group', { name: 'Band' });
    expect(within(bands).getAllByRole('button').map((b) => b.textContent)).toEqual(['all', '≥ 0.90 (1)', '0.85–0.90 (1)', '< 0.80 (1)']);
    expect(screen.getAllByRole('group', { name: 'Your answer' })).toHaveLength(3);
    expect(screen.getByText(/band 0.85–0.90/)).toBeInTheDocument();
    expect(screen.getByText('second opinion disagrees').closest('p')).toHaveAttribute('data-disagree', 'true');
    expect(screen.getByText(/A plugin of it/)).toBeInTheDocument();
    expect(screen.getByText(/Second opinion asked/)).toBeInTheDocument();
    await userEvent.click(within(bands).getByRole('button', { name: '0.85–0.90 (1)' }));
    expect(screen.getAllByRole('group', { name: 'Your answer' })).toHaveLength(1);
    expect(screen.queryByText(/Second opinion asked/)).not.toBeInTheDocument();
  });
});
