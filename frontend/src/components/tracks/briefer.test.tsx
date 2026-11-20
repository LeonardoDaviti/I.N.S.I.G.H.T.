// 0245 (frontend v10.28): the general track briefer's views over three invented tracks of three different kinds
// (garden tools, board games, bread baking): the quick look, the weekly issue, the tables, the schema editor and the
// rail's count, and none of it while the backend's switch is off. Synthetic data only; no word of these tracks is in
// the code.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import TrackTopic from './TrackTopic';
import TrackSheet from './TrackSheet';
import ReaderNavRail from '../reader/ReaderNavRail';
import {
  chipParams, citeMarks, dayWord, filterChips, mondayOf, nextSort, railThings, sinceLine, sortThings, toggleChip,
  weekLine,
} from './briefWords';
import {
  briefApi, tracksApi, type QuickLook, type Thing, type ThingFieldDef, type ThingKindDef, type ThingSection,
  type TrackPage, type TrackSchemaView, type WeekIssue,
} from '../../services/tracks';
import { trackCountsApi } from '../../hooks/useTrackCounts';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const NOW = new Date('2026-11-20T12:00:00Z');
const LOOKED = '2026-11-17T12:00:00Z';   // a Tuesday

// ---- three invented tracks, each its schema --------------------------------------------------------------------

const PRACTICE: ThingKindDef = { kind: 'practice_or_claim', about: 'a method', fields: [
  { name: 'what', type: 'text', key: true }, { name: 'result', type: 'text' }, { name: 'evidence', type: 'text' }] };

const GARDEN: ThingKindDef = { kind: 'tool', about: 'one garden tool', fields: [
  { name: 'name', type: 'text', key: true }, { name: 'price', type: 'money' }, { name: 'weight', type: 'number', unit: 'kg' },
  { name: 'power', type: 'enum', values: ['hand', 'battery', 'mains'] }, { name: 'review', type: 'link' }] };
const GAMES: ThingKindDef = { kind: 'game', about: 'one board game', fields: [
  { name: 'title', type: 'text', key: true }, { name: 'players', type: 'number', unit: 'players' },
  { name: 'price', type: 'money' }, { name: 'rules', type: 'link' }] };
const BREAD: ThingKindDef = { kind: 'loaf', about: 'one bread recipe', fields: [
  { name: 'bread', type: 'text', key: true }, { name: 'hydration', type: 'number', unit: '%' },
  { name: 'flour', type: 'enum', values: ['wheat', 'rye', 'spelt'] }, { name: 'minutes', type: 'number', unit: 'minutes' }] };

const post = (id: string, title: string, url: string | null = `https://example.org/${id}`, at = '2026-11-19T09:00:00Z') =>
  ({ id, title, url, at });

const num = (n: number, extra: Record<string, unknown> = {}) => ({ number: n, range_to: null, ...extra });

function thing(id: string, kind: ThingKindDef, values: Record<string, [unknown, string]>, posts = [post(`p-${id}`, `About ${id}`)]): Thing {
  return {
    id, kind: kind.kind, posts, first_at: posts[0].at, last_at: posts[0].at, found_at: '2026-11-19T10:00:00Z', new: true,
    fields: Object.fromEntries(Object.entries(values).map(([k, [value, shown]]) => [k, { value: value as never, shown, quote: shown, post: posts[0].id }])),
  };
}

const TOOLS = [
  thing('t1', GARDEN, { name: ['Hori knife', 'Hori knife'], price: [num(30, { currency: 'USD' }), '30 USD'],
    weight: [num(0.3, { unit: 'kg' }), '0.3 kg'], power: ['hand', 'hand'], review: ['https://reviews.example.com/hori', 'https://reviews.example.com/hori'] }),
  thing('t2', GARDEN, { name: ['Cordless hedge trimmer', 'Cordless hedge trimmer'], price: [num(150, { currency: 'USD' }), '150 USD'],
    weight: [num(2.4, { unit: 'kg' }), '2.4 kg'], power: ['battery', 'battery'] }),
  thing('t3', GARDEN, { name: ['Wheel hoe', 'Wheel hoe'], price: [num(90, { currency: 'EUR' }), '90 EUR'], power: ['hand', 'hand'] }),
];
const GAMES_ROWS = [
  thing('g1', GAMES, { title: ['Harbour Lights', 'Harbour Lights'], players: [num(2, { range_to: 4, unit: 'players' }), '2-4 players'],
    price: [num(45, { currency: 'GBP' }), '45 GBP'] }),
  thing('g2', GAMES, { title: ['Seed Bank', 'Seed Bank'], players: [num(1, { range_to: 5, unit: 'players' }), '1-5 players'],
    rules: ['https://games.example.net/seed-bank.pdf', 'https://games.example.net/seed-bank.pdf'] }),
];
const LOAVES = [
  thing('l1', BREAD, { bread: ['Dark rye', 'Dark rye'], hydration: [num(85, { unit: '%' }), '85 %'], flour: ['rye', 'rye'],
    minutes: [num(300, { unit: 'minutes' }), '300 minutes'] }),
];

