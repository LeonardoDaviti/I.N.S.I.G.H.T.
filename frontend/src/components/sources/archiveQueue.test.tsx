import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';

import ArchiveSection from './ArchiveSection';
import IngestionArchive from './IngestionArchive';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { archiveQueueApi } from '../../services/api';
import type { ArchivePlan, ArchiveStatusResponse, JobRun } from '../../services/api';

// Issue 0130: an archive back to a date, a queued one, why an archive added nothing, and Resume interrupted archives.

const channel = (over: Partial<ArchiveStatusResponse> = {}): ArchiveStatusResponse => ({
  success: true,
  archive: { stored_posts: 300, available_posts: 60000, last_inspected_at: '2026-11-07T10:00:00Z', resume_ready: false },
  support: { kind: 'telegram_mtproto', available_basis: 'upper_bound', archivable: true, reason: null, unavailable: false,
    live_fetch_limit: 50, until: true },
  latest_job: null,
  ...over,
});

const plan: ArchivePlan = {
  available_posts: 60000, available_basis: 'upper_bound', older_posts: 59700, estimated_pages: 597, estimated_seconds: 3000,
  current_stored_posts: 300, oldest_published_at: '2026-09-01T00:00:00Z', continues_from: '2026-09-01T00:00:00Z',
  resume: false, resume_available: false, rate_limit: { page_delay_seconds: 2 },
};

const job = (over: Partial<JobRun> = {}): JobRun => ({
  id: 'job-9', job_type: 'archive_source', status: 'queued', trigger: 'manual',
  payload: { lane: 'telegram', queued_at: '2026-11-07T10:00:00Z' }, started_at: '2026-11-07T10:00:00Z', ...over,
});

afterEach(() => vi.restoreAllMocks());

describe('archives back to a date and the queue', () => {
  it('offers "back to" 1 Nov 2025 on a channel and starts the archive with it; a queued job says so', async () => {
    const startArchive = vi.spyOn(archiveQueueApi, 'startArchive').mockResolvedValue({ job_id: 'job-9', status: 'queued' });
    renderWithProviders(<ArchiveSection sourceId="s1" />, { api: makeFakeApi({
      getSourceArchive: vi.fn().mockResolvedValue(channel()),
      planSourceArchive: vi.fn().mockResolvedValue(plan),
      getOperationJob: vi.fn().mockResolvedValue({ success: true, job: job() }),
    }) });
    expect(await screen.findByLabelText('Back to')).toHaveValue('2025-11-01');
    fireEvent.click(screen.getByRole('button', { name: 'Plan' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Run archive back to 2025-11-01' }));
    expect(startArchive).toHaveBeenCalledWith('s1', false, '2025-11-01');
    expect(await screen.findByText('Queued')).toBeInTheDocument();
    expect(screen.getByText(/one Telegram and one X archive run at a time/)).toBeInTheDocument();
  });

  it('a blank date archives the whole history the usual way', async () => {
    const startSourceArchive = vi.fn().mockResolvedValue({ job_id: 'job-1' });
    renderWithProviders(<ArchiveSection sourceId="s1" />, { api: makeFakeApi({
      getSourceArchive: vi.fn().mockResolvedValue(channel()),
      planSourceArchive: vi.fn().mockResolvedValue(plan),
      startSourceArchive,
      getOperationJob: vi.fn().mockResolvedValue({ success: true, job: job({ status: 'running' }) }),
    }) });
    fireEvent.change(await screen.findByLabelText('Back to'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Plan' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Run archive' }));
    expect(startSourceArchive).toHaveBeenCalledWith('s1', false);
  });

  it('says why the last archive added nothing', async () => {
    renderWithProviders(<ArchiveSection sourceId="s2" />, { api: makeFakeApi({
      getSourceArchive: vi.fn().mockResolvedValue(channel({
        support: { kind: 'page_watch', available_basis: 'estimate', archivable: true, reason: null, unavailable: false,
          live_fetch_limit: 50 },
        latest_job: { id: 'job-2', status: 'success', finished_at: '2026-11-07T11:00:00Z',
          message: 'Archive completed with 0 posts; nothing new: 102 pages already stored (not read again) · 8 pages no post (no article, or no date)',
          result: { posts_fetched: 0, posts_inserted: 0, pages_fetched: 8,
            unreached: { stored: 102, no_post: 8, unreadable: 0, updated: 0 } } as never },
      })),
    }) });
    expect(await screen.findByText(/nothing new: 102 pages already stored \(not read again\) · 8 pages no post/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Back to')).not.toBeInTheDocument();
  });

  it('resumes every interrupted archive in one tap', async () => {
    const resume = vi.spyOn(archiveQueueApi, 'resumeInterrupted').mockResolvedValue({ count: 3 });
    const entry = (id: string) => ({ source_id: id, display_name: `Source ${id}`, platform: 'rss', enabled: true, stored_posts: 10 });
    renderWithProviders(<IngestionArchive />, { api: makeFakeApi({
      getArchiveCatalog: vi.fn().mockResolvedValue({ success: true, total: 3, sources: [entry('a'), entry('b'), entry('c')],
        interrupted: ['a', 'b', 'c'], queued: [] }),
    }) });
    fireEvent.click(await screen.findByRole('button', { name: 'Resume 3 interrupted archives' }));
    expect(resume).toHaveBeenCalled();
    expect(await screen.findByText(/3 archives queued: they resume in turn/)).toBeInTheDocument();
    expect(screen.getAllByText(/interrupted by a restart/)).toHaveLength(3);
  });
});
