import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import type { RunReport, SchedulerConfig } from '../../services/api';
import { useAnalysisEnabled } from '../../hooks/useAnalysis';
import { useApi } from '../../services/ApiContext';
import { asRunReport } from '../../lib/runReport';
import { formatCount } from '../../lib/format';
import { formatTimeRemaining, schedulerStaleness } from '../../lib/schedulerStatus';
import IngestionStatusNotice from '../ops/IngestionStatusNotice';
import RunCycleButton from '../ops/RunCycleButton';
import RunReportSummary from '../ops/RunReportSummary';
import { Button, Dialog, DialogContent, DialogFooter, Input, tabTriggerClass } from '../ui';
import IngestionJobs from './IngestionJobs';
import IngestionAnalysisActions from './IngestionAnalysisActions';
import { Notice } from '../states';

export const OPERATIONS_OVERVIEW_KEY = ['operations', 'overview'] as const;
export const SCHEDULER_KEY = ['operations', 'scheduler'] as const;

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

const fieldLabel = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';

/**
 * The scheduler's settings. Reading-only it is the tick interval and the
 * sources.json sync; with analysis on, the briefing interval and toggles too.
 * Numbers are edited as text and clamped on save, so clearing a field to type
 * a new value works.
 */
function SchedulerDialog({
  open,
  config,
  analysis,
  onClose,
  onSave,
}: {
  open: boolean;
  config: SchedulerConfig;
  analysis: boolean;
  onClose: () => void;
  onSave: (next: SchedulerConfig) => Promise<boolean>;
}) {
  const [tick, setTick] = useState(String(config.ingest_tick_minutes ?? 60));
  const [interval, setIntervalHours] = useState(String(config.interval_hours));
  const [toggles, setToggles] = useState(() => ({
    sync_sources_each_cycle: config.sync_sources_each_cycle,
    generate_daily_briefing: config.generate_daily_briefing,
    generate_topic_briefing: config.generate_topic_briefing,
  }));
  const [saving, setSaving] = useState(false);
  const rows: Array<[keyof typeof toggles, string]> = [
    ['sync_sources_each_cycle', 'Sync sources.json every cycle'],
    ...(analysis ? [
      ['generate_daily_briefing', 'Write the daily briefing'],
      ['generate_topic_briefing', 'Write the topic briefing'],
    ] as Array<[keyof typeof toggles, string]> : []),
  ];

  const submit = async () => {
    setSaving(true);
    const saved = await onSave({
      ...config,
      ...toggles,
      ingest_tick_minutes: Math.max(15, Math.round(Number(tick)) || 15),
      interval_hours: Math.max(0.25, Number(interval) || 0.25),
    });
    setSaving(false);
    if (saved) onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent
        title="Scheduler"
        description={analysis ? 'How often the scheduler looks for due sources and writes briefings.' : 'How often the scheduler looks for due sources.'}
      >
        <form className="mt-5 space-y-5" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="ingestion-tick" className={fieldLabel}>Check for due sources every (minutes)</label>
              <Input id="ingestion-tick" type="number" min={15} step={5} value={tick} onChange={(e) => setTick(e.target.value)} className="tabular-nums" />
              <p className="mt-1 text-[0.75rem] text-fg-3">At least 15. Each source still waits for its own cadence.</p>
            </div>
            {analysis ? (
              <div>
                <label htmlFor="ingestion-interval" className={fieldLabel}>Write briefings every (hours)</label>
                <Input id="ingestion-interval" type="number" min={0.25} step={0.25} value={interval} onChange={(e) => setIntervalHours(e.target.value)} className="tabular-nums" />
              </div>
            ) : null}
          </div>
          <fieldset className="divide-y divide-line rounded-md border border-line">
            <legend className="sr-only">Each cycle</legend>
            {rows.map(([key, text]) => (
              <label key={key} className="flex min-h-[2.75rem] cursor-pointer items-center justify-between gap-3 px-3 text-[0.875rem] text-fg">
                <span>{text}</span>
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[rgb(var(--text))]"
                  checked={Boolean(toggles[key])}
                  onChange={(e) => setToggles((prev) => ({ ...prev, [key]: e.target.checked }))}
                />
              </label>
            ))}
          </fieldset>
          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const sectionTitle = 'text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg';

/** The tab's two views, as `?sub=`: the overview (default) and the job history. */
const SUB_VIEWS = ['overview', 'jobs'] as const;
type SubView = (typeof SUB_VIEWS)[number];

/**
 * Sources → ingestion (reading-finish R3, S4): the useful parts of the old
 * ingestion page, under the sources it fetches.
 */
export default function IngestionPanel() {
  const api = useApi();
  const queryClient = useQueryClient();
  const analysis = useAnalysisEnabled();
  const [sessionReport, setSessionReport] = useState<RunReport | null>(null);
  const [schedulerOpen, setSchedulerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const sub: SubView = searchParams.get('sub') === 'jobs' ? 'jobs' : 'overview';

  const overview = useQuery({
    queryKey: [...OPERATIONS_OVERVIEW_KEY],
    queryFn: async () => {
      const response = await api.getOperationsOverview();
      if (response.success === false) throw new Error(response.error || 'Could not load the job history.');
      return response;
    },
    refetchInterval: 15_000,
  });
  const jobs = overview.data?.jobs ?? [];

  const scheduler = useQuery({
    queryKey: [...SCHEDULER_KEY],
    queryFn: async () => {
      const response = await api.getSchedulerConfig();
      if (!response.success || !response.scheduler) throw new Error(response.error || 'Could not read the scheduler.');
      return response.scheduler;
    },
    refetchInterval: 30_000,
  });
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
        {SUB_VIEWS.map((key) => (
          <Link
            key={key}
            to={key === 'jobs' ? '?tab=ingestion&sub=jobs' : '?tab=ingestion'}
            replace
            aria-current={key === sub ? 'page' : undefined}
            className={tabTriggerClass}
          >
            {key}
          </Link>
        ))}
      </nav>
      {error ? <Notice tone="error" title={error} action={{ label: 'Dismiss', onClick: () => setError(null) }} /> : null}
      {sub === 'jobs' ? <IngestionJobs jobs={jobs} loading={overview.isPending} /> : (
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
