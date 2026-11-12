// 0173 ("Is this worth it?", Mark X): the tap, the wait for the worker, the verdict with its reasons and the items it
// relied on, Ask again; in the Add source dialog once a feed is found, and on Discover's rows. Nothing is followed by
// it. Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SourceJudge from './SourceJudge';
import MainSourceMissing from './MainSourceMissing';
import AddSourceModal from '../AddSourceModal';
import { judgeLine, sourceJudgeApi, waitingLine, type SourceJudgement } from '../../services/sourceJudge';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { MainSourceRow } from '../../services/api';

const ON = { getMarkxOn: vi.fn().mockResolvedValue({ on: true }) };
const ADDRESS = 'https://judged.example/blog';

const judgement = (over: Partial<SourceJudgement> = {}): SourceJudgement => ({
  id: 'j1', address: ADDRESS, key: 'judged.example/blog', status: 'answered', reason: null, verdict: 'follow',
  reasons: ['Its own release notes on widgets, linked by 3 of your sources.', 'Started 2 of your stories.'],
  fits: true, original: 'high',
  examples: [{ id: 'i1', url: 'https://judged.example/blog/widget-5', title: 'Widget 5 is out', published_at: '2026-11-10T10:00:00Z' }],
  items: 10, follows_as: 'feed', follow_address: 'https://judged.example/blog/feed.xml',
  measured: ['Linked by your sources: 3 sources (9 posts, 4 in the last 90 days): A, B, C', 'Reads: full: full text in the feed'],
  reads: 'full', cadence: '2 a week', rewriter: false, same_items: false,
  asked_at: '2026-11-11T10:00:00Z', answered_at: '2026-11-11T11:00:00Z', fresh_until: '2026-12-11T10:00:00Z', fresh: true,
  ...over,
});

afterEach(() => vi.restoreAllMocks());

describe('the lines in words', () => {
  it('says the verdict’s facts and what it waits for', () => {
    expect(judgeLine(judgement())).toBe('fits what you read · original: high · full text · 2 a week');
    expect(judgeLine(judgement({ fits: false, original: 'low', reads: 'teaser', rewriter: true, cadence: null })))
      .toBe('not what you read · original: low · teasers only · reads like a rewriter');
    expect(waitingLine(judgement({ status: 'asked' }))).toBe('Read 10 items · waiting for the worker’s next run');
    expect(waitingLine(judgement({ status: 'unreadable', reason: 'blocked' }))).toBe('Can’t read it: blocked');
  });
});

describe('Is this worth it? (0173)', () => {
  it('asks on the tap only and shows the wait for the worker', async () => {
    const get = vi.spyOn(sourceJudgeApi, 'get').mockResolvedValue({ judgement: judgement({ status: 'asked', verdict: null, reasons: [] }) });
    const ask = vi.spyOn(sourceJudgeApi, 'ask').mockResolvedValue({ judgement: judgement({ status: 'asked', verdict: null, reasons: [] }) });
    renderWithProviders(<SourceJudge address={ADDRESS} />, { api: makeFakeApi(ON) });
    const button = await screen.findByRole('button', { name: 'Is this worth it?' });
    expect(ask).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
    await userEvent.click(button);
    expect(ask).toHaveBeenCalledWith(ADDRESS, false);
    expect(await screen.findByText('Read 10 items · waiting for the worker’s next run')).toBeInTheDocument();
  });

  it('shows the verdict, its reasons, the items it relied on and what was measured; Ask again asks again', async () => {
    vi.spyOn(sourceJudgeApi, 'get').mockResolvedValue({ judgement: judgement() });
    const ask = vi.spyOn(sourceJudgeApi, 'ask').mockResolvedValue({ judgement: judgement() });
    renderWithProviders(<SourceJudge address={ADDRESS} />, { api: makeFakeApi(ON) });
    await userEvent.click(await screen.findByRole('button', { name: 'Is this worth it?' }));
    const box = await screen.findByRole('group', { name: "The worker's judgement" });
    expect(box).toHaveTextContent('Worth following · fits what you read · original: high · full text · 2 a week');
    expect(box).toHaveTextContent('Started 2 of your stories.');
    expect(within(within(box).getByRole('list', { name: 'Items it relied on' })).getByRole('link', { name: 'Widget 5 is out' }))
      .toHaveAttribute('href', 'https://judged.example/blog/widget-5');
    expect(within(box).queryByText(/Linked by your sources/)).not.toBeInTheDocument();
    await userEvent.click(within(box).getByRole('button', { name: 'What INSIGHT measured' }));
    expect(within(box).getByText(/Linked by your sources: 3 sources/)).toBeInTheDocument();
    await userEvent.click(within(box).getByRole('button', { name: 'Ask again' }));
    expect(ask).toHaveBeenLastCalledWith(ADDRESS, true);
  });

  it('says nothing while Mark X is off', async () => {
    renderWithProviders(<SourceJudge address={ADDRESS} />, { api: makeFakeApi({ getMarkxOn: vi.fn().mockRejectedValue(new Error('404')) }) });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole('button', { name: 'Is this worth it?' })).not.toBeInTheDocument();
  });
});

describe('where it is asked', () => {
  it('in the Add source dialog once the finder found a feed, asking about the feed and adding nothing', async () => {
    const ask = vi.spyOn(sourceJudgeApi, 'ask').mockResolvedValue({ judgement: judgement({ status: 'reading', verdict: null }) });
    vi.spyOn(sourceJudgeApi, 'get').mockResolvedValue({ judgement: judgement({ status: 'reading', verdict: null }) });
    const api = {
      ...ON,
      findFeed: vi.fn().mockResolvedValue({ success: true, status: 'found', feeds: [{ url: 'https://judged.example/feed.xml', title: 'Judged' }] }),
    };
    const onAdd = vi.fn();
    renderWithProviders(<AddSourceModal onClose={vi.fn()} onAdd={onAdd} />, { api: makeFakeApi(api) });
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).queryByRole('button', { name: 'Is this worth it?' })).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText('Feed URL or handle'), 'judged.example');
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Is this worth it?' }));
    expect(ask).toHaveBeenCalledWith('https://judged.example/feed.xml', false);
    expect(await within(dialog).findByText('Reading its newest items…')).toBeInTheDocument();
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('on Discover’s "The main source is missing" rows', async () => {
    const row: MainSourceRow = {
      key: 'main:judged.example/blog/', kind: 'missing',
      channel: { key: 'judged.example/blog/', kind: 'site', platform: 'site', url: ADDRESS, prefix: '/blog/' },
      actor: { id: 'e1', name: 'Judged' }, source: null, events: [], latest: null,
      test: { label: 'feed', holds: 1, of: 1, pages: [], preview: null, at: '2100-04-01T13:00:00Z' },
    } as unknown as MainSourceRow;
    const ask = vi.spyOn(sourceJudgeApi, 'ask').mockResolvedValue({ judgement: judgement() });
    renderWithProviders(<MainSourceMissing onFollow={vi.fn()} />, {
      api: makeFakeApi({ ...ON, getMainSourceMissing: vi.fn().mockResolvedValue({ success: true, rows: [row], total: 1, checked: 1, events: 0, within_days: 30 }) }),
    });
    await userEvent.click(await screen.findByRole('button', { name: 'Is this worth it?' }));
    expect(ask).toHaveBeenCalledWith(ADDRESS, false);
  });
});
