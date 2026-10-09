import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SourceHealthTable from './SourceHealthTable';
import { healthResponse, healthRow, runReport, worstHealthRows } from './fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const HOUR = 3_600_000;

function rows(now = new Date()) {
  return [
    healthRow({
      source_id: 'backoff-1',
      display_name: 'Flaky Feed',
      status: 'backoff',
      decision: 'skip_backoff',
      consecutive_failures: 2,
      next_retry_at: new Date(now.getTime() + 3 * HOUR + 10 * 60_000).toISOString(),
      last_error: 'HTTP 503 Service Unavailable',
      last_outcome: 'error',
    }, now),
    healthRow({ source_id: 'ok-1', display_name: 'Calm Feed' }, now),
  ];
}

function rowFor(name: string): HTMLElement {
  const cell = screen.getByText(name);
  const row = cell.closest('tr');
  if (!row) throw new Error(`no row for ${name}`);
  return row as HTMLElement;
}

describe('SourceHealthTable', () => {
  it('renders every source with tier, interval, next due, backoff and last error', async () => {
    const getSourcesHealth = vi.fn().mockResolvedValue(healthResponse(rows()));
    renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth }) });

    const backoff = rowFor(await screen.findByText('Flaky Feed').then((el) => el.textContent ?? ''));
    expect(backoff).toHaveTextContent('retry in 3h');
    expect(backoff).toHaveTextContent('Backoff');
    expect(backoff).toHaveTextContent('HTTP 503 Service Unavailable');
    const calm = rowFor('Calm Feed');
    expect(calm).toHaveTextContent('Medium');
    expect(calm).toHaveTextContent('every 12h · tier');
    expect(calm).toHaveTextContent('in 3h');
    expect(screen.getAllByRole('row')).toHaveLength(3); // header + 2
  });

  it('Fetch now calls fetchSourceNow, toasts the new posts and refreshes the table', async () => {
    const getSourcesHealth = vi.fn().mockResolvedValue(healthResponse(rows()));
    const fetchSourceNow = vi.fn().mockResolvedValue(runReport({ posts_inserted: 7, selector: { kind: 'source', id: 'ok-1' } }));
    renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth, fetchSourceNow }) });

    await screen.findByText('Calm Feed');
    await userEvent.click(within(rowFor('Calm Feed')).getByRole('button', { name: 'Fetch Calm Feed now' }));

    await waitFor(() => expect(fetchSourceNow).toHaveBeenCalledWith('ok-1', expect.any(Object)));
    expect(await screen.findByText('7 new posts')).toBeInTheDocument();
    await waitFor(() => expect(getSourcesHealth).toHaveBeenCalledTimes(2));
  });

  it('the override editor validates before it calls the API', async () => {
    const getSourcesHealth = vi.fn().mockResolvedValue(healthResponse(rows()));
    const setCadenceOverride = vi.fn().mockResolvedValue({
      success: true,
      row: healthRow({ source_id: 'ok-1', display_name: 'Calm Feed', override_hours: 6, interval_hours: 6, interval_basis: 'override' }),
    });
    renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth, setCadenceOverride }) });

    await screen.findByText('Calm Feed');
    await userEvent.click(within(rowFor('Calm Feed')).getByRole('button', { name: 'Edit cadence for Calm Feed' }));
    const input = screen.getByRole('textbox', { name: /override/i });

    await userEvent.type(input, '3000');
    await userEvent.click(screen.getByRole('button', { name: 'Save override' }));
    expect(await screen.findByText(/between 1 and 2160 hours/i)).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(setCadenceOverride).not.toHaveBeenCalled();

    await userEvent.clear(input);
    await userEvent.type(input, '6');
    await userEvent.click(screen.getByRole('button', { name: 'Save override' }));
    await waitFor(() => expect(setCadenceOverride).toHaveBeenCalledWith('ok-1', 6));
    expect(await screen.findByText('every 6h · override')).toBeInTheDocument();
  });

  it('?status=error shows only failing sources (error and backoff)', async () => {
    const getSourcesHealth = vi.fn().mockResolvedValue(healthResponse(worstHealthRows()));
    renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth }), route: '/settings/sources?tab=health&status=error' });

    await screen.findByText(/^Bundesministerium/);
    const bodyRows = screen.getAllByRole('row').slice(1);
    expect(bodyRows).toHaveLength(2);
    expect(screen.queryByText('ai_newz')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /failing/i })).toHaveAttribute('aria-pressed', 'true');
  });

  it('sorts by status (worst first) by default and can sort by name', async () => {
    const getSourcesHealth = vi.fn().mockResolvedValue(healthResponse([...rows()].reverse()));
    renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth }) });

    await screen.findByText('Calm Feed');
    const names = () => screen.getAllByRole('row').slice(1).map((row) => row.getAttribute('data-source-id'));
    expect(names()).toEqual(['backoff-1', 'ok-1']);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Sort by' }), 'name');
    expect(names()).toEqual(['ok-1', 'backoff-1']);
  });

  it('shows the unavailable reason, and the empty and error states', async () => {
    const getSourcesHealth = vi.fn().mockResolvedValue(healthResponse(worstHealthRows()));
    const { unmount } = renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth }) });
    // The reason sits, unclamped, on its own full-width line right under the row.
    const telegram = rowFor(await screen.findByText('ai_newz').then((el) => el.textContent ?? ''));
    expect(telegram.nextElementSibling).toHaveTextContent('No Telegram session');
    expect(within(telegram.nextElementSibling as HTMLElement).getByText(/telegram_login/).tagName).toBe('CODE');
    unmount();

    renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([])) }) });
    expect(await screen.findByText('No sources yet')).toBeInTheDocument();
  });

  it('derives status from the last attempt: a due source whose last fetch failed reads as failing', async () => {
    const now = new Date();
    const getSourcesHealth = vi.fn().mockResolvedValue(healthResponse([
      healthRow({ source_id: 'rl-1', display_name: 'Rate Limited', status: 'due', last_outcome: 'error', last_error: 'HTTP 429 Too Many Requests' }, now),
      healthRow({ source_id: 'ok-1', display_name: 'Calm Feed' }, now),
    ]));
    renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth }) });
    const limited = rowFor(await screen.findByText('Rate Limited').then((el) => el.textContent ?? ''));
    expect(limited).toHaveTextContent('Failing');
    expect(limited).not.toHaveTextContent(/\bDue\b/);
    expect(screen.getByRole('button', { name: /Failing/ })).toHaveTextContent('1');
  });

  it('renders the API error with a Retry', async () => {
    const getSourcesHealth = vi.fn().mockRejectedValueOnce(new Error('The backend is unavailable')).mockResolvedValue(healthResponse(rows()));
    renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth }) });
    expect(await screen.findByText('The backend is unavailable')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Calm Feed')).toBeInTheDocument();
  });

  it('dev ?data=worst renders the worst-case fixture without calling the API; ?data=huge paginates', async () => {
    const getSourcesHealth = vi.fn();
    const { unmount } = renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth }), route: '/settings/sources?tab=health&data=worst' });
    expect(await screen.findByText('ai_newz')).toBeInTheDocument();
    expect(screen.getByText(/^Bundesministerium/)).toHaveAttribute('title', expect.stringMatching(/Pressemitteilungen$/));
    expect(rowFor('Jo')).toHaveTextContent('Disabled');
    expect(screen.getByText('dormant · retry in 5d')).toBeInTheDocument();
    expect(getSourcesHealth).not.toHaveBeenCalled();
    unmount();

    renderWithProviders(<SourceHealthTable />, { api: makeFakeApi({ getSourcesHealth }), route: '/settings/sources?data=huge' });
    await screen.findByRole('button', { name: /show 100 more of 900/i });
    expect(screen.getAllByRole('row')).toHaveLength(101);
  });
});

