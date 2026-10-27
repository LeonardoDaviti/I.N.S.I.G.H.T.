import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SourcesConfig from './SourcesConfig';
import { healthResponse, healthRow, runReport } from '../components/ops/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api, ArchiveCatalogEntry, ArchiveStatusResponse, JobRun, SchedulerConfig } from '../services/api';


const MINUTE = 60_000;

function scheduler(overrides: Partial<SchedulerConfig> = {}): SchedulerConfig {
  return {
    interval_hours: 24,
    sync_sources_each_cycle: true,
    ingest_tick_minutes: 60,
    state: {
      last_tick_at: new Date(Date.now() - 10 * MINUTE).toISOString(),
      next_tick_at: new Date(Date.now() + 50 * MINUTE).toISOString(),
    },
    ...overrides,
  };
}

function job(overrides: Partial<JobRun> = {}): JobRun {
  return {
    id: 'job-1',
    job_type: 'ingestion_run',
    job_label: 'Ingestion run',
    status: 'completed',
    trigger: 'scheduler',
    message: '12 due, 66 deferred, 0 failed; 48 new posts',
    started_at: '2026-10-09T10:00:00+00:00',
    finished_at: '2026-10-09T10:01:05+00:00',
    ...overrides,
  };
}


function catalogEntry(overrides: Partial<ArchiveCatalogEntry> = {}): ArchiveCatalogEntry {
  return {
    source_id: 'mkbhd',
    display_name: 'Marques Brownlee',
    platform: 'youtube',
    enabled: true,
    kind: 'youtube_channel',
    stored_posts: 120,
    available_posts: 1722,
    backlog_posts: 1602,
    archive_status: 'partial',
    resume_ready: false,
    ...overrides,
  };
}

function archiveStatus(overrides: Partial<ArchiveStatusResponse> = {}): ArchiveStatusResponse {
  return {
    success: true,
    archive: { stored_posts: 120, available_posts: 1722, resume_ready: true, checkpoint: { collected_posts: 80, pages_fetched: 4 },
      rate_limit: { page_delay_seconds: 5, batch_size: 10, batch_cooldown_seconds: 30 } },
    support: { kind: 'youtube_channel', available_basis: 'exact', archivable: true, reason: null, unavailable: false, live_fetch_limit: 50 },
    latest_job: null,
    ...overrides,
  };
}

function setup({
  route = '/settings/sources?tab=ingestion',
  overrides = {},
}: { route?: string; overrides?: Partial<Record<keyof Api, unknown>> } = {}) {
  const methods = {
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog' })])),
    getSources: vi.fn().mockResolvedValue({ success: true, sources: [], total: 0 }),
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [] }),
    getOperationsOverview: vi.fn().mockResolvedValue({ success: true, jobs: [job()], alerts: [] }),
    getSchedulerConfig: vi.fn().mockResolvedValue({ success: true, scheduler: scheduler() }),
    getOperationJob: vi.fn().mockResolvedValue({ success: true, job: job({ payload: { ...runReport() } }) }),
    runIngestionCycle: vi.fn().mockResolvedValue(runReport({ posts_inserted: 7 })),
    getVersion: vi.fn().mockResolvedValue({ version: null, commit: null, commit_date: null }),
    ...overrides,
  };
  const utils = renderWithProviders(<SourcesConfig />, { api: makeFakeApi(methods), route });
  return { ...utils, api: methods };
}

