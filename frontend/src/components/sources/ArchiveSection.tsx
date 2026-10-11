import { useEffect, useId, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import type { ArchiveJobSummary, ArchivePlan, ArchiveStatusResponse, ArchiveSupport, JobRun } from '../../services/api';
import { useApi } from '../../services/ApiContext';
import { useOperationJob } from '../../hooks/useOperations';
import { SOURCES_HEALTH_KEY } from '../../hooks/useSourcesHealth';
import { errorMessage } from '../../lib/apiError';
import {
  archiveCeiling,
  archivePresets,
  archiveResultLine,
  clampDesired,
  defaultDesired,
  describeAvailable,
  describeRate,
  formatEstimate,
} from '../../lib/archive';
import { formatRelativeTime } from '../../lib/dates';
import { formatCount, plural } from '../../lib/format';
import { Button, FilterChip, Input, StatusGlyph } from '../ui';
import { Notice } from '../states';

const archiveStatusKey = (sourceId: string) => ['archive-status', sourceId] as const;

/** A backend older than this section has no `support`: archive allowed, the count unqualified. */
function supportOf(status: ArchiveStatusResponse): ArchiveSupport {
  if (status.support) return status.support;
  const available = status.archive?.available_posts;
  return {
    kind: '',
    available_basis: available === null || available === undefined ? 'unknown' : 'estimate',
    archivable: true,
    reason: null,
    unavailable: false,
    live_fetch_limit: 50,
  };
}

/** One shape for "the last run": the polled job, or the status's newest job summary. */
interface RunView {
  status: string;
  progress: number | null;
  message: string | null;
  lastEvent: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  fetched?: number;
  inserted?: number;
  pages?: number;
}

function fromJob(job: JobRun): RunView {
  const events = Array.isArray(job.payload?.events) ? job.payload.events as Array<{ message?: string }> : [];
  const payload = job.payload ?? {};
  return {
    status: job.status,
    progress: typeof job.progress === 'number' ? job.progress : null,
    message: job.message ?? null,
    lastEvent: events.length ? events[events.length - 1]?.message ?? null : null,
    startedAt: job.started_at ?? null,
    finishedAt: job.finished_at ?? null,
    fetched: payload.posts_fetched,
    inserted: payload.posts_inserted,
    pages: payload.pages_fetched,
  };
}

function fromSummary(job: ArchiveJobSummary): RunView {
  return {
    status: job.status,
    progress: job.progress ?? null,
    message: job.message ?? null,
    lastEvent: null,
    startedAt: job.started_at ?? null,
    finishedAt: job.finished_at ?? null,
    fetched: job.result?.posts_fetched,
    inserted: job.result?.posts_inserted,
    pages: job.result?.pages_fetched,
  };
}

function resultLine(run: RunView): string {
  return archiveResultLine({ posts_fetched: run.fetched, posts_inserted: run.inserted, pages_fetched: run.pages })
    ?? run.message ?? 'Finished';
}

/** A monochrome progress bar (the sheet and the job history). */
export function ArchiveProgressBar({ percent }: { percent: number }) {
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      role="progressbar"
      aria-label="Archive progress"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      className="h-1 overflow-hidden rounded-full bg-raised"
    >
      <div className="h-full bg-fg" style={{ width: `${value}%` }} />
    </div>
  );
}

function Progress({ run, now }: { run: RunView; now: Date }) {
  const percent = Math.max(0, Math.min(100, Math.round(run.progress ?? 0)));
  return (
    <div className="space-y-1.5" role="status">
      <div className="flex items-center justify-between gap-3 text-[0.8125rem]">
        <StatusGlyph status="running" label="archiving…" />
        <span className="tabular-nums text-fg">{percent}%</span>
      </div>
      <ArchiveProgressBar percent={percent} />
      {run.lastEvent ? <p className="text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]">{run.lastEvent}</p> : null}
      {run.startedAt ? <p className="text-[0.75rem] text-fg-3">started {formatRelativeTime(run.startedAt, now)}</p> : null}
    </div>
  );
}

