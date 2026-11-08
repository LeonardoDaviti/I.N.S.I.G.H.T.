// 0136 (back in the news, Shadow): the rows /markx shows, the lab's measured precision and the owner's running one,
// and the four label buttons. Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXBack from './MarkXBack';
import { markxBackApi, type MarkxBack } from '../../services/api';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const PAGE: MarkxBack = {
  items: [{
    id: 'b1', story: 's1', headline: 'Widget 4.1 preview', first_at: '2026-06-01T10:00:00+00:00',
    window_at: '2026-07-10T10:00:00+00:00', days_later: 39, trig: ['E'],
    posts: [
      { id: 'n1', n: 1, title: 'Widget 4.1 safety finding', source: 'Example Blog', at: '2026-07-10T10:00:00+00:00',
        url: null, trig: ['E'], verdict: 'development', about: 'Widget 4.1' },
      { id: 'n2', n: 2, title: 'A recap', source: 'Example News', at: '2026-07-11T10:00:00+00:00', url: null, trig: ['E'],
        verdict: 'retold', about: null },
    ],
    old_thing: 'Widget 4.1', what_new: ['A third party found a flaw in it.'], runs: ['development', 'development', 'retold'],
    label: null,
  }],
  counts: { candidates: 3, development: 1, retold: 1, waiting: 1 },
  precision: { labelled: 0, development: 0, precision: null },
  measured: { precision: 0.87, lo: 0.68, hi: 0.96, n: 23, words: 'measured 87% precise (68–96%), about 1 in 8 wrong' },
};

afterEach(() => vi.restoreAllMocks());

describe('Back in the news (0136)', () => {
  it('shows each row with its old story, the days later, the new posts and the reasons, and the precisions', async () => {
    vi.spyOn(markxBackApi, 'list').mockResolvedValue(PAGE);
    renderWithProviders(<MarkXBack />, { api: makeFakeApi({}) });
    const region = await screen.findByRole('region', { name: 'Back in the news' });
    expect(region).toHaveTextContent('measured 87% precise (68–96%), about 1 in 8 wrong');
    expect(region).toHaveTextContent('none labelled yet');
    expect(region).toHaveTextContent('3 candidates, 1 waiting for Haiku');
    expect(within(region).getByRole('link', { name: 'Widget 4.1 preview' })).toHaveAttribute('href', '/posts/s1');
    expect(region).toHaveTextContent('back 39 days later · names its subject');
    expect(region).toHaveTextContent('Haiku: Widget 4.1 — A third party found a flaw in it. (2 of 3 runs)');
    const posts = within(region).getByRole('list', { name: 'The new posts' });
    expect(within(posts).getAllByRole('listitem')[0]).toHaveTextContent('1. Widget 4.1 safety finding · Example Blog');
    expect(within(posts).getAllByRole('listitem')[1]).toHaveTextContent('retold');
  });

  it('labels a row with one of the four and undoes it', async () => {
    vi.spyOn(markxBackApi, 'list').mockResolvedValue(PAGE);
    const label = vi.spyOn(markxBackApi, 'label')
      .mockResolvedValueOnce({ id: 'l1', answer: 'related', label: 'related', precision: { labelled: 1, development: 0, precision: 0 } })
      .mockResolvedValueOnce({ id: 'l2', answer: 'undo', label: null, precision: { labelled: 0, development: 0, precision: null } });
    renderWithProviders(<MarkXBack />, { api: makeFakeApi({}) });
    const group = await screen.findByRole('group', { name: 'What is this?' });
    expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual(['development', 'retold', 'related', 'unrelated']);
    await userEvent.click(within(group).getByRole('button', { name: 'related' }));
    expect(label).toHaveBeenCalledWith('b1', 'related');
    expect(await within(group).findByText('you said related')).toBeInTheDocument();
    await userEvent.click(within(group).getByRole('button', { name: 'undo' }));
    expect(label).toHaveBeenLastCalledWith('b1', 'undo');
    await waitFor(() => expect(within(group).getByRole('button', { name: 'development' })).toBeInTheDocument());
  });

  it('shows the running precision from the labels', async () => {
    vi.spyOn(markxBackApi, 'list').mockResolvedValue({ ...PAGE, precision: { labelled: 4, development: 3, precision: 0.75 } });
    renderWithProviders(<MarkXBack />, { api: makeFakeApi({}) });
    expect(await screen.findByRole('region', { name: 'Back in the news' })).toHaveTextContent('your labels: 3 of 4 development (75%)');
  });

  it('shows nothing before the first candidate', async () => {
    const list = vi.spyOn(markxBackApi, 'list').mockResolvedValue({ ...PAGE, items: [], counts: { candidates: 0 } });
    renderWithProviders(<MarkXBack />, { api: makeFakeApi({}) });
    await waitFor(() => expect(list).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));   // the query settles
    expect(screen.queryByRole('region', { name: 'Back in the news' })).not.toBeInTheDocument();
  });
});
