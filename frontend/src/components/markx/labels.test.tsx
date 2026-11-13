import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXLabels from './MarkXLabels';
import MarkXNews from './MarkXNews';
import type { MarkxLabelItem, MarkxLabelQueue, MarkxNews, MarkxPrecision, MarkxStat } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const now = new Date().toISOString();
const QUEUE: MarkxLabelQueue = {
  run: 'r1', cut: '2100-03-04', total: 2, done: 0, answered: [], pools: { 'join:near': 1, 'merge:all': 1 },
  features: [{ feature: 'join', name: 'F2 joins', total: 1, done: 0, population: 5 },
    { feature: 'merge', name: 'Merges', total: 1, done: 0, population: 1 }],
  next: ['t1', 't2'],
};
const ITEM: MarkxLabelItem = {
  id: 't1', feature: 'join', name: 'F2 joins', question: "Is the POST about the STORY's event?",
  answers: ['same_event', 'follow_up', 'related', 'different', 'unsure'],
  evidence: 'STORY\nHeadline: Acme released Widget 4\n\nPOST\nTitle: Widget 4 is out', extracted: null, day: now, split: 'dev',
  pool: 'join:near', position: 1, label: null, verdict: null,
};

describe('the labels tab (issue 0086 F)', () => {
  it('shows the evidence blind, then the verdict once answered, then the next item', async () => {
    const labelMarkxItem = vi.fn().mockResolvedValue({
      label: { id: 'l1', answer: 'related', note: 'only background', split: 'dev' }, next: 't2', done: 1, total: 2,
      verdict: { relation: 'same_event', p: 0.62, reason: 'The same release.', bar: 0.6, decision: 'joined' },
    });
    const getMarkxLabelItem = vi.fn((id: string) => Promise.resolve(id === 't1' ? ITEM
      : { ...ITEM, id: 't2', feature: 'merge', name: 'Merges', question: 'Are STORY A and STORY B the same event?', position: 2,
        evidence: 'STORY A\nHeadline: one\n\nSTORY B\nHeadline: two' }));
    const getMarkxLabels = vi.fn().mockResolvedValueOnce(QUEUE)          // after the answer: t1 is no longer next
      .mockResolvedValue({ ...QUEUE, done: 1, next: ['t2'], answered: ['t1'] });
    renderWithProviders(<MarkXLabels />, { api: makeFakeApi({ getMarkxLabels, getMarkxLabelItem, labelMarkxItem }) });
    expect(await screen.findByText(/Headline: Acme released Widget 4/)).toBeInTheDocument();
    expect(screen.getByText(/0 of 2 items answered · dev before 2100-03-04/)).toBeInTheDocument();
    expect(screen.queryByText(/The same release/)).not.toBeInTheDocument();          // blind before the answer
    await userEvent.type(screen.getByPlaceholderText(/note/), 'only background');
    const answers = screen.getByRole('group', { name: 'Your answer' });
    await userEvent.click(within(answers).getByRole('button', { name: 'related' }));
    expect(labelMarkxItem).toHaveBeenCalledWith('t1', 'related', 'only background');
    expect(await screen.findByText(/Haiku: same event 0.62/)).toBeInTheDocument();
    expect(screen.getByText(/Bar 0.60: joined/)).toBeInTheDocument();
    await waitFor(() => expect(getMarkxLabels).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/Headline: Acme released Widget 4/)).toBeInTheDocument();   // still on the answered item
    expect(within(answers).getByRole('button', { name: 'related' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'next' }));
    expect(await screen.findByText('Are STORY A and STORY B the same event?')).toBeInTheDocument();
  });

  it('says the queue is being built until insight-ingestion has kept it (0182)', async () => {
    const getMarkxLabels = vi.fn().mockResolvedValue({ ...QUEUE, total: 0, next: [], features: [], pools: {}, building: true });
    const getMarkxLabelItem = vi.fn();
    renderWithProviders(<MarkXLabels />, { api: makeFakeApi({ getMarkxLabels, getMarkxLabelItem }) });
    expect(await screen.findByText('The queue is being built')).toBeInTheDocument();
    expect(getMarkxLabelItem).not.toHaveBeenCalled();
  });

  it('shows the last kept queue while the newest run\'s is built (0182)', async () => {
    const getMarkxLabels = vi.fn().mockResolvedValue({ ...QUEUE, building: true });
    renderWithProviders(<MarkXLabels />, { api: makeFakeApi({ getMarkxLabels, getMarkxLabelItem: vi.fn().mockResolvedValue(ITEM) }) });
    expect(await screen.findByText(/Headline: Acme released Widget 4/)).toBeInTheDocument();
    expect(screen.getByText(/The last decision run's queue is being built/)).toBeInTheDocument();
  });

  it('shows each feature with its bar, dev and test, and the re-picked bar', async () => {
    const s = (precision: number | null, labelled: number): MarkxStat => ({ labelled, right: Math.round((precision ?? 0) * labelled),
      precision, lo: precision === null ? null : precision - 0.2, hi: precision === null ? null : Math.min(1, precision + 0.05),
      n_eff: labelled });
    const prec: MarkxPrecision = {
      labeller: 'owner', labellers: ['owner', 'claude-A'], cut: '2100-03-04', target: 0.95, stale: 0, unsure: 1, flags: {},
      features: [{ feature: 'join', name: 'F2 joins', acted: 'joined', bar: 0.6, population: 175, labelled: 30,
        splits: { dev: { acted: s(0.86, 20), rejected: s(0.9, 4) }, test: { acted: s(0.8, 6), rejected: s(null, 0) },
          all: { acted: s(0.85, 26), rejected: s(0.9, 4) } },
        sweep: [{ bar: 0.6, dev: s(0.86, 20), test: s(0.8, 6) }, { bar: 0.7, dev: s(0.96, 14), test: s(0.9, 4) }],
        repick: { bar: 0.7, dev: s(0.96, 14), test: s(0.9, 4) }, flags: { wrong_story: 2 } }],
    };
    const getMarkxPrecision = vi.fn().mockResolvedValue(prec);
    renderWithProviders(<MarkXLabels />, { api: makeFakeApi({ getMarkxLabels: vi.fn().mockResolvedValue(QUEUE),
      getMarkxLabelItem: vi.fn().mockResolvedValue(ITEM), getMarkxPrecision,
      getMarkxPerspectiveAccuracy: vi.fn().mockReturnValue(new Promise(() => {})) }) });   // 0119 B7's section: pending here
    await userEvent.click(screen.getByRole('button', { name: 'precision' }));
    const card = await screen.findByRole('region', { name: 'F2 joins' });
    expect(within(card).getByText(/bar 0.60 · 175 questions · 30 labelled/)).toBeInTheDocument();
    expect(within(card).getAllByText('86% (66–91%)').length).toBeGreaterThan(0);
    expect(within(card).getByText(/the lowest bar reaching 95% is 0.70: test 90% \(70–95%\) on 4/)).toBeInTheDocument();
    expect(within(card).getByText(/One tap on Mark X News: 2 wrong story/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Labels by' }), 'claude-A');
    await waitFor(() => expect(getMarkxPrecision).toHaveBeenCalledWith('claude-A'));
  });
});

describe('one tap on a Mark X News member', () => {
  it('stores "wrong story" and takes it back', async () => {
    const news: MarkxNews = {
      run: { id: 'r1', started_at: now, finished_at: now, code_version: 'markx-decide-v1' },
      counts: { NEW: 1, rows: 1, ix_rows: 0 }, gone: [],
      items: [{ id: 'p1', tag: 'NEW', headline: { text: 'Acme releases Widget 4.1', from: 'haiku' }, first_at: now, voices: 2,
        reports: 2, shares: 0, mentions: 0, score: 2, story: 's1', removed: [], ix: [],
        posts: [{ id: 'p1', title: 'Widget 4.1 is out', source: 'Example Blog', kind: 'site', at: now, role: 'report', story: 's1',
          flag: null, why: { role: 'member', reason: 'judge:pair', p: 0.9, relation: 'same_event', words: null }, ix: null }] }],
    };
    const flagMarkxMember = vi.fn((post: string, story: string, answer: string) => Promise.resolve({ id: 'l', post, story, answer }));
    renderWithProviders(<MarkXNews />, { api: makeFakeApi({ getMarkxNews: vi.fn().mockResolvedValue(news), flagMarkxMember }) });
    await userEvent.click(await screen.findByText('Acme releases Widget 4.1'));
    await userEvent.click(screen.getByRole('button', { name: 'wrong story' }));
    expect(flagMarkxMember).toHaveBeenCalledWith('p1', 's1', 'wrong_story');
    expect(await screen.findByText('you: wrong story')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'undo' }));
    expect(flagMarkxMember).toHaveBeenLastCalledWith('p1', 's1', 'ok');
    expect(await screen.findByRole('button', { name: 'not about this' })).toBeInTheDocument();
  });
});
