// 0207 (tracks: evolving sub-topics, digests, new since you looked, tools in use): the lines in words and the topic
// view's new parts. Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import TrackTopic from './TrackTopic';
import { baseline, isNew, newSince, shadowLine, stateWords, suggestionLine, toolLine, trackNewLine } from './trackWords';
import { tracksApi, type TrackItem, type TrackPage, type TrackSection } from '../../services/tracks';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const T0 = Date.parse('2026-11-10T00:00:00Z') / 1000;
const iso = (s: number) => new Date(s * 1000).toISOString();

const item = (over: Partial<TrackItem> = {}): TrackItem => ({
  post_id: 'p1', title: 'A terminal for agents', url: null, at: iso(T0 + 3600), source: 'Example Channel', source_id: 's1',
  confidence: 0.9, subtopic: 'terminals', why: 'A terminal built to run many agent sessions.', origin: 'active', place: 'track',
  label: null, rank: 0.9, calibrated: false, joined_at: iso(T0 + 3600), ...over,
});

const section = (over: Partial<TrackSection> = {}): TrackSection => ({
  id: 'st1', name: 'Agent terminals', definition: 'Terminals and multiplexers for running agents', locked: false,
  made_by: 'insight', named_by: 'haiku', keys: ['terminals'], count: 2, state: 'active', last_member_at: iso(T0 + 7200),
  joined: [T0 + 7200, T0 + 3600],
  digest: { points: [{ text: 'Two builders ship terminals made for agent sessions.', cites: ['p2', 'p1'] },
    { text: 'One reports running 25 sessions at once.', cites: ['p2'] }], at: iso(T0 + 7300), stale: false },
  items: [item({ post_id: 'p2', title: 'Running 25 agent sessions', joined_at: iso(T0 + 7200), at: iso(T0 + 7200) }), item()],
  ...over,
});

const PAGE: TrackPage = {
  track: { id: 'f1', name: 'Agentic Workflows', kind: 'folder', topic: true, description: 'Tools and methods practitioners use or build',
    excludes: null, sources: [{ id: 's1', name: 'Example Channel' }], version: 1 },
  sections: [section(), section({ id: 'st2', name: 'Old harnesses', state: 'quiet', joined: [T0 - 90 * 86400], digest: null,
    items: [item({ post_id: 'p3', title: 'An old harness', joined_at: iso(T0 - 90 * 86400) })], count: 1 })],
  discover: [],
  counts: { track: 3, discover: 0, out: 1, waiting: 0, judged: 4 },
  calibration: { labels: 0, right: 0, precision: null, lower: null, bands: [], join_edge: null, bar: { precision: 0.9, lower: 0.85, labels: 20 } },
  suggestions: [{ track: 'f1', track_name: 'Agentic Workflows', source_id: 's9', source: 'Example Builder', n: 4, of: 12, share: 0.333, lower: 0.138 }],
  examples: { in: [], out: [] },
  subtopics: [],
  tools: [{ id: 'e1', name: 'Vexterm', kind: 'software', what: 'a terminal for agents', posts: 5, voices: 3, last_at: iso(T0), recent: 4, in_track: 2 }],
  shadow: { subtopics: { what: 'posts in the right sub-topic', right: 157, of: 200, lower: 0.72, on: false },
    digests: { what: 'digest points their posts support', right: 73, of: 88, lower: 0.74, on: false },
    tools: { what: 'tools right for the track', right: 23, of: 27, lower: 0.68, on: false } },
  footer: null,
  prefilter: null,
};

afterEach(() => vi.restoreAllMocks());

