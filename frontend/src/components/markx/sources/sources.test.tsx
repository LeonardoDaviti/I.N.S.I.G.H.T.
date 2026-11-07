import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import MarkXSourcesPage from './MarkXSourcesPage';
import { sortRows } from './format';
import MarkXSourcePage from './MarkXSourcePage';
import type { MarkxSourceCard, MarkxSourcePage, MarkxSourceRow, MarkxSourcesList, MarkxSourceTab } from '../../../services/api';
import { makeFakeApi as makeApi } from '../../../test/fakeApi';
import { renderWithProviders } from '../../../test/render';

// the sources methods live outside createApi (api.ts' 0132 B block), so the fake takes them untyped
const makeFakeApi = (methods: Record<string, unknown>) => makeApi(methods as Parameters<typeof makeApi>[0]);

const cell = (value: unknown, n = 20, too_few = false) => ({ value, n, too_few });
const row = (id: string, name: string, stats: MarkxSourceRow['stats'], over: Partial<MarkxSourceRow> = {}): MarkxSourceRow => ({
  kind: 'source', id, name, platform: 'site', enabled: true, channels: 1, stats, ...over,
});
const COLUMNS = ['role', 'per_week', 'first_to_report', 'news_yield', 'cited_by', 'solo_share'];
const list = (rows: MarkxSourceRow[]): MarkxSourcesList => ({
  rows, columns: COLUMNS, formulas: { first_to_report: 'earliest voice / its stories' }, computed_at: '2026-11-08T03:00:00+00:00', job: null,
});
const WIRE = row('s1', 'Example Wire', { role: cell('reporter'), per_week: cell(4.2), first_to_report: cell(0.8, 12), cited_by: cell(3) });
const BLOG = row('s2', 'Other Blog', { role: cell('commentator'), first_to_report: cell(0.2, 11), cited_by: cell(7) });
const THIN = row('s3', 'Thin Feed', { role: cell('too_few', 1), first_to_report: cell(1.0, 2, true), cited_by: cell(0) });
const VOICE = row('v1', 'Acme', { role: cell('official') }, { kind: 'voice', platform: 'voice', channels: 2 });

function names() {
  const table = screen.getByRole('table', { name: 'Sources' });
  return within(table).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[0].querySelector('a')?.textContent);
}

describe('the source list (0132 B)', () => {
  it('shows one row per source or voice, the columns, no overall score, and too few', async () => {
    const getMarkxSources = vi.fn().mockResolvedValue(list([WIRE, BLOG, THIN, VOICE]));
    renderWithProviders(<MarkXSourcesPage />, { api: makeFakeApi({ getMarkxSources }) });
    expect(await screen.findByRole('table', { name: 'Sources' })).toBeInTheDocument();
    expect(names()).toEqual(['Acme', 'Example Wire', 'Other Blog', 'Thin Feed']);
    expect(screen.getAllByText('voice · 2 channels').length).toBeGreaterThan(0);
    expect(within(screen.getByRole('table')).queryByText(/score/i)).toBeNull();      // no overall score column
    const thin = within(screen.getByRole('table')).getAllByRole('row').find((r) => r.textContent?.includes('Thin Feed'))!;
    expect(within(thin).getByText('too few')).toBeInTheDocument();
    expect(within(thin).getByText('too few to tell')).toBeInTheDocument();      // the role
    expect(within(screen.getByRole('table')).getByRole('link', { name: 'Example Wire' })).toHaveAttribute('href', '/markx/sources/s1');
  });

  it('sorts by any column, too few last', async () => {
    const getMarkxSources = vi.fn().mockResolvedValue(list([WIRE, BLOG, THIN]));
    renderWithProviders(<MarkXSourcesPage />, { api: makeFakeApi({ getMarkxSources }) });
    await screen.findByRole('table', { name: 'Sources' });
    const table = screen.getByRole('table');
    await userEvent.click(within(table).getByRole('button', { name: 'Sort by first to report' }));
    expect(names()).toEqual(['Example Wire', 'Other Blog', 'Thin Feed']);        // 80%, 20%, too few
    await userEvent.click(within(table).getByRole('button', { name: 'Sort by first to report' }));
    expect(names()).toEqual(['Other Blog', 'Example Wire', 'Thin Feed']);        // ascending: too few still last
    await userEvent.click(within(table).getByRole('button', { name: 'Sort by cited by' }));
    expect(names()).toEqual(['Other Blog', 'Example Wire', 'Thin Feed']);
  });

  it('sortRows keeps a missing number last either way', () => {
    const asc = sortRows([THIN, WIRE, BLOG], { by: 'per_week', desc: false }).map((r) => r.id);
    expect(asc).toEqual(['s1', 's2', 's3']);
  });

  it('says so when nothing is computed yet', async () => {
    const getMarkxSources = vi.fn().mockResolvedValue({ ...list([]), computed_at: null });
    renderWithProviders(<MarkXSourcesPage />, { api: makeFakeApi({ getMarkxSources }) });
    expect(await screen.findByText('No sources computed yet')).toBeInTheDocument();
    expect(screen.getByText('Not computed yet')).toBeInTheDocument();
  });

  it('has a phone layout with every column', async () => {
    const getMarkxSources = vi.fn().mockResolvedValue(list([WIRE]));
    const { container } = renderWithProviders(<MarkXSourcesPage />, { api: makeFakeApi({ getMarkxSources }) });
    await screen.findByRole('table', { name: 'Sources' });
    const phone = container.querySelector('[data-phone-list]') as HTMLElement;
    expect(phone.className).toContain('sm:hidden');
    expect(within(phone).getAllByText('First to report')).toHaveLength(2);           // a sort button and the line
    expect(within(phone).getByText('80%')).toBeInTheDocument();
  });
});

