import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import { ThemeProvider } from '../ThemeProvider';
import AppShell from '../layout/AppShell';
import MarkXPage from '../../pages/MarkXPage';
import MarkXPanel from './MarkXPanel';
import { ApiError } from '../../lib/apiError';
import type { Api } from '../../services/api';
import type { MarkxNews, MarkxPostPanel } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const now = new Date().toISOString();
const NEWS: MarkxNews = {
  run: { id: 'r1', started_at: now, finished_at: now, code_version: 'markx-decide-v1' },
  counts: { NEW: 1, CHANGED: 1, SAME: 3, rows: 5, ix_rows: 4, gone: 0 },
  gone: [],
  items: [
    {
      id: 'p1', tag: 'NEW', headline: { text: 'Acme releases Widget 4.1', from: 'haiku' }, first_at: now, voices: 2, reports: 2,
      shares: 0, mentions: 0, score: 2, story: 's1', removed: [], ix: [],
      posts: [
        { id: 'p1', title: 'Widget 4.1 is out', source: 'Example Blog', kind: 'site', at: now, role: 'report',
          why: { role: 'member', reason: 'judge:pair', p: 0.9, relation: 'same_event', words: 'Both report the release.' }, ix: null },
        { id: 'p2', title: 'Acme ships Widget 4.1', source: 'Example Channel', kind: 'telegram', at: now, role: 'report',
          why: { role: 'member', reason: 'judge:pair', p: 0.9, relation: 'same_event', words: null }, ix: null },
      ],
    },
    {
      id: 'p5', tag: 'CHANGED', headline: { text: 'Gadget 2 launch', from: 'lead title' }, first_at: now, voices: 3, reports: 3,
      shares: 0, mentions: 0, score: 3, story: 's2', ix: [{ id: 'p5', title: 'Gadget 2 launch', voices: 3 }],
      posts: [
        { id: 'p5', title: 'Gadget 2 launch', source: 'Example News', kind: 'site', at: now, role: 'report',
          why: { role: 'member', reason: 'rule:none', p: null, relation: null, words: null }, ix: { row: 'p5', title: 'Gadget 2 launch', same_row: true } },
      ],
      removed: [{ id: 'p6', title: 'Unrelated market note', source: 'Example Wire', kind: 'telegram', at: now,
        check: { relation: 'different', p: 0.1, words: 'Another event.' }, now_in: null, mention: null }],
    },
  ],
};

describe('Mark X page (issue 0086 E)', () => {
  it('shows the rows with their tags, and why each post is there once opened', async () => {
    const getMarkxNews = vi.fn().mockResolvedValue(NEWS);
    renderWithProviders(<MarkXPage />, { api: makeFakeApi({ getMarkxNews }) });
    expect(await screen.findByText('Acme releases Widget 4.1')).toBeInTheDocument();
    expect(getMarkxNews).toHaveBeenCalledWith(false);                      // only the differences by default
    expect(screen.getByText(/Mark X 5 rows · Mark IX 4 · 1 new, 1 changed, 3 same/)).toBeInTheDocument();
    await userEvent.click(screen.getByText('Gadget 2 launch', { selector: 'span' }));
    const left = screen.getByRole('list', { name: 'Left out' });
    expect(within(left).getByText(/taken out/)).toBeInTheDocument();
    expect(within(left).getByText(/Haiku: different 0.10 — Another event./)).toBeInTheDocument();
    expect(screen.getByText("Mark IX's rule: first post")).toBeInTheDocument();
    await userEvent.click(screen.getByRole('switch', { name: 'Only differences' }));
    await waitFor(() => expect(getMarkxNews).toHaveBeenCalledWith(true));
  });

  it('says so when no decision has run', async () => {
    renderWithProviders(<MarkXPage />, { api: makeFakeApi({
      getMarkxNews: vi.fn().mockResolvedValue({ run: null, counts: {}, items: [], gone: [] }) }) });
    expect(await screen.findByText('No Mark X News yet')).toBeInTheDocument();
  });
});

describe('the menu item', () => {
  function shell(on: boolean) {
    const api: Api = makeFakeApi({
      getFolders: vi.fn().mockResolvedValue({ success: true, folders: [] }),
      getOperationsOverview: vi.fn().mockResolvedValue({ success: true, jobs: [] }),
      getMarkxOn: on ? vi.fn().mockResolvedValue({ on: true }) : vi.fn().mockRejectedValue(new ApiError(404, 'Not Found')),
    });
    renderWithProviders(<ThemeProvider><AppShell><Routes><Route path="*" element={<p>page</p>} /></Routes></AppShell></ThemeProvider>,
      { api, route: '/' });
  }

  it('is in the top bar only while Mark X is on', async () => {
    shell(true);
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(await within(nav).findByRole('link', { name: 'mark x' })).toHaveAttribute('href', '/markx');
  });

  it('is not there when it is off', async () => {
    shell(false);
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    await waitFor(() => expect(within(nav).getAllByRole('link').map((l) => l.textContent)).toEqual(['feed', 'sources', 'blog']));
  });
});

describe('the post page panel', () => {
  it('is folded, and loads only when opened', async () => {
    const panel: MarkxPostPanel = {
      post_id: 'p1', read: true,
      reading: { guide: 'read-v2', kind: 'report', events: 'one', lang: 'en', headline: 'Acme released Widget 4.1', main: null, mentions: [] },
      entities: [{ name: 'Widget 4.1', type: 'product', role: 'subject', maker: 'Acme', family: 'Widget', version: '4.1', variant: null, span: 'Widget 4.1' }],
      stories: [{ id: 's1', headline: 'Acme releases Widget 4.1', first_at: now, posts: 2, role: 'member', reason: 'judge:pair', p: 0.9,
        relation: 'same_event', words: 'Both report it.' }],
      connections: [{ relation: 'follows_up', p: 0.8, rule: null, from: 'story', other_kind: 'story', other: 's9', title: 'Widget 4 preview', reason: 'A later release.' }],
    };
    const getMarkxPost = vi.fn().mockResolvedValue(panel);
    renderWithProviders(<MarkXPanel postId="p1" />, { api: makeFakeApi({ getMarkxPost }) });
    expect(getMarkxPost).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText('Mark X'));
    expect(await screen.findByText('Acme released Widget 4.1')).toBeInTheDocument();
    expect(screen.getByText(/Haiku: same event 0.90, a story Mark IX doesn't have/)).toBeInTheDocument();
    expect(screen.getByText('follows up')).toBeInTheDocument();
    expect(getMarkxPost).toHaveBeenCalledWith('p1');
  });
});