describe('the 0207 lines in words', () => {
  it('counts what is new since a look, per section and for the track', () => {
    const seen = { track: iso(T0 + 5000), subtopics: { st1: iso(T0 + 8000) } };
    expect(baseline(seen, 'st1')).toBe(iso(T0 + 8000));
    expect(baseline(seen, 'st2')).toBe(iso(T0 + 5000));
    expect(baseline(seen, null)).toBe(iso(T0 + 5000));
    expect(baseline(null, 'st1')).toBeNull();
    expect(newSince([T0 + 7200, T0 + 3600], iso(T0 + 5000))).toBe(1);
    expect(newSince([T0 + 7200], null)).toBe(0);                       // never looked: the first look sets the baseline
    expect(isNew(item({ joined_at: iso(T0 + 7200) }), iso(T0 + 5000))).toBe(true);
    expect(isNew(item(), iso(T0 + 5000))).toBe(false);
    expect(trackNewLine(PAGE, seen)).toBe('1 post new since you looked');
    expect(trackNewLine(PAGE, { track: iso(T0 + 9000), subtopics: {} })).toBe('nothing new since you looked');
    expect(trackNewLine(PAGE, { track: null, subtopics: {} })).toBeNull();
  });

  it('says a sub-topic state, a tool and a suggestion by its share', () => {
    expect(stateWords({ state: 'new' })).toBe('new this week');
    expect(stateWords({ state: 'quiet' })).toBe('quiet');
    expect(stateWords({ state: 'active' })).toBeNull();
    expect(toolLine(PAGE.tools![0])).toBe('3 voices · 5 posts · 4 in 30 days');
    expect(shadowLine(PAGE.shadow!.subtopics)).toBe('Shadow: 79% of posts in the right sub-topic (157 of 200 checked)');
    expect(shadowLine({ ...PAGE.shadow!.tools!, on: true })).toBeNull();
    expect(shadowLine(undefined)).toBeNull();
    expect(suggestionLine(PAGE.suggestions[0]))
      .toBe('Example Builder: 4 of its 12 posts in 30 days are your Agentic Workflows — make it active?');
  });
});

describe('the topic view (0207)', () => {
  it('shows the digest with its citations, the tools, what is new, and marks a sub-topic seen', async () => {
    vi.spyOn(tracksApi, 'page').mockResolvedValue(PAGE);
    const look = vi.spyOn(tracksApi, 'look').mockImplementation(async (_id, sub) => ({
      before: { track: iso(T0 + 5000), subtopics: {} },
      now: { track: iso(T0 + 9999), subtopics: sub ? { [sub]: iso(T0 + 9999) } : {} },
    }));
    renderWithProviders(<TrackTopic folderId="f1" />, { api: makeFakeApi({}) });
    const terms = await screen.findByRole('region', { name: 'Agent terminals' });
    await waitFor(() => expect(look).toHaveBeenCalledWith('f1'));
    const digest = within(terms).getByLabelText('Digest of Agent terminals');
    expect(digest).toHaveTextContent('Two builders ship terminals made for agent sessions.');
    const cites = within(digest).getAllByRole('link');
    expect(cites.map((a) => a.textContent)).toEqual(['[1]', '[2]', '[1]']);
    expect(cites[0]).toHaveAttribute('href', '/posts/p2');
    expect(cites[0]).toHaveAttribute('title', 'Running 25 agent sessions');
    expect(await within(terms).findByText('· 1 new since you looked')).toBeInTheDocument();
    expect(terms.querySelector('[data-track-item="p2"]')).toHaveAttribute('data-new', 'true');
    expect(terms.querySelector('[data-track-item="p1"]')).not.toHaveAttribute('data-new');
    const tools = screen.getByRole('region', { name: 'Tools in use' });
    expect(tools).toHaveTextContent('Shadow: 85% of tools right for the track (23 of 27 checked)');
    expect(digest).toHaveTextContent('Shadow: 83% of digest points their posts support');
    expect(screen.getByText(/Sub-topics found and placed by INSIGHT/)).toHaveTextContent('Shadow: 79%');
    expect(within(tools).getByRole('link', { name: 'Vexterm' })).toHaveAttribute('href', '/markx/entities/e1');
    await userEvent.click(within(terms).getByRole('button', { name: 'mark seen' }));
    expect(look).toHaveBeenLastCalledWith('f1', 'st1');
    await waitFor(() => expect(within(terms).queryByText('· 1 new since you looked')).toBeNull());
    // a quiet sub-topic is folded until opened
    const old = screen.getByRole('region', { name: 'Old harnesses' });
    expect(within(old).getByText('· quiet')).toBeInTheDocument();
    expect(old.querySelector('[data-track-item="p3"]')).toBeNull();
    await userEvent.click(within(old).getByRole('button', { name: /Old harnesses/ }));
    expect(old.querySelector('[data-track-item="p3"]')).not.toBeNull();
  });
});