const sig = (signal: string, value: unknown, over: Record<string, unknown> = {}) => ({
  signal, value, n: 20, min: 10, counts: 'posts', too_few: false, formula: `${signal} formula`, evidence: {}, ...over,
});
const cards = (stanceTask: string | null = 't1'): MarkxSourceCard[] => [
  { card: 'who', title: 'Who it is', experimental: false, signals: [sig('role', 'staff_or_beat', {
    evidence: { line: '60% of 12 read posts are about Other Co (needs a bio)', needs_bio: true,
      posts: [{ id: 'p1', title: 'A post about Other Co', at: '2026-11-01T00:00:00+00:00', source: 'Example Wire' }] } })] },
  { card: 'first', title: 'First to report', experimental: false, signals: [sig('first_to_report', 0.5, {
    evidence: { stories: [{ story: 'st1', title: 'Widget 4.1 ships', first: true, next: 'Other Blog', hours: 2, post: 'p2' }] } })] },
  { card: 'covered', title: 'Covered by others', experimental: false, signals: [sig('solo_share', 0.4, { n: 3, too_few: true })] },
  { card: 'cited', title: 'Cited by', experimental: false, signals: [sig('cited_by', 1, { min: 0, evidence: {
    voices: [{ voice: 'Other Blog', posts: 2, example: { id: 'p3', title: 'Linking it', at: null, source: 'Other Blog' } }],
    classics: 0, classic_rows: [], bias: 'Only your own sources count, and nobody links Telegram posts.' } })] },
  { card: 'stance', title: 'Stance and framing', experimental: true, signals: [sig('stance', 1, { min: 15, n: 15, evidence: {
    task: stanceTask, labels: {}, patterns: [{ pattern: 'distrusts the vendor', kind: 'stance',
      quotes: [{ post: 1, quote: 'we cannot trust it', post_id: 'p4' }, { post: 2, quote: 'never again', post_id: null }] }] } })] },
];
const tab = (id: string, name: string, kind: 'source' | 'voice' = 'source'): MarkxSourceTab => ({
  kind, id, name, platform: kind === 'voice' ? 'voice' : 'x', computed: true, cards: cards(),
});
const page = (over: Partial<MarkxSourcePage> = {}): MarkxSourcePage => ({
  subject: { kind: 'source', id: 's1', name: 'Example Wire', voice: null }, tabs: [tab('s1', 'Example Wire')],
  computed_at: '2026-11-08T03:00:00+00:00', ...over,
});