function section(kind: ThingKindDef, things: Thing[], header = `${kind.kind[0].toUpperCase()}${kind.kind.slice(1)} (${things.length})`): ThingSection {
  return { kind: kind.kind, header, about: kind.about ?? '', count: things.length, new: things.length, fields: kind.fields, things };
}

const schemaView = (kind: ThingKindDef, on = true): TrackSchemaView => ({
  on, version: 1, by: 'haiku', track_version: 1, stale: false, at: '2026-11-10T00:00:00Z', schema: { kinds: [kind, PRACTICE] },
});

const PAGE: TrackPage = {
  track: { id: 'garden', name: 'My invented garden track', kind: 'folder', topic: true, description: 'Garden tools worth buying', excludes: null,
    sources: [], version: 1 },
  sections: [{ id: 's1', name: 'Tools', definition: null, locked: false, made_by: 'insight', keys: [], count: 1, state: 'active',
    items: [{ post_id: 'p-t1', title: 'A post about a knife', url: null, at: '2026-11-19T09:00:00Z', source: 'An Example Source',
      source_id: 'src', confidence: 0.9, subtopic: null, why: null, origin: 'active', place: 'track', label: null, rank: 0.9,
      calibrated: false, joined_at: '2026-11-19T09:00:00Z' }] }],
  discover: [], counts: { track: 1 }, calibration: null, suggestions: [], examples: { in: [], out: [] }, subtopics: [],
  footer: null, prefilter: null,
};

const LOOK: QuickLook = {
  on: true, track: { id: 'garden', name: 'x' }, since: LOOKED,
  sections: [section(GARDEN, TOOLS.slice(0, 2), 'Tool (2)')],
  points: [{ text: 'Battery trimmers got lighter.', cites: [{ thing: 't2', n: 2 }] },
    { text: 'A hand tool under 50 USD stands out.', cites: [{ thing: 't1', n: 1 }, { thing: 'gone', n: null }] }],
  as_of: '2026-11-19T11:00:00Z', stale: false,
  also: [post('p-chat', 'What do you all use for weeding?', null)],
  counts: { things: 2, also: 1 }, nothing_new: false, last_issue: '2026-11-09', weeks: ['2026-11-16', '2026-11-09', '2026-11-02'],
};

const ISSUE = (week: string, over: Partial<WeekIssue> = {}): WeekIssue => ({
  on: true, track: { id: 'garden', name: 'x' }, week: { start: week, end: week === '2026-11-09' ? '2026-11-15' : '2026-11-08', closed: true },
  points: [{ text: 'Three hand tools this week.', cites: [{ thing: 't3', n: 3 }] }], points_at: '2026-11-16T06:00:00Z',
  sections: [section(GARDEN, TOOLS, 'Tool (3)')], also: [post('p-also', 'A garden diary')],
  counts: { things: 3, new: 3, posts: 3, also: 1 }, built_at: '2026-11-16T06:00:00Z', updated: week === '2026-11-09', ...over,
});

function mockOn(look: QuickLook = LOOK, schema: TrackSchemaView = schemaView(GARDEN)) {
  vi.spyOn(tracksApi, 'page').mockResolvedValue(PAGE);
  vi.spyOn(tracksApi, 'look').mockResolvedValue({ before: { track: LOOKED, subtopics: {} }, now: { track: NOW.toISOString(), subtopics: {} } });
  vi.spyOn(briefApi, 'schema').mockResolvedValue(schema);
  return vi.spyOn(briefApi, 'quickLook').mockResolvedValue(look);
}

afterEach(() => vi.restoreAllMocks());

// ---- the words ----------------------------------------------------------------------------------------------------

