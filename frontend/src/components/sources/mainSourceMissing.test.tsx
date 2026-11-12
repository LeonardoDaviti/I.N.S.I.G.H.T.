import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import MainSourceMissing from './MainSourceMissing';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { MainSourceResponse, MainSourceRow } from '../../services/api';
import { ownPageLine, rowReason, testLine } from '../../lib/mainSource';

const event = {
  story: 's1', headline: 'Acme ships Widget 5', event_type: 'model_release', voices: 3, first_at: '2100-04-01T12:00:00Z',
  own_page: { url: 'https://acme.example/blog/widget-5', how: 'held' as const, held_by: ['Link Aggregator'] },
  posts: [{ id: 'p1', title: 'Widget 5 is out', source: 'Channel A', source_id: 'a', url: 'https://t.me/channel_a/1', at: null }],
};
const missing: MainSourceRow = {
  key: 'main:acme.example/blog/', kind: 'missing',
  channel: { key: 'acme.example/blog/', kind: 'site', platform: 'site', url: 'https://acme.example/blog', prefix: '/blog/' },
  actor: { id: 'e1', name: 'Acme' }, source: null, events: [event], latest: event.first_at,
  test: { label: 'page', holds: 1, of: 1, pages: [], preview: { prefix: '/blog/', found: 12, items: [] }, at: '2100-04-01T13:00:00Z' },
};
const section: MainSourceRow = {
  ...missing, key: 'main:acme.example/', kind: 'wrong_section',
  channel: { key: 'acme.example/', kind: 'site', platform: 'site', url: 'https://acme.example/', prefix: '/' },
  source: { id: 'src1', name: 'Acme News', enabled: true, watch: '/news/' }, test: null,
};
const off: MainSourceRow = {
  ...missing, key: 'main:source:src2', kind: 'disabled',
  channel: { key: 'source:src2', kind: 'source', platform: 'reddit', url: '', prefix: null },
  source: { id: 'src2', name: 'r/acme', enabled: false, watch: null }, test: null,
};

function answer(rows: MainSourceRow[]): MainSourceResponse {
  return { success: true, rows, total: rows.length, checked: 10, events: rows.length, within_days: 30 };
}

function setup(rows: MainSourceRow[], api: Record<string, unknown> = {}) {
  const onFollow = vi.fn();
  const getMainSourceMissing = vi.fn().mockResolvedValue(answer(rows));
  renderWithProviders(<MainSourceMissing onFollow={onFollow} />, { api: makeFakeApi({ getMainSourceMissing, ...api }) });
  return { onFollow, getMainSourceMissing };
}

describe('MainSourceMissing (issue 0170)', () => {
  it('lists the channel, why, the follow test and the events behind a fold', async () => {
    setup([missing]);
    expect(await screen.findByText('acme.example/blog/')).toBeInTheDocument();
    expect(screen.getByText(/1 event your sources covered links Acme's own post in its \/blog\/ section/)).toBeInTheDocument();
    expect(screen.getByText('Page watching: reads 12 articles under /blog/ (holds 1 of 1 event page)')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Acme' })).toHaveAttribute('href', '/markx/entities/e1');
    fireEvent.click(screen.getByRole('button', { name: 'The 1 event' }));
    expect(screen.getByRole('link', { name: 'Acme ships Widget 5' })).toHaveAttribute('href', '/markx/stories/s1');
    expect(screen.getByText(/held as a post of Link Aggregator/)).toBeInTheDocument();
    expect(screen.getByText('Widget 5 is out')).toBeInTheDocument();
  });

  it('Follow… opens Add source on the section; Not interested hides the row by its key', async () => {
    const hideSuggestedSource = vi.fn().mockResolvedValue({ success: true });
    const { onFollow } = setup([missing], { hideSuggestedSource });
    fireEvent.click(await screen.findByRole('button', { name: 'Follow…' }));
    expect(onFollow).toHaveBeenCalledWith('https://acme.example/blog');
    fireEvent.click(screen.getByRole('button', { name: 'Not interested' }));
    await waitFor(() => expect(hideSuggestedSource).toHaveBeenCalledWith('main:acme.example/blog/'));
    await waitFor(() => expect(screen.queryByText('acme.example/blog/')).not.toBeInTheDocument());
  });

  it('a followed site missing the section offers it as a second section', async () => {
    const { onFollow } = setup([section]);
    expect(await screen.findByText(/You follow Acme News \(it watches \/news\/\), but Acme's own page for 1 event is under \//))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Follow this section…' }));
    expect(onFollow).toHaveBeenCalledWith('https://acme.example/');
  });

  it('a turned-off source is surfaced with Turn on, no follow and no test', async () => {
    const setSourceEnabled = vi.fn().mockResolvedValue({ success: true });
    setup([off], { setSourceEnabled });
    expect(await screen.findByText('r/acme is turned off')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Follow/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Not tested yet/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Turn on' }));
    await waitFor(() => expect(setSourceEnabled).toHaveBeenCalledWith('src2', true));
    await waitFor(() => expect(screen.queryByText('r/acme is turned off')).not.toBeInTheDocument());
  });

  it('shows nothing when there is nothing, or when the list cannot be read', async () => {
    const { getMainSourceMissing } = setup([]);
    await waitFor(() => expect(getMainSourceMissing).toHaveBeenCalled());
    expect(screen.queryByRole('region', { name: 'The main source is missing' })).not.toBeInTheDocument();
  });

  it('says each line plainly', () => {
    expect(testLine(null)).toMatch(/^Not tested yet/);
    expect(testLine({ label: 'feed', holds: 2, of: 3, at: '' })).toBe('Feed found (holds 2 of 3 event pages)');
    expect(testLine({ label: 'headlines', at: '' })).toBe('No feed, and page watching reads none of its pages');
    expect(ownPageLine({ url: 'u', how: 'linked', held_by: [] })).toBe('linked by your sources');
    expect(rowReason({ ...missing, events: [event, { ...event, story: 's2' }],
      channel: { ...missing.channel, kind: 'account', platform: 'x', key: 'x.com/acme' } }))
      .toBe("2 events your sources covered link Acme's own post in its posts on X, which you don't follow.");
  });
});
