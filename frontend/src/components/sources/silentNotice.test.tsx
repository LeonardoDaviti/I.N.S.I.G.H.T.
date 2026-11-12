import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import SilentNotice from './SilentNotice';
import SilentSources from './SilentSources';
import { filterByStatus, rowFact, silentNote } from './sourceList';
import { healthRow } from '../ops/fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { SourceHealthRow, SourceSilence } from '../../services/api';

// Issue 0178: a source silent far beyond its own rhythm, where it went, Switch or It stopped.
const now = new Date('2026-11-12T09:00:00Z');
const found: SourceSilence = {
  days: 64, usual_gap_hours: 33.6, last_post_at: '2026-09-09T05:44:39Z', looked_at: '2026-11-12T06:00:00Z',
  moved: [{ via: 'home page', from: 'https://news.old.example/', to: 'https://new.example/digest/' }],
  replacement: { kind: 'feed', url: 'https://new.example/digest/feed.xml', title: 'The Digest', latest: ['Issue B'],
    via: 'its home page now lands at new.example/digest' },
};

function silentRow(silent: SourceSilence | null = found, over: Partial<SourceHealthRow> = {}) {
  return healthRow({ source_id: 's1', display_name: 'Digest', silent, ...over }, now);
}

describe('SilentNotice', () => {
  it('says how long against its rhythm, where it went, and offers the switch', () => {
    renderWithProviders(<SilentNotice row={silentRow()} now={now} />, { api: makeFakeApi({}) });
    expect(screen.getByText('Silent for 64 days: it usually posts every 1.4d.')).toBeInTheDocument();
    expect(screen.getByText('Its home page now lands at new.example/digest/')).toBeInTheDocument();
    expect(screen.getByText(/INSIGHT found where it went: The Digest/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Switch to new.example/digest/feed.xml' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'It stopped' })).toBeInTheDocument();
  });

  it('Switch uses the switch path, only when the owner taps it', async () => {
    const switchSource = vi.fn().mockResolvedValue({ success: true });
    const onSwitched = vi.fn();
    renderWithProviders(<SilentNotice row={silentRow()} now={now} onSwitched={onSwitched} />, { api: makeFakeApi({ switchSource }) });
    expect(switchSource).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Switch to new.example/digest/feed.xml' }));
    await waitFor(() => expect(onSwitched).toHaveBeenCalled());
    expect(switchSource).toHaveBeenCalledWith('s1', 'https://new.example/digest/feed.xml');
  });

  it('It stopped records it and hides the notice', async () => {
    const markSourceStopped = vi.fn().mockResolvedValue({ success: true, row: silentRow(null) });
    renderWithProviders(<SilentNotice row={silentRow()} now={now} />, { api: makeFakeApi({ markSourceStopped }) });
    fireEvent.click(screen.getByRole('button', { name: 'It stopped' }));
    await waitFor(() => expect(markSourceStopped).toHaveBeenCalledWith('s1'));
    await waitFor(() => expect(screen.queryByText(/Silent for/)).not.toBeInTheDocument());
  });

  it('with nothing found offers only It stopped', () => {
    renderWithProviders(<SilentNotice row={silentRow({ ...found, moved: [], replacement: null })} now={now} />, { api: makeFakeApi({}) });
    expect(screen.getByText('INSIGHT looked where it went 3h ago and found no live feed.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Switch/ })).not.toBeInTheDocument();
  });

  it('renders nothing for a source that is not silent', () => {
    renderWithProviders(<SilentNotice row={silentRow(null)} now={now} />, { api: makeFakeApi({}) });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('the list note and the Silent filter', () => {
  it('says it on the row, before quiet', () => {
    expect(silentNote(silentRow())).toBe('Silent 64 days (usually every 1.4d): new feed found');
    expect(silentNote(silentRow({ ...found, replacement: null }))).toBe('Silent 64 days (usually every 1.4d): moved to new.example');
    expect(silentNote(silentRow({ ...found, replacement: null, moved: [] }))).toBe('Silent 64 days (usually every 1.4d)');
    expect(rowFact(silentRow(found, { quiet: true }), now)).toBe('Silent 64 days (usually every 1.4d): new feed found');
  });

  it('the Silent chip keeps the silent sources', () => {
    const rows = [silentRow(), healthRow({ source_id: 's2' }, now)];
    expect(filterByStatus(rows, 'silent').map((row) => row.source_id)).toEqual(['s1']);
  });
});

describe("Discover's silent sources", () => {
  it('lists each silent source by name with its notice', async () => {
    const getSourcesHealth = vi.fn().mockResolvedValue({
      success: true, generated_at: now.toISOString(), summary: { due_now: 0, deferred: 2, backoff: 0, unavailable: 0, errors: 0, silent: 1 },
      rows: [silentRow(), healthRow({ source_id: 's2', display_name: 'Lively' }, now)],
    });
    renderWithProviders(<SilentSources now={now} />, { api: makeFakeApi({ getSourcesHealth }) });
    expect(await screen.findByText('Sources you follow that went silent')).toBeInTheDocument();
    expect(screen.getByText('Digest')).toBeInTheDocument();
    expect(screen.queryByText('Lively')).not.toBeInTheDocument();
  });
});
