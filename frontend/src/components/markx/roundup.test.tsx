// 0181 (own round-ups): the /markx section with the latest daily and weekly issue and the past ones (curators, "only
// in round-ups"), and a story's "also in round-ups" line. Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import MarkXRoundup, { AlsoInRoundups } from './MarkXRoundup';
import { markxRoundupApi, type MarkxRoundupIssue, type MarkxRoundupIssues } from '../../services/api';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const DAILY: MarkxRoundupIssue = {
  id: 7, span: 'day', from: '2100-06-01T20:00:00+00:00', until: '2100-06-02T20:00:00+00:00', version: 1,
  built_at: '2100-06-03T03:00:00+00:00', roundups: 2, units: 3, count: 2, left_out: { promo: 3, other: 2 },
  items: [
    { key: 'mx:s1', kind: 'mx_story', ref: 's1', headline: 'Acme releases Widget 4.1', curators: 2, issues: 2,
      only_roundups: false, at: '2100-06-02T10:00:00+00:00', posts: ['p1'],
      units: [{ unit: 1, post: 'r1', n: 3, item: 'Widget 4.1 is out', source: 'Example Digest', title: 'Daily' },
              { unit: 2, post: 'r2', n: 1, item: 'Acme shipped Widget 4.1', source: 'Example Links', title: 'Links' }] },
    { key: 'page:example.com/news/a', kind: 'page', ref: 'https://example.com/news/a', headline: 'A study nobody else covered',
      curators: 1, issues: 1, only_roundups: true, at: '2100-06-02T09:00:00+00:00', posts: [],
      units: [{ unit: 3, post: 'r1', n: 7, item: 'A study nobody else covered', source: 'Example Digest', title: 'Daily' }] },
  ],
};
const WEEKLY: MarkxRoundupIssue = { ...DAILY, id: 8, span: 'week', from: '2100-05-23T20:00:00+00:00',
  until: '2100-05-30T20:00:00+00:00', items: [{ ...DAILY.items![1], key: 'page:w', headline: 'The week in one line' }] };
const PAST: MarkxRoundupIssue = { ...DAILY, id: 5, from: '2100-05-31T20:00:00+00:00', until: '2100-06-01T20:00:00+00:00',
  version: 2, items: undefined };
const ISSUES: MarkxRoundupIssues = { daily: DAILY, weekly: WEEKLY, past: [PAST], tz_offset_minutes: 240 };

afterEach(() => vi.restoreAllMocks());

describe('Own round-up (0181)', () => {
  it('shows the latest daily issue by curators, flags what only round-ups carry, and switches to the weekly', async () => {
    vi.spyOn(markxRoundupApi, 'issues').mockResolvedValue(ISSUES);
    renderWithProviders(<MarkXRoundup />, { api: makeFakeApi({}) });
    const region = await screen.findByRole('region', { name: 'Own round-up' });
    expect(await within(region).findByText(/Daily · 2 Jun · 2 round-ups · 2 items · 5 left out \(not news\)/)).toBeInTheDocument();
    const rows = within(within(region).getByRole('list', { name: 'Round-up items' })).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('Acme releases Widget 4.1');
    expect(rows[0]).toHaveTextContent('2 curators · Example Digest, Example Links');
    expect(within(rows[0]).getByRole('link', { name: 'Acme releases Widget 4.1' })).toHaveAttribute('href', '/markx/stories/s1');
    expect(rows[0]).not.toHaveTextContent('only in round-ups');
    expect(rows[1]).toHaveTextContent('1 curator · Example Digest · only in round-ups');
    await userEvent.click(within(region).getByRole('button', { name: 'weekly' }));
    expect(region).toHaveTextContent('Weekly · 24 May–30 May');
    expect(region).toHaveTextContent('The week in one line');
  });

  it('opens a past issue, its version shown', async () => {
    vi.spyOn(markxRoundupApi, 'issues').mockResolvedValue(ISSUES);
    const one = vi.spyOn(markxRoundupApi, 'issue').mockResolvedValue({ ...PAST, items: [{ ...DAILY.items![0], headline: 'An older story' }] });
    renderWithProviders(<MarkXRoundup />, { api: makeFakeApi({}) });
    const region = await screen.findByRole('region', { name: 'Own round-up' });
    await userEvent.click(await within(region).findByText('Past round-ups · 1'));
    await userEvent.click(within(region).getByRole('button', { name: 'daily 1 Jun' }));
    expect(one).toHaveBeenCalledWith(5);
    expect(await within(region).findByText('An older story')).toBeInTheDocument();
    expect(region).toHaveTextContent('version 2');
  });

  it('says so when no issue is built yet', async () => {
    vi.spyOn(markxRoundupApi, 'issues').mockResolvedValue({ daily: null, weekly: null, past: [], tz_offset_minutes: 240 });
    renderWithProviders(<MarkXRoundup />, { api: makeFakeApi({}) });
    expect(await screen.findByText('No daily round-up built yet.')).toBeInTheDocument();
  });
});

describe('Also in round-ups (0181)', () => {
  it('names each round-up carrying a member, and nothing when none does', () => {
    const { container, rerender } = render(
      <MemoryRouter>
        <AlsoInRoundups roundups={[{ post: 'r1', source: 'Example Digest', title: 'Daily', n: 3, item: 'Widget 4.1 is out' }]} />
      </MemoryRouter>);
    expect(container).toHaveTextContent('Also in round-ups: Example Digest (item 3)');
    expect(screen.getByRole('link', { name: 'Example Digest' })).toHaveAttribute('href', '/posts/r1');
    rerender(<MemoryRouter><AlsoInRoundups roundups={[]} /></MemoryRouter>);
    expect(container).toBeEmptyDOMElement();
  });
});