describe('the briefer words', () => {
  it('says days, weeks and the rail count', () => {
    expect(dayWord(LOOKED, NOW)).toBe('Tue');
    expect(dayWord('2026-11-02T12:00:00Z', NOW)).toBe('2 Nov');
    expect(dayWord('2025-11-02T12:00:00Z', NOW)).toBe('2 Nov 2025');
    expect(sinceLine(LOOKED, 6, NOW)).toBe('since Tue · 6 new');
    expect(weekLine('2026-11-16', '2026-11-22')).toBe('week of 16-22 Nov');
    expect(weekLine('2026-09-28', '2026-10-04')).toBe('week of 28 Sep-4 Oct');
    expect(mondayOf(NOW)).toBe('2026-11-16T00:00:00.000Z');
    expect(railThings(0)).toBeNull();
    expect(railThings(undefined)).toBeNull();
    expect(railThings(1)).toBe('1 new thing');
    expect(railThings(3)).toBe('3 new things');
    expect(railThings(12)).toBe('9+ new things');
  });

  it('builds filter chips from each type, for three kinds of track', () => {
    const garden = filterChips(GARDEN.fields, TOOLS);
    // money: only its most common currency (two USD, one EUR); number: a round middle; enum: the values held; link: has
    expect(garden.map((c) => c.label)).toEqual(['Price ≤ 30 USD', 'Price ≥ 30 USD', 'Weight ≤ 0.3 kg', 'Weight ≥ 0.3 kg',
      'hand', 'battery', 'has review']);
    expect(garden[0].params).toEqual({ 'price.currency': 'USD', 'price.max': '30' });
    const games = filterChips(GAMES.fields, GAMES_ROWS);
    expect(games.map((c) => c.label)).toEqual(['Players ≤ 1 players', 'Players ≥ 1 players', 'has rules']);
    expect(filterChips(BREAD.fields, LOAVES).map((c) => c.label)).toEqual(['rye']);
    // enum values add up; a range replaces its other end
    let chosen = toggleChip([], garden[4]);
    chosen = toggleChip(chosen, garden[5]);
    chosen = toggleChip(chosen, garden[0]);
    chosen = toggleChip(chosen, garden[1]);
    expect(chipParams(chosen)).toEqual({ power: 'hand,battery', 'price.currency': 'USD', 'price.min': '30' });
    expect(chipParams(toggleChip(chosen, garden[4]))).toEqual({ power: 'battery', 'price.currency': 'USD', 'price.min': '30' });
  });

  it('sorts by a typed field and numbers the cites', () => {
    expect(sortThings(TOOLS, { field: 'price', dir: 'desc' }).map((t) => t.id)).toEqual(['t2', 't3', 't1']);
    expect(sortThings(TOOLS, { field: 'weight', dir: 'asc' }).map((t) => t.id)).toEqual(['t1', 't2', 't3']);
    expect(sortThings(TOOLS, null)).toBe(TOOLS);
    expect(nextSort(null, 'price')).toEqual({ field: 'price', dir: 'asc' });
    expect(nextSort({ field: 'price', dir: 'asc' }, 'price')).toEqual({ field: 'price', dir: 'desc' });
    expect(nextSort({ field: 'price', dir: 'desc' }, 'price')).toBeNull();
    const marks = citeMarks(LOOK.points, LOOK.sections);
    expect([...marks.entries()].map(([id, m]) => [id, m.n])).toEqual([['t2', 2], ['t1', 1]]);
  });
});

// ---- the track page -----------------------------------------------------------------------------------------------

