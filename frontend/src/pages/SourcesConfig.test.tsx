import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SourcesConfig from './SourcesConfig';
import { healthResponse, healthRow, runReport } from '../components/ops/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api } from '../services/api';

const ai = { id: 'f-ai', name: 'AI engineering' };
const ar = { id: 'f-ar', name: 'AR glasses' };

function rows() {
  return [
    healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog', folders: [ai] }),
    healthRow({
      source_id: 'flaky',
      display_name: 'Flaky Feed',
      status: 'backoff',
      decision: 'skip_backoff',
      consecutive_failures: 2,
      next_retry_at: new Date(Date.now() + 3 * 3_600_000 + 600_000).toISOString(),
      last_outcome: 'error',
      last_error: 'HTTP 503 Service Unavailable',
      folders: [ai, ar],
    }),
    healthRow({ source_id: 'tg', display_name: 'ai_newz', platform: 'telegram', kind: 'telegram_mtproto', status: 'unavailable', folders: [] }),
    healthRow({ source_id: 'off', display_name: 'Road to VR', status: 'disabled', enabled: false, folders: [ar] }),
  ];
}

function setup(route = '/settings/sources', overrides: Partial<Record<keyof Api, unknown>> = {}) {
  const methods = {
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse(rows())),
    getSourcesWithSettings: vi.fn().mockResolvedValue({ success: true, sources: [], total: 0 }),
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [{ ...ai, sort_order: 0 }, { ...ar, sort_order: 1 }] }),
    getExperts: vi.fn().mockResolvedValue({ success: true, experts: [{ id: 'e1', name: 'Should never show', folder_id: 'f-ai' }] }),
    getSourceFolders: vi.fn().mockResolvedValue({ success: true, folder_ids: [] }),
    setSourceEnabled: vi.fn().mockResolvedValue({ success: true }),
    deleteSource: vi.fn().mockResolvedValue({ success: true }),
    addSourceToFolder: vi.fn().mockResolvedValue({ success: true }),
    ...overrides,
  };
  const utils = renderWithProviders(<SourcesConfig />, { api: makeFakeApi(methods), route });
  return { ...utils, api: methods };
}

const groupNames = () => screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
const rowIds = (root: HTMLElement = document.body) =>
  [...root.querySelectorAll('li[data-source-id]')].map((li) => li.getAttribute('data-source-id'));
const rowOf = (id: string, nth = 0) => document.querySelectorAll<HTMLElement>(`li[data-source-id="${id}"]`)[nth];

