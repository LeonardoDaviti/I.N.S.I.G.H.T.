import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXNews from './MarkXNews';
import type { MarkxNews, MarkxRow } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const now = new Date().toISOString();
const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function row(id: string, headline: string, from: 'haiku' | 'lead title' = 'haiku'): MarkxRow {
  return {
    id, tag: 'NEW', headline: { text: headline, from }, first_at: now, voices: 2, reports: 2, shares: 0, mentions: 0,
    score: 2, story: null, removed: [], ix: [],
    posts: [{ id, title: `post ${id}`, source: 'Example Site', kind: 'site', at: now, role: 'report', story: null, flag: null,
      why: null, ix: null }],
  } as MarkxRow;
}

// The page's order (News' own): r1 r2 r3 r4 r5; r5 came after the last sectioning.
const NEWS: MarkxNews = {
  run: { id: 'run1', started_at: now, finished_at: now, code_version: 'markx-decide-v1' },
  counts: { NEW: 5, rows: 5, ix_rows: 0, untitled: 1 }, gone: [],
  items: [row('r1', 'Acme releases Widget 5'), row('r2', 'Beta raises a round'), row('r3', 'Gamma ships Gadget 2'),
    row('r4', 'A study of widgets'), row('r5', 'Delta post title', 'lead title')],
  sections: {
    at: ago(12), pending: false, new: ['r5'],
    groups: [{ title: 'Product launches', rows: ['r1', 'r3'] }, { title: 'Funding', rows: ['r2'] },
      { title: 'Research', rows: ['r4'] }],
  },
};

function headings() {
  return screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
}

describe('Mark X News in sections (0174)', () => {
  it('groups the rows under the section titles, the new rows first, each in News order', async () => {
    renderWithProviders(<MarkXNews />, { api: makeFakeApi({ getMarkxNews: vi.fn().mockResolvedValue(NEWS) }) });
    expect(await screen.findByText('Acme releases Widget 5')).toBeInTheDocument();
    expect(headings()).toEqual(['New since · 1', 'Product launches · 2', 'Funding · 1', 'Research · 1']);
    const launches = screen.getByRole('region', { name: 'Product launches' });
    expect(within(launches).getAllByRole('listitem').filter((li) => li.id).map((li) => li.id)).toEqual(['mx-r1', 'mx-r3']);
    expect(within(screen.getByRole('region', { name: 'New since' })).getByText('Delta post title')).toBeInTheDocument();
    expect(screen.getByText(/Sections updated 12m ago/)).toBeInTheDocument();
    expect(screen.getByText(/1 row not titled by Haiku yet/)).toBeInTheDocument();
  });

  it('shows the plain list with the toggle', async () => {
    renderWithProviders(<MarkXNews />, { api: makeFakeApi({ getMarkxNews: vi.fn().mockResolvedValue(NEWS) }) });
    await screen.findByText('Acme releases Widget 5');
    await userEvent.click(screen.getByRole('switch', { name: 'In sections' }));
    expect(headings()).toEqual(['Last 48 hours']);
    expect(screen.queryByRole('region', { name: 'Funding' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('switch', { name: 'In sections' }));
    expect(headings()[0]).toBe('New since · 1');
  });

  it('is the plain list while no answer came, and says one is asked', async () => {
    const waiting = { ...NEWS, sections: { at: null, pending: true, groups: [], new: [] } };
    renderWithProviders(<MarkXNews />, { api: makeFakeApi({ getMarkxNews: vi.fn().mockResolvedValue(waiting) }) });
    await screen.findByText('Acme releases Widget 5');
    expect(headings()).toEqual(['Last 48 hours']);
    expect(screen.queryByRole('switch', { name: 'In sections' })).not.toBeInTheDocument();
    expect(screen.getByText(/Sections asked, waiting for the worker/)).toBeInTheDocument();
  });
});