describe('the quick look on a track page', () => {
  it('shows nothing of the briefer while the switch is off', async () => {
    vi.spyOn(tracksApi, 'page').mockResolvedValue(PAGE);
    vi.spyOn(tracksApi, 'look').mockResolvedValue({ before: { track: LOOKED, subtopics: {} }, now: { track: LOOKED, subtopics: {} } });
    const schema = vi.spyOn(briefApi, 'schema').mockResolvedValue({ ...schemaView(GARDEN), on: false, schema: null });
    const quick = vi.spyOn(briefApi, 'quickLook');
    renderWithProviders(<TrackTopic folderId="garden" />, { api: makeFakeApi({}) });
    expect(await screen.findByRole('region', { name: 'Tools' })).toBeInTheDocument();
    await waitFor(() => expect(schema).toHaveBeenCalled());
    expect(screen.queryByRole('tablist')).toBeNull();
    expect(screen.queryByRole('region', { name: 'Since you looked' })).toBeNull();
    expect(quick).not.toHaveBeenCalled();
  });

  it('shows since when, what changed with quiet cites, the new things by kind, then the posts', async () => {
    const quick = mockOn();
    renderWithProviders(<TrackTopic folderId="garden" />, { api: makeFakeApi({}) });
    const panel = await screen.findByRole('region', { name: 'Since you looked' });
    expect(quick).toHaveBeenCalledWith('garden', LOOKED);              // from the look before this visit
    expect(panel).toHaveTextContent(/since \w{3} · 3 new/);
    const changed = within(panel).getByRole('region', { name: 'What changed' });
    expect(changed).not.toHaveTextContent('(Post');
    const cites = within(changed).getAllByRole('link');
    expect(cites.map((a) => a.textContent)).toEqual(['2', '1']);
    expect(cites[0]).toHaveAttribute('href', '/posts/p-t2');
    expect(cites[0].closest('sup')).not.toBeNull();
    const tools = within(panel).getByRole('region', { name: 'Tool (2)' });
    expect(within(tools).getByText('New: tool (2)')).toBeInTheDocument();
    expect(tools.querySelector('[data-thing="t1"]')).toHaveTextContent('Hori knife · 30 USD · 0.3 kg · hand · reviews.example.com');
    expect(within(tools).getByRole('link', { name: 'Open the post about Hori knife' })).toHaveAttribute('href', '/posts/p-t1');   // in INSIGHT: a bridge's address may not open on the reader's device
    expect(within(panel).getByRole('region', { name: 'Also in the track' })).toHaveTextContent('What do you all use for weeding?');
    // the posts follow, as today
    const order = [...document.querySelectorAll('[aria-label="Since you looked"], [aria-label="Tools"]')].map((e) => e.getAttribute('aria-label'));
    expect(order).toEqual(['Since you looked', 'Tools']);
    // see all › opens the kind's table
    const table = vi.spyOn(briefApi, 'things').mockResolvedValue({ on: true, track: { id: 'garden', name: 'x' }, kind: 'tool',
      kinds: ['tool', 'practice_or_claim'], fields: GARDEN.fields, filters: {}, count: 3, things: TOOLS });
    await userEvent.click(within(tools).getByRole('button', { name: 'see all ›' }));
    await waitFor(() => expect(table).toHaveBeenCalledWith('garden', 'tool'));
    expect(await screen.findByRole('region', { name: 'Tables' })).toBeInTheDocument();
  });

  it('shows a thing\'s own practices inside it and at most five rows a kind (v10.29)', async () => {
    const practice = thing('pr1', PRACTICE, { what: ['Oil the blade monthly', 'Oil the blade monthly'], result: ['No rust after a year', 'No rust after a year'] });
    const many = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map((x) => thing(`m${x}`, GARDEN, { name: [`Tool ${x}`, `Tool ${x}`] }));
    const look: QuickLook = { ...LOOK, points: [], sections: [section(GARDEN, [{ ...TOOLS[0], practices: [practice], sources: 3 }, ...many], 'Tool (8)')] };
    mockOn(look);
    renderWithProviders(<TrackTopic folderId="garden" />, { api: makeFakeApi({}) });
    const panel = await screen.findByRole('region', { name: 'Since you looked' });
    const tools = within(panel).getByRole('region', { name: 'Tool (8)' });
    expect(tools.querySelector('[data-thing-practices="t1"]')).toHaveTextContent('Oil the blade monthly → No rust after a year');
    expect(tools.querySelectorAll('[data-thing]')).toHaveLength(5);
    expect(tools.querySelector('[data-thing="t1"]')).toHaveTextContent('Hori knife · 3 sources');
  });

  it('says nothing new since the look, with the last issue a tap away', async () => {
    mockOn({ ...LOOK, sections: [], points: [], also: [], counts: { things: 0, also: 0 }, nothing_new: true, as_of: null });
    const issue = vi.spyOn(briefApi, 'issue').mockImplementation(async (_id, w) => ISSUE(w));
    renderWithProviders(<TrackTopic folderId="garden" />, { api: makeFakeApi({}) });
    const panel = await screen.findByRole('region', { name: 'Since you looked' });
    expect(panel).toHaveTextContent(/^Nothing new since \w{3}/);
    await userEvent.click(within(panel).getByRole('button', { name: /the issue of 9 Nov/ }));
    await waitFor(() => expect(issue).toHaveBeenCalledWith('garden', '2026-11-09'));
  });

  it('never puts points older than a newer find above the posts: they follow, as of their day', async () => {
    mockOn({ ...LOOK, stale: true });
    renderWithProviders(<TrackTopic folderId="garden" />, { api: makeFakeApi({}) });
    const panel = await screen.findByRole('region', { name: 'Since you looked' });
    expect(within(panel).queryByRole('region', { name: 'What changed' })).toBeNull();
    const late = await screen.findByRole('region', { name: 'What changed' });
    expect(late).toHaveTextContent(/What changed · as of \w{3}/);
    const order = [...document.querySelectorAll('[aria-label="Tools"], [aria-label="What changed"]')].map((e) => e.getAttribute('aria-label'));
    expect(order).toEqual(['Tools', 'What changed']);
  });
});

