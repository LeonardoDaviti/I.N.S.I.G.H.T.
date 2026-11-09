// 0145 (tracks as topics, Mark X): the track's topic view (sections by sub-topic, Discover with its rank, joined by
// INSIGHT, ✓ / ✗), a folder that is no topic yet, the sheet (describe, sub-topics), the sources it found, and the lines
// in words. Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import TrackTopic from './TrackTopic';
import TrackSourceLines from './TrackSourceLines';
import { footerLine, foundByLine, joinLine, precisionLine, rankWords, suggestionLine } from './trackWords';
import { tracksApi, type TrackItem, type TrackPage } from '../../services/tracks';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const item = (over: Partial<TrackItem> = {}): TrackItem => ({
  post_id: 'p1', title: 'A modular wall storage system', url: null, at: '2026-11-08T10:00:00+00:00', source: 'Example Channel',
  source_id: 's1', confidence: 0.92, subtopic: 'wall storage', why: 'Print the rails and hooks: cheap, sturdy, expandable.',
  origin: 'active', place: 'track', label: null, rank: 0.92, calibrated: false, ...over,
});

const CAL = {
  labels: 4, right: 3, precision: 0.75, lower: 0.3, bands: [], join_edge: null,
  bar: { precision: 0.9, lower: 0.85, labels: 20 },
};

const PAGE: TrackPage = {
  track: { id: 'f1', name: 'Prints', kind: 'track', topic: true, description: 'Things worth 3D printing', excludes: 'printer reviews',
    sources: [{ id: 's1', name: 'Example Channel' }], version: 1 },
  sections: [
    { id: 'st1', name: 'Wall storage', definition: 'rails, hooks, shelves', locked: false, made_by: 'insight', keys: ['wall storage', 'shelves'],
      count: 2, items: [item(), item({ post_id: 'p2', title: 'Printed shelf brackets', origin: 'passive', place: 'joined', source: 'Example Blog' })] },
  ],
  discover: [item({ post_id: 'p3', title: 'A desk cable tray', origin: 'passive', place: 'discover', confidence: 0.7, rank: 0.7 })],
  counts: { track: 1, joined: 1, discover: 1, out: 5, waiting: 2, judged: 8 },
  calibration: CAL,
  suggestions: [{ track: 'f1', track_name: 'Prints', source_id: 's9', source: 'Example Blog', n: 3 }],
  examples: { in: [{ post_id: 'p1', title: 'A modular wall storage system' }], out: [{ post_id: 'p9', title: 'A filament sale' }] },
  subtopics: [{ id: 'st1', name: 'Wall storage', definition: 'rails, hooks, shelves', keys: ['wall storage', 'shelves'], locked: false,
    made_by: 'insight', created_at: null, count: 2 },
  { id: 'st2', name: 'Desk', definition: null, keys: ['desk'], locked: true, made_by: 'owner', created_at: null, count: 0 }],
  footer: { cost_usd: 0.1234, cost_per_day: 0.01, items_per_day: 1.29, tasks: 40 },
  prefilter: { threshold: 0.55, ready: true, pos: 1, neg: 1, description: true, last: null, totals: null, history: { done: null, at: null } },
};

afterEach(() => vi.restoreAllMocks());

describe('the lines in words', () => {
  it('says the precision, the bar, the rank, a suggestion and the footer', () => {
    expect(precisionLine(null)).toBe('no Discover match labelled yet');
    expect(precisionLine(CAL)).toBe('your labels: 3 of 4 right (75%)');
    expect(joinLine(CAL)).toBe('joins by itself at 90% (lower bound 85%) with 20+ labels: not yet, matches wait in Discover');
    expect(joinLine({ ...CAL, join_edge: 0.8 })).toBe('joins by itself at 90% (lower bound 85%) with 20+ labels: on, from confidence 0.8');
    expect(rankWords(item({ confidence: 0.7 }))).toBe('confidence 70%');
    expect(rankWords(item({ rank: 0.83, calibrated: true }))).toBe('~83% precise at this confidence');
    expect(suggestionLine(PAGE.suggestions[0])).toBe('Example Blog: 3 of your Prints in 30 days — make it active?');
    expect(footerLine(PAGE.footer!, PAGE.counts)).toBe('$0.12 so far · $0.01 a day · 1.29 items a day · 40 questions · 5 posts judged out (kept)');
  });
});