/**
 * The source sheet's archive: what is stored, what the source has (worded by what
 * the source can tell), how many to fetch, the plan, then run or resume with
 * progress and the last result. A source that cannot archive is one quiet line.
 */
export default function ArchiveSection({ sourceId }: { sourceId: string }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: [...archiveStatusKey(sourceId)],
    queryFn: () => api.getSourceArchive(sourceId),
  });

  if (status.isPending) return <p className="text-[0.75rem] text-fg-3">Loading archive…</p>;
  if (status.isError) {
    return <p className="text-[0.75rem] text-fg-3">Archive status unavailable: {errorMessage(status.error)}</p>;
  }
  const support = supportOf(status.data);
  if (!support.archivable) {
    return <p className="text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">No archive: {support.reason}</p>;
  }
  return (
    <ArchiveControls
      sourceId={sourceId}
      status={status.data}
      support={support}
      onChanged={() => {
        void queryClient.invalidateQueries({ queryKey: [...archiveStatusKey(sourceId)] });
        void queryClient.invalidateQueries({ queryKey: [...SOURCES_HEALTH_KEY] });
      }}
    />
  );
}

function ArchiveControls({ sourceId, status, support, onChanged }: {
  sourceId: string;
  status: ArchiveStatusResponse;
  support: ArchiveSupport;
  onChanged: () => void;
}) {
  const api = useApi();
  const ids = useId();
  const archive = status.archive ?? {};
  const stored = archive.stored_posts ?? 0;
  const [plan, setPlan] = useState<ArchivePlan | null>(null);
  // The plan's own count wins once there is one: it is a fresh measurement.
  const available = plan ? plan.available_posts : archive.available_posts ?? null;
  const basis = plan?.available_basis ?? support.available_basis;
  const ceiling = archiveCeiling(available, basis);
  const availableText = describeAvailable({ available, basis, stored });

  const [desiredText, setDesiredText] = useState(() => String(defaultDesired(ceiling)));
  const desired = clampDesired(Number(desiredText), ceiling);
  const resumeReady = Boolean(archive.resume_ready);
  const [resume, setResume] = useState(resumeReady);
  const [plannedFor, setPlannedFor] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const latest = status.latest_job ?? null;
  const [jobId, setJobId] = useState<string | null>(latest?.status === 'running' ? latest.id : null);
  const job = useOperationJob(jobId);
  const run: RunView | null = job.data ? fromJob(job.data) : latest ? fromSummary(latest) : null;
  const running = run?.status === 'running';
  const now = new Date();

  // When the followed job finishes, the stored count and the checkpoint have moved.
  const finished = Boolean(jobId && job.data && job.data.status !== 'running');
  useEffect(() => {
    if (finished) onChanged();
  }, [finished]); // eslint-disable-line react-hooks/exhaustive-deps -- once per finish

  const planKey = `${desired}:${resume}`;
  const planCurrent = plan !== null && plannedFor === planKey;

  const choose = (value: number) => setDesiredText(String(clampDesired(value, ceiling)));

  const requestPlan = async () => {
    setPlanning(true);
    setError(null);
    try {
      const next = await api.planSourceArchive(sourceId, desired, resume);
      setPlan(next);
      setPlannedFor(planKey);
    } catch (err) {
      setPlan(null);
      setError(errorMessage(err));
    } finally {
      setPlanning(false);
    }
  };

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const { job_id: started } = await api.startSourceArchive(sourceId, desired, resume);
      setJobId(started);
      setPlan(null);
      setPlannedFor(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  };

  const label = 'block text-[0.75rem] text-fg-3';
  const checkpoint = archive.checkpoint;
  const estimate = plan ? formatEstimate(plan.estimated_seconds) : null;
  const rate = plan ? describeRate(plan.rate_limit) : null;

  return (
    <div className="space-y-4">
      <div className="text-[0.8125rem] font-medium text-fg">Archive</div>
      <dl role="group" aria-label="Archive counts" className="grid grid-cols-2 gap-x-3 gap-y-2">
        <div className="min-w-0 border-l border-line pl-3">
          <dt className={label}>Stored</dt>
          <dd className="text-[0.9375rem] font-semibold tabular-nums text-fg">{formatCount(stored)}</dd>
        </div>
        <div className="min-w-0 border-l border-line pl-3">
          <dt className={label}>At the source</dt>
          <dd className="text-[0.9375rem] font-semibold tabular-nums text-fg">{availableText.figure}</dd>
          {!plan && archive.last_inspected_at && available !== null ? (
            <dd className="text-[0.75rem] text-fg-3">checked {formatRelativeTime(archive.last_inspected_at, now)}</dd>
          ) : null}
        </div>
      </dl>
      {availableText.note ? <p className="text-[0.75rem] text-fg-2">{availableText.note}</p> : null}

      {running && run ? <Progress run={run} now={now} /> : (
        <>
          <div>
            <label htmlFor={`${ids}-desired`} className="mb-1.5 block text-[0.8125rem] font-medium text-fg">Posts to fetch</label>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                id={`${ids}-desired`}
                inputMode="numeric"
                value={desiredText}
                onChange={(e) => setDesiredText(e.target.value.replace(/[^\d]/g, ''))}
                onBlur={() => setDesiredText(String(desired))}
                aria-describedby={`${ids}-desired-help`}
                className="w-28 tabular-nums"
              />
              {archivePresets(ceiling).map((preset) => (
                <FilterChip key={preset.label} selected={desired === preset.value} onClick={() => choose(preset.value)}>
                  {preset.label}
                </FilterChip>
              ))}
            </div>
            <p id={`${ids}-desired-help`} className="mt-1 text-[0.75rem] text-fg-3">
              Newest first. Posts already stored are updated, not duplicated.
            </p>
          </div>

          {resumeReady ? (
            <label className="flex items-start gap-2 text-[0.8125rem] text-fg-2">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-[rgb(var(--text))]"
                checked={resume}
                onChange={(e) => setResume(e.target.checked)}
              />
              <span>
                Continue from the last run
                {checkpoint?.collected_posts ? (
                  <span className="text-fg-3"> ({plural(checkpoint.collected_posts, 'post')} collected so far)</span>
                ) : null}
              </span>
            </label>
          ) : null}

          {planCurrent && plan ? (
            <div className="space-y-0.5 border-l border-line-strong pl-3 text-[0.8125rem]" aria-label="Archive plan">
              <p className="tabular-nums text-fg">
                {plan.remaining_posts > 0
                  ? `${plural(plan.remaining_posts, 'post')} to fetch · ${plural(plan.estimated_pages, 'page')}${estimate ? ` · ${estimate}` : ''}`
                  : 'Nothing left to fetch for this count.'}
              </p>
              {plan.resume ? (
                <p className="text-fg-3">Resumes from the checkpoint; {plural(plan.desired_posts - plan.remaining_posts, 'post')} already collected.</p>
              ) : null}
              {rate ? <p className="text-fg-3">{rate}</p> : null}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => void requestPlan()} disabled={planning || starting} aria-busy={planning}>
              {planning ? 'Planning…' : 'Plan'}
            </Button>
            {planCurrent && plan && plan.remaining_posts > 0 ? (
              <Button variant="primary" size="sm" onClick={() => void start()} disabled={starting} aria-busy={starting}>
                {starting ? 'Starting…' : plan.resume ? 'Resume archive' : 'Run archive'}
              </Button>
            ) : null}
            {planning ? <span className="text-[0.75rem] text-fg-3">Asking the source; a large channel can take minutes.</span> : null}
          </div>
        </>
      )}

      {error ? <Notice tone="error" title={error} /> : null}

      {run && !running ? (
        run.status === 'failed' ? (
          <Notice tone="error" title="The last archive failed" message={run.message || 'No reason was recorded.'} />
        ) : (
          <p className="text-[0.75rem] text-fg-2">
            <StatusGlyph status="ok" label="last run" />
            <span className="tabular-nums">
              {' '}{run.finishedAt ? `${formatRelativeTime(run.finishedAt, now)}: ` : ''}{resultLine(run)}
            </span>
          </p>
        )
      ) : null}
    </div>
  );
}