describe('the weekly issue', () => {
  it('opens the last closed week, moves along the date strip, and shows tables, cards and "updated"', async () => {
    mockOn();
    const issue = vi.spyOn(briefApi, 'issue').mockImplementation(async (_id, w) => ISSUE(w));
    renderWithProviders(<TrackTopic folderId="garden" />, { api: makeFakeApi({}) });
    await screen.findByRole('region', { name: 'Since you looked' });
    await userEvent.click(screen.getByRole('tab', { name: 'issues' }));
    const view = await screen.findByRole('region', { name: 'Weekly issue' });
    await waitFor(() => expect(issue).toHaveBeenCalledWith('garden', '2026-11-09'));
    expect(await within(view).findByText('week of 9-15 Nov')).toBeInTheDocument();
    expect(within(view).getByText('updated')).toBeInTheDocument();
    expect(within(view).getByRole('button', { name: 'Week of 9 Nov' })).toHaveAttribute('aria-pressed', 'true');
    const tools = within(view).getByRole('region', { name: 'Tool (3)' });
    expect(tools.querySelector('[data-things-table="tool"] table')).not.toBeNull();
    expect(tools.querySelectorAll('[data-thing-card]')).toHaveLength(3);    // the phone's cards (under 640px)
    expect(within(tools).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Name', 'Price', 'Weight', 'Power', 'Review', 'Open']);
    expect(within(view).getByRole('region', { name: 'Also in the track' })).toHaveTextContent('A garden diary');
    expect(within(view).getByRole('region', { name: 'What changed' })).toHaveTextContent('Three hand tools this week.');
    await userEvent.click(within(view).getByRole('button', { name: 'Older issue' }));
    await waitFor(() => expect(issue).toHaveBeenCalledWith('garden', '2026-11-02'));
    expect(await within(view).findByText('week of 2-8 Nov')).toBeInTheDocument();
    expect(within(view).queryByText('updated')).toBeNull();
    expect(within(view).getByRole('button', { name: 'Older issue' })).toBeDisabled();
  });
});

describe('the tables', () => {
  it('filters a kind by its chips and sorts by a column, for a board-game track', async () => {
    mockOn({ ...LOOK, sections: [section(GAMES, GAMES_ROWS)], points: [] }, schemaView(GAMES));
    const table = vi.spyOn(briefApi, 'things').mockImplementation(async (_id, kind, filters = {}) => ({
      on: true, track: { id: 'garden', name: 'x' }, kind, kinds: ['game', 'practice_or_claim'], fields: GAMES.fields, filters,
      count: filters.rules ? 1 : 2, things: filters.rules ? [GAMES_ROWS[1]] : GAMES_ROWS,
    }));
    renderWithProviders(<TrackTopic folderId="garden" />, { api: makeFakeApi({}) });
    await screen.findByRole('region', { name: 'Since you looked' });
    await userEvent.click(screen.getByRole('tab', { name: 'tables' }));
    const tables = await screen.findByRole('region', { name: 'Tables' });
    expect(within(within(tables).getByRole('group', { name: 'Kinds' })).getAllByRole('button').map((b) => b.textContent))
      .toEqual(['Game', 'Practices and claims']);
    expect(await within(tables).findByText('2 rows · newest first')).toBeInTheDocument();
    await userEvent.click(within(tables).getByRole('button', { name: 'has rules' }));
    await waitFor(() => expect(table).toHaveBeenCalledWith('garden', 'game', { rules: 'any' }));
    expect(await within(tables).findByText('1 row · newest first')).toBeInTheDocument();
    await userEvent.click(within(tables).getByRole('button', { name: 'has rules' }));
    const head = (await within(tables).findAllByRole('columnheader'))[0];
    await userEvent.click(within(head).getByRole('button', { name: 'Title' }));
    expect(head).toHaveAttribute('aria-sort', 'ascending');
    const rows = tables.querySelectorAll('[data-things-table] tbody tr');
    expect([...rows].map((r) => r.getAttribute('data-thing'))).toEqual(['g1', 'g2']);
    await userEvent.click(within(head).getByRole('button', { name: /Title/ }));
    expect([...tables.querySelectorAll('[data-things-table] tbody tr')].map((r) => r.getAttribute('data-thing'))).toEqual(['g2', 'g1']);
  });
});

describe('the schema editor in the track sheet', () => {
  it('renames, removes and adds a field, then saves the kinds (the practice kind left to code)', async () => {
    vi.spyOn(briefApi, 'schema').mockResolvedValue(schemaView(BREAD));
    const save = vi.spyOn(briefApi, 'saveSchema').mockImplementation(async (_id, kinds) => ({
      ...schemaView(BREAD), version: 2, by: 'owner', schema: { kinds: [...kinds, PRACTICE] } }));
    renderWithProviders(<TrackSheet open onOpenChange={() => undefined} page={{ ...PAGE, track: { ...PAGE.track, id: 'bread' } }} />,
      { api: makeFakeApi({}) });
    const editor = await screen.findByRole('region', { name: 'Kinds and fields' });
    expect(editor).toHaveTextContent('Always kept: practices and claims (what, result, evidence).');
    const second = within(editor).getByLabelText('Field 2 of Loaf');
    await userEvent.clear(second);
    await userEvent.type(second, 'water Pct');
    expect(second).toHaveValue('water_pct');
    await userEvent.click(within(editor).getByRole('button', { name: 'Remove Minutes from Loaf' }));
    await userEvent.type(within(editor).getByLabelText('New field of Loaf'), 'Oven');
    await userEvent.selectOptions(within(editor).getByLabelText('Its type'), 'enum');
    await userEvent.type(within(editor).getByLabelText('Its values, with commas'), 'gas, wood');
    await userEvent.click(within(editor).getByRole('button', { name: 'add' }));
    await userEvent.click(within(editor).getByRole('button', { name: 'Save the fields' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const [id, kinds] = save.mock.calls[0];
    expect(id).toBe('bread');
    expect(kinds.map((k) => k.kind)).toEqual(['loaf']);
    expect(kinds[0].fields.map((f: ThingFieldDef) => [f.name, f.type])).toEqual([
      ['bread', 'text'], ['water_pct', 'number'], ['flour', 'enum'], ['oven', 'enum']]);
    expect(kinds[0].fields[3].values).toEqual(['gas', 'wood']);
    expect(await within(editor).findByText(/\(your edit\)/)).toBeInTheDocument();
  });

  it('is not there while the switch is off', async () => {
    const schema = vi.spyOn(briefApi, 'schema').mockResolvedValue({ ...schemaView(BREAD), on: false });
    renderWithProviders(<TrackSheet open onOpenChange={() => undefined} page={PAGE} />, { api: makeFakeApi({}) });
    await waitFor(() => expect(schema).toHaveBeenCalled());
    expect(screen.queryByRole('region', { name: 'Kinds and fields' })).toBeNull();
  });
});

describe('the rail', () => {
  it('counts new things per track, capped at 9+, silent at 0', async () => {
    vi.spyOn(trackCountsApi, 'counts').mockResolvedValue({ by_track: {
      garden: { unread: 2, discover: 0, count: 2, things: 12 },
      games: { unread: 0, discover: 0, count: 0, things: 0 },
      bread: { unread: 1, discover: 0, count: 1 },
    } });
    const api = makeFakeApi({
      getMarkxOn: vi.fn().mockResolvedValue({ on: true }),
      getFolders: vi.fn().mockResolvedValue({ success: true, folders: [
        { id: 'garden', name: 'Invented garden', sort_order: 1 }, { id: 'games', name: 'Invented games', sort_order: 2 },
        { id: 'bread', name: 'Invented bread', sort_order: 3 }] }),
    });
    renderWithProviders(<ReaderNavRail scope="all" counts={{ total: 3, by_source: {}, by_folder: {} } as never} search=""
      drawerOpen={false} onDrawerOpenChange={() => undefined} />, { api });
    const garden = await screen.findByRole('link', { name: /Invented garden/ });
    await waitFor(() => expect(garden).toHaveTextContent('9+ new things'));
    expect(screen.getByRole('link', { name: /Invented games/ }).querySelector('[data-rail-things]')).toBeNull();
    expect(screen.getByRole('link', { name: /Invented bread/ }).querySelector('[data-rail-things]')).toBeNull();
  });
});
