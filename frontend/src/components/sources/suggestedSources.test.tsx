import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, screen } from '@testing-library/react';

import SuggestedSources from './SuggestedSources';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { SuggestedSource, SuggestedSourcesResponse } from '../../services/api';

const NOW = new Date('2026-11-12T12:00:00Z');
const site: SuggestedSource = {
  key: 'acme.example.org', url: 'https://acme.example.org', voices: 3, voice_names: ['Voice A'], article_count: 2, link_count: 4,
  articles: [],
};
const answer = (extra: Partial<SuggestedSourcesResponse>): SuggestedSourcesResponse => ({ success: true, suggestions: [site], ...extra });

afterEach(() => { vi.useRealTimers(); });

// Discover is served from its last background build.
describe('Discover says when its list was built', () => {
  it("says how long ago, and asks again a minute later while a newer build is made", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
    const getSuggestedSources = vi.fn()
      .mockResolvedValueOnce(answer({ built_at: '2026-11-12T11:48:00Z', refreshing: true }))
      .mockResolvedValue(answer({ built_at: '2026-11-12T12:00:30Z', refreshing: false }));
    const { unmount } = renderWithProviders(<SuggestedSources onFollow={vi.fn()} />, { api: makeFakeApi({ getSuggestedSources }) });
    expect(await screen.findByText('Updated 12m ago · updating…')).toBeInTheDocument();
    expect(getSuggestedSources).toHaveBeenCalledTimes(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(59_000); });
    expect(getSuggestedSources).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(getSuggestedSources).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('Updated just now')).toBeInTheDocument();

    // Built, not refreshing: no more asking.
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(getSuggestedSources).toHaveBeenCalledTimes(2);
    unmount();
  });

  it('keeps asking each minute while the build is still under way', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const getSuggestedSources = vi.fn()
      .mockResolvedValueOnce(answer({ built_at: null, refreshing: true }))
      .mockResolvedValueOnce(answer({ built_at: null, refreshing: true }))
      .mockResolvedValue(answer({ built_at: '2026-11-12T12:00:30Z', refreshing: false }));
    renderWithProviders(<SuggestedSources onFollow={vi.fn()} />, { api: makeFakeApi({ getSuggestedSources }) });
    expect(await screen.findByText('updating…')).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(61_000); });
    expect(getSuggestedSources).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(61_000); });
    expect(getSuggestedSources).toHaveBeenCalledTimes(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(180_000); });
    expect(getSuggestedSources).toHaveBeenCalledTimes(3);
    vi.useRealTimers();
  });

  it('asks nothing more once gone, and says nothing for an older server', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const getSuggestedSources = vi.fn().mockResolvedValue(answer({ built_at: null, refreshing: true }));
    const { unmount } = renderWithProviders(<SuggestedSources onFollow={vi.fn()} />, { api: makeFakeApi({ getSuggestedSources }) });
    expect(await screen.findByText('updating…')).toBeInTheDocument();
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(getSuggestedSources).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
    renderWithProviders(<SuggestedSources onFollow={vi.fn()} />, { api: makeFakeApi({ getSuggestedSources: vi.fn().mockResolvedValue(answer({})) }) });
    expect(await screen.findByText('acme.example.org')).toBeInTheDocument();
    expect(screen.queryByText(/^Updated|updating…/)).toBeNull();
  });
});

describe('Discover keeps the unfollowable and the quiet apart (0280 C1)', () => {
  it('lists them below the main list with their counts, the quiet closed', async () => {
    const wire = { ...site, key: 'wire.example', url: 'https://wire.example', section: 'unfollowable' as const,
      follow_test: { label: 'headlines' as const, at: '2026-11-01T00:00:00Z' } };
    const old = { ...site, key: 'old.example', url: 'https://old.example', section: 'quiet' as const, last_days: 200 };
    const getSuggestedSources = vi.fn().mockResolvedValue(answer({
      suggestions: [site], built_at: NOW.toISOString(),
      apart: { unfollowable: { total: 3, rows: [wire] }, quiet: { total: 1, rows: [old] } },
    }));
    renderWithProviders(<SuggestedSources onFollow={vi.fn()} />, { api: makeFakeApi({ getSuggestedSources }) });
    expect(await screen.findByText('acme.example.org')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Can't be followed as a feed \(3\)/ })).toBeInTheDocument();
    expect(screen.getByText('wire.example')).toBeInTheDocument();
    const quiet = screen.getByRole('button', { name: /Quiet lately \(1\)/ });
    expect(screen.queryByText('old.example')).toBeNull();
    act(() => { quiet.click(); });
    expect(screen.getByText('old.example')).toBeInTheDocument();
  });
});
