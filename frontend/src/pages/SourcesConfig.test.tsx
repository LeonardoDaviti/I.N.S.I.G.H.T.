import { describe, expect, it, onTestFinished, vi } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SourcesConfig from './SourcesConfig';
import { healthResponse, healthRow, runReport } from '../components/ops/fixtures';
import { demoCredentials } from '../components/connections/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api } from '../services/api';
import { useLocation, useNavigate } from 'react-router-dom';

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
    getSources: vi.fn().mockResolvedValue({ success: true, sources: [], total: 0 }),
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [{ ...ai, sort_order: 0 }, { ...ar, sort_order: 1 }] }),
    getSourceFolders: vi.fn().mockResolvedValue({ success: true, folder_ids: [] }),
    setSourceEnabled: vi.fn().mockResolvedValue({ success: true }),
    deleteSource: vi.fn().mockResolvedValue({ success: true }),
    addSourceToFolder: vi.fn().mockResolvedValue({ success: true }),
    removeSourceFromFolder: vi.fn().mockResolvedValue({ success: true }),
    setSourceMainDigest: vi.fn().mockImplementation((id: string, on: boolean) => Promise.resolve({ success: true, source_id: id, in_main_digest: on })),
    deleteFolder: vi.fn().mockResolvedValue({ success: true }),
    renameTrack: vi.fn().mockResolvedValue({ success: true }),
    setTrackMainDigest: vi.fn().mockResolvedValue({ success: true }),
    ...overrides,
  };
  const utils = renderWithProviders(<><SourcesConfig /><Where /></>, { api: makeFakeApi(methods), route });
  return { ...utils, api: methods };
}

/** The URL, and the browser's Back button (a modal sheet makes the page inert, so it is called directly). */
let browserBack: () => void = () => {};
function Where() {
  const location = useLocation();
  const navigate = useNavigate();
  browserBack = () => navigate(-1);
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}
const where = () => screen.getByTestId('where').textContent;

const groupNames = () => screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
const rowIds = (root: HTMLElement = document.body) =>
  [...root.querySelectorAll('li[data-source-id]')].map((li) => li.getAttribute('data-source-id'));
const rowOf = (id: string, nth = 0) => document.querySelectorAll<HTMLElement>(`li[data-source-id="${id}"]`)[nth];

