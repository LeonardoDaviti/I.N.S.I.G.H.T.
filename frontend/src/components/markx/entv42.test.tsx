import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXPanel from './MarkXPanel';
import { MarkXWorker } from './MarkXOverview';
import type { MarkxEntitiesGuide, MarkxOverview, MarkxPostPanel } from '../../services/markx';
import { makeFakeApi as makeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

// the label's and the switch's calls live in the Mark X chunks (not api.ts), so the fake takes them untyped
const makeFakeApi = (methods: Record<string, unknown>) => makeApi(methods as Parameters<typeof makeApi>[0]);

// Issue 0133 v4.2 (ent-v4.2 in Shadow): the second question's entities marked, right / wrong on every new entity,
// and the running precision with the lab's stated line on the Worker tab.
const e = (name: string, type: string, role: string, extra: Partial<MarkxPostPanel['entities'][number]> = {}) => ({
  name, type, role, maker: null, family: null, version: null, variant: null, span: name, entity_id: null,
  guide: 'ent-v4.2', ...extra });

describe('ent-v4.2 on the post panel', () => {
  it('marks the second question’s entities and labels each new entity', async () => {
    const varga = e('Varga et al. 2021', 'document', 'source', { n: 2, q2: true, new: true, label: null });
    const book = e('Deep Book', 'document', 'recommended', { n: 1, new: true, label: 'wrong' });
    const panel: MarkxPostPanel = {
      post_id: 'p1', read: true, reading: null, stories: [], connections: [], entities_guide: 'ent-v4.2',
      entities: [e('Acme', 'org', 'subject', { n: 0, new: false }), book, varga],
      sources: [varga], recommended: [book], documents: [],
    };
    const labelMarkxMention = vi.fn(async () => ({ post: 'p1', guide: 'ent-v4.2', n: 2, label: 'right' }));
    renderWithProviders(<MarkXPanel postId="p1" />, {
      api: makeFakeApi({ getMarkxPost: vi.fn().mockResolvedValue(panel), labelMarkxMention }) });
    await userEvent.click(screen.getByText('Mark X'));
    const ents = await screen.findByRole('region', { name: 'Entities' });
    expect(within(ents).queryByRole('group', { name: /Is Acme right/ })).not.toBeInTheDocument();   // not new
    const docs = screen.getByRole('region', { name: 'Documents and cited sources' });
    expect(within(docs).getByText(/second question/)).toBeInTheDocument();
    expect(within(docs).getByText(/you said wrong/)).toBeInTheDocument();
    const q = within(docs).getByRole('group', { name: 'Is Varga et al. 2021 right?' });
    await userEvent.click(within(q).getByRole('button', { name: 'entity right' }));
    expect(labelMarkxMention).toHaveBeenLastCalledWith('p1', 'ent-v4.2', 2, 'right');
    await waitFor(() => expect(within(q).getByText(/you said right/)).toBeInTheDocument());
  });
});

describe('ent-v4.2 on the Worker tab', () => {
  it('states the lab’s line and the running precision from the labels', async () => {
    const state: MarkxEntitiesGuide = { guide: 'ent-v4.2', chars: 6000, rule: false, default: 'ent-v3',
      arms: [{ guide: 'ent-v3', chars: 1500, rule: false, ready: true },
        { guide: 'ent-v4.2', chars: 6000, rule: false, ready: true, note: 'lab: 89–93% precise, finds about 62%; post hoc' }],
      labels: { guide: 'ent-v4.2', labelled: 40, right: 36, precision: 0.9, low: 0.77, high: 0.96,
        q2: { labelled: 10, right: 8, precision: 0.8, low: 0.49, high: 0.94 },
        lab: 'lab: 89–93% precise, finds about 62%; post hoc', leave_at: { labelled: 100, low: 0.85 } } };
    const overview: MarkxOverview = {
      worker: { queue: {}, days: [], tokens: { calls: 0, tokens_in: 0, tokens_out: 0, paid_usd: 0, api_usd: 0 }, failed: [],
        invalid: [], workers: [], last_run: null },
      briefing: { day: null, briefings: [] }, entities: { today: [], week: [] },
      reading_window: { days: 30, default: 30 }, entities_guide: state,
    };
    renderWithProviders(<MarkXWorker />, { api: makeFakeApi({ getMarkxOverview: vi.fn(async () => overview),
      setMarkxEntitiesGuide: vi.fn(), setMarkxReadingWindow: vi.fn(), runMarkxDecisions: vi.fn() }) });
    const section = await screen.findByRole('region', { name: 'Entities guide' });
    expect(within(section).getByRole('radio', { name: /^ent-v4.2 · 6,000 characters · lab: 89–93% precise, finds about 62%; post hoc/ }))
      .toBeChecked();
    const prec = within(section).getByRole('region', { name: 'ent-v4.2 precision' });
    expect(prec).toHaveTextContent('36 of 40 new entities right: 90% (95% from 77% to 96%)');
    expect(prec).toHaveTextContent('second question: 8 of 10 right: 80%');
    expect(prec).toHaveTextContent('leaves Shadow at 100+ labelled with the lower bound ≥ 85%');
  });
});
