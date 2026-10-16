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
  older_posts: 1697,
  estimated_pages: 25,
  estimated_seconds: 7800,
  current_stored_posts: 25,
  oldest_published_at: '2025-03-03T12:00:00Z',
  continues_from: '2025-03-03T12:00:00Z',
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
  it('shows what is stored, what the source has and when it was measured, and asks for no count', async () => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-10-11T10:00:00Z') });
    setup({ getSourceArchive: vi.fn().mockResolvedValue(status()) });
    const facts = await screen.findByRole('group', { name: 'Archive counts' });
    expect(within(facts).getByText('Stored')).toBeInTheDocument();
    expect(within(facts).getByText('25')).toBeInTheDocument();
    expect(within(facts).getByText('1,722')).toBeInTheDocument();
    expect(within(facts).getByText('measured 3d ago')).toBeInTheDocument();
    expect(screen.queryByLabelText('Posts to fetch')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^All/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /run archive/i })).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it('a source never measured says so', async () => {
    setup({ getSourceArchive: vi.fn().mockResolvedValue(status({ archive: { stored_posts: 25, available_posts: null } })) });
    expect(await screen.findByText('not measured yet')).toBeInTheDocument();
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
  });

  it('a plan without a size says where it continues from, size unknown, and can run', async () => {
    setup({
      getSourceArchive: vi.fn().mockResolvedValue(status({ support: support({ kind: 'substack', available_basis: 'unknown' }) })),
      planSourceArchive: vi.fn().mockResolvedValue(plan({ available_posts: null, available_basis: 'unknown', older_posts: null,
        estimated_pages: null, estimated_seconds: null })),
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Plan' }));
    expect(await screen.findByText('You have 25 posts, back to 3 Mar 2025. The archive continues from there · size unknown'))
      .toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run archive' })).toBeInTheDocument();
  });

  it('nothing older to fetch offers no run', async () => {
    setup({ getSourceArchive: vi.fn().mockResolvedValue(status()), planSourceArchive: vi.fn().mockResolvedValue(plan({ older_posts: 0 })) });
    fireEvent.click(await screen.findByRole('button', { name: 'Plan' }));
    expect(await screen.findByText(/Nothing older to fetch/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run archive' })).not.toBeInTheDocument();
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
    expect(planSourceArchive).toHaveBeenCalledWith('s1', false);
    expect(await screen.findByText(/You have 25 posts, back to 3 Mar 2025\. The archive continues from there: about 1,697 older posts/))
      .toBeInTheDocument();
    expect(screen.getByText(/~2h 10m/)).toBeInTheDocument();
    expect(screen.getByText(/5s between pages, 30s every 10 pages/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Run archive' }));
    expect(startSourceArchive).toHaveBeenCalledWith('s1', false);
    expect(await screen.findByText('40%')).toBeInTheDocument();
    expect(screen.getByText('Fetched youtube_channel page 10')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run archive' })).not.toBeInTheDocument();

    expect(await screen.findByText(/500 posts fetched, 475 new/, {}, { timeout: 8000 })).toBeInTheDocument();
  }, 12_000);

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
    expect(startSourceArchive).toHaveBeenCalledWith('s1', true);
  });

  it('offers to resume a checkpointed run', async () => {
    const planSourceArchive = vi.fn().mockResolvedValue(plan({ resume: true, resume_available: true, continues_from: null,
      checkpoint: { collected_posts: 120 } }));
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
    expect(planSourceArchive).toHaveBeenCalledWith('s1', true);
    expect(await screen.findByText(/resumes from its checkpoint \(120 posts collected so far\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Resume archive' }));
    expect(startSourceArchive).toHaveBeenCalledWith('s1', true);
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