describe('Sources → ingestion tab', () => {
  it('is the third tab; Run due sources runs a cycle and shows its report', async () => {
    const { api } = setup();
    expect(await screen.findByRole('tab', { name: 'ingestion' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['sources', 'connections', 'ingestion']);

    await userEvent.click(await screen.findByRole('button', { name: 'Run due sources' }));
    await waitFor(() => expect(api.runIngestionCycle).toHaveBeenCalledWith(expect.objectContaining({ force: false })));
    const lastRun = await screen.findByRole('region', { name: 'Last run' });
    expect((await within(lastRun).findAllByText(/7 new posts/)).length).toBeGreaterThan(0);
  });

  it('before anything runs here, the last run is the newest stored ingestion run', async () => {
    setup({
      overrides: {
        getOperationsOverview: vi.fn().mockResolvedValue({
          success: true,
          alerts: [],
          jobs: [
            job({ id: 'b1', job_type: 'daily_briefing', job_label: 'Daily briefing', message: 'Briefing written' }),
            job({ id: 'r1', payload: { ...runReport({ posts_inserted: 21 }) } }),
          ],
        }),
      },
    });
    const lastRun = await screen.findByRole('region', { name: 'Last run' });
    expect((await within(lastRun).findAllByText(/21 new posts/)).length).toBeGreaterThan(0);
  });

  it('a stored run from before issue 0005 still shows; its enrichment field is ignored', async () => {
    setup({
      overrides: {
        getOperationsOverview: vi.fn().mockResolvedValue({
          success: true,
          alerts: [],
          jobs: [job({ id: 'r1', payload: { ...runReport(), enrichment: { skipped: 'analysis off' } } })],
        }),
      },
    });
    const lastRun = await screen.findByRole('region', { name: 'Last run' });
    expect((await within(lastRun).findAllByText(/48 new posts/)).length).toBeGreaterThan(0);
    expect(within(lastRun).queryByText(/enrich/i)).toBeNull();
  });

  it('the scheduler status says how often it checks and when it next ticks', async () => {
    setup();
    const status = await screen.findByRole('region', { name: 'Scheduler' });
    expect(await within(status).findByText(/checks for due sources every 60 min/i)).toBeInTheDocument();
    expect(within(status).getByText(/next tick in 4\dm/i)).toBeInTheDocument();
    expect(within(status).queryByText(/not running/i)).toBeNull();
  });

  it.each([
    ['has never ticked', { last_tick_at: null, next_tick_at: null }, /has not recorded a tick/i],
    ['last ticked hours ago', { last_tick_at: new Date(Date.now() - 5 * 60 * MINUTE).toISOString(), next_tick_at: null }, /last ticked 5h/i],
  ])('a scheduler that %s is shown as not running', async (_, state, why) => {
    setup({ overrides: { getSchedulerConfig: vi.fn().mockResolvedValue({ success: true, scheduler: scheduler({ state }) }) } });
    const status = await screen.findByRole('region', { name: 'Scheduler' });
    expect(await within(status).findByText('Ingestion is not running')).toBeInTheDocument();
    expect(within(status).getByText(why)).toBeInTheDocument();
    expect(within(status).queryByText(/next tick in/i)).toBeNull();
  });

  it('when the scheduler cannot be read, it says so instead of guessing', async () => {
    setup({ overrides: { getSchedulerConfig: vi.fn().mockResolvedValue({ success: false, error: 'boom' }) } });
    const status = await screen.findByRole('region', { name: 'Scheduler' });
    expect(await within(status).findByText(/could not read the scheduler/i)).toBeInTheDocument();
  });

  it('the tick interval can be changed; the dialog has no briefing settings', async () => {
    const updateSchedulerConfig = vi.fn().mockImplementation((config: SchedulerConfig) => Promise.resolve({ success: true, scheduler: scheduler(config) }));
    setup({ overrides: { updateSchedulerConfig } });
    await userEvent.click(await screen.findByRole('button', { name: 'Change interval' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByText(/briefing/i)).toBeNull();
    const tick = within(dialog).getByLabelText(/check for due sources every/i);
    await userEvent.clear(tick);
    await userEvent.type(tick, '30');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updateSchedulerConfig).toHaveBeenCalledWith(expect.objectContaining({ ingest_tick_minutes: 30 })));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('jobs lists the history; a job opens with what it delivered, then its per-source events', async () => {
    // A job stored before issue 0021: the old summary, and the events that only repeated it.
    const stored = job({
      id: 'r1',
      payload: {
        ...runReport({ posts_inserted: 9, sources_with_new: undefined, inserted_by_source: [{ source_id: 'simon', display_name: 'Simon Willison’s Weblog', inserted: 9 }] }),
        summary: '2 due, 76 deferred, 0 failed; 9 new posts',
        enrichment: { skipped: 'analysis off' },
        events: [
          { at: '2026-10-09T10:00:00+00:00', level: 'info', message: 'Ingestion decided', data: { phase: 'decided' } },
          { at: '2026-10-09T10:00:01+00:00', level: 'info', message: 'Simon Willison’s Weblog: 9 new of 20 · 1 of 2 sources', data: { phase: 'source' } },
          { at: '2026-10-09T10:00:02+00:00', level: 'info', message: 'Ingestion saved', data: { phase: 'saved' } },
          { at: '2026-10-09T10:00:03+00:00', level: 'success', message: '12 due, 66 deferred, 0 failed; 48 new posts', status: 'success' },
        ],
      },
    });
    const getOperationJob = vi.fn().mockResolvedValue({ success: true, job: stored });
    setup({
      overrides: {
        getOperationJob,
        getOperationsOverview: vi.fn().mockResolvedValue({
          success: true,
          alerts: [],
          jobs: [stored, job({ id: 'b1', job_type: 'daily_briefing', job_label: 'Daily briefing', message: 'Briefing written' })],
        }),
      },
    });
    await userEvent.click(await screen.findByRole('link', { name: 'jobs' }));
    const history = await screen.findByRole('region', { name: 'Recent jobs' });
    expect(await within(history).findByText('Briefing written')).toBeInTheDocument();
    expect(within(history).getByText('9 new posts from 1 source')).toBeInTheDocument();
    expect(within(history).queryByText(/deferred/)).toBeNull();
    await userEvent.click(within(history).getAllByRole('button')[0]);
    await waitFor(() => expect(getOperationJob).toHaveBeenCalledWith('r1'));
    const detail = screen.getByRole('region', { name: 'Ingestion run' });
    expect(await within(detail).findByRole('heading', { name: '9 new posts from 1 source' })).toBeInTheDocument();
    expect(within(detail).getByRole('link', { name: /Simon Willison’s Weblog/ })).toHaveAttribute('href', '/read/source/simon');
    const events = within(detail).getByRole('list', { name: 'Events' });
    expect(within(events).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      expect.stringContaining('Simon Willison’s Weblog: 9 new of 20 · 1 of 2 sources'),
    ]);
    expect(within(detail).queryByText(/deferred|enrich|Ingestion decided/i)).toBeNull();
  });

  it('a running run says how many sources are left and how many posts are new', async () => {
    const running = job({ id: 'r2', status: 'running', finished_at: null, message: 'Forced ingestion cycle',
      payload: { sources: { done: 52, total: 81 }, new_posts: 334, events: [{ level: 'info', message: 'r/viture: 3 new of 25 · 52 of 81 sources' }] } });
    setup({ route: '/settings/sources?tab=ingestion&sub=jobs&job=r2', overrides: { getOperationJob: vi.fn().mockResolvedValue({ success: true, job: running }) } });
    const detail = await screen.findByRole('region', { name: 'Ingestion run' });
    expect(await within(detail).findByText('52 of 81 sources · 334 new posts')).toBeInTheDocument();
    expect(within(detail).getByText('r/viture: 3 new of 25 · 52 of 81 sources')).toBeInTheDocument();
  });

  it('archive jobs show their progress in the history and their result in the detail', async () => {
    const getOperationJob = vi.fn().mockResolvedValue({
      success: true,
      job: job({ id: 'a2', job_type: 'archive_source', job_label: 'Archive', status: 'success', source_display_name: 'Marques Brownlee',
        message: 'Archived 500 posts', payload: { posts_fetched: 500, posts_inserted: 475, posts_updated: 25, pages_fetched: 25, stored_posts: 500 } }),
    });
    setup({
      overrides: {
        getOperationJob,
        getOperationsOverview: vi.fn().mockResolvedValue({
          success: true,
          alerts: [],
          jobs: [
            job({ id: 'a1', job_type: 'archive_source', job_label: 'Archive', status: 'running', progress: 42, finished_at: null,
              source_display_name: 'iFixit', message: 'Archive' }),
            job({ id: 'a2', job_type: 'archive_source', job_label: 'Archive', status: 'success', source_display_name: 'Marques Brownlee',
              message: 'Archived 500 posts' }),
          ],
        }),
      },
    });
    await userEvent.click(await screen.findByRole('link', { name: 'jobs' }));
    const history = await screen.findByRole('region', { name: 'Recent jobs' });
    const running = (await within(history).findByText(/iFixit/)).closest('button') as HTMLElement;
    expect(within(running).getByRole('progressbar', { name: 'Archive progress' })).toHaveAttribute('aria-valuenow', '42');
    expect(within(running).getByText('42%')).toBeInTheDocument();
    await userEvent.click(within(history).getByText(/Marques Brownlee/));
    const detail = await screen.findByRole('region', { name: 'Archive' });
    expect(await within(detail).findByText('500 posts fetched, 475 new, 25 updated · 25 pages · 500 stored')).toBeInTheDocument();
  });

  it('archive lists every source with its archive status and backlog', async () => {
    setup({
      overrides: {
        getArchiveCatalog: vi.fn().mockResolvedValue({
          success: true,
          total: 3,
          sources: [
            catalogEntry({ last_inspected_at: new Date(Date.now() - 3 * 86_400_000).toISOString() }),
            catalogEntry({ source_id: 'simon', display_name: 'Simon Willison’s Weblog', platform: 'rss', kind: 'generic_rss',
              stored_posts: 30, available_posts: 30, backlog_posts: 0, archive_status: 'archived' }),
            catalogEntry({ source_id: 'kaitchup', display_name: 'The Kaitchup', platform: 'substack', kind: 'substack',
              stored_posts: 0, available_posts: null, backlog_posts: null, archive_status: 'not_archived' }),
          ],
        }),
      },
    });
    await userEvent.click(await screen.findByRole('link', { name: 'archive' }));
    const catalog = await screen.findByRole('region', { name: 'Catalog' });
    const mkbhd = (await within(catalog).findByText('Marques Brownlee')).closest('li') as HTMLElement;
    expect(within(mkbhd).getByText('partial')).toBeInTheDocument();
    expect(within(mkbhd).getByText(/120 of 1,722 stored/)).toBeInTheDocument();
    expect(within(mkbhd).getByText(/1,602 in backlog · measured 3d ago/)).toBeInTheDocument();
    const simon = within(catalog).getByText('Simon Willison’s Weblog').closest('li') as HTMLElement;
    expect(within(simon).getByText('archived')).toBeInTheDocument();
    expect(within(simon).getByText(/no backlog/)).toBeInTheDocument();
    const kaitchup = within(catalog).getByText('The Kaitchup').closest('li') as HTMLElement;
    expect(within(kaitchup).getByText('not archived')).toBeInTheDocument();
    expect(within(kaitchup).getByText(/0 stored · not measured yet/)).toBeInTheDocument();

    await userEvent.type(within(catalog).getByRole('searchbox', { name: 'Search the catalog' }), 'kait');
    expect(within(catalog).queryByText('Marques Brownlee')).toBeNull();
    expect(within(catalog).getByText('The Kaitchup')).toBeInTheDocument();
  });

  it('a URL-named source is named from its address, never by its id (issue 0027)', async () => {
    setup({
      overrides: {
        getArchiveCatalog: vi.fn().mockResolvedValue({ success: true, total: 1, sources: [
          catalogEntry({ source_id: '00000000-0000-4000-8000-000000000042', display_name: 'https://rss.arxiv.org/rss/cs.CL', platform: 'rss', kind: 'generic_rss' }),
        ] }),
      },
    });
    await userEvent.click(await screen.findByRole('link', { name: 'archive' }));
    const catalog = await screen.findByRole('region', { name: 'Catalog' });
    expect(await within(catalog).findByText('arXiv cs.CL')).toBeInTheDocument();
    expect(catalog).not.toHaveTextContent('00000000-0000-4000-8000-000000000042');
  });

  it('a backfill runs with the chosen resume, page delay, batch size and cooldown', async () => {
    const planSourceArchive = vi.fn().mockResolvedValue({
      available_posts: 1722, available_basis: 'exact', older_posts: 1602, estimated_pages: 21,
      estimated_seconds: 3600, current_stored_posts: 120, resume: true, resume_available: true,
      rate_limit: { page_delay_seconds: 8, batch_size: 5, batch_cooldown_seconds: 60 },
    });
    const startSourceArchive = vi.fn().mockResolvedValue({ job_id: 'arch-1' });
    setup({
      route: '/settings/sources?tab=ingestion&sub=archive',
      overrides: {
        getArchiveCatalog: vi.fn().mockResolvedValue({ success: true, total: 1, sources: [catalogEntry({ resume_ready: true })] }),
        getSourceArchive: vi.fn().mockResolvedValue(archiveStatus()),
        planSourceArchive,
        startSourceArchive,
        getOperationJob: vi.fn().mockResolvedValue({ success: true, job: job({ id: 'arch-1', job_type: 'archive_source', status: 'running', progress: 5, finished_at: null }) }),
      },
    });
    const catalog = await screen.findByRole('region', { name: 'Catalog' });
    await userEvent.click(await within(catalog).findByRole('button', { name: /Marques Brownlee/ }));
    const backfill = await screen.findByRole('region', { name: 'Marques Brownlee' });
    expect(await within(backfill).findByLabelText(/Continue from the last run/)).toBeChecked();

    for (const [label, value] of [['Page delay (s)', '8'], ['Batch size', '5'], ['Batch cooldown (s)', '60']]) {
      const field = within(backfill).getByLabelText(label);
      await userEvent.clear(field);
      await userEvent.type(field, value);
    }
    await userEvent.click(within(backfill).getByRole('button', { name: 'Plan' }));
    const rate = { pageDelaySeconds: 8, batchSize: 5, batchCooldownSeconds: 60 };
    await waitFor(() => expect(planSourceArchive).toHaveBeenCalledWith('mkbhd', true, rate));
    await userEvent.click(await within(backfill).findByRole('button', { name: 'Resume archive' }));
    await waitFor(() => expect(startSourceArchive).toHaveBeenCalledWith('mkbhd', true, rate));
    expect(await within(backfill).findByText('5%')).toBeInTheDocument();
  });

  it('logs load the application log and switch to another', async () => {
    const getIngestionLogs = vi.fn().mockImplementation((log: string) => Promise.resolve({
      success: true,
      log,
      available_logs: ['application', 'errors', 'youtube'],
      exists: true,
      lines: log === 'errors' ? ['ERROR telegram: session expired'] : ['INFO fetched Simon Willison', 'INFO 7 new posts'],
    }));
    setup({ route: '/settings/sources?tab=ingestion&sub=logs', overrides: { getIngestionLogs } });
    const logs = await screen.findByRole('region', { name: 'Log' });
    expect(await within(logs).findByText(/INFO 7 new posts/)).toBeInTheDocument();
    expect(getIngestionLogs).toHaveBeenCalledWith('application', expect.any(Number));
    expect(within(logs).getByText(/last 2 lines/)).toBeInTheDocument();
    await userEvent.selectOptions(within(logs).getByLabelText('Log file'), 'errors');
    expect(await within(logs).findByText(/session expired/)).toBeInTheDocument();
    expect(within(logs).queryByText(/7 new posts/)).toBeNull();
  });

  it('a log that cannot be read says so', async () => {
    setup({
      route: '/settings/sources?tab=ingestion&sub=logs',
      overrides: { getIngestionLogs: vi.fn().mockRejectedValue(new Error('Unsupported log')) },
    });
    const logs = await screen.findByRole('region', { name: 'Log' });
    expect(await within(logs).findByText(/Could not read the log: Unsupported log/)).toBeInTheDocument();
  });

  it('a ?job= link (from a run toast) opens that job', async () => {
    const { api } = setup({ route: '/settings/sources?tab=ingestion&sub=jobs&job=r9' });
    await screen.findByRole('region', { name: 'Recent jobs' });
    await waitFor(() => expect(api.getOperationJob).toHaveBeenCalledWith('r9'));
  });

  it('no briefing or source-registry controls, and no Fetch one source', async () => {
    setup();
    await screen.findByRole('region', { name: 'Last run' });
    expect(screen.queryByRole('region', { name: 'Write a briefing' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Source registry' })).toBeNull();
    expect(screen.queryByText(/briefing/i)).toBeNull();
    expect(screen.queryByText(/fetch one source/i)).toBeNull();
  });

  it('ends with the running version: a dev build in tests, on every view', async () => {
    const { api } = setup();
    expect(await screen.findByText('I.N.S.I.G.H.T. dev build')).toBeInTheDocument();
    expect(api.getVersion).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('link', { name: 'jobs' }));
    expect(await screen.findByText('I.N.S.I.G.H.T. dev build')).toBeInTheDocument();
  });

  it('an API on another build says the two are out of step', async () => {
    setup({ overrides: { getVersion: vi.fn().mockResolvedValue({ version: 'Mark IX v9.0', commit: '0b1458d', commit_date: '2026-10-11' }) } });
    expect(await screen.findByText('I.N.S.I.G.H.T. Web dev build · API Mark IX v9.0 · 0b1458d, out of step')).toBeInTheDocument();
  });
});
