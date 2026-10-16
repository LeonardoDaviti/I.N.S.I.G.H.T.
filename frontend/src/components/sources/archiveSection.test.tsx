import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';

import ArchiveSection from './ArchiveSection';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { ArchivePlan, ArchiveStatusResponse, ArchiveSupport, JobRun } from '../../services/api';

const support = (over: Partial<ArchiveSupport> = {}): ArchiveSupport => ({
  kind: 'youtube_channel',
  available_basis: 'exact',
  archivable: true,
  reason: null,
  unavailable: false,
  live_fetch_limit: 50,
  ...over,
});

const status = (over: Partial<ArchiveStatusResponse> = {}): ArchiveStatusResponse => ({
  success: true,
  archive: { stored_posts: 25, available_posts: 1722, last_inspected_at: '2026-10-08T10:00:00Z', resume_ready: false },
  support: support(),
  latest_job: null,
  ...over,
});

const plan = (over: Partial<ArchivePlan> = {}): ArchivePlan => ({
  available_posts: 1722,
  available_basis: 'exact',
  desired_posts: 500,
  remaining_posts: 500,
  estimated_pages: 25,
  estimated_seconds: 7800,
  resume: false,
  resume_available: false,
  rate_limit: { page_delay_seconds: 5, batch_size: 10, batch_cooldown_seconds: 30 },
  ...over,
});

const job = (over: Partial<JobRun> = {}): JobRun => ({
  id: 'job-1',
  job_type: 'archive_source',
  status: 'running',
  trigger: 'manual',
  progress: 40,
  payload: { events: [{ at: '2026-10-11T10:00:00Z', level: 'info', message: 'Fetched youtube_channel page 10' }] },
  started_at: '2026-10-11T09:59:00Z',
  ...over,
});

function setup(api: Record<string, unknown>) {
  return renderWithProviders(<ArchiveSection sourceId="s1" />, { api: makeFakeApi(api) });
}