describe('found by (0147)', () => {
  it('names the finders that put a passive post up for judging, on hover', async () => {
    expect(foundByLine({ found_by: ['probe', 'entity', 'domain'] })).toBe('found by: example post, entity, domain');
    expect(foundByLine({ found_by: [] })).toBeNull();
    expect(foundByLine({})).toBeNull();
    const page = { ...PAGE, discover: [{ ...PAGE.discover[0], found_by: ['word', 'source'] }] };
    vi.spyOn(tracksApi, 'page').mockResolvedValue(page);
    renderWithProviders(<TrackTopic folderId="f1" />, { api: makeFakeApi({}) });
    const discover = await screen.findByRole('region', { name: 'Discover' });
    expect(within(discover).getByText(/confidence 70%/)).toHaveAttribute('title', 'found by: words, source');
    const storage = screen.getByRole('region', { name: 'Wall storage' });
    expect(within(storage).getAllByText(/Example Channel/)[0]).not.toHaveAttribute('title');
  });
});

describe('a track as a topic (0145)', () => {
  it('reads as sections by sub-topic, then Discover, with joined by INSIGHT and the bar', async () => {
    vi.spyOn(tracksApi, 'page').mockResolvedValue(PAGE);
    renderWithProviders(<TrackTopic folderId="f1" />, { api: makeFakeApi({}) });
    const storage = await screen.findByRole('region', { name: 'Wall storage' });
    expect(storage).toHaveTextContent('Wall storage · 2');
    expect(storage).toHaveTextContent('Print the rails and hooks: cheap, sturdy, expandable.');
    expect(within(storage).getByRole('link', { name: 'A modular wall storage system' })).toHaveAttribute('href', '/posts/p1');
    expect(storage).toHaveTextContent('joined by INSIGHT');
    const discover = screen.getByRole('region', { name: 'Discover' });
    expect(discover).toHaveTextContent('A desk cable tray');
    expect(discover).toHaveTextContent('confidence 70%');
    expect(screen.getByText(/your labels: 3 of 4 right/)).toHaveTextContent('2 posts waiting for Haiku');
    expect(screen.getByText(/Example Blog: 3 of your Prints/)).toBeInTheDocument();
    expect(screen.getByText(/\$0.12 so far/)).toBeInTheDocument();
  });

  it('takes ✓ and ✗ and undoes them', async () => {
    vi.spyOn(tracksApi, 'page').mockResolvedValue(PAGE);
    const label = vi.spyOn(tracksApi, 'label')
      .mockResolvedValueOnce({ id: 'l1', label: 'in' })
      .mockResolvedValueOnce({ id: 'l2', label: null });
    renderWithProviders(<TrackTopic folderId="f1" />, { api: makeFakeApi({}) });
    const discover = await screen.findByRole('region', { name: 'Discover' });
    const group = within(discover).getByRole('group', { name: 'Does it belong here?' });
    await userEvent.click(within(group).getByRole('button', { name: 'Belongs in this track' }));
    expect(label).toHaveBeenCalledWith('f1', 'p3', 'in');
    expect(await within(group).findByText('✓ yours')).toBeInTheDocument();
    await userEvent.click(within(group).getByRole('button', { name: 'undo' }));
    expect(label).toHaveBeenLastCalledWith('f1', 'p3', 'undo');
  });

  it('makes a suggested source active', async () => {
    vi.spyOn(tracksApi, 'page').mockResolvedValue(PAGE);
    const activate = vi.spyOn(tracksApi, 'activate').mockResolvedValue({ added: true });
    renderWithProviders(<TrackTopic folderId="f1" />, { api: makeFakeApi({}) });
    await userEvent.click(await screen.findByRole('button', { name: 'make it active' }));
    expect(activate).toHaveBeenCalledWith('f1', 's9');
  });

  it('a folder that is no topic offers to describe it, and the sheet saves the words', async () => {
    const folder: TrackPage = { ...PAGE, track: { ...PAGE.track, topic: false, description: null, excludes: null },
      sections: [], discover: [], counts: {}, calibration: null, suggestions: [], examples: { in: [], out: [] }, subtopics: [],
      footer: null, prefilter: null };
    vi.spyOn(tracksApi, 'page').mockResolvedValue(folder);
    const describe_ = vi.spyOn(tracksApi, 'describe').mockResolvedValue(PAGE);
    renderWithProviders(<TrackTopic folderId="f1" />, { api: makeFakeApi({}) });
    expect(await screen.findByText('This track is a folder of sources')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Describe this track' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Example Channel')).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText('What belongs'), 'Cheap local AI setups');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(describe_).toHaveBeenCalledWith('f1', { description: 'Cheap local AI setups', excludes: '' }));
  });

  it('the sheet lists the examples and edits the sub-topics', async () => {
    vi.spyOn(tracksApi, 'page').mockResolvedValue(PAGE);
    const edit = vi.spyOn(tracksApi, 'editSubtopics').mockResolvedValue([]);
    renderWithProviders(<TrackTopic folderId="f1" />, { api: makeFakeApi({}) });
    await userEvent.click(await screen.findByRole('button', { name: 'edit the topic' }));
    const dialog = await screen.findByRole('dialog');
    const examples = within(dialog).getByRole('region', { name: 'Examples so far' });
    expect(examples).toHaveTextContent('✓ A modular wall storage system');
    expect(examples).toHaveTextContent('✗ A filament sale');
    const subs = within(dialog).getByRole('region', { name: 'Sub-topics' });
    expect(subs).toHaveTextContent('Desk0 · locked');
    const first = subs.querySelector('[data-subtopic="st1"]') as HTMLElement;
    await userEvent.click(within(first).getByRole('button', { name: 'take in Desk' }));
    expect(edit).toHaveBeenCalledWith('f1', { action: 'merge', id: 'st1', ids: ['st2'] });
    await userEvent.click(within(first).getByRole('button', { name: 'lock' }));
    expect(edit).toHaveBeenLastCalledWith('f1', { action: 'lock', id: 'st1' });
    await userEvent.click(within(first).getByRole('button', { name: 'split' }));
    await userEvent.click(within(first).getByRole('checkbox', { name: 'shelves' }));
    const name = within(first).getByLabelText("The new sub-topic's name");
    await userEvent.clear(name);
    await userEvent.type(name, 'Shelves');
    await userEvent.click(within(first).getByRole('button', { name: 'Split' }));
    expect(edit).toHaveBeenLastCalledWith('f1', { action: 'split', id: 'st1', name: 'Shelves', keys: ['shelves'] });
  });
});

describe("Discover's line (0145)", () => {
  it('names the sources the tracks found, while Mark X is on', async () => {
    vi.spyOn(tracksApi, 'suggestions').mockResolvedValue(PAGE.suggestions);
    renderWithProviders(<TrackSourceLines />, { api: makeFakeApi({ getMarkxOn: vi.fn().mockResolvedValue({ on: true }) }) });
    const link = await screen.findByRole('link', { name: /Example Blog: 3 of your Prints/ });
    expect(link).toHaveAttribute('href', '/read/folder/f1?view=topic');
  });

  it('says nothing while Mark X is off', async () => {
    const got = vi.spyOn(tracksApi, 'suggestions');
    renderWithProviders(<TrackSourceLines />, { api: makeFakeApi({ getMarkxOn: vi.fn().mockRejectedValue(new Error('404')) }) });
    await new Promise((r) => setTimeout(r, 20));
    expect(got).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: 'Sources your tracks found' })).toBeNull();
  });
});
