import { useSearchParams } from 'react-router-dom';

import type { JobRun } from '../../services/api';
import { useOperationJob } from '../../hooks/useOperations';
import { asRunReport } from '../../lib/runReport';
import { plural } from '../../lib/format';
import { jobLabel } from '../../lib/operationsOverview';
import { formatJobDuration, jobEvents, jobGlyph, jobSummary, runProgressLine } from '../../lib/jobRuns';
import { formatLocalDateTime } from '../../lib/dates';
import { sourceLabel } from '../../lib/sourceLabel';
import RunReportSummary from '../ops/RunReportSummary';
import { ArchiveProgressBar } from './ArchiveSection';
import { archiveResultLine } from '../../lib/archive';
import { StatusGlyph } from '../ui';

const sectionTitle = 'text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg';

/** One job: what it was, how it went, what it delivered and its per-source events. */
function JobDetail({ job }: { job: JobRun }) {
  const report = job.job_type === 'ingestion_run' ? asRunReport(job.payload) : null;
  const archiveResult = job.job_type === 'archive_source' && job.payload ? archiveResultLine(job.payload) : null;
  const events = jobEvents(job);
  const facts: Array<[string, React.ReactNode]> = [
    ['Status', <StatusGlyph key="s" status={jobGlyph(job.status)} label={job.status} />],
    ['Source', job.source_display_name ? sourceLabel(job.source_display_name) : 'All sources'],
    ['Started', formatLocalDateTime(job.started_at) || '—'],
    ['Duration', formatJobDuration(job.started_at, job.finished_at) || (job.finished_at ? '—' : 'still running')],
  ];
  const progress = runProgressLine(job);
  if (progress) facts.push(['Progress', progress]);
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-3 gap-y-3 sm:grid-cols-4">
        {facts.map(([term, value]) => (
          <div key={term} className="min-w-0 border-l border-line pl-3">
            <dt className="text-[0.75rem] text-fg-3">{term}</dt>
            <dd className="break-words text-[0.8125rem] tabular-nums text-fg [overflow-wrap:anywhere]">{value}</dd>
          </div>
        ))}
      </dl>
      {report ? <RunReportSummary report={report} /> : archiveResult ? (
        <p className="text-[0.875rem] tabular-nums text-fg-2">{archiveResult}</p>
      ) : job.message ? (
        <p className="text-[0.875rem] text-fg-2 [overflow-wrap:anywhere]">{job.message}</p>
      ) : null}
      {events.length ? (
        <ol aria-label="Events" className="max-h-[18rem] divide-y divide-line overflow-y-auto rounded-md border border-line font-mono text-[0.75rem] leading-5">
          {events.map((event, index) => (
            <li key={`${event.at ?? 'event'}-${index}`} className="flex min-w-0 gap-3 px-3 py-1.5">
              <span className="shrink-0 tabular-nums text-fg-3">{formatLocalDateTime(event.at) || '—'}</span>
              <span className={`shrink-0 ${event.level === 'error' ? 'font-semibold text-fg' : 'text-fg-3'}`}>
                {event.level === 'error' ? '× error' : event.level || 'info'}
              </span>
              <span className="min-w-0 break-words text-fg-2 [overflow-wrap:anywhere]">{event.message || 'No message'}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

/**
 * The job history under Sources → ingestion: recent jobs, and the one picked
 * in full. The pick lives in `?job=`, so a run toast's "View job" opens it.
 */
export default function IngestionJobs({ jobs, loading }: { jobs: JobRun[]; loading: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get('job');
  const select = (id: string) => {
    const params = new URLSearchParams(searchParams);
    params.set('job', id);
    setSearchParams(params, { replace: true });
  };
  const detail = useOperationJob(selectedId);

  return (
    <div className="grid gap-8 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
      <section aria-labelledby="ingestion-jobs" className="min-w-0 space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 id="ingestion-jobs" className={sectionTitle}>Recent jobs</h2>
          <span className="text-[0.75rem] tabular-nums text-fg-3">{loading && !jobs.length ? 'Loading…' : plural(jobs.length, 'job')}</span>
        </div>
        <ul className="divide-y divide-line border-y border-line">
          {jobs.map((job) => {
            const selected = job.id === selectedId;
            const summary = jobSummary(job);
            const when = [formatLocalDateTime(job.started_at), formatJobDuration(job.started_at, job.finished_at)].filter(Boolean).join(' · ');
            return (
              <li key={job.id}>
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => select(job.id)}
                  className={`w-full min-w-0 px-2 py-2.5 text-left text-[0.8125rem] transition-colors duration-[120ms] hover:bg-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-fg motion-reduce:transition-none ${selected ? 'bg-raised' : ''}`}
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0 break-words font-medium text-fg [overflow-wrap:anywhere]">
                      {jobLabel(job)}
                      {job.source_display_name ? <span className="font-normal text-fg-2"> · {sourceLabel(job.source_display_name)}</span> : null}
                    </div>
                    <StatusGlyph status={jobGlyph(job.status)} label={job.status} />
                  </div>
                  {job.job_type === 'archive_source' && job.status === 'running' && typeof job.progress === 'number' ? (
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="min-w-0 flex-1"><ArchiveProgressBar percent={job.progress} /></div>
                      <span className="text-[0.75rem] tabular-nums text-fg-2">{Math.round(job.progress)}%</span>
                    </div>
                  ) : null}
                  {summary ? <p className="mt-0.5 line-clamp-2 text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]">{summary}</p> : null}
                  {when ? <p className="mt-0.5 text-[0.75rem] tabular-nums text-fg-3">{when}</p> : null}
                </button>
              </li>
            );
          })}
          {!jobs.length && !loading ? (
            <li className="px-2 py-8 text-center text-[0.8125rem] text-fg-3">No jobs yet. Run due sources and the run shows up here.</li>
          ) : null}
        </ul>
        <p className="text-[0.75rem] text-fg-3">Hourly checks that find nothing due fetch nothing and are not listed.</p>
      </section>
      <section aria-labelledby="ingestion-job-detail" className="min-w-0 space-y-4">
        <h2 id="ingestion-job-detail" className={sectionTitle}>{detail.data ? jobLabel(detail.data) : 'Job detail'}</h2>
        {detail.data ? <JobDetail job={detail.data} /> : detail.isError ? (
          <p className="text-[0.8125rem] text-fg-2">Could not load this job.</p>
        ) : (
          <p className="text-[0.8125rem] text-fg-3">{selectedId ? 'Loading…' : 'Choose a job to see its report and events.'}</p>
        )}
      </section>
    </div>
  );
}
