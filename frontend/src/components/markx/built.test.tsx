import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import MarkXPage from '../../pages/MarkXPage';
import MarkXStoryPage from '../../pages/MarkXStoryPage';
import type { MarkxNews, MarkxPerspectiveLine } from '../../services/markx';
import type { MarkxBuilt } from '../../services/api';
import type { BuiltLine, BuiltRow, BuiltStoryView } from './MarkXBuilt';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const now = new Date().toISOString();
const why = { role: 'member' as const, reason: 'judge:pair', p: 0.9, relation: 'same_event', words: null };
const line = (id: string, title: string, built: BuiltLine['built'] = null): BuiltLine => ({
  id, title, source: `Example ${id}`, kind: 'telegram', at: now, role: 'report', why, ix: null, story: 's1', fold: null, built,
});
const BUILT: MarkxBuilt = {
  code: 'built-v1', event_type: 'model_release', read: { read: 3, members: 4 },
  original: { post: 'p2', how: 'links' }, source_page: null, release_at: now,
  leaks: [{ post: 'p1', hours: 9, joins: true, own_coverage: false }],
  came_true: [],
  leaked_before: [{ story: 's0', headline: 'Rumour: Widget 5 next week', hours: 96, joins: false, via: 'connection', posts: ['q1', 'q2'] }],
};
const ROW: BuiltRow = {
  id: 'p2', tag: 'NEW', headline: { text: 'Acme releases Widget 5', from: 'haiku' }, first_at: now, voices: 3, reports: 3,
  shares: 0, mentions: 0, score: 3, story: 's1', removed: [], ix: [], built: BUILT,
  posts: [line('p2', 'Acme: Widget 5 is here', { role: 'original', how: 'links' }),
    line('p1', 'Widget 5 leaks: tomorrow', { role: 'leak', hours: 9, joins: true, own_coverage: false }),
    line('p3', 'Widget 5 tested')],
};
const NEWS: MarkxNews = {
  run: { id: 'r1', started_at: now, finished_at: now, code_version: 'markx-decide-v1' },
  counts: { NEW: 1, rows: 1, ix_rows: 0 }, gone: [], items: [ROW],
};

describe('how a Mark X story is built (0128)', () => {
  it('the News row: the event type, the original first with how it was found, the leak, the story it came true from', async () => {
    renderWithProviders(<MarkXPage />, { api: makeFakeApi({ getMarkxNews: vi.fn().mockResolvedValue(NEWS) }) });
    expect(await screen.findByText(/model release ·/)).toBeInTheDocument();
    await userEvent.click(screen.getByText('Acme releases Widget 5'));
    const posts = screen.getByRole('list', { name: 'Posts in this Mark X row' });
    const items = within(posts).getAllByRole('listitem');
    expect(within(items[0]).getByText(/original · by links/)).toBeInTheDocument();
    expect(within(items[0]).getByText('Acme: Widget 5 is here')).toBeInTheDocument();
    expect(within(items[1]).getByText(/leak · 9 h before the release · joins the release/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Rumour: Widget 5 next week' })).toHaveAttribute('href', '/markx/stories/s0');
    expect(screen.getByText(/Leaked earlier/)).toBeInTheDocument();
  });

  it('a row with nothing read shows no event type', async () => {
    const row = { ...ROW, built: { ...BUILT, event_type: null, original: null, leaks: [], leaked_before: [] },
      posts: [line('p3', 'Widget 5 tested')] };
    renderWithProviders(<MarkXPage />, { api: makeFakeApi({ getMarkxNews: vi.fn().mockResolvedValue({ ...NEWS, items: [row] }) }) });
    expect(await screen.findByText('Acme releases Widget 5')).toBeInTheDocument();
    expect(screen.queryByText(/model release/)).toBeNull();
    expect(screen.queryByText(/Leaked earlier/)).toBeNull();
  });

  it('the story page: how it was built above the sheet, the original first among worth opening', async () => {
    const m = (post: string, label: MarkxPerspectiveLine['label']): MarkxPerspectiveLine => ({
      post, member: true, label, sign: null, by: 'haiku', worth: true, before: false, point: null, claims: [], copies: [],
      facts: [], mine: null,
    });
    const post = (id: string, title: string) => ({ id, title, source: `Example ${id}`, kind: 'telegram', at: now, url: null });
    const view: BuiltStoryView = {
      story: { id: 's1', headline: 'Acme releases Widget 5', first_at: now }, judged: true, sheet: null,
      header: { text: 'Experimental.', source: 'lab', labels: 0 },
      members: [m('p3', 'new_facts'), m('p2', 'original')],
      counts: { members: 3, worth: 2, same: 0, copies: 0, unjudged: 0 },
      posts: { p1: post('p1', 'Widget 5 leaks: tomorrow'), p2: post('p2', 'Acme: Widget 5 is here'), p3: post('p3', 'Widget 5 tested') },
      built: BUILT,
    };
    renderWithProviders(
      <Routes><Route path="/markx/stories/:storyId" element={<MarkXStoryPage />} /></Routes>,
      { api: makeFakeApi({ getMarkxStory: vi.fn().mockResolvedValue(view) }), route: '/markx/stories/s1' },
    );
    const section = await screen.findByRole('region', { name: 'How it was built' });
    expect(within(section).getByText(/the original shown first is right on 61%/)).toBeInTheDocument();
    expect(within(section).getByText(/3 of 4 read/)).toBeInTheDocument();
    expect(within(section).getByRole('link', { name: 'Acme: Widget 5 is here' })).toHaveAttribute('href', '/posts/p2');
    const before = within(section).getByRole('list', { name: 'Before the release' });
    expect(within(before).getByText(/leak, 9 h before the release/)).toBeInTheDocument();
    expect(within(section).getByRole('link', { name: 'Rumour: Widget 5 next week' })).toBeInTheDocument();
    const worth = screen.getByRole('region', { name: 'Worth opening' });
    const first = within(worth).getAllByRole('listitem')[0];
    expect(within(first).getAllByText('Acme: Widget 5 is here').length).toBeGreaterThan(0);
  });
});
