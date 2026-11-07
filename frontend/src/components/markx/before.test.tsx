// 0131 (Stalker's first edges): the Mark X post panel's Before list, its uncertain marks and their ✓ / ✗, and the
// Worker tab's relate queue. Synthetic data only.
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXPanel from './MarkXPanel';
import { MarkXWorker } from './MarkXOverview';
import { markxGraphApi } from '../../services/api';
import type { MarkxOverview, MarkxPostPanel } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const old = '2026-06-01T10:00:00+00:00';
const older = '2026-03-01T10:00:00+00:00';
const PANEL: MarkxPostPanel = {
  post_id: 'p1', read: true, reading: null, entities: [], stories: [], connections: [],
  before: [
    { post_id: 'o1', relation: 'builds_on', rule: 'author_link_other', p: 1, reason: 'As I wrote back then, it works.',
      uncertain: false, at: older, title: 'The method, explained', source: 'Example Blog', label: null },
    { post_id: 'o2', relation: 'follows_up', rule: null, p: 0.6667, reason: 'The newer post reports the rollout.',
      uncertain: true, at: old, title: 'Widget 4.1 preview', source: 'Example Channel', label: null },
  ],
  before_more: 3,
};

describe('the Before list (0131)', () => {
  it('shows the older posts with their relation, reason and what made each, the rest counted', async () => {
    renderWithProviders(<MarkXPanel postId="p1" />, { api: makeFakeApi({ getMarkxPost: vi.fn().mockResolvedValue(PANEL) }) });
    await userEvent.click(screen.getByText('Mark X'));
    const list = await screen.findByRole('region', { name: 'Before' });
    const [first, second] = within(list).getAllByRole('listitem');
    expect(first.textContent).toMatch(/^builds on The method, explained · Example Blog · .* · the author links it/);
    expect(first).toHaveTextContent('As I wrote back then, it works.');
    expect(within(first).queryByText('uncertain')).not.toBeInTheDocument();
    expect(within(first).queryByRole('group', { name: 'Is this edge right?' })).not.toBeInTheDocument();
    expect(within(first).getByRole('link', { name: 'The method, explained' })).toHaveAttribute('href', '/posts/o1');
    expect(second).toHaveTextContent('Haiku: follows up 0.67');
    expect(within(second).getByText('uncertain')).toBeInTheDocument();
    expect(within(list).getByText('+3 more')).toBeInTheDocument();
  });

  it('labels an uncertain edge right or wrong, and undoes it', async () => {
    const labelEdge = vi.spyOn(markxGraphApi, 'labelEdge')
      .mockResolvedValueOnce({ id: 'l1', answer: 'wrong', label: 'wrong', relation: 'follows_up' })
      .mockResolvedValueOnce({ id: 'l2', answer: 'undo', label: null, relation: 'follows_up' });
    renderWithProviders(<MarkXPanel postId="p1" />, { api: makeFakeApi({ getMarkxPost: vi.fn().mockResolvedValue(PANEL) }) });
    await userEvent.click(screen.getByText('Mark X'));
    const group = await screen.findByRole('group', { name: 'Is this edge right?' });
    await userEvent.click(within(group).getByRole('button', { name: 'edge wrong' }));
    expect(labelEdge).toHaveBeenCalledWith('p1', 'o2', 'wrong');
    expect(await within(group).findByText('you said wrong')).toBeInTheDocument();
    await userEvent.click(within(group).getByRole('button', { name: 'undo' }));
    expect(labelEdge).toHaveBeenLastCalledWith('p1', 'o2', 'undo');
    await waitFor(() => expect(within(group).getByRole('button', { name: 'edge right' })).toBeInTheDocument());
    labelEdge.mockRestore();
  });

  it('shows nothing when the post connects to no older post', async () => {
    renderWithProviders(<MarkXPanel postId="p1" />, {
      api: makeFakeApi({ getMarkxPost: vi.fn().mockResolvedValue({ ...PANEL, before: [], before_more: 0 }) }),
    });
    await userEvent.click(screen.getByText('Mark X'));
    await screen.findByRole('region', { name: 'Entities' });
    expect(screen.queryByRole('region', { name: 'Before' })).not.toBeInTheDocument();
  });
});

describe('the Worker tab (0131)', () => {
  it("shows relate's queue", async () => {
    const overview: MarkxOverview = {
      worker: { queue: { relate: { open: 100, leased: 20, answered: 7 } }, days: [],
        tokens: { calls: 0, tokens_in: 0, tokens_out: 0, paid_usd: 0, api_usd: 0 }, failed: [], invalid: [], workers: [],
        last_run: null, jobs: {} as MarkxOverview['worker']['jobs'] },
      briefing: { day: null, briefings: [] }, entities: { today: [], week: [] },
      reading_window: { days: 30, default: 30 },
    };
    renderWithProviders(<MarkXWorker />, {
      api: makeFakeApi({ getMarkxOverview: vi.fn(async () => overview), setMarkxReadingWindow: vi.fn(), runMarkxDecisions: vi.fn() }),
    });
    const queue = await screen.findByRole('region', { name: 'Queue' });
    const row = within(queue).getByText('relate').closest('tr') as HTMLElement;
    expect(row.textContent).toMatch(/relate.*100.*20/);
  });
});