describe('SourcesConfig', () => {
  it('is one list grouped by track: no tabs, no expert labels, one line per source', async () => {
    setup();
    await screen.findByText('Road to VR');
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(screen.queryByText(/expert/i)).not.toBeInTheDocument();
    expect(groupNames()).toEqual(['AI engineering2', 'AR glasses2', 'Not in a track1']);
    // A source in two tracks shows in both; worst status first inside a group.
    expect(rowIds()).toEqual(['flaky', 'simon', 'flaky', 'off', 'tg']);
    expect(rowOf('flaky')).toHaveTextContent('retry in 3h');
    expect(within(rowOf('off')).getByRole('switch', { name: 'Enable Road to VR' })).toHaveAttribute('aria-checked', 'false');
  });

  it('?tab=health opens the list grouped by status, keeping its status filter', async () => {
    setup('/settings/sources?tab=health');
    await screen.findByText('Road to VR');
    expect(groupNames()).toEqual(['Backoff1', 'Unavailable1', 'Scheduled1', 'Disabled1']);
    expect(screen.getByRole('combobox', { name: 'Group' })).toHaveValue('status');
  });

  it('?tab=health&status=error shows only failing sources', async () => {
    setup('/settings/sources?tab=health&status=error');
    await screen.findByText('Flaky Feed');
    expect(rowIds()).toEqual(['flaky']);
    expect(screen.getByRole('button', { name: /Failing/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('search, status chips and group-by filter and regroup the list', async () => {
    setup();
    await screen.findByText('Road to VR');
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search sources' }), 'simon');
    expect(rowIds()).toEqual(['simon']);
    expect(groupNames()).toEqual(['AI engineering1']);
    await userEvent.clear(screen.getByRole('searchbox', { name: 'Search sources' }));

    await userEvent.click(screen.getByRole('button', { name: /Disabled/ }));
    expect(rowIds()).toEqual(['off']);
    await userEvent.click(screen.getByRole('button', { name: /^All/ }));

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Group' }), 'platform');
    expect(groupNames()).toEqual(['RSS3', 'Telegram1']);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Group' }), 'none');
    expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0);
    expect(rowIds()).toEqual(['flaky', 'tg', 'simon', 'off']);
  });

  it('a group header collapses and expands its rows', async () => {
    setup();
    await screen.findByText('Road to VR');
    const header = screen.getByRole('button', { name: /^AI engineering/ });
    await userEvent.click(header);
    expect(header).toHaveAttribute('aria-expanded', 'false');
    expect(rowIds()).toEqual(['flaky', 'off', 'tg']);
    await userEvent.click(header);
    expect(rowIds()).toHaveLength(5);
  });

  it('selecting shows the bulk bar; Disable and Delete act on every selected source', async () => {
    const { api } = setup();
    await screen.findByText('Road to VR');
    expect(screen.queryByRole('region', { name: 'Selected sources' })).not.toBeInTheDocument();
    await userEvent.click(within(rowOf('simon')).getByRole('checkbox'));
    await userEvent.click(within(rowOf('tg')).getByRole('checkbox'));
    const bar = screen.getByRole('region', { name: 'Selected sources' });
    expect(bar).toHaveTextContent('2 selected');

    await userEvent.click(within(bar).getByRole('button', { name: 'Disable' }));
    await waitFor(() => expect(api.setSourceEnabled).toHaveBeenCalledTimes(2));
    expect(api.setSourceEnabled).toHaveBeenCalledWith('simon', false);
    expect(api.setSourceEnabled).toHaveBeenCalledWith('tg', false);

    await userEvent.selectOptions(within(screen.getByRole('region', { name: 'Selected sources' })).getByRole('combobox'), 'f-ar');
    await waitFor(() => expect(api.addSourceToFolder).toHaveBeenCalledWith('f-ar', 'simon'));

    await userEvent.click(within(bar).getByRole('button', { name: 'Delete…' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Delete 2 sources?');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete 2 sources' }));
    await waitFor(() => expect(api.deleteSource).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('region', { name: 'Selected sources' })).not.toBeInTheDocument();

  });

  it('a group checkbox selects the whole group; Escape clears the selection', async () => {
    setup();
    await screen.findByText('Road to VR');
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select every source in AR glasses' }));
    expect(screen.getByRole('region', { name: 'Selected sources' })).toHaveTextContent('2 selected');
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('region', { name: 'Selected sources' })).not.toBeInTheDocument();
  });

  it('j/k move the active row and focus, x selects it, o opens its sheet', async () => {
    setup();
    await screen.findByText('Road to VR');
    await userEvent.keyboard('j');
    expect(rowOf('flaky', 0)).toHaveAttribute('aria-current', 'true');
    expect(document.activeElement).toBe(within(rowOf('flaky', 0)).getByRole('button', { name: 'Flaky Feed' }));
    await userEvent.keyboard('j');
    expect(rowOf('simon')).toHaveAttribute('aria-current', 'true');
    await userEvent.keyboard('k');
    expect(rowOf('flaky', 0)).toHaveAttribute('aria-current', 'true');
    await userEvent.keyboard('x');
    expect(within(rowOf('flaky', 0)).getByRole('checkbox')).toBeChecked();
    // The same source is selected wherever it shows.
    expect(within(rowOf('flaky', 1)).getByRole('checkbox')).toBeChecked();
    await userEvent.keyboard('o');
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByRole('heading', { name: 'Flaky Feed' })).toBeInTheDocument();
    expect(sheet).toHaveTextContent('HTTP 503 Service Unavailable');
  });

  it('the list keys work while a row checkbox has focus', async () => {
    setup();
    await screen.findByText('Road to VR');
    await userEvent.click(within(rowOf('simon')).getByRole('checkbox'));
    await userEvent.keyboard('j');
    expect(rowOf('flaky', 1)).toHaveAttribute('aria-current', 'true');
    await userEvent.keyboard('x');
    expect(screen.getByRole('region', { name: 'Selected sources' })).toHaveTextContent('2 selected');
  });

  it('the sheet fetches now and deletes after a confirmation', async () => {
    const fetchSourceNow = vi.fn().mockResolvedValue(runReport({ posts_inserted: 3, selector: { kind: 'source', id: 'simon' } }));
    const { api } = setup('/settings/sources', { fetchSourceNow });
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    await userEvent.click(within(sheet).getByRole('button', { name: 'Fetch now' }));
    await waitFor(() => expect(fetchSourceNow).toHaveBeenCalledWith('simon', expect.any(Object)));

    await userEvent.click(within(sheet).getByRole('button', { name: 'Delete source…' }));
    const dialog = await screen.findByRole('alertdialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete source' }));
    await waitFor(() => expect(api.deleteSource).toHaveBeenCalledWith('simon'));
  });

  it('the row switch toggles one source', async () => {
    const { api } = setup();
    await screen.findByText('Road to VR');
    await userEvent.click(within(rowOf('off')).getByRole('switch'));
    await waitFor(() => expect(api.setSourceEnabled).toHaveBeenCalledWith('off', true));
  });

  it('empty and no-match states', async () => {
    const { unmount } = setup('/settings/sources', { getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([])) });
    expect(await screen.findByText('No sources yet')).toBeInTheDocument();
    unmount();
    setup('/settings/sources?q=zzzz');
    expect(await screen.findByText('No sources match')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(await screen.findByText('Road to VR')).toBeInTheDocument();
  });
});
