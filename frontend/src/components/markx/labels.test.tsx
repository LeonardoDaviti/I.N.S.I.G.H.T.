import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXNews from './MarkXNews';
import type { MarkxNews } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

// v10.22 (0216 D): the Labels tab and its queue are removed; the one tap on a News member stays.
const now = new Date().toISOString();

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
