import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXPage from '../../pages/MarkXPage';
import type { MarkxFold, MarkxLine, MarkxNews } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const now = new Date().toISOString();
const why = { role: 'member' as const, reason: 'judge:pair', p: 0.9, relation: 'same_event', words: null };
const fold = (state: MarkxFold['state'], over: Partial<MarkxFold> = {}): MarkxFold => ({
  state, head: 'p1', by: state === 'folded' ? 'rule' : null, answer: null,
  rule: state === 'head' ? 'head' : state, count: state === 'head' ? 2 : null, ...over,
});
const line = (id: string, title: string, f: MarkxFold | null): MarkxLine => ({
  id, title, source: `Example ${id}`, kind: 'telegram', at: now, role: 'report', why, ix: null, story: 's1', fold: f,
});
const NEWS: MarkxNews = {
  run: { id: 'r1', started_at: now, finished_at: now, code_version: 'markx-decide-v1' },
  counts: { NEW: 1, rows: 1, ix_rows: 0 },
  gone: [],
  folds: { answered: 3, folded: { n: 2, right: 1, precision: 0.5, interval: [0.09, 0.91] }, missed: 1,
    lab: { f1: 0.7, single_runs: [0.68, 0.72, 0.71], set: '60 unseen lab clusters', date: '2026-11-06' } },
  items: [{
    id: 'p1', tag: 'NEW', headline: { text: 'Acme releases Widget 4.1', from: 'haiku' }, first_at: now, voices: 4, reports: 4,
    shares: 0, mentions: 0, score: 4, story: 's1', removed: [], ix: [], folded: 2,
    posts: [
      line('p1', 'Acme: Widget 4.1 is here', fold('head')),
      line('p2', 'Widget 4.1 вышла', fold('folded')),
      line('p3', 'Why Widget 4.1 matters', fold('shown')),
      line('p4', 'Widget 4.1, the link', fold('folded')),
      line('p5', 'Not read yet', null),
    ],
  }],
};

describe('duplicates folded (0127)', () => {
  it('shows the head, folds the retellings under one line, and counts them', async () => {
    renderWithProviders(<MarkXPage />, { api: makeFakeApi({ getMarkxNews: vi.fn().mockResolvedValue(NEWS) }) });
    expect(await screen.findByText(/Duplicates folded: experimental; on unseen lab stories F1 0.70/)).toBeInTheDocument();
    expect(screen.getByText(/your labels: 1 of 2 folds right · 1 missed/)).toBeInTheDocument();
    expect(screen.getByText(/· 2 retold/)).toBeInTheDocument();
    await userEvent.click(screen.getByText('Acme releases Widget 4.1'));
    const posts = screen.getByRole('list', { name: 'Posts in this Mark X row' });
    expect(within(posts).getByText('↳ 2 more retell it')).toBeInTheDocument();
    const retold = within(posts).getByRole('list', { name: 'Retold', hidden: true });
    expect(within(retold).getByText('Widget 4.1 вышла')).toBeInTheDocument();
    expect(within(retold).getByText('Widget 4.1, the link')).toBeInTheDocument();
    expect(within(retold).queryByText('Why Widget 4.1 matters')).toBeNull();
    // the head has no fold buttons; the member outside the group can be folded; an unread one has none
    const head = within(posts).getByText('Acme: Widget 4.1 is here').closest('li')!;
    expect(within(head).queryByRole('group', { name: 'Does it retell the same happening?' })).toBeNull();
    const shown = within(posts).getByText('Why Widget 4.1 matters').closest('li')!;
    expect(within(shown).getByRole('button', { name: 'fold: same happening' })).toBeInTheDocument();
    const unread = within(posts).getByText('Not read yet').closest('li')!;
    expect(within(unread).queryByRole('group', { name: 'Does it retell the same happening?' })).toBeNull();
  });

  it('an answer is sent at once, shown, and can be undone', async () => {
    const answerMarkxFold = vi.fn()
      .mockResolvedValueOnce({ story: 's1', post: 'p2', state: 'shown', answer: 'not_same' })
      .mockResolvedValueOnce({ story: 's1', post: 'p2', state: 'folded', answer: null });
    const getMarkxNews = vi.fn().mockResolvedValue(NEWS);
    renderWithProviders(<MarkXPage />, { api: makeFakeApi({ getMarkxNews, answerMarkxFold }) });
    await userEvent.click(await screen.findByText('Acme releases Widget 4.1'));
    await userEvent.click(screen.getByText('↳ 2 more retell it'));
    const retold = screen.getByRole('list', { name: 'Retold' });
    const row = within(retold).getByText('Widget 4.1 вышла').closest('li')!;
    await userEvent.click(within(row).getByRole('button', { name: 'not the same ✗' }));
    expect(answerMarkxFold).toHaveBeenCalledWith('s1', 'p2', 'not_same');
    expect(await within(row).findByText('you: not the same')).toBeInTheDocument();
    await waitFor(() => expect(getMarkxNews.mock.calls.length).toBeGreaterThan(1));   // the page is read again
    await userEvent.click(within(row).getByRole('button', { name: 'undo' }));
    expect(answerMarkxFold).toHaveBeenLastCalledWith('s1', 'p2', 'undo');
    await waitFor(() => expect(within(row).getByRole('button', { name: 'same happening ✓' })).toBeInTheDocument());
  });
});