function renderPage(methods: Record<string, unknown>, id = 's1') {
  return renderWithProviders(
    <Routes><Route path="/markx/sources/:sourceId" element={<MarkXSourcePage />} /></Routes>,
    { api: makeFakeApi(methods), route: `/markx/sources/${id}` },
  );
}

describe('a source page (0132 B)', () => {
  it('shows a card per signal: the number, the formula, the evidence posts, and too few to tell', async () => {
    const getMarkxSource = vi.fn().mockResolvedValue(page());
    renderPage({ getMarkxSource });
    expect(await screen.findByRole('heading', { name: 'Example Wire' })).toBeInTheDocument();
    expect(getMarkxSource).toHaveBeenCalledWith('s1');
    const who = screen.getByRole('region', { name: 'Who it is' });
    expect(within(who).getByText('staff or beat')).toBeInTheDocument();
    expect(within(who).getByText(/can't tell staff from a beat writer/)).toBeInTheDocument();
    expect(within(who).getByRole('link', { name: 'A post about Other Co' })).toHaveAttribute('href', '/posts/p1');
    expect(within(who).getByText('role formula')).toBeInTheDocument();
    const first = screen.getByRole('region', { name: 'First to report' });
    expect(within(first).getByText(/first; Other Blog 2 h later/)).toBeInTheDocument();
    const covered = screen.getByRole('region', { name: 'Covered by others' });
    expect(within(covered).getByText(/too few to tell/)).toBeInTheDocument();
    expect(within(covered).getByText(/3 posts; 10 needed/)).toBeInTheDocument();
    const cited = screen.getByRole('region', { name: 'Cited by' });
    expect(within(cited).getByText(/nobody links Telegram posts/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Stance and framing' })).getByText('Experimental')).toBeInTheDocument();
    expect(screen.getByText(/No overall score/)).toBeInTheDocument();
  });

  it('labels a stance pattern right, and a second tap takes it back', async () => {
    const getMarkxSource = vi.fn().mockResolvedValue(page());
    const labelMarkxStance = vi.fn().mockResolvedValueOnce({ labels: { 0: 'right' } }).mockResolvedValueOnce({ labels: {} });
    renderPage({ getMarkxSource, labelMarkxStance });
    const stance = await screen.findByRole('region', { name: 'Stance and framing' });
    expect(within(stance).getByText('distrusts the vendor')).toBeInTheDocument();
    expect(within(stance).getByRole('link', { name: 'post 1' })).toHaveAttribute('href', '/posts/p4');
    await userEvent.click(within(stance).getByRole('button', { name: '✓ right' }));
    expect(labelMarkxStance).toHaveBeenLastCalledWith('t1', 0, 'right');
    await waitFor(() => expect(within(stance).getByRole('button', { name: '✓ right' })).toHaveAttribute('aria-pressed', 'true'));
    await userEvent.click(within(stance).getByRole('button', { name: '✓ right' }));
    expect(labelMarkxStance).toHaveBeenLastCalledWith('t1', 0, 'undo');
    await waitFor(() => expect(within(stance).getByRole('button', { name: '✓ right' })).toHaveAttribute('aria-pressed', 'false'));
  });

  it('a voice has a tab per channel, its own first', async () => {
    const getMarkxSource = vi.fn().mockResolvedValue(page({
      subject: { kind: 'voice', id: 'v1', name: 'Acme', voice: null },
      tabs: [tab('v1', 'Acme', 'voice'), tab('s1', 'Acme on X'), tab('s2', 'Acme blog')],
    }));
    renderPage({ getMarkxSource }, 'v1');
    const tabs = await screen.findByRole('tablist', { name: 'Channels' });
    expect(within(tabs).getAllByRole('tab').map((t) => t.textContent)).toEqual(['All channels', 'Acme on X', 'Acme blog']);
    expect(screen.getByText('voice · 2 channels', { exact: false })).toBeInTheDocument();
  });

  it('a source not computed yet says so', async () => {
    const getMarkxSource = vi.fn().mockResolvedValue(page({ tabs: [{ ...tab('s1', 'Example Wire'), computed: false }], computed_at: null }));
    renderPage({ getMarkxSource });
    expect(await screen.findByText(/Not computed yet/)).toBeInTheDocument();
  });
});
