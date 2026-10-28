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
    // The header does not repeat the chips' counts (issue 0027).
    const header = screen.getByText(/^4 sources · /);
    expect(header.textContent).not.toMatch(/ on\b|failing/);
  });

  it('grouped by track: a source in two tracks shows in both, the untracked come last without a header', async () => {
    setup('/settings/sources?group=track');
    await screen.findByText('Road to VR');
    expect(groupNames()).toEqual(['AI engineering2', 'AR glasses2']);
    expect(rowIds()).toEqual(['flaky', 'simon', 'flaky', 'off', 'tg']);
    expect(screen.queryByText(/not in a track/i)).not.toBeInTheDocument();
  });

  it('the Group choices are none, track and kind; there is no Sort dropdown', async () => {
    setup();
    await screen.findByText('Road to VR');
    const options = within(screen.getByRole('combobox', { name: 'Group' })).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['No grouping', 'Track', 'Kind']);
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

  it('the old ?status=backoff opens Failing, its chip shown (issue 0029)', async () => {
    setup('/settings/sources?status=backoff');
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

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Group' }), 'kind');
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
    const fetchSourceNow = vi.fn().mockResolvedValue(runReport({ posts_inserted: 3, sources_with_new: 1 }));
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

  it('the sheet saves its name and fetch delay only: no posts per fetch, no priority, no Cancel beside settings that save instantly', async () => {
    const updateSourceSettings = vi.fn().mockResolvedValue({ success: true });
    setup('/settings/sources', { updateSourceSettings });
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).queryByText(/max posts per fetch/i)).toBeNull();
    expect(within(sheet).queryByText(/not enforced/i)).toBeNull();
    expect(within(sheet).queryByLabelText(/priority/i)).toBeNull();
    expect(within(sheet).queryByRole('button', { name: 'Cancel' })).toBeNull();
    await userEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updateSourceSettings).toHaveBeenCalled());
    const sent = updateSourceSettings.mock.calls[0][1];
    expect(sent).not.toHaveProperty('max_posts_per_fetch');
    expect(sent).not.toHaveProperty('priority');
  });

  it('the sheet names the source’s kind, as the list does, not its platform (issue 0027)', async () => {
    setup('/settings/sources', { getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([
      healthRow({ source_id: 'kc', display_name: 'The Kaitchup', platform: 'rss', kind: 'substack', folders: [] }),
    ])) });
    await userEvent.click(await screen.findByRole('button', { name: 'The Kaitchup' }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByText(/^Substack ·/)).toBeInTheDocument();
    expect(within(sheet).queryByText(/^RSS ·/)).toBeNull();
  });

  it('the sheet names the switch "Show in Main feed", says no digest and nothing about tracks it may not have (issue 0027)', async () => {
    setup();
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByRole('switch', { name: 'Show in Main feed' })).toBeInTheDocument();
    expect(sheet).not.toHaveTextContent(/digest/i);
    expect(sheet).not.toHaveTextContent(/through its tracks/i);
  });

  it.each([
    ['a disabled source', healthRow({ source_id: 'off', display_name: 'Road to VR', status: 'disabled', enabled: false, folders: [] }),
      /Off: not fetched until you switch it on/],
    ['an unavailable source', healthRow({
      source_id: 'tg', display_name: 'ai_newz', platform: 'telegram', kind: 'telegram_mtproto', status: 'unavailable', folders: [],
      unavailable_reason: 'no Telegram session; sign in under Sources → Connections', decision_detail: 'Unavailable: no Telegram session',
    }), /add in Connections/],
  ])('%s’s sheet says why in one line, without cadence, main feed, archive or Fetch now (issue 0027)', async (_, row, line) => {
    const name = row.display_name;
    setup('/settings/sources', { getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([row])) });
    await userEvent.click(await screen.findByRole('button', { name }));
    const sheet = await screen.findByRole('dialog');
    expect(await within(sheet).findAllByText(line)).toHaveLength(1);
    expect(within(sheet).queryByRole('button', { name: 'Fetch now' })).toBeNull();
    expect(within(sheet).queryByRole('textbox', { name: /override|own|hours/i })).toBeNull();
    expect(within(sheet).queryByText(/main feed/i)).toBeNull();
    expect(within(sheet).queryByText(/archive/i)).toBeNull();
    // Name, fetch delay, the switch and Delete stay.
    expect(within(sheet).getByRole('button', { name: 'Delete source…' })).toBeInTheDocument();
  });

  it.each([
    ['the next check',{ next_tick_at: new Date(Date.now() + 37 * 60_000 + 30_000).toISOString() }, 'due · next check in 37m'],
    ['that the scheduler is not running', { next_tick_at: null }, 'due · scheduler not running'],
  ])('a due source says %s, and Fetch now reads as optional', async (_, state, label) => {
    const getSourcesHealth = vi.fn().mockResolvedValue(healthResponse([
      healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog', status: 'due', decision: 'fetch_due', folders: [ai] }),
    ]));
    const getSchedulerConfig = vi.fn().mockResolvedValue({ success: true, scheduler: { sync_sources_each_cycle: false, state } });
    setup('/settings/sources', { getSourcesHealth, getSchedulerConfig });
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    expect(await within(sheet).findByText(label)).toBeInTheDocument();
    expect(within(sheet).getByRole('button', { name: 'Fetch now' })).toHaveAttribute('title', expect.stringMatching(/^Optional/));
  });

  it('a sheet opened while its source fetches says Fetching…, though another sheet started it', async () => {
    const getOperationsOverview = vi.fn().mockResolvedValue({ success: true, alerts: [], jobs: [
      { id: 'j1', job_type: 'ingestion_run', status: 'running', trigger: 'manual', source_id: 'simon' },
    ] });
    setup('/settings/sources', { getOperationsOverview });
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    expect(await within(sheet).findByRole('button', { name: 'Fetching…' })).toBeDisabled();
  });

  it('adding a source fetches it straight away, and the toast says so', async () => {
    let finish: (value: unknown) => void = () => {};
    const fetchSourceNow = vi.fn().mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const addSource = vi.fn().mockResolvedValue({ success: true, source_id: 'new-1' });
    const findFeed = vi.fn().mockResolvedValue({ success: true, status: 'feed', feeds: [{ url: 'https://new.example/feed.xml', title: 'New' }] });
    setup('/settings/sources', { addSource, fetchSourceNow, findFeed });
    await userEvent.click(await screen.findByRole('button', { name: 'Add source' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Feed URL or handle'), 'https://new.example/feed.xml');
    const add = within(dialog).getByRole('button', { name: 'Add source' });
    await waitFor(() => expect(add).toBeEnabled());
    await userEvent.click(add);

    await waitFor(() => expect(fetchSourceNow).toHaveBeenCalledWith('new-1', expect.any(Object)));
    expect(await screen.findByText('Added — fetching now')).toBeInTheDocument();
    await act(async () => { finish(runReport({ posts_inserted: 4, sources_with_new: 1 })); });
    expect(await screen.findByText('4 new posts from 1 source')).toBeInTheDocument();
  });

  it('adding several fetches each added source straight away and closes the dialog (issue 0035)', async () => {
    const fetchSourceNow = vi.fn().mockResolvedValue(runReport());
    const addSource = vi.fn((payload: { handle_or_url: string }) => Promise.resolve({ success: true, source_id: `id:${payload.handle_or_url}` }));
    const findFeed = vi.fn((url: string) => Promise.resolve({ success: true, status: 'feed', feeds: [{ url, title: url.toUpperCase() }] }));
    setup('/settings/sources', { addSource, fetchSourceNow, findFeed });
    await userEvent.click(await screen.findByRole('button', { name: 'Add source' }));
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Add several…' }));
    const dialog = screen.getByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText(/^Addresses/), 'https://a.example/feed{enter}https://b.example/feed{enter}https://c.example/feed');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Find feeds' }));
    await within(dialog).findByText('HTTPS://C.EXAMPLE/FEED');
    await userEvent.click(within(screen.getByTestId('several-row:https://b.example/feed')).getByRole('checkbox'));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add 2 sources' }));
    await waitFor(() => expect(fetchSourceNow).toHaveBeenCalledTimes(2));
    expect(fetchSourceNow.mock.calls.map(([id]) => id)).toEqual(['id:https://a.example/feed', 'id:https://c.example/feed']);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Add several sources' })).not.toBeInTheDocument());
  });

  it('links the OPML export of every source (issue 0035)', async () => {
    setup();
    await screen.findByText('Road to VR');
    const link = screen.getByRole('link', { name: 'Export sources (OPML)' });
    expect(link).toHaveAttribute('href', '/api/sources/export.opml');
    expect(link).toHaveAttribute('download');
  });

  it('the Pipecraft template adds pipecraft.me, read by its adapter', async () => {
    const addSource = vi.fn().mockResolvedValue({ success: true, source_id: 'pc-1' });
    setup('/settings/sources', { addSource });
    await userEvent.click(await screen.findByRole('button', { name: 'Add source' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pipecraft (Tornike Gomareli)' }));
    // One address: no field to fill, one plain sentence, and the address stays editable.
    expect(within(dialog).queryByText(/archive scope/i)).toBeNull();
    expect(within(dialog).queryByRole('textbox', { name: /pipecraft/i })).toBeNull();
    expect(within(dialog).queryByText(/adapter|sitemap/i)).toBeNull();
    expect(within(dialog).getByLabelText('Feed URL or handle')).toBeEnabled();
    expect(within(dialog).queryByText(/max posts per fetch|priority/i)).toBeNull();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add source' }));
    await waitFor(() => expect(addSource).toHaveBeenCalled());
    expect(JSON.stringify(addSource.mock.calls[0])).toContain('https://www.pipecraft.me/');
    expect(addSource.mock.calls[0][0]).not.toHaveProperty('max_posts_per_fetch');
    expect(addSource.mock.calls[0][0]).not.toHaveProperty('priority');
  });

  it('the GitHub Trending template adds all languages, or the one typed', async () => {
    const addSource = vi.fn().mockResolvedValue({ success: true, source_id: 'gh-1' });
    setup('/settings/sources', { addSource });
    const add = async (language: string) => {
      await userEvent.click(await screen.findByRole('button', { name: 'Add source' }));
      const dialog = await screen.findByRole('dialog');
      await userEvent.click(within(dialog).getByRole('button', { name: 'GitHub Trending' }));
      if (language) await userEvent.type(within(dialog).getByLabelText(/^Language/), language);
      await userEvent.click(within(dialog).getByRole('button', { name: 'Add source' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    };
    await add('');
    await waitFor(() => expect(addSource).toHaveBeenCalledTimes(1));
    expect(addSource.mock.calls[0][0]).toMatchObject({
      handle_or_url: 'https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml', display_name: 'GitHub Trending',
    });
    await add('Python');
    await waitFor(() => expect(addSource).toHaveBeenCalledTimes(2));
    expect(addSource.mock.calls[1][0]).toMatchObject({
      handle_or_url: 'https://mshibanami.github.io/GitHubTrendingRSS/daily/python.xml', display_name: 'GitHub Trending · Python',
    });
  });

  it('a one-address template already in the sources is not offered again', async () => {
    const getSources = vi.fn().mockResolvedValue({ success: true, total: 1, sources: [
      { id: 'pc', platform: 'rss', handle_or_url: 'https://pipecraft.me', enabled: true, settings: {} },
    ] });
    setup('/settings/sources', { getSources });
    await waitFor(() => expect(getSources).toHaveBeenCalled());
    await userEvent.click(await screen.findByRole('button', { name: 'Add source' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByRole('button', { name: 'Pipecraft (Tornike Gomareli)' })).toBeNull();
    // Others stay, and so do templates with a field (one source per value).
    expect(within(dialog).getByRole('button', { name: 'Gwern' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'GitHub Trending' })).toBeInTheDocument();
  });

  describe('Add source finds the feed of a page (issue 0026)', () => {
    const typePage = async (findFeed: unknown, getSources?: unknown, more: Record<string, unknown> = {}) => {
      const addSource = vi.fn().mockResolvedValue({ success: true, source_id: 'new-1' });
      setup('/settings/sources', { addSource, findFeed, fetchSourceNow: vi.fn().mockResolvedValue(runReport()),
        ...(getSources ? { getSources } : {}), ...more });
      if (getSources) await waitFor(() => expect(getSources).toHaveBeenCalled());
      await userEvent.click(await screen.findByRole('button', { name: 'Add source' }));
      const dialog = await screen.findByRole('dialog');
      const field = within(dialog).getByLabelText('Feed URL or handle');
      await userEvent.type(field, 'borretti.me/article/no-man-is-an-island');
      return { dialog, field, addSource, add: within(dialog).getByRole('button', { name: 'Add source' }) };
    };
    const feed = (url: string, title: string) => ({ url, title });

    it('one feed found: the field becomes it, named by its title, and a quiet line says so', async () => {
      let answer: (value: unknown) => void = () => {};
      const findFeed = vi.fn().mockReturnValue(new Promise((resolve) => { answer = resolve; }));
      const { dialog, field, add, addSource } = await typePage(findFeed);
      expect(within(dialog).getByText('Looking for a feed…')).toBeInTheDocument();
      expect(add).toBeDisabled();
      await waitFor(() => expect(findFeed).toHaveBeenCalledWith('borretti.me/article/no-man-is-an-island'));
      await act(async () => { answer({ success: true, status: 'found', feeds: [feed('https://borretti.me/feed.xml', 'Fernando Borretti')] }); });

      expect(field).toHaveValue('https://borretti.me/feed.xml');
      expect(within(dialog).getByLabelText('Name')).toHaveValue('Fernando Borretti');
      expect(within(dialog).getByText('Found the feed for this page: borretti.me/feed.xml')).toBeInTheDocument();
      field.focus();
      await userEvent.tab();   // leaving the field does not look again: the feed is known
      expect(findFeed).toHaveBeenCalledTimes(1);
      await userEvent.click(add);
      await waitFor(() => expect(addSource).toHaveBeenCalled());
      expect(addSource.mock.calls[0][0]).toMatchObject({ handle_or_url: 'https://borretti.me/feed.xml', display_name: 'Fernando Borretti' });
    });

    it('an answer for an address since typed over is dropped: the field keeps the typing (issue 0029)', async () => {
      let answer: (value: unknown) => void = () => {};
      const findFeed = vi.fn().mockReturnValue(new Promise((resolve) => { answer = resolve; }));
      const { dialog, field, add } = await typePage(findFeed);
      await waitFor(() => expect(findFeed).toHaveBeenCalledWith('borretti.me/article/no-man-is-an-island'));
      await userEvent.type(field, '-2');
      await act(async () => { answer({ success: true, status: 'found', feeds: [feed('https://borretti.me/feed.xml', 'Fernando Borretti')] }); });

      expect(field).toHaveValue('borretti.me/article/no-man-is-an-island-2');
      expect(within(dialog).getByLabelText('Name')).toHaveValue('');
      expect(add).toBeDisabled();
    });

    it('several feeds: a choice list, the first chosen; another can be picked', async () => {
      const findFeed = vi.fn().mockResolvedValue({ success: true, status: 'found', feeds: [
        feed('https://arstechnica.com/ai/feed/', 'AI - Ars Technica'), feed('https://arstechnica.com/feed/', 'Ars Technica'),
      ] });
      const { dialog, field } = await typePage(findFeed);
      const first = await within(dialog).findByRole('radio', { name: /AI - Ars Technica/ });
      expect(first).toBeChecked();
      expect(within(dialog).getByText('This page has 2 feeds')).toBeInTheDocument();
      await userEvent.click(within(dialog).getByRole('radio', { name: /^Ars Technica/ }));
      expect(field).toHaveValue('https://arstechnica.com/feed/');
      expect(within(dialog).getByLabelText('Name')).toHaveValue('Ars Technica');
      expect(within(dialog).getByRole('button', { name: 'Add source' })).toBeEnabled();
    });

    it('a site INSIGHT reads directly is left as typed', async () => {
      const { dialog, field, add } = await typePage(vi.fn().mockResolvedValue({ success: true, status: 'direct', feeds: [] }));
      expect(await within(dialog).findByText('INSIGHT reads this site directly')).toBeInTheDocument();
      expect(field).toHaveValue('borretti.me/article/no-man-is-an-island');
      expect(add).toBeEnabled();
    });

    it('no feed found: Add stays disabled', async () => {
      const { dialog, add } = await typePage(vi.fn().mockResolvedValue({ success: true, status: 'none', feeds: [] }));
      expect(await within(dialog).findByText('No feed found on this page')).toBeInTheDocument();
      expect(add).toBeDisabled();
    });

    describe('no feed: follow the page instead (issue 0028)', () => {
      const none = () => vi.fn().mockResolvedValue({ success: true, status: 'none', feeds: [] });
      const items = [
        { url: 'https://borretti.me/article/a', title: 'Article A', published_at: '2026-10-12T00:00:00+00:00' },
        { url: 'https://borretti.me/article/b', title: 'Article B', published_at: '2026-10-01T00:00:00+00:00' },
      ];

      it('shows the preview, re-previews a new path, and adds with settings.page_watch', async () => {
        const previewPageWatch = vi.fn((_url: string, prefix?: string) => Promise.resolve(prefix
          ? { success: true, prefix, found: 1, sitemap: false, items: items.slice(1) }
          : { success: true, prefix: '/article/', found: 279, sitemap: true, items }));
        const { dialog, add, addSource } = await typePage(none(), undefined, { previewPageWatch });
        await userEvent.click(await within(dialog).findByRole('button', { name: 'Follow this page instead' }));

        expect(await within(dialog).findByText('Found 279 articles under /article/ (from the sitemap)')).toBeInTheDocument();
        expect(previewPageWatch).toHaveBeenCalledWith('borretti.me/article/no-man-is-an-island', undefined);
        expect(within(dialog).getByText('Article A')).toBeInTheDocument();
        expect(within(dialog).getByText('2026-10-12')).toBeInTheDocument();
        const path = within(dialog).getByLabelText(/^Path/);
        expect(path).toHaveValue('/article/');
        expect(add).toBeEnabled();

        await userEvent.clear(path);
        await userEvent.type(path, 'article/b');
        expect(await within(dialog).findByText('Found 1 article under /article/b/')).toBeInTheDocument();
        expect(previewPageWatch).toHaveBeenLastCalledWith('borretti.me/article/no-man-is-an-island', '/article/b/');
        expect(within(dialog).queryByText('Article A')).not.toBeInTheDocument();

        await userEvent.click(add);
        await waitFor(() => expect(addSource).toHaveBeenCalled());
        expect(addSource.mock.calls[0][0]).toMatchObject({
          handle_or_url: 'https://borretti.me/article/no-man-is-an-island', page_watch: { prefix: '/article/b/' } });
      });

      it('a page built with JavaScript says so and cannot be added', async () => {
        const previewPageWatch = vi.fn().mockResolvedValue({ success: true, prefix: '/', found: 0, sitemap: false, items: [] });
        const { dialog, add } = await typePage(none(), undefined, { previewPageWatch });
        await userEvent.click(await within(dialog).findByRole('button', { name: 'Follow this page instead' }));
        expect(await within(dialog).findByText('This page\'s articles can\'t be read without a browser (it builds them with JavaScript).')).toBeInTheDocument();
        expect(add).toBeDisabled();
      });
    });

    it('a found feed already in the sources says so', async () => {
      const getSources = vi.fn().mockResolvedValue({ success: true, total: 1, sources: [
        { id: 'fb', platform: 'rss', handle_or_url: 'https://borretti.me/feed.xml', enabled: true, settings: {} },
      ] });
      const { dialog, add } = await typePage(
        vi.fn().mockResolvedValue({ success: true, status: 'found', feeds: [feed('https://borretti.me/feed.xml', 'Fernando Borretti')] }),
        getSources,
      );
      expect(await within(dialog).findByText('This feed is already in your sources')).toBeInTheDocument();
      expect(add).toBeDisabled();
    });
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

  it('status chips: all, enabled, disabled, failing always; unavailable only with sources; no backoff, which failing counts (issue 0027)', async () => {
    setup();
    await screen.findByText('Road to VR');
    const chips = within(screen.getByRole('group', { name: 'Filter by status' })).getAllByRole('button').map((b) => b.textContent);
    expect(chips).toEqual(['All4', 'Enabled3', 'Disabled1', 'Failing1', 'Unavailable1', 'Scheduled1']);
    await userEvent.click(screen.getByRole('button', { name: /^Enabled/ }));
    expect(rowIds()).toEqual(['flaky', 'tg', 'simon']);
  });

  it('with no unavailable source there is no "Unavailable 0" chip', async () => {
    setup('/settings/sources', { getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([
      healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog', folders: [ai] }),
    ])) });
    await screen.findByText('Simon Willison’s Weblog');
    const chips = within(screen.getByRole('group', { name: 'Filter by status' })).getAllByRole('button').map((b) => b.textContent);
    expect(chips).toEqual(['All1', 'Enabled1', 'Disabled0', 'Failing0', 'Scheduled1']);
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

  it('the bulk bar removes from a track and switches Show in Main feed', async () => {
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

    await userEvent.selectOptions(within(bar).getByRole('combobox', { name: 'Show in Main feed' }), 'off');
    await waitFor(() => expect(api.setSourceMainDigest).toHaveBeenCalledTimes(2));
    expect(api.setSourceMainDigest).toHaveBeenCalledWith('simon', false);
    expect(api.setSourceMainDigest).toHaveBeenCalledWith('off', false);
    expect(within(bar).getByRole('button', { name: 'Enable' })).toBeInTheDocument();
    expect(within(bar).getByRole('button', { name: 'Delete…' })).toBeInTheDocument();
  });

  it('a track header fetches the track; its menu renames, switches Show in Main feed and deletes after a confirmation', async () => {
    const fetchFolderNow = vi.fn().mockResolvedValue(runReport());
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
    const digest = screen.getByRole('menuitemcheckbox', { name: 'Show in Main feed' });
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

  it.each([
    ['all of its sources are out', [false, false], 'false', true],
    ['its sources differ', [true, false], 'mixed', true],
    ['all of its sources are in', [true, true], 'true', false],
  ])('a track’s main-feed check follows its sources, not a stored track flag: %s', async (_, inMain, checked, next) => {
    const getSourcesHealth = vi.fn().mockResolvedValue(healthResponse([
      healthRow({ source_id: 'a', display_name: 'Paper A', in_main_digest: inMain[0], folders: [ai] }),
      healthRow({ source_id: 'b', display_name: 'Paper B', in_main_digest: inMain[1], folders: [ai] }),
    ]));
    // The track's own stored flag says "in"; it must not decide the check.
    const getFolders = vi.fn().mockResolvedValue({ success: true, folders: [{ ...ai, sort_order: 0, exclude_from_main_digest: false }] });
    const { api } = setup('/settings/sources?group=track', { getSourcesHealth, getFolders });
    await screen.findByText('Paper A');
    await userEvent.click(screen.getByRole('button', { name: 'More actions for track AI engineering' }));
    const item = screen.getByRole('menuitemcheckbox', { name: /main feed/i });
    expect(item).toHaveAttribute('aria-checked', checked);
    await userEvent.click(item);
    await waitFor(() => expect(api.setTrackMainDigest).toHaveBeenCalledWith('f-ai', next));
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

  it('how often it is fetched: plain words, and your own hours are validated before the API (issue 0027)', async () => {
    const setCadenceOverride = vi.fn().mockResolvedValue({
      success: true,
      row: healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog', override_hours: 6, interval_hours: 6, interval_basis: 'override', folders: [ai] }),
    });
    setup('/settings/sources', { setCadenceOverride });
    await userEvent.click(await screen.findByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    const input = within(sheet).getByRole('textbox', { name: /set your own/i });
    expect(within(sheet).getByText(/^Fetched every /)).toBeInTheDocument();
    expect(sheet).not.toHaveTextContent(/probation|tier|backlog guard|kind floor|override/i);

    await userEvent.type(input, '3000');
    await userEvent.click(within(sheet).getByRole('button', { name: 'Save hours' }));
    expect(await within(sheet).findByText(/between 1 and 2160 hours/i)).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(setCadenceOverride).not.toHaveBeenCalled();

    await userEvent.clear(input);
    await userEvent.type(input, 'abc');
    await userEvent.click(within(sheet).getByRole('button', { name: 'Save hours' }));
    expect(setCadenceOverride).not.toHaveBeenCalled();

    await userEvent.clear(input);
    await userEvent.type(input, '6');
    await userEvent.click(within(sheet).getByRole('button', { name: 'Save hours' }));
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
