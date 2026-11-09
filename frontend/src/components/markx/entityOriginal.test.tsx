import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import MarkXEntityPage from '../../pages/MarkXEntityPage';
import type { MarkxEntityPage } from '../../services/markx';
import { makeFakeApi as makeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const makeFakeApi = (methods: Record<string, unknown>) => makeApi(methods as Parameters<typeof makeApi>[0]);
const now = new Date().toISOString();

// Issue 0138: the entity page shows its Original first; an entity no current reading names shows the older posts.
const base: MarkxEntityPage = {
  entity: { id: 'd1', name: 'The Nimbus Paper', type: 'document', maker: null, level: 'thing', version: null, variant: null,
    size: null, build: null, status: 'provisional', family: null },
  asked: 'd1', redirected: false, aliases: ['The Nimbus Paper'], maker: null, family: null, versions: [], posts: 2, voices: 2,
  accuracy: { merges: 'm', surges: 's', collisions: 'c' }, queue: [], surges: [], stories: [], sources: [],
  loose: [{ id: 'p1', title: 'A paper on lattices', source: 'Channel A', at: now, roles: ['subject'], read: false }],
  current: true,
};

function open(page: MarkxEntityPage, api: Record<string, unknown> = {}) {
  renderWithProviders(<Routes>
    <Route path="/markx/entities/:entityId" element={<MarkXEntityPage />} />
    <Route path="/sources" element={<p>Add source page</p>} />
  </Routes>, { api: makeFakeApi({ getMarkxEntity: vi.fn().mockResolvedValue(page), ...api }), route: '/markx/entities/d1' });
}

describe('the entity page (issue 0138)', () => {
  it('shows the collected original first, with its code and demo', async () => {
    open({ ...base,
      original: { url: 'https://arxiv.org/abs/2611.01234', kind: 'paper', rule: 'identifier',
        post: { id: 'o1', title: 'The Nimbus Paper (abstract)', collected: true }, asked: { outcome: 'collected', at: now } },
      addresses: [{ kind: 'code', url: 'https://github.com/x/y', rule: 'identifier' }, { kind: 'demo', url: 'https://huggingface.co/spaces/x/y', rule: 'identifier' }] });
    const section = await screen.findByRole('region', { name: 'Original' });
    expect(within(section).getByRole('link', { name: 'The Nimbus Paper (abstract)' })).toHaveAttribute('href', '/posts/o1');
    expect(within(section).getByText(/paper, found by its identifier · collected original/)).toBeInTheDocument();
    expect(within(section).getByRole('link', { name: 'code' })).toHaveAttribute('href', 'https://github.com/x/y');
    const regions = screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'));
    expect(regions[0]).toBe('Original');
  });

  it('an original not stored yet links its page', async () => {
    open({ ...base, original: { url: 'https://arxiv.org/abs/2611.01234', kind: 'paper', rule: 'title', post: null, asked: null }, addresses: [] });
    const section = await screen.findByRole('region', { name: 'Original' });
    expect(within(section).getByRole('link', { name: 'https://arxiv.org/abs/2611.01234' })).toBeInTheDocument();
    expect(within(section).getByText(/not collected yet/)).toBeInTheDocument();
  });

  it('an entity only an earlier guide named lists those posts and what each names now', async () => {
    open({ ...base, posts: 0, voices: 0, loose: [], current: false, original: null, addresses: [],
      older: [{ id: 'p9', title: 'A post about a saga', source: 'Channel B', at: now, url: null, guide: 'ent-v3', span: 'Kestrel Gadget',
        now: [{ id: 'e2', name: 'The Kestrel Saga', type: 'other' }] }] });
    const section = await screen.findByRole('region', { name: 'Named by an earlier guide' });
    expect(within(section).getByText(/Not named in any post’s current reading. An earlier guide \(ent-v3\) named it in 1 post:/)).toBeInTheDocument();
    expect(within(section).getByRole('link', { name: 'A post about a saga' })).toHaveAttribute('href', '/posts/p9');
    expect(within(section).getByRole('link', { name: 'The Kestrel Saga' })).toHaveAttribute('href', '/markx/entities/e2');
    expect(screen.queryByRole('region', { name: 'Original' })).not.toBeInTheDocument();
  });

  it('the rabbit hole lists sites, works and people; one tap collects the works, then opens Add source (E3)', async () => {
    const savePage = vi.fn().mockResolvedValue({ success: true, status: 'saved' });
    open({ ...base, entity: { ...base.entity, name: 'Example Futures', type: 'org' }, rabbit_hole: {
      sites: [{ url: 'https://blog.example-futures.org/', host: 'blog.example-futures.org', state: 'followed' },
        { url: 'https://forecast-2030.example/', host: 'forecast-2030.example', state: 'stored' },
        { url: 'https://forecast-2040.example/', host: 'forecast-2040.example', state: 'page' }],
      works: [{ id: 'w1', name: 'Forecast 2030', url: 'https://forecast-2030.example/', kind: 'work', stored: true, post_id: 'p30' },
        { id: 'w2', name: 'Forecast 2040', url: 'https://forecast-2040.example/', kind: 'work', stored: false, post_id: null }],
      people: [{ id: 'h1', name: 'Ivo Kestrel' }], left: { sites: 1, works: 1 } } }, { savePage });
    const section = await screen.findByRole('region', { name: 'The rabbit hole' });
    expect(within(section).getByText('Followed ✓')).toBeInTheDocument();
    expect(within(section).getByRole('link', { name: 'Watch page' })).toHaveAttribute('href', '/sources?follow=https%3A%2F%2Fforecast-2040.example%2F');
    expect(within(section).getByRole('link', { name: 'Stored ✓' })).toHaveAttribute('href', '/posts/p30');
    expect(within(section).getByRole('link', { name: 'Ivo Kestrel' })).toHaveAttribute('href', '/markx/entities/h1');
    fireEvent.click(within(section).getByRole('button', { name: 'Go down the rabbit hole' }));
    await waitFor(() => expect(screen.getByText('Add source page')).toBeInTheDocument());
    expect(savePage).toHaveBeenCalledWith('https://forecast-2040.example/');
  });
});
