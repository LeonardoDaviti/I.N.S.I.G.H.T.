// 0148 (the track scout, Mark X): the Topic view's "Sources for this track" (suggested rows in words, Follow as active
// / passive, Not this one, what could not be read and why, "Find sources for this track"), and Discover's rows under the
// track's name. Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import TrackScout from './TrackScout';
import ScoutSourceLines from './ScoutSourceLines';
import { runLine, scoutApi, scoutLine, unreadLine, type ScoutCandidate, type ScoutPage } from '../../services/scout';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const cand = (over: Partial<ScoutCandidate> = {}): ScoutCandidate => ({
  id: 'c1', run_id: 'r1', track: 'f1', finder: 'haiku', platform: 'reddit', address: 'https://www.reddit.com/r/printedparts',
  key: 'reddit.com/r/printedparts', name: 'Printed parts', why: 'Makers sharing useful prints', place: 'suggested', reason: null,
  items: 20, judged: 20, fits: 14, precision: 0.7, per_week: 3, cadence: '3 a week', labels: [], reads_well: true,
  follows_as: 'kind', follow_address: 'r/printedparts', answer: null, source_id: null, ...over,
});

const PAGE: ScoutPage = {
  suggested: [cand(), cand({ id: 'c2', name: 'Example Makers', platform: 'site', fits: 8, judged: 20, precision: 0.4,
    cadence: '2 a month', labels: ['summaries only'], follows_as: 'feed' })],
  reads_badly: [cand({ id: 'c3', name: 'Quiet Blog', platform: 'site', place: 'reads_badly', reads_well: false,
    reason: 'undated: 20 of 20 items have no date' })],
  unreadable: [cand({ id: 'c4', name: 'example.org', platform: 'site', place: 'unreadable', reads_well: false, reason: 'blocked' })],
  judging: [],
  unread: 0,
  followed: [{ source_id: 's1', name: 'Example Channel', as: 'active', since: '2026-11-01T00:00:00Z', judged: 4, fits: 3, precision: 0.75 }],
  runs: [{ id: 'r1', trigger: 'tap', status: 'done', reads: 12, requests: 80, judgements: 200, asked: 'answered',
    finders: {}, started_at: '2026-11-10T10:00:00Z', finished_at: '2026-11-10T11:00:00Z' }],
  floor: 0.3,
  budget: { reads: 40, judgements: 800, requests: 800 },
};

afterEach(() => vi.restoreAllMocks());

describe('the lines in words', () => {
  it('says the fit, the cadence and the health', () => {
    expect(scoutLine(PAGE.suggested[0])).toBe('Printed parts (Reddit): 14 of its last 20 posts fit · 3 a week · reads well');
    expect(scoutLine(PAGE.suggested[1])).toBe('Example Makers (site): 8 of its last 20 posts fit · 2 a month · reads well · summaries only');
    expect(unreadLine(PAGE.reads_badly[0])).toBe("Quiet Blog (site): can't read well: undated: 20 of 20 items have no date");
    expect(unreadLine(PAGE.unreadable[0])).toBe("example.org (site): can't read: blocked");
    expect(runLine({ ...PAGE.runs[0], status: 'waiting', asked: 'open' }, PAGE)).toMatch(/Waiting for Haiku to name more sources/);
    expect(runLine({ ...PAGE.runs[0], status: 'running' }, PAGE)).toBe('Reading candidates · 12 read so far');
  });
});

describe('Sources for this track (0148)', () => {
  it('lists the suggestions ranked, the sources followed and what could not be read', async () => {
    vi.spyOn(scoutApi, 'page').mockResolvedValue(PAGE);
    renderWithProviders(<TrackScout folderId="f1" />, { api: makeFakeApi({}) });
    const list = await screen.findByRole('list', { name: 'Suggested sources' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('Printed parts (Reddit): 14 of its last 20 posts fit');
    expect(rows[0]).toHaveTextContent('Makers sharing useful prints');
    expect(rows[1]).toHaveTextContent('Example Makers (site)');
    expect(screen.getByRole('list', { name: 'Followed from the scout' })).toHaveTextContent('Example Channel (active) · 3 of 4 posts fit');
    expect(screen.getByText('2 sources could not be read well')).toBeInTheDocument();
    expect(screen.getByText(/Quiet Blog \(site\): can't read well: undated/)).toBeInTheDocument();
  });

  it('follows as active or passive', async () => {
    vi.spyOn(scoutApi, 'page').mockResolvedValue(PAGE);
    const follow = vi.spyOn(scoutApi, 'follow').mockResolvedValue({ source_id: 's9', as: 'active' });
    renderWithProviders(<TrackScout folderId="f1" />, { api: makeFakeApi({}) });
    const first = await screen.findByRole('group', { name: 'Follow Printed parts?' });
    await userEvent.click(within(first).getByRole('button', { name: 'Follow as active' }));
    expect(follow).toHaveBeenCalledWith('c1', 'active');
    expect(await within(first).findByText('Followed as active')).toBeInTheDocument();
    const second = screen.getByRole('group', { name: 'Follow Example Makers?' });
    await userEvent.click(within(second).getByRole('button', { name: 'Follow as passive' }));
    expect(follow).toHaveBeenLastCalledWith('c2', 'passive');
  });

  it('says not this one', async () => {
    vi.spyOn(scoutApi, 'page').mockResolvedValue(PAGE);
    const not = vi.spyOn(scoutApi, 'notThis').mockResolvedValue({ answer: 'not' });
    renderWithProviders(<TrackScout folderId="f1" />, { api: makeFakeApi({}) });
    const first = await screen.findByRole('group', { name: 'Follow Printed parts?' });
    await userEvent.click(within(first).getByRole('button', { name: 'Not this one' }));
    expect(not).toHaveBeenCalledWith('c1');
  });

  it('starts a scout on the tap', async () => {
    vi.spyOn(scoutApi, 'page').mockResolvedValue({ ...PAGE, suggested: [], runs: [] });
    const start = vi.spyOn(scoutApi, 'start').mockResolvedValue({ id: 'r2', candidates: { match: 3, shape: 5 } });
    renderWithProviders(<TrackScout folderId="f1" />, { api: makeFakeApi({}) });
    await userEvent.click(await screen.findByRole('button', { name: 'Find sources for this track' }));
    expect(start).toHaveBeenCalledWith('f1');
  });
});

describe("Discover's rows (0148)", () => {
  it('lists each track’s suggestions under its name while Mark X is on', async () => {
    vi.spyOn(scoutApi, 'suggestions').mockResolvedValue([cand({ track_name: 'Prints' })]);
    renderWithProviders(<ScoutSourceLines />, { api: makeFakeApi({ getMarkxOn: vi.fn().mockResolvedValue({ on: true }) }) });
    const region = await screen.findByRole('region', { name: 'Sources for Prints' });
    expect(within(region).getByRole('link', { name: 'Prints' })).toHaveAttribute('href', '/read/folder/f1?view=topic');
    expect(region).toHaveTextContent('Printed parts (Reddit): 14 of its last 20 posts fit');
    expect(within(region).getByRole('button', { name: 'Follow as active' })).toBeInTheDocument();
  });

  it('says nothing while Mark X is off', async () => {
    const got = vi.spyOn(scoutApi, 'suggestions');
    renderWithProviders(<ScoutSourceLines />, { api: makeFakeApi({ getMarkxOn: vi.fn().mockRejectedValue(new Error('404')) }) });
    await new Promise((r) => setTimeout(r, 20));
    expect(got).not.toHaveBeenCalled();
  });
});
