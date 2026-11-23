// v10.43: Data repairs on the ingestion overview: each repair's last run and preview with a linked sample; Run again
// and Preview only ask (the jobs process runs them). Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import DataRepairs from './DataRepairs';
import { countsLine, dataRepairsApi, sampleHref, type DataRepair } from '../../services/dataRepairs';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const repair = (over: Partial<DataRepair> = {}): DataRepair => ({
  name: 'hide_listing_pages', title: 'Hide stored listing pages', about: 'Listing pages are hidden.', version: 'v10.35',
  ran_version: 'v10.35', due: false,
  last_run: { at: new Date(Date.now() - 3_600_000).toISOString(), version: 'v10.35', dry_run: false,
    counts: { 'listing pages': 3, sources: 1, hidden: 3 },
    sample: [{ label: 'Example Blog: https://blog.example.org/tag/widgets/', url: 'https://blog.example.org/tag/widgets/', source_id: 's1' },
      { label: '“here” → “Widget 5”', url: 'https://w.example/5', post_id: 'p1' }], seconds: 1.2 },
  last_preview: null, requested: null, requested_at: null, running: null, running_since: null, undo: false,
  ...over,
});

afterEach(() => vi.restoreAllMocks());

describe('the words and links', () => {
  it('counts what changed and links a sample to its post, else its address', () => {
    expect(countsLine({ 'listing pages': 3, sources: 0, split_off: 2 })).toBe('3 listing pages · 2 split off');
    expect(countsLine({ retitled: 0 })).toBe('Nothing to change');
    expect(sampleHref({ label: 'x', post_id: 'p1', url: 'https://a.example' })).toEqual({ to: '/posts/p1', external: false });
    expect(sampleHref({ label: 'x', url: 'https://a.example' })).toEqual({ to: 'https://a.example', external: true });
    expect(sampleHref({ label: 'x', track_id: 't1' })).toEqual({ to: '/tracks/t1', external: false });
    expect(sampleHref({ label: 'x' })).toBeNull();
  });
});

describe('Data repairs (v10.43)', () => {
  it('shows each last run with its sample, and Run again / Preview only ask', async () => {
    vi.spyOn(dataRepairsApi, 'list').mockResolvedValue({ repairs: [repair(), repair({
      name: 'repair_foreign_pages', title: 'Move pages', ran_version: null, due: true,
      last_run: { at: new Date().toISOString(), version: 'v10.42', dry_run: false, error: 'RuntimeError: No Saved source' },
    })] });
    const ask = vi.spyOn(dataRepairsApi, 'ask').mockResolvedValue(repair({ requested: 'preview' }));
    renderWithProviders(<DataRepairs titleClass="" />, { api: makeFakeApi({}) });
    const row = (await screen.findByText('Hide stored listing pages')).closest('li') as HTMLElement;
    expect(within(row).getByText(/3 listing pages · 1 sources · 3 hidden/)).toBeInTheDocument();
    expect(within(row).getByText('Done for v10.35')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: '“here” → “Widget 5”' })).toHaveAttribute('href', '/posts/p1');
    expect(within(row).getByRole('link', { name: /Example Blog/ })).toHaveAttribute('href', 'https://blog.example.org/tag/widgets/');
    const failed = screen.getByText('Move pages').closest('li') as HTMLElement;
    expect(within(failed).getByRole('alert')).toHaveTextContent('No Saved source');
    expect(within(failed).getByText('Failed; tried again at the next start')).toBeInTheDocument();
    await userEvent.click(within(row).getByRole('button', { name: 'Preview' }));
    expect(ask).toHaveBeenCalledWith('hide_listing_pages', 'preview');
    expect(await within(row).findByText(/Preview asked/)).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Run again' })).toBeDisabled();
  });

  it('shows a preview as what it would change', async () => {
    vi.spyOn(dataRepairsApi, 'list').mockResolvedValue({ repairs: [repair({
      last_preview: { at: new Date().toISOString(), version: 'v10.35', dry_run: true, counts: { 'listing pages': 2 }, sample: [] },
    })] });
    renderWithProviders(<DataRepairs titleClass="" />, { api: makeFakeApi({}) });
    expect(await screen.findByText(/would change: 2 listing pages/)).toBeInTheDocument();
  });
});
