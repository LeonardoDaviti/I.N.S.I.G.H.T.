import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import ReplacementNotice from './ReplacementNotice';
import ReaderPage from '../../pages/ReaderPage';
import { feedPage, feedItem } from '../reader/fixtures';
import { healthResponse, healthRow } from '../ops/fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { STALLED_SOURCES_PATH, brokenNote, filterSources, readSourcesView, rowFact, stalledNote } from './sourceList';

// Issue 0242: sources that stopped without anyone seeing, in front of the owner.
const now = new Date('2026-11-19T12:00:00Z');
const REDDIT_REASON = 'Reddit closed its feeds: add Reddit credentials in Sources → Connections';
const dead = { host: 'gone.example', since: '2026-10-20T00:00:00Z', reason: 'does not resolve or has no route', checked_at: '2026-11-19T10:00:00Z' };

describe('stalledNote', () => {
  it('says why a source stopped: its unavailable reason, its dead host, or how long and how often', () => {
    expect(stalledNote(healthRow({ status: 'unavailable', unavailable_reason: REDDIT_REASON, stalled: { since: '2026-11-17T17:00:00Z', days: 2, failures: 0 } })))
      .toBe(`Stopped: ${REDDIT_REASON}`);
    expect(stalledNote(healthRow({ status: 'backoff', dead, stalled: { since: dead.since, days: 30, failures: 12 } })))
      .toBe('Stopped: gone.example does not resolve or has no route; switch it off or replace it');
    expect(stalledNote(healthRow({ status: 'backoff', stalled: { since: '2026-11-13T00:00:00Z', days: 6, failures: 9 } })))
      .toBe('Stopped: nothing fetched for 6 days, failed 9 times in a row');
    expect(stalledNote(healthRow({ status: 'error', stalled: { since: '2026-11-19T06:00:00Z', days: 0, failures: 5 } })))
      .toBe('Stopped: failed 5 times in a row');
    expect(stalledNote(healthRow({ status: 'error', stalled: { since: null, days: 10, failures: 3 } })))
      .toBe('Stopped: never fetched (added 10 days ago)');
    // Issue 0254: its archive brought posts while the live feed never worked.
    expect(stalledNote(healthRow({ status: 'backoff', stalled: { since: null, days: 4, failures: 6, posts: 48,
      reason: 'the feed has 42 items but 1 would be stored' } })))
      .toBe('Stopped: its live feed fails: the feed has 42 items but 1 would be stored');
    expect(stalledNote(healthRow({ status: 'backoff', stalled: { since: null, days: 4, failures: 0, posts: 20, reason: null } })))
      .toBe('Stopped: its live feed has not worked yet');
    expect(stalledNote(healthRow({ stalled: null }))).toBeNull();
  });

  it('comes first in the row, and the Stopped chip narrows the list to them', () => {
    const stopped = healthRow({ source_id: 'stopped', status: 'backoff', consecutive_failures: 9,
      stalled: { since: '2026-11-13T00:00:00Z', days: 6, failures: 9 }, doctor_looked_at: '2026-11-19T10:00:00Z' }, now);
    expect(rowFact(stopped, now)).toBe('Stopped: nothing fetched for 6 days, failed 9 times in a row');
    expect(rowFact({ ...stopped, enabled: false }, now)).toBe('off');
    const rows = [stopped, healthRow({ source_id: 'fine' }, now)];
    expect(filterSources(rows, { q: '', status: 'stalled' }).map((row) => row.source_id)).toEqual(['stopped']);
    expect(readSourcesView(new URLSearchParams('status=stalled')).status).toBe('stalled');
    expect(STALLED_SOURCES_PATH).toBe('/settings/sources?status=stalled');
  });

  it('names a dead host before any other broken note', () => {
    expect(brokenNote(healthRow({ dead, doctor_looked_at: null }))).toBe('Dead host: gone.example does not resolve or has no route');
  });
});

describe('ReplacementNotice on a dead host', () => {
  it('suggests switching it off or replacing it, and says nothing is removed', () => {
    renderWithProviders(<ReplacementNotice row={healthRow({ dead, doctor_looked_at: null }, now)} now={now} onSwitched={vi.fn()} />,
      { api: makeFakeApi({}) });
    expect(screen.getByText('gone.example does not resolve or has no route: this source looks dead.')).toBeInTheDocument();
    expect(screen.getByText(/Switch it off, or replace it with another address; INSIGHT never removes it\./)).toBeInTheDocument();
  });
});

describe("the reader's nav", () => {
  function setup(rows: ReturnType<typeof healthRow>[]) {
    const api = makeFakeApi({
      getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ source_id: 's1' })])),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 3, by_source: { s1: 3 }, by_folder: {} }),
      getFolders: vi.fn().mockResolvedValue({ success: true, folders: [] }),
      getSourcesHealth: vi.fn().mockResolvedValue(healthResponse(rows)),
    });
    renderWithProviders(<Routes><Route path="/" element={<ReaderPage />} /></Routes>, { api, route: '/' });
  }

  it('links the stopped sources under the main feed', async () => {
    setup([healthRow({ source_id: 's1', stalled: { since: null, days: 4, failures: 6 } }),
      healthRow({ source_id: 's2', stalled: { since: '2026-11-13T00:00:00Z', days: 6, failures: 0 } }), healthRow({ source_id: 's3' })]);
    const rail = await screen.findByRole('navigation', { name: 'Main feed, tracks and sources' });
    const link = await screen.findAllByRole('link', { name: '2 sources stopped' });
    expect(link[0]).toHaveAttribute('href', STALLED_SOURCES_PATH);
    expect(rail).toContainElement(link[0]);
  });

  it('shows nothing when every source works', async () => {
    setup([healthRow({ source_id: 's1' })]);
    await screen.findByRole('navigation', { name: 'Main feed, tracks and sources' });
    expect(screen.queryByText(/sources? stopped/)).not.toBeInTheDocument();
  });
});
