import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';

import type { RunReport, SchedulerConfig } from '../../services/api';
import { useAnalysisEnabled } from '../../hooks/useAnalysis';
import { OPERATIONS_OVERVIEW_KEY, SCHEDULER_KEY, useOperationsOverview, useSchedulerConfig } from '../../hooks/useOperations';
import { INGESTION_SUB_VIEWS, ingestionSubViewHref, normalizeIngestionSubView, type IngestionSubView } from '../../lib/ingestionNavigation';
import { useApi } from '../../services/ApiContext';
import { asRunReport } from '../../lib/runReport';
import { formatCount } from '../../lib/format';
import { formatTimeRemaining, schedulerStaleness } from '../../lib/schedulerStatus';
import IngestionStatusNotice from '../ops/IngestionStatusNotice';
import RunCycleButton from '../ops/RunCycleButton';
import RunReportSummary from '../ops/RunReportSummary';
import { Button, tabTriggerClass } from '../ui';
import SchedulerDialog from './SchedulerDialog';
import IngestionJobs from './IngestionJobs';
import IngestionArchive from './IngestionArchive';
import IngestionLogs from './IngestionLogs';
import IngestionAnalysisActions from './IngestionAnalysisActions';
import { Notice } from '../states';

/** Now, every 30 seconds while the page is visible: enough for a minute countdown. */
function useClock(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') setNow(Date.now());
    }, 30_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

const sectionTitle = 'text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg';

/**
 * Sources → ingestion (reading-finish R3, S4): the useful parts of the old
 * ingestion page, under the sources it fetches. Views as `?sub=`: overview,
 * archive (backfill, issue 0005 slice 3), jobs and logs.
 */
export default function IngestionPanel() {
  const api = useApi();
  const queryClient = useQueryClient();
  const analysis = useAnalysisEnabled();
  const [sessionReport, setSessionReport] = useState<RunReport | null>(null);
  const [schedulerOpen, setSchedulerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const sub: IngestionSubView = normalizeIngestionSubView(searchParams.get('sub'));

  const overview = useOperationsOverview();
  const jobs = overview.data?.jobs ?? [];
  const scheduler = useSchedulerConfig();
  const nowMs = useClock();

  // The newest stored ingestion run, so the report survives a reload.
  const storedReport = (() => {
    for (const job of jobs) {
      if (job.job_type !== 'ingestion_run') continue;
      const report = asRunReport(job.payload);
      if (report) return report;
    }
    return null;
  })();
  const report = sessionReport ?? storedReport;

  const onReport = (next: RunReport) => {
    setSessionReport(next);
    void queryClient.invalidateQueries({ queryKey: [...OPERATIONS_OVERVIEW_KEY] });
    void queryClient.invalidateQueries({ queryKey: [...SCHEDULER_KEY] });
  };

  const saveScheduler = async (next: SchedulerConfig): Promise<boolean> => {
    const response = await api.updateSchedulerConfig(next);
    if (!response.success || !response.scheduler) {
      setError(response.error || 'Could not save the scheduler.');
      return false;
    }
    setError(null);
    queryClient.setQueryData([...SCHEDULER_KEY], { ...response.scheduler, state: response.scheduler.state ?? scheduler.data?.state });
    return true;
  };

  const schedulerStatus = (() => {
    if (scheduler.isError) {
      return <p className="text-[0.875rem] text-fg-2">Could not read the scheduler, so whether it runs is unknown.</p>;
    }
    if (!scheduler.data) return <p className="text-[0.875rem] text-fg-3">Reading the scheduler…</p>;
    const tickMinutes = Number(scheduler.data.ingest_tick_minutes ?? 60);
    const stalled = schedulerStaleness(scheduler.data.state ?? {}, tickMinutes, nowMs);
    if (stalled) return <IngestionStatusNotice state="stopped" message={stalled} />;
    const parts = [`Checks for due sources every ${formatCount(tickMinutes)} min`];
    const next = scheduler.data.state?.next_tick_at ? new Date(scheduler.data.state.next_tick_at).getTime() : NaN;
    if (!Number.isNaN(next)) {
      const remaining = next - nowMs;
      parts.push(remaining <= 0 ? 'next tick due now' : `next tick in ${formatTimeRemaining(remaining).replace(/ \d+s$/, '')}`);
    }
    return <p className="text-[0.875rem] tabular-nums text-fg-2">{parts.join(' · ')}</p>;
  })();

  return (
    <div className="space-y-8">
      <nav aria-label="Ingestion views" className="flex items-end gap-5 border-b border-line">
        {INGESTION_SUB_VIEWS.map((key) => (
          <Link
            key={key}
            to={ingestionSubViewHref(key)}
            replace
            aria-current={key === sub ? 'page' : undefined}
            className={tabTriggerClass}
          >
            {key}
          </Link>
        ))}
      </nav>
      {error ? <Notice tone="error" title={error} action={{ label: 'Dismiss', onClick: () => setError(null) }} /> : null}
      {sub === 'jobs' ? <IngestionJobs jobs={jobs} loading={overview.isPending} /> : sub === 'archive' ? <IngestionArchive /> : sub === 'logs' ? <IngestionLogs /> : (
        <div className="space-y-10">
          <section aria-labelledby="ingestion-scheduler" className="space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h2 id="ingestion-scheduler" className={sectionTitle}>Scheduler</h2>
              {scheduler.data ? (
                <Button variant="ghost" size="sm" onClick={() => setSchedulerOpen(true)}>Change interval</Button>
              ) : null}
            </div>
            {schedulerStatus}
            <RunCycleButton onReport={onReport} />
          </section>
          <section aria-labelledby="ingestion-last-run" className="space-y-3">
            <h2 id="ingestion-last-run" className={sectionTitle}>Last run</h2>
            {report ? <RunReportSummary report={report} /> : (
              <p className="text-[0.875rem] text-fg-2">
                {overview.isPending ? 'Loading…' : 'No run yet. Run due sources fetches what is due now, exactly as the next scheduler tick would; each source keeps its own cadence and backoff.'}
              </p>
            )}
          </section>
          {analysis ? (
            <IngestionAnalysisActions onDone={() => void queryClient.invalidateQueries({ queryKey: [...OPERATIONS_OVERVIEW_KEY] })} />
          ) : null}
        </div>
      )}
      {scheduler.data && schedulerOpen ? (
        <SchedulerDialog
          open
          config={scheduler.data}
          analysis={analysis}
          onClose={() => setSchedulerOpen(false)}
          onSave={saveScheduler}
        />
      ) : null}
    </div>
  );
}