describe('SourcesConfig', () => {
  it('is one flat list by default: sources, connections and ingestion tabs, no expert labels, one line per source', async () => {
    setup();
    await screen.findByText('Road to VR');
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['sources', 'connections', 'ingestion']);
    expect(screen.getByRole('tab', { name: 'sources' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText(/expert/i)).not.toBeInTheDocument();
    expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0);
    expect(screen.getByRole('combobox', { name: 'Group' })).toHaveValue('none');
    // Worst status first.
    expect(rowIds()).toEqual(['flaky', 'tg', 'simon', 'off']);
    expect(rowOf('flaky')).toHaveTextContent('retry in 3h');
    expect(within(rowOf('off')).getByRole('switch', { name: 'Enable Road to VR' })).toHaveAttribute('aria-checked', 'false');
  });

  it('grouped by track: a source in two tracks shows in both, the untracked come last without a header', async () => {
    setup('/settings/sources?group=track');
    await screen.findByText('Road to VR');
    expect(groupNames()).toEqual(['AI engineering2', 'AR glasses2']);
    expect(rowIds()).toEqual(['flaky', 'simon', 'flaky', 'off', 'tg']);
    expect(screen.queryByText(/not in a track/i)).not.toBeInTheDocument();
  });

  it('the Group choices are none, track and platform; there is no Sort dropdown', async () => {
    setup();
    await screen.findByText('Road to VR');
    const options = within(screen.getByRole('combobox', { name: 'Group' })).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['No grouping', 'Track', 'Platform']);
    expect(screen.queryByRole('combobox', { name: 'Sort' })).not.toBeInTheDocument();
  });

  it('?tab=health opens the flat list, keeping its status filter', async () => {
    setup('/settings/sources?tab=health&status=disabled');
    await screen.findByText('Road to VR');
    expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0);
    expect(rowIds()).toEqual(['off']);
    await waitFor(() => expect(where()).toBe('/settings/sources?status=disabled'));
  });

  it('old sort and group values open the default list', async () => {
    setup('/settings/sources?group=status&sort=success');
    await screen.findByText('Road to VR');
    expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0);
    expect(rowIds()).toEqual(['flaky', 'tg', 'simon', 'off']);
    expect(screen.getByRole('button', { name: 'Sort by Status, descending' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('?tab=health&status=error shows only failing sources', async () => {
    setup('/settings/sources?tab=health&status=error');
    await screen.findByText('Flaky Feed');
    expect(rowIds()).toEqual(['flaky']);
    expect(screen.getByRole('button', { name: /Failing/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('search, status chips and group-by filter and regroup the list', async () => {
    setup('/settings/sources?group=track');
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
    setup('/settings/sources?group=track');
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

    await userEvent.selectOptions(within(screen.getByRole('region', { name: 'Selected sources' })).getByRole('combobox', { name: 'Add to track' }), 'f-ar');
    await waitFor(() => expect(api.addSourceToFolder).toHaveBeenCalledWith('f-ar', 'simon'));

    await userEvent.click(within(bar).getByRole('button', { name: 'Delete…' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Delete 2 sources?');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete 2 sources' }));
    await waitFor(() => expect(api.deleteSource).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('region', { name: 'Selected sources' })).not.toBeInTheDocument();

  });

  it('a group checkbox selects the whole group; Escape clears the selection', async () => {
    setup('/settings/sources?group=track');
    await screen.findByText('Road to VR');
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select every source in AR glasses' }));
    expect(screen.getByRole('region', { name: 'Selected sources' })).toHaveTextContent('2 selected');
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('region', { name: 'Selected sources' })).not.toBeInTheDocument();
  });

  it('j/k move the active row and focus, x selects it, o opens its sheet', async () => {
    setup('/settings/sources?group=track');
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
    setup('/settings/sources?group=track');
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

  it('?tab=connections opens Connections; the sources tab returns to the list', async () => {
    const getCredentials = vi.fn().mockResolvedValue(demoCredentials());
    setup('/settings/sources?tab=connections&provider=substack', { getCredentials });
    expect(await screen.findByRole('region', { name: 'Connections' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'connections' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('field-summary')).toHaveTextContent('••••a3f9');
    expect(screen.queryByText('Road to VR')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'sources' }));
    expect(await screen.findByText('Road to VR')).toBeInTheDocument();
  });

  it('an unavailable source links from its sheet to Connections', async () => {
    const getCredentials = vi.fn().mockResolvedValue(demoCredentials());
    const tg = healthRow({
      source_id: 'tg', display_name: 'ai_newz', platform: 'telegram', kind: 'telegram_mtproto', status: 'unavailable',
      decision: 'skip_unavailable', decision_detail: 'Telegram API ID is not set; add it in Sources → Connections',
      unavailable_reason: 'Telegram API ID is not set; add it in Sources → Connections', folders: [],
    });
    setup('/settings/sources', { getCredentials, getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([tg])) });
    await userEvent.click(await screen.findByRole('button', { name: 'ai_newz' }));
    const sheet = await screen.findByRole('dialog');
    await userEvent.click(within(sheet).getByRole('link', { name: 'add in Connections' }));
    expect(await screen.findByRole('region', { name: 'Connections' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'API ID' })).toHaveTextContent('••••4821');
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
  it('a row shows status, name, kind, posts, last new post and a status note, never the URL', async () => {
    const hourAgo = new Date(Date.now() - 3 * 3_600_000).toISOString();
    const row = { ...healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog', stored_posts: 1204, folders: [ai] }), last_post_at: hourAgo };
    setup('/settings/sources', { getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([row])) });
    await screen.findByText('Simon Willison’s Weblog');
    const li = rowOf('simon');
    expect(li).toHaveTextContent('RSS');
    expect(li).toHaveTextContent('1,204 posts');
    expect(li).toHaveTextContent('newest post 3h');
    expect(li).not.toHaveTextContent('http');
  });

  it('"/" is not bound: search is a plain field', async () => {
    setup();
    await screen.findByText('Road to VR');
    await userEvent.keyboard('/');
    expect(screen.getByRole('searchbox', { name: 'Search sources' })).not.toHaveFocus();
    expect(document.querySelector('kbd')).toBeNull();
  });

  it('status chips: all, enabled, disabled, failing, unavailable always; backoff only with sources', async () => {
    setup();
    await screen.findByText('Road to VR');
    const chips = within(screen.getByRole('group', { name: 'Filter by status' })).getAllByRole('button').map((b) => b.textContent);
    expect(chips).toEqual(['All4', 'Enabled3', 'Disabled1', 'Failing1', 'Unavailable1', 'Backoff1', 'Scheduled1']);
    await userEvent.click(screen.getByRole('button', { name: /^Enabled/ }));
    expect(rowIds()).toEqual(['flaky', 'tg', 'simon']);
  });

  it('a column header sorts, a second press reverses, and the sort lives in the URL', async () => {
    const day = 86_400_000;
    const many = [
      healthRow({ source_id: 'b', display_name: 'Bravo', stored_posts: 5, created_at: new Date(Date.now() - 2 * day).toISOString() }),
      healthRow({ source_id: 'a', display_name: 'Alpha', stored_posts: 50, created_at: new Date(Date.now() - 30 * day).toISOString() }),
      healthRow({ source_id: 'c', display_name: 'Charlie', stored_posts: 9, status: 'error', last_outcome: 'error', last_error: 'boom', created_at: new Date(Date.now() - 9 * day).toISOString() }),
    ];
    setup('/settings/sources', { getSourcesHealth: vi.fn().mockResolvedValue(healthResponse(many)) });
    await screen.findByText('Alpha');
    expect(rowIds()).toEqual(['c', 'a', 'b']);
    const headers = screen.getByRole('group', { name: 'Sort sources' });
    await userEvent.click(within(headers).getByRole('button', { name: 'Sort by Name' }));
    expect(rowIds()).toEqual(['a', 'b', 'c']);
    await userEvent.click(within(headers).getByRole('button', { name: 'Sort by Posts' }));
    expect(rowIds()).toEqual(['a', 'c', 'b']);

    // Added: newest first, then reversed.
    await userEvent.click(within(headers).getByRole('button', { name: 'Sort by Added' }));
    expect(rowIds()).toEqual(['b', 'c', 'a']);
    const added = within(headers).getByRole('button', { name: 'Sort by Added, descending' });
    expect(added).toHaveAttribute('aria-pressed', 'true');
    expect(where()).toBe('/settings/sources?sort=added');
    await userEvent.click(added);
    expect(rowIds()).toEqual(['a', 'c', 'b']);
    expect(within(headers).getByRole('button', { name: 'Sort by Added, ascending' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(headers).getByRole('button', { name: 'Sort by Posts' })).toHaveAttribute('aria-pressed', 'false');
    expect(where()).toBe('/settings/sources?sort=added&dir=asc');
  });

  it('on narrow screens "Sort: …" opens the same column choices', async () => {
    setup('/settings/sources?sort=added');
    await screen.findByText('Road to VR');
    const toggle = screen.getByRole('button', { name: 'Sort: Added, descending' });
    expect(toggle).toHaveTextContent('Sort: Added ↓');
    await userEvent.click(toggle);
    const choices = screen.getByRole('group', { name: 'Sort by' });
    expect(within(choices).getAllByRole('button').map((b) => b.textContent)).toEqual(['Name', 'Kind', 'Posts', 'Last post', 'Added↓', 'Status']);
    await userEvent.click(within(choices).getByRole('button', { name: 'Sort by Added, descending' }));
    expect(where()).toBe('/settings/sources?sort=added&dir=asc');
    expect(screen.getByRole('button', { name: 'Sort: Added, ascending' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('each row reads its source; the sheet has Read posts', async () => {
    setup();
    await screen.findByText('Road to VR');
    expect(within(rowOf('simon')).getByRole('link', { name: 'Read Simon Willison’s Weblog' })).toHaveAttribute('href', '/read/source/simon');
    await userEvent.click(screen.getByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByRole('link', { name: 'Read posts' })).toHaveAttribute('href', '/read/source/simon');
  });

  it('shift-click selects the range from the last checked row', async () => {
    setup('/settings/sources?group=none');
    await screen.findByText('Road to VR');
    expect(rowIds()).toEqual(['flaky', 'tg', 'simon', 'off']);
    await userEvent.click(within(rowOf('flaky')).getByRole('checkbox'));
    const user = userEvent.setup();
    await user.keyboard('{Shift>}');
    await user.click(within(rowOf('simon')).getByRole('checkbox'));
    await user.keyboard('{/Shift}');
    expect(screen.getByRole('region', { name: 'Selected sources' })).toHaveTextContent('3 selected');
    expect(within(rowOf('off')).getByRole('checkbox')).not.toBeChecked();
  });

  it('checkboxes hide until hover or focus, and show for every row once one is selected', async () => {
    setup();
    await screen.findByText('Road to VR');
    const box = within(rowOf('simon')).getByRole('checkbox');
    expect(box.className).toContain('opacity-0');
    expect(box.className).toContain('group-hover/row:opacity-100');
    expect(box.className).toContain('coarse:opacity-100');
    await userEvent.click(box);
    expect(within(rowOf('off')).getByRole('checkbox').className).not.toContain('opacity-0');
  });

  it('the bulk bar removes from a track and switches the main digest', async () => {
    const { api } = setup();
    await screen.findByText('Road to VR');
    await userEvent.click(within(rowOf('simon')).getByRole('checkbox'));
    await userEvent.click(within(rowOf('off')).getByRole('checkbox'));
    const bar = screen.getByRole('region', { name: 'Selected sources' });
    const remove = within(bar).getByRole('combobox', { name: 'Remove from track' });
    // Only the tracks a selected source is in.
    expect(within(remove).getAllByRole('option').map((o) => o.textContent)).toEqual(['Remove from track…', 'AI engineering', 'AR glasses']);
    await userEvent.selectOptions(remove, 'f-ar');
    await waitFor(() => expect(api.removeSourceFromFolder).toHaveBeenCalledWith('f-ar', 'off'));
    expect(api.removeSourceFromFolder).toHaveBeenCalledTimes(1);

    await userEvent.selectOptions(within(bar).getByRole('combobox', { name: 'Main digest' }), 'off');
    await waitFor(() => expect(api.setSourceMainDigest).toHaveBeenCalledTimes(2));
    expect(api.setSourceMainDigest).toHaveBeenCalledWith('simon', false);
    expect(api.setSourceMainDigest).toHaveBeenCalledWith('off', false);
    expect(within(bar).getByRole('button', { name: 'Enable' })).toBeInTheDocument();
    expect(within(bar).getByRole('button', { name: 'Delete…' })).toBeInTheDocument();
  });

  it('a track header fetches the track; its menu renames, switches the digest and deletes after a confirmation', async () => {
    const fetchFolderNow = vi.fn().mockResolvedValue(runReport({ selector: { kind: 'folder', id: 'f-ai' } }));
    const { api } = setup('/settings/sources?group=track', { fetchFolderNow });
    await screen.findByText('Road to VR');
    await userEvent.click(screen.getByRole('button', { name: 'Fetch track AI engineering' }));
    await waitFor(() => expect(fetchFolderNow).toHaveBeenCalledWith('f-ai', expect.any(Object)));

    await userEvent.click(screen.getByRole('button', { name: 'More actions for track AI engineering' }));
    // Phones fetch from the menu (the header button is hidden there); arrows move between items.
    expect(screen.getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['Fetch now', 'Rename…', '×Delete track…']);
    expect(screen.getByRole('menuitem', { name: 'Fetch now' })).toHaveFocus();
    await userEvent.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Rename…' })).toHaveFocus();
    await userEvent.click(screen.getByRole('menuitem', { name: 'Rename…' }));
    const rename = await screen.findByRole('dialog', { name: 'Rename track' });
    const field = within(rename).getByRole('textbox', { name: 'Track name' });
    await userEvent.clear(field);
    await userEvent.type(field, 'Agents');
    await userEvent.click(within(rename).getByRole('button', { name: 'Rename' }));
    await waitFor(() => expect(api.renameTrack).toHaveBeenCalledWith('f-ai', 'Agents'));

    await userEvent.click(screen.getByRole('button', { name: 'More actions for track AI engineering' }));
    const digest = screen.getByRole('menuitemcheckbox', { name: 'In main feed and digest' });
    expect(digest).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(digest);
    await waitFor(() => expect(api.setTrackMainDigest).toHaveBeenCalledWith('f-ai', false));

    await userEvent.click(screen.getByRole('button', { name: 'More actions for track AI engineering' }));
    await userEvent.click(screen.getByRole('menuitem', { name: /Delete track/ }));
    const confirm = await screen.findByRole('alertdialog');
    expect(confirm).toHaveTextContent('Delete the track "AI engineering"?');
    expect(api.deleteFolder).not.toHaveBeenCalled();
    await userEvent.click(within(confirm).getByRole('button', { name: 'Delete track' }));
    await waitFor(() => expect(api.deleteFolder).toHaveBeenCalledWith('f-ai'));
  });

  it('the sheet shows the URL with a copy button and a danger delete', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    setup('/settings/sources', {
      getSources: vi.fn().mockResolvedValue({
        success: true,
        total: 1,
        sources: [{ id: 'simon', platform: 'rss', handle_or_url: 'https://simonwillison.net/atom/everything/', enabled: true, settings: { display_name: 'Simon Willison’s Weblog' } }],
      }),
    });
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    await waitFor(() => expect(sheet).toHaveTextContent('https://simonwillison.net/atom/everything/'));
    await userEvent.click(within(sheet).getByRole('button', { name: 'Copy URL' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://simonwillison.net/atom/everything/'));
    expect(within(sheet).getByRole('status')).toHaveTextContent('URL copied');
    expect(within(sheet).getByRole('button', { name: /Delete source/ }).querySelector('[data-danger-mark]')).not.toBeNull();
  });

  it('the cadence override validates before it calls the API', async () => {
    const setCadenceOverride = vi.fn().mockResolvedValue({
      success: true,
      row: healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog', override_hours: 6, interval_hours: 6, interval_basis: 'override', folders: [ai] }),
    });
    setup('/settings/sources', { setCadenceOverride });
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    const input = within(sheet).getByRole('textbox', { name: /override/i });

    await userEvent.type(input, '3000');
    await userEvent.click(within(sheet).getByRole('button', { name: 'Save override' }));
    expect(await within(sheet).findByText(/between 1 and 2160 hours/i)).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(setCadenceOverride).not.toHaveBeenCalled();

    await userEvent.clear(input);
    await userEvent.type(input, 'abc');
    await userEvent.click(within(sheet).getByRole('button', { name: 'Save override' }));
    expect(setCadenceOverride).not.toHaveBeenCalled();

    await userEvent.clear(input);
    await userEvent.type(input, '6');
    await userEvent.click(within(sheet).getByRole('button', { name: 'Save override' }));
    await waitFor(() => expect(setCadenceOverride).toHaveBeenCalledWith('simon', 6));
  });
});

// Issue 0003: reading views link here by id; the URL owns the sheet.
describe('SourcesConfig deep links', () => {
  it('?source=<id> opens that source’s sheet; closing it removes the parameter', async () => {
    setup('/settings/sources?source=flaky');
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByRole('heading', { name: 'Flaky Feed' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(where()).toBe('/settings/sources');
  });

  it('opening a row puts it in the URL, and Back closes the sheet', async () => {
    setup('/settings/sources?q=simon');
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    await screen.findByRole('dialog');
    expect(where()).toBe('/settings/sources?q=simon&source=simon');
    act(() => browserBack());
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(where()).toBe('/settings/sources?q=simon');
  });

  it('closing a sheet opened from the list goes back instead of stacking history', async () => {
    setup('/settings/sources');
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    await screen.findByRole('dialog');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(where()).toBe('/settings/sources');
  });

  it('an unknown source shows the list with a quiet note, not an error', async () => {
    setup('/settings/sources?source=a984b1ff-gone');
    await screen.findByText('Road to VR');
    expect(await screen.findByText('That source no longer exists')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('?track=<id> scrolls to that track’s group and highlights it briefly', async () => {
    const scrolled: Element[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) { scrolled.push(this); };
    onTestFinished(() => { Element.prototype.scrollIntoView = original; });
    setup('/settings/sources?track=f-ar');
    await screen.findByText('Road to VR');
    const group = screen.getByRole('region', { name: /AR glasses/ });
    await waitFor(() => expect(scrolled).toContain(group));
    expect(group).toHaveAttribute('data-highlighted', 'true');
    await waitFor(() => expect(group).not.toHaveAttribute('data-highlighted'), { timeout: 3000 });
  });

  it('an unknown track shows the list with a quiet note', async () => {
    setup('/settings/sources?track=f-gone');
    await screen.findByText('Road to VR');
    expect(await screen.findByText('That track no longer exists')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
