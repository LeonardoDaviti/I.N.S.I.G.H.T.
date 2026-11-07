import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import MarkXPanel from './MarkXPanel';
import { MarkXWorker } from './MarkXOverview';
import MarkXEntityPage from '../../pages/MarkXEntityPage';
import type { MarkxEntitiesGuide, MarkxEntityPage, MarkxOverview, MarkxPostPanel } from '../../services/markx';
import { makeFakeApi as makeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

// the guide switch's method lives outside createApi (api.ts' 0133 block), so the fake takes it untyped
const makeFakeApi = (methods: Record<string, unknown>) => makeApi(methods as Parameters<typeof makeApi>[0]);

// Issue 0133 (ent-v4): documents and cited sources on the post panel and the entity page, and the guide switch.
const now = new Date().toISOString();
const e = (name: string, type: string, role: string, extra: Partial<MarkxPostPanel['entities'][number]> = {}) => ({
  name, type, role, maker: null, family: null, version: null, variant: null, span: name, entity_id: null, ...extra });

describe('ent-v4 on the post panel', () => {
  it('lists the documents it names and its cited sources under their roles, and the guide they came from', async () => {
    const panel: MarkxPostPanel = {
      post_id: 'p1', read: true, reading: null, stories: [], connections: [], entities_guide: 'ent-v4',
      entities: [e('Acme', 'org', 'actor'), e('Orbit Filing', 'document', 'source', { by: 'Acme', entity_id: 'd1' }),
        e('Varga et al. 2021', 'document', 'source', { rule: 'citation' }), e('Deep Book', 'document', 'recommended'),
        e('Orbit Manual', 'document', 'mention')],
      sources: [e('Orbit Filing', 'document', 'source', { by: 'Acme', entity_id: 'd1' }),
        e('Varga et al. 2021', 'document', 'source', { rule: 'citation' })],
      recommended: [e('Deep Book', 'document', 'recommended')],
      documents: [e('Orbit Manual', 'document', 'mention')],
    };
    renderWithProviders(<MarkXPanel postId="p1" />, { api: makeFakeApi({ getMarkxPost: vi.fn().mockResolvedValue(panel) }) });
    await userEvent.click(screen.getByText('Mark X'));
    const ents = await screen.findByRole('region', { name: 'Entities' });
    expect(within(ents).getByText(/· ent-v4/)).toBeInTheDocument();
    expect(within(ents).queryByText('Deep Book')).not.toBeInTheDocument();      // under its role, below
    const docs = screen.getByRole('region', { name: 'Documents and cited sources' });
    expect(within(docs).getByText('cited as evidence')).toBeInTheDocument();
    expect(within(docs).getByRole('link', { name: 'Orbit Filing' })).toHaveAttribute('href', '/markx/entities/d1');
    expect(within(docs).getByText(/by Acme/)).toBeInTheDocument();
    expect(within(docs).getByText(/citation rule/)).toBeInTheDocument();
    expect(within(docs).getByText('recommended')).toBeInTheDocument();
    expect(within(docs).getByText('Orbit Manual')).toBeInTheDocument();
  });

  it('shows no such section for an ent-v3 post', async () => {
    const panel: MarkxPostPanel = { post_id: 'p1', read: true, reading: null, stories: [], connections: [],
      entities: [e('Acme', 'org', 'subject')], entities_guide: 'ent-v3', documents: [], sources: [], recommended: [] };
    renderWithProviders(<MarkXPanel postId="p1" />, { api: makeFakeApi({ getMarkxPost: vi.fn().mockResolvedValue(panel) }) });
    await userEvent.click(screen.getByText('Mark X'));
    await screen.findByRole('region', { name: 'Entities' });
    expect(screen.queryByRole('region', { name: 'Documents and cited sources' })).not.toBeInTheDocument();
  });
});

describe('ent-v4 on the entity page', () => {
  it('shows who published a document and the posts citing and recommending it', async () => {
    const PAGE: MarkxEntityPage = {
      entity: { id: 'd1', name: 'Orbit Filing', type: 'document', maker: null, level: 'thing', version: null, variant: null,
        size: null, build: null, status: 'provisional', family: null },
      asked: 'd1', redirected: false, aliases: ['Orbit Filing'], maker: null, family: null, versions: [], posts: 2, voices: 2,
      accuracy: { merges: 'm', surges: 's', collisions: 'c' }, queue: [], surges: [], stories: [], sources: [],
      loose: [], published_by: [{ id: 'o1', name: 'Acme Corp', type: 'org' }], published: [],
      citing: [{ id: 'p1', title: 'Revenue rose', source: 'Example News', at: now, roles: ['source'], read: false }],
      recommending: [{ id: 'p2', title: 'Read this', source: 'Example Wire', at: now, roles: ['recommended'], read: false }],
    };
    renderWithProviders(<Routes><Route path="/markx/entities/:entityId" element={<MarkXEntityPage />} /></Routes>,
      { api: makeFakeApi({ getMarkxEntity: vi.fn().mockResolvedValue(PAGE) }), route: '/markx/entities/d1' });
    expect(await screen.findByRole('heading', { name: 'Orbit Filing' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Acme Corp' })).toHaveAttribute('href', '/markx/entities/o1');
    expect(within(screen.getByRole('region', { name: 'Cited as evidence' })).getByText('Revenue rose')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Recommended' })).getByText('Read this')).toBeInTheDocument();
  });
});

describe('the entities guide switch (Worker tab)', () => {
  const state = (guide: string): MarkxEntitiesGuide => ({ guide, chars: guide === 'ent-v3' ? 1500 : 6000, rule: guide !== 'ent-v3',
    default: 'ent-v3', arms: [{ guide: 'ent-v3', chars: 1500, rule: false, ready: true },
      { guide: 'ent-v4', chars: 6000, rule: true, ready: false }, { guide: 'ent-v3-6k', chars: 6000, rule: true, ready: true }] });
  const overview = (guide: string): MarkxOverview => ({
    worker: { queue: {}, days: [], tokens: { calls: 0, tokens_in: 0, tokens_out: 0, paid_usd: 0, api_usd: 0 }, failed: [],
      invalid: [], workers: [], last_run: null },
    briefing: { day: null, briefings: [] }, entities: { today: [], week: [] },
    reading_window: { days: 30, default: 30 }, entities_guide: state(guide),
  });

  it('defaults to ent-v3, keeps the placeholder disabled, and switches to another guide', async () => {
    let guide = 'ent-v3';
    const getMarkxOverview = vi.fn(async () => overview(guide));
    const setMarkxEntitiesGuide = vi.fn(async (g: string) => { guide = g; return { reading_window_days: 30, default: 30, entities_guide: state(g) }; });
    renderWithProviders(<MarkXWorker />, { api: makeFakeApi({ getMarkxOverview, setMarkxEntitiesGuide,
      setMarkxReadingWindow: vi.fn(), runMarkxDecisions: vi.fn() }) });
    const section = await screen.findByRole('region', { name: 'Entities guide' });
    expect(within(section).getByRole('radio', { name: /^ent-v3 · 1,500/ })).toBeChecked();
    expect(within(section).getByRole('radio', { name: /^ent-v4 ·/ })).toBeDisabled();
    expect(within(section).getByText(/waiting for the lab’s guide/)).toBeInTheDocument();
    await userEvent.click(within(section).getByRole('radio', { name: /^ent-v3-6k/ }));
    expect(setMarkxEntitiesGuide).toHaveBeenLastCalledWith('ent-v3-6k');
    await waitFor(() => expect(within(section).getByRole('radio', { name: /^ent-v3-6k/ })).toBeChecked());
  });
});
