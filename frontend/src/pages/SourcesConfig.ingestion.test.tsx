import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SourcesConfig from './SourcesConfig';
import { healthResponse, healthRow, runReport } from '../components/ops/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api, JobRun, SchedulerConfig } from '../services/api';

vi.mock('../services/trackApi', () => ({
  renameTrack: vi.fn().mockResolvedValue(undefined),
  setTrackMainDigest: vi.fn().mockResolvedValue(undefined),
}));

const MINUTE = 60_000;

function scheduler(overrides: Partial<SchedulerConfig> = {}): SchedulerConfig {
  return {
    interval_hours: 24,
    sync_sources_each_cycle: true,
    generate_daily_briefing: true,
    generate_topic_briefing: false,
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

function setup({
  route = '/settings/sources?tab=ingestion',
  analysis = false,
  overrides = {},
}: { route?: string; analysis?: boolean; overrides?: Partial<Record<keyof Api, unknown>> } = {}) {
  const methods = {
    getConfig: vi.fn().mockResolvedValue({ analysis_enabled: analysis }),
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog' })])),
    getSourcesWithSettings: vi.fn().mockResolvedValue({ success: true, sources: [], total: 0 }),
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [] }),
    getExperts: vi.fn().mockResolvedValue({ success: true, experts: [] }),
    getOperationsOverview: vi.fn().mockResolvedValue({ success: true, jobs: [job()], alerts: [] }),
    getSchedulerConfig: vi.fn().mockResolvedValue({ success: true, scheduler: scheduler() }),
    getOperationJob: vi.fn().mockResolvedValue({ success: true, job: job({ payload: runReport() }) }),
    runIngestionCycle: vi.fn().mockResolvedValue(runReport({ summary: '3 due, 75 deferred, 0 failed; 7 new posts', posts_inserted: 7 })),
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
            job({ id: 'r1', payload: runReport({ summary: '5 due, 70 deferred, 1 failed; 21 new posts', posts_inserted: 21 }) }),
          ],
        }),
      },
    });
    const lastRun = await screen.findByRole('region', { name: 'Last run' });
    expect((await within(lastRun).findAllByText(/21 new posts/)).length).toBeGreaterThan(0);
  });

  it('reading-only, the last run says its enrichment was skipped', async () => {
    setup({
      overrides: {
        getOperationsOverview: vi.fn().mockResolvedValue({
          success: true,
          alerts: [],
          jobs: [job({ id: 'r1', payload: runReport({ enrichment: { skipped: 'analysis off' } }) })],
        }),
      },
    });
    const lastRun = await screen.findByRole('region', { name: 'Last run' });
    expect(await within(lastRun).findByText('Enrichment skipped (analysis off)')).toBeInTheDocument();
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

  it('the tick interval can be changed; reading-only, the dialog has no briefing settings', async () => {
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

  it('jobs lists the history; a job opens its report and events', async () => {
    const getOperationJob = vi.fn().mockResolvedValue({
      success: true,
      job: job({ id: 'r1', payload: { ...runReport({ summary: '2 due, 76 deferred, 0 failed; 9 new posts', posts_inserted: 9 }), events: [{ at: '2026-10-09T10:00:01+00:00', level: 'info', message: 'Fetched Simon' }] } }),
    });
    setup({
      overrides: {
        getOperationJob,
        getOperationsOverview: vi.fn().mockResolvedValue({
          success: true,
          alerts: [],
          jobs: [job({ id: 'r1' }), job({ id: 'b1', job_type: 'daily_briefing', job_label: 'Daily briefing', message: 'Briefing written' })],
        }),
      },
    });
    await userEvent.click(await screen.findByRole('link', { name: 'jobs' }));
    const history = await screen.findByRole('region', { name: 'Recent jobs' });
    expect(await within(history).findByText('Briefing written')).toBeInTheDocument();
    await userEvent.click(within(history).getAllByRole('button')[0]);
    await waitFor(() => expect(getOperationJob).toHaveBeenCalledWith('r1'));
    const detail = screen.getByRole('region', { name: 'Ingestion run' });
    expect((await within(detail).findAllByText(/9 new posts/)).length).toBeGreaterThan(0);
    expect(within(detail).getByText('Fetched Simon')).toBeInTheDocument();
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

  it('a ?job= link (from a run toast) opens that job', async () => {
    const { api } = setup({ route: '/settings/sources?tab=ingestion&sub=jobs&job=r9' });
    await screen.findByRole('region', { name: 'Recent jobs' });
    await waitFor(() => expect(api.getOperationJob).toHaveBeenCalledWith('r9'));
  });

  it('reading-only: no briefing or source-registry controls, and no Fetch one source', async () => {
    setup();
    await screen.findByRole('region', { name: 'Last run' });
    expect(screen.queryByRole('region', { name: 'Write a briefing' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Source registry' })).toBeNull();
    expect(screen.queryByText(/briefing/i)).toBeNull();
    expect(screen.queryByText(/fetch one source/i)).toBeNull();
  });

  it('with analysis on, briefings and the source registry are there too', async () => {
    const generateBriefing = vi.fn().mockResolvedValue({ success: true });
    const syncSources = vi.fn().mockResolvedValue({ success: true });
    setup({ analysis: true, overrides: { generateBriefing, syncSources } });
    const briefing = await screen.findByRole('region', { name: 'Write a briefing' });
    await userEvent.click(within(briefing).getByRole('button', { name: 'Daily briefing' }));
    await waitFor(() => expect(generateBriefing).toHaveBeenCalledTimes(1));
    const registry = screen.getByRole('region', { name: 'Source registry' });
    await userEvent.click(within(registry).getByRole('button', { name: 'JSON → database' }));
    await waitFor(() => expect(syncSources).toHaveBeenCalledWith('json-to-db'));
    expect(screen.queryByText(/fetch one source/i)).toBeNull();
  });
});