describe('ArchiveSection', () => {
  it('shows what is stored, what the source has, and presets up to all of it', async () => {
    setup({ getSourceArchive: vi.fn().mockResolvedValue(status()) });
    const facts = await screen.findByRole('group', { name: 'Archive counts' });
    expect(within(facts).getByText('Stored')).toBeInTheDocument();
    expect(within(facts).getByText('25')).toBeInTheDocument();
    expect(within(facts).getByText('1,722')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'All 1,722' })).toBeInTheDocument();
    expect(screen.getByLabelText('Posts to fetch')).toHaveValue('500');
    expect(screen.queryByRole('button', { name: /run archive/i })).not.toBeInTheDocument();
  });

  it('a source that cannot archive is one quiet line saying why', async () => {
    setup({
      getSourceArchive: vi.fn().mockResolvedValue(status({
        archive: { stored_posts: 228, available_posts: 25 },
        support: support({ kind: 'generic_rss', available_basis: 'feed_window', archivable: false,
          reason: 'This feed only lists its latest 25 posts, and every fetch already reads up to 50.' }),
      })),
    });
    expect(await screen.findByText(/only lists its latest 25 posts/)).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Archive counts' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Plan' })).not.toBeInTheDocument();
  });

  it('says honestly when the source reports no total', async () => {
    setup({
      getSourceArchive: vi.fn().mockResolvedValue(status({
        archive: { stored_posts: 40, available_posts: null },
        support: support({ kind: 'substack', available_basis: 'unknown' }),
      })),
    });
    expect(await screen.findByText('at least 40')).toBeInTheDocument();
    expect(screen.getByText(/does not report a total/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^All/ })).not.toBeInTheDocument();
  });

  it('clamps the wanted count to what is available', async () => {
    setup({ getSourceArchive: vi.fn().mockResolvedValue(status()) });
    const field = await screen.findByLabelText('Posts to fetch');
    fireEvent.change(field, { target: { value: '90000' } });
    fireEvent.blur(field);
    expect(field).toHaveValue('1722');
  });

  it('plans before it runs, then follows the job to its result', async () => {
    const planSourceArchive = vi.fn().mockResolvedValue(plan());
    const startSourceArchive = vi.fn().mockResolvedValue({ job_id: 'job-1' });
    const getOperationJob = vi.fn()
      .mockResolvedValueOnce({ success: true, job: job() })
      .mockResolvedValue({ success: true, job: job({ status: 'success', progress: 100, finished_at: '2026-10-11T10:05:00Z',
        payload: { posts_fetched: 500, posts_inserted: 475, pages_fetched: 25 } }) });
    const getSourceArchive = vi.fn().mockResolvedValue(status());
    setup({ getSourceArchive, planSourceArchive, startSourceArchive, getOperationJob });

    fireEvent.click(await screen.findByRole('button', { name: 'Plan' }));
    expect(planSourceArchive).toHaveBeenCalledWith('s1', 500, false);
    expect(await screen.findByText(/25 pages/)).toBeInTheDocument();
    expect(screen.getByText(/~2h 10m/)).toBeInTheDocument();
    expect(screen.getByText(/5s between pages, 30s every 10 pages/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Run archive' }));
    expect(startSourceArchive).toHaveBeenCalledWith('s1', 500, false);
    expect(await screen.findByText('40%')).toBeInTheDocument();
    expect(screen.getByText('Fetched youtube_channel page 10')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run archive' })).not.toBeInTheDocument();

    expect(await screen.findByText(/500 posts fetched, 475 new/, {}, { timeout: 8000 })).toBeInTheDocument();
  }, 12_000);

  it('changing the count after a plan asks for a new plan', async () => {
    setup({ getSourceArchive: vi.fn().mockResolvedValue(status()), planSourceArchive: vi.fn().mockResolvedValue(plan()) });
    fireEvent.click(await screen.findByRole('button', { name: 'Plan' }));
    await screen.findByRole('button', { name: 'Run archive' });
    fireEvent.click(screen.getByRole('button', { name: '100' }));
    expect(screen.queryByRole('button', { name: 'Run archive' })).not.toBeInTheDocument();
  });

  it('a paused archive says why and resumes from its checkpoint', async () => {
    const startSourceArchive = vi.fn().mockResolvedValue({ job_id: 'job-3' });
    setup({
      getSourceArchive: vi.fn().mockResolvedValue(status({
        archive: { stored_posts: 145, available_posts: 1722, resume_ready: true, checkpoint: { collected_posts: 120, pages_fetched: 6 } },
        latest_job: { id: 'job-2', status: 'success', message: 'Paused: reddit.com is limiting us; resume later',
          finished_at: '2026-10-11T10:05:00Z',
          result: { posts_fetched: 120, posts_inserted: 120, pages_fetched: 6, paused: true, paused_reason: 'reddit.com is limiting us' } },
      })),
      startSourceArchive,
      getOperationJob: vi.fn().mockResolvedValue({ success: true, job: job({ id: 'job-3' }) }),
    });
    const notice = await screen.findByRole('alert');
    expect(within(notice).getByText('Paused: reddit.com is limiting us')).toBeInTheDocument();
    fireEvent.click(within(notice).getByRole('button', { name: 'Resume' }));
    expect(startSourceArchive).toHaveBeenCalledWith('s1', 500, true);
  });

  it('offers to resume a checkpointed run', async () => {
    const planSourceArchive = vi.fn().mockResolvedValue(plan({ resume: true, resume_available: true, remaining_posts: 380 }));
    const startSourceArchive = vi.fn().mockResolvedValue({ job_id: 'job-2' });
    setup({
      getSourceArchive: vi.fn().mockResolvedValue(status({
        archive: { stored_posts: 145, available_posts: 1722, resume_ready: true, checkpoint: { collected_posts: 120, pages_fetched: 6 } },
      })),
      planSourceArchive,
      startSourceArchive,
      getOperationJob: vi.fn().mockResolvedValue({ success: true, job: job({ id: 'job-2' }) }),
    });
    expect(await screen.findByLabelText(/Continue from the last run/)).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Plan' }));
    expect(planSourceArchive).toHaveBeenCalledWith('s1', 500, true);
    fireEvent.click(await screen.findByRole('button', { name: 'Resume archive' }));
    expect(startSourceArchive).toHaveBeenCalledWith('s1', 500, true);
  });

  it('a failed plan is an error and nothing can run', async () => {
    setup({
      getSourceArchive: vi.fn().mockResolvedValue(status()),
      planSourceArchive: vi.fn().mockRejectedValue(new Error('yt-dlp is disabled')),
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Plan' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('yt-dlp is disabled');
    expect(screen.queryByRole('button', { name: 'Run archive' })).not.toBeInTheDocument();
  });

  it('attaches to an archive that is already running', async () => {
    setup({
      getSourceArchive: vi.fn().mockResolvedValue(status({
        latest_job: { id: 'job-9', status: 'running', progress: 12, started_at: '2026-10-11T09:00:00Z' },
      })),
      getOperationJob: vi.fn().mockResolvedValue({ success: true, job: job({ id: 'job-9', progress: 12 }) }),
    });
    expect(await screen.findByText('12%')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Plan' })).not.toBeInTheDocument();
  });

  it('shows the last run and a failed one as an error', async () => {
    setup({
      getSourceArchive: vi.fn().mockResolvedValue(status({
        latest_job: { id: 'job-3', status: 'failed', message: 'HTTP 429 from youtube', started_at: '2026-10-10T09:00:00Z',
          finished_at: '2026-10-10T09:01:00Z', result: {} },
      })),
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 429 from youtube');
  });

  it('a status it cannot read is a quiet error, not a broken sheet', async () => {
    setup({ getSourceArchive: vi.fn().mockRejectedValue(new Error('HTTP 500')) });
    expect(await screen.findByText(/Archive status unavailable: HTTP 500/)).toBeInTheDocument();
  });
});
