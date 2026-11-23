// v10.42: sub-tracks and the reader's stack on the topic view. Invented names only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import TrackTopic from './TrackTopic';
import { tracksApi, type TrackPage } from '../../services/tracks';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const base = (over: Partial<TrackPage['track']> = {}, rest: Partial<TrackPage> = {}): TrackPage => ({
  track: { id: 'f1', name: 'Zq Safety', kind: 'folder', topic: true, description: 'Safety of the tools I use and the world',
    excludes: null, sources: [], version: 1, parent: null, rest: false, sort: 'newest', stack: [], ...over },
  subtracks: [],
  sections: [], discover: [], counts: { track: 0, judged: 0 },
  calibration: { labels: 0, right: 0, precision: null, lower: null, bands: [], join_edge: null, bar: { precision: 0.9, lower: 0.85, labels: 20 } },
  suggestions: [], examples: { in: [], out: [] }, subtopics: [], footer: null, prefilter: null, ...rest,
});

afterEach(() => vi.restoreAllMocks());

describe('sub-tracks (v10.42)', () => {
  it('the parent lists its sub-tracks with their stack and first posts', async () => {
    vi.spyOn(tracksApi, 'page').mockResolvedValue(base({}, { subtracks: [
      { id: 's1', name: 'Mine', description: 'Updates for my tools', rest: false, sort: 'newest',
        stack: [{ id: 'e1', name: 'Zqphone OS', type: 'software' }], count: 2,
        items: [{ post_id: 'p1', at: null, title: 'Zqphone OS 2026.11 adds a USB lock', source: 'Zq releases' }] },
      { id: 's2', name: 'World', description: 'Breaches worldwide', rest: true, sort: 'news', stack: [], count: 9, items: [] },
    ] }));
    vi.spyOn(tracksApi, 'look').mockResolvedValue({ before: { track: null, subtopics: {} }, now: { track: null, subtopics: {} } });
    renderWithProviders(<TrackTopic folderId="f1" />, { api: makeFakeApi({}) });
    const subs = await screen.findByRole('region', { name: 'Sub-tracks' });
    expect(within(subs).getByRole('link', { name: 'Mine' })).toHaveAttribute('href', '/read/folder/s1');
    expect(subs).toHaveTextContent('Your stack: Zqphone OS');
    expect(subs).toHaveTextContent('Zqphone OS 2026.11 adds a USB lock');
    expect(subs).toHaveTextContent('The rest of this track · ranked as News ranks them');
    expect(screen.queryByRole('region', { name: 'Your stack' })).toBeNull();     // the parent has no stack of its own
  });

  it('a sub-track edits its stack: add from the picker, remove with ×', async () => {
    const page = base({ id: 's1', name: 'Mine', parent: { id: 'f1', name: 'Zq Safety' },
      stack: [{ id: 'e1', name: 'Zqphone OS', type: 'software' }] });
    vi.spyOn(tracksApi, 'page').mockResolvedValue(page);
    vi.spyOn(tracksApi, 'look').mockResolvedValue({ before: { track: null, subtopics: {} }, now: { track: null, subtopics: {} } });
    vi.spyOn(tracksApi, 'findThings').mockResolvedValue([
      { id: 'e2', name: 'Vrrm Browser', type: 'software', level: 'thing', mentions: 12 },
    ]);
    const save = vi.spyOn(tracksApi, 'setStack').mockImplementation(async (_id, things) => ({
      ...page, track: { ...page.track, stack: things.map((id) => ({ id, name: id === 'e2' ? 'Vrrm Browser' : 'Zqphone OS', type: null })) },
    }));
    renderWithProviders(<TrackTopic folderId="s1" />, { api: makeFakeApi({}) });
    const stack = await screen.findByRole('region', { name: 'Your stack' });
    expect(screen.getByRole('region', { name: 'Sub-tracks' })).toHaveTextContent('Part of Zq Safety');
    await userEvent.type(within(stack).getByLabelText('Find a thing to add'), 'vrrm');
    await userEvent.click(await within(stack).findByRole('button', { name: /Vrrm Browser/ }));
    expect(save).toHaveBeenLastCalledWith('s1', ['e1', 'e2']);
    await waitFor(() => expect(within(stack).getByLabelText('Things you use')).toHaveTextContent('Vrrm Browser'));
    await userEvent.click(within(stack).getByRole('button', { name: 'Remove Zqphone OS' }));
    expect(save).toHaveBeenLastCalledWith('s1', ['e2']);
  });
});
