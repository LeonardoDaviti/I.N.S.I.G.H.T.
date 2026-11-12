import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import MarkXEntityPage from '../../pages/MarkXEntityPage';
import MarkXEntities from './MarkXEntities';
import MarkXPanel from './MarkXPanel';
import { Timeline, timelineWhy } from './MarkXTimeline';
import type { MarkxEntityPage, MarkxEntityQueue, MarkxEntityRef, MarkxPostPanel, MarkxQueueItem, MarkxTimeline,
  MarkxTimelineEvent } from '../../services/markx';
import { makeFakeApi as makeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

/** Issue 0165, invented names: the entity page's Timeline (and its components), the post page's "before" from it,
 *  and a rename question in the review queue. Synthetic data only. */
const makeFakeApi = (methods: Record<string, unknown>) => makeApi(methods as Parameters<typeof makeApi>[0]);
const post = (id: string, title: string, source: string) => ({ id, title, source, kind: 'site', url: null });
const ev = (kind: MarkxTimelineEvent['kind'], at: string, extra: Partial<MarkxTimelineEvent> = {}): MarkxTimelineEvent => ({
  kind, at, rank: 0, top: true, post: null, ...extra,
});

const TIMELINE: MarkxTimeline = {
  shown: 3, total: 5, earlier: [{ id: 'old', name: 'Acme Forge Snap', names: ['Acme Forge Snap'] }],
  items: [
    ev('birth', '2026-05-27T10:00:00Z', { post: post('p1', 'Acme Forge Snap: fast starts', 'Acme Dev'), name: 'Acme Forge Snap', also: ['release'] }),
    ev('first_outside', '2026-10-19T00:00:00Z', { post: post('p2', 'Restoring warm workers', 'Engine Blog'), linked: true }),
    ev('outside', '2026-10-22T00:00:00Z', { post: post('p3', 'A retailer uses it', 'Acme News'), month: '2026-10', n: 2, sources: 1, top: false }),
    ev('earlier_name', '2026-10-22T00:00:00Z', { post: post('p3', 'A retailer uses it', 'Acme News'), name: 'Acme Forge Snap', top: false }),
    ev('renamed', '2026-11-10T15:00:00Z', { post: post('p4', 'Start in seconds with Acme Snap', 'Acme Dev'), name: 'Acme Snap' }),
  ],
};

const ref = (id: string, name: string): MarkxEntityRef => ({
  id, name, type: 'software', maker: 'Acme', level: 'thing', version: null, variant: null, size: null, build: null,
  status: 'provisional', family: null,
});

describe('the Timeline block (0165 C)', () => {
  it('shows the most important events oldest first, why each is there, and opens the rest', async () => {
    renderWithProviders(<Timeline timeline={TIMELINE} />, { api: makeFakeApi({}) });
    const block = screen.getByRole('region', { name: 'Timeline' });
    expect(within(block).getByRole('heading')).toHaveTextContent('Timeline · 5 events · earlier name Acme Forge Snap');
    let rows = within(block).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('2026-05-27Acme Forge Snap: fast starts · Acme Dev · first seen, as Acme Forge Snap · release');
    expect(rows[1]).toHaveTextContent('first outside mention · links back');
    expect(rows[2]).toHaveTextContent('renamed Acme Snap');
    expect(within(rows[0]).getByRole('link')).toHaveAttribute('href', '/posts/p1');
    await userEvent.click(within(block).getByRole('button', { name: 'All 5 events' }));
    rows = within(block).getAllByRole('listitem');
    expect(rows).toHaveLength(5);
    expect(rows[2]).toHaveTextContent('outside · 2 posts, 1 source in 2026-10');
    expect(rows[3]).toHaveTextContent('last seen as Acme Forge Snap');
    expect(within(block).queryByRole('button')).not.toBeInTheDocument();
  });

  it('words a story line', () => {
    expect(timelineWhy(ev('story', '2026-01-01', { mark: 'x', voices: 3 }))).toBe('story · 3 sources');
    expect(timelineWhy(ev('back', '2026-01-01'))).toBe('back in the news');
  });

  it('is on the entity page with its components', async () => {
    const page: MarkxEntityPage = {
      entity: ref('e1', 'Acme Forge'), asked: 'e1', redirected: false, aliases: ['Acme Forge'], maker: null, family: null,
      versions: [], posts: 3, voices: 2, stories: [], loose: [], sources: [], surges: [], queue: [], current: true,
      accuracy: { merges: 'm', surges: 's', collisions: 'c' },
      components: [{ id: 'c1', name: 'Acme Forge Snap', type: 'software', posts: 4 }], timeline: TIMELINE,
    };
    renderWithProviders(<Routes><Route path="/markx/entities/:entityId" element={<MarkXEntityPage />} /></Routes>,
      { api: makeFakeApi({ getMarkxEntity: vi.fn().mockResolvedValue(page) }), route: '/markx/entities/e1' });
    const comps = await screen.findByRole('region', { name: 'Components' });
    expect(within(comps).getByRole('link', { name: 'Acme Forge Snap' })).toHaveAttribute('href', '/markx/entities/c1');
    expect(comps).toHaveTextContent('Acme Forge Snap · 4 posts');
    expect(screen.getByRole('region', { name: 'Timeline' })).toBeInTheDocument();
  });

  it('is absent when the page has none', async () => {
    const page = { entity: ref('e1', 'Acme Kite'), asked: 'e1', redirected: false, aliases: ['Acme Kite'], maker: null,
      family: null, versions: [], posts: 1, voices: 1, stories: [], loose: [], sources: [], surges: [], queue: [],
      accuracy: { merges: 'm', surges: 's', collisions: 'c' }, timeline: null } as MarkxEntityPage;
    renderWithProviders(<Routes><Route path="/markx/entities/:entityId" element={<MarkXEntityPage />} /></Routes>,
      { api: makeFakeApi({ getMarkxEntity: vi.fn().mockResolvedValue(page) }), route: '/markx/entities/e1' });
    await screen.findByRole('region', { name: 'Sources' });
    expect(screen.queryByRole('region', { name: 'Timeline' })).not.toBeInTheDocument();
  });
});

describe('the post page’s before (0165 D)', () => {
  it('shows its subject’s previous events, even when it connects to no older post', async () => {
    const panel: MarkxPostPanel = {
      post_id: 'p4', read: true, reading: null, entities: [], stories: [], connections: [], before: [], before_more: 0,
      before_timeline: [{ entity: { id: 'e1', name: 'Acme Snap' }, items: TIMELINE.items.slice(0, 2) }],
    };
    renderWithProviders(<MarkXPanel postId="p4" />, { api: makeFakeApi({ getMarkxPost: vi.fn().mockResolvedValue(panel) }) });
    await userEvent.click(screen.getByText('Mark X'));
    const before = await screen.findByRole('region', { name: 'Before' });
    expect(before).toHaveTextContent('In Acme Snap’s timeline');
    expect(within(before).getByRole('link', { name: 'Acme Snap' })).toHaveAttribute('href', '/markx/entities/e1');
    const rows = within(before).getAllByRole('listitem');
    expect(rows.map((r) => r.getAttribute('data-kind'))).toEqual(['birth', 'first_outside']);
  });
});

describe('a rename question (0165 B)', () => {
  it('asks whether the older name was renamed, says why, and answers same thing, renamed', async () => {
    const now = new Date().toISOString();
    const it_: MarkxQueueItem = {
      id: 'q7', kind: 'rename', proposal: 'same', reason: 'rename', confidence: 0.9, answer: null, answered_at: null,
      created_at: now, join: null,
      evidence: { judge: { relation: 'renamed', confidence: 0.9, evidence: 'The launch post says it was part of Forge.' },
        asked_because: 'they share an own address (github.com/acme/snap)' },
      a: { ...ref('old', 'Acme Forge Snap'), root: 'old', posts: [] },
      b: { ...ref('new', 'Acme Snap'), root: 'new', posts: [] },
    };
    const queue: MarkxEntityQueue = { open: [it_], answered: [], merges: [],
      accuracy: { merges: 'm', surges: 's', collisions: 'c' },
      counts: { open: 1, answered: {}, automatic_merges: 0, automatic_undone: 0 } };
    const answerMarkxEntity = vi.fn().mockResolvedValue({ answer: 'same', renamed: true });
    renderWithProviders(<MarkXEntities />, { api: makeFakeApi({
      getMarkxEntities: vi.fn().mockResolvedValue({ window_days: 30, total: 0, queue: 1, accuracy: queue.accuracy, items: [] }),
      getMarkxEntityQueue: vi.fn().mockResolvedValue(queue), answerMarkxEntity }) });
    expect(await screen.findByText(/Renamed\? Acme Forge Snap \(older\) → Acme Snap \(newer\)/)).toBeInTheDocument();
    expect(screen.getByText('Asked because they share an own address (github.com/acme/snap)')).toBeInTheDocument();
    const buttons = screen.getByRole('group', { name: 'Your answer' });
    expect(within(buttons).getAllByRole('button').map((b) => b.textContent))
      .toEqual(['same thing, renamed', 'different', 'not an entity']);
    await userEvent.click(within(buttons).getByRole('button', { name: 'same thing, renamed' }));
    await waitFor(() => expect(answerMarkxEntity).toHaveBeenCalledWith('q7', 'same'));
  });
});
