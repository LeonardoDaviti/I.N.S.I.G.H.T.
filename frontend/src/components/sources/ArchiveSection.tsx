import { useEffect, useId, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import type { ArchiveJobSummary, ArchivePacing, ArchivePlan, ArchiveRateLimit, ArchiveResultExtra, ArchiveStatusResponse, ArchiveSupport, ArchiveWaiting, JobRun, LinkedPagesSummary } from '../../services/api';
import { archiveQueueApi } from '../../services/api';
import { useApi } from '../../services/ApiContext';
import { useOperationJob } from '../../hooks/useOperations';
import { SOURCES_HEALTH_KEY } from '../../hooks/useSourcesHealth';
import { errorMessage } from '../../lib/apiError';
import { archiveResultLine, describeAvailable, describeLinked, describePlan, describeRate } from '../../lib/archive';
import { waitingLine } from '../../lib/archiveWaiting';
import { jobWaiting } from '../../lib/jobRuns';
import { formatRelativeTime } from '../../lib/dates';
import { formatEstimate } from '../../lib/duration';
import { formatCount, plural } from '../../lib/format';
import { Button, Input, StatusGlyph } from '../ui';
import { Notice } from '../states';
import ArchiveCoverageLine from './ArchiveCoverageLine';

const archiveStatusKey = (sourceId: string) => ['archive-status', sourceId] as const;
const linkedKey = (sourceId: string) => ['archive-linked', sourceId] as const;
/** Every source's archive state (the ingestion tab's catalog); refreshed when an archive here moves. */
export const ARCHIVE_CATALOG_KEY = ['archive-catalog'] as const;

/** The default horizon of an archive back to a date (issue 0130 C, the owner's default). */
export const DEFAULT_UNTIL = '2025-11-01';

/** The pacing fields, in the order shown: the saved key, the request's name, the smallest value. */
const PACING: Array<{ key: keyof ArchiveRateLimit; field: keyof ArchivePacing; label: string; min: number }> = [
  { key: 'page_delay_seconds', field: 'pageDelaySeconds', label: 'Page delay (s)', min: 0 },
  { key: 'batch_size', field: 'batchSize', label: 'Batch size', min: 1 },
  { key: 'batch_cooldown_seconds', field: 'batchCooldownSeconds', label: 'Batch cooldown (s)', min: 0 },
];
type PacingText = Record<keyof ArchiveRateLimit, string>;

function pacingText(rate?: ArchiveRateLimit | null): PacingText {
  const text = (value?: number) => (typeof value === 'number' ? String(value) : '');
  return {
    page_delay_seconds: text(rate?.page_delay_seconds),
    batch_size: text(rate?.batch_size),
    batch_cooldown_seconds: text(rate?.batch_cooldown_seconds),
  };
}

/** The filled pacing fields as overrides; a blank field keeps the kind's own value. */
function pacingOverrides(text: PacingText): ArchivePacing {
  const out: ArchivePacing = {};
  for (const { key, field, min } of PACING) {
    if (text[key] !== '') out[field] = Math.max(min, Number(text[key]));
  }
  return out;
}

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
  /** Why the archive paused (a site limiting us); it resumes from its checkpoint. */
  pausedReason?: string;
  /** What it waits for (issue 0107: a host's limit); the scheduler continues it. */
  waiting?: ArchiveWaiting | null;
  /** It read the source's linked, not stored pages (issue 0084 B), not its archive. */
  linked?: boolean;
  /** Issue 0130: why it added no more, the date it stopped at, a changed layout. */
  extra?: ArchiveResultExtra;
}

const count = (value: unknown) => (typeof value === 'number' ? value : undefined);
const pausedReason = (result?: { paused?: boolean; paused_reason?: unknown } | null) =>
  (result?.paused && typeof result.paused_reason === 'string' ? result.paused_reason : undefined);

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
    fetched: count(payload.posts_fetched),
    inserted: count(payload.posts_inserted),
    pages: count(payload.pages_fetched),
    pausedReason: pausedReason(payload),
    waiting: jobWaiting(job),
    linked: Boolean(payload.linked),
    extra: payload as ArchiveResultExtra,
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
    pausedReason: pausedReason(job.result),
    waiting: jobWaiting({ status: job.status, payload: job.result }),
    linked: Boolean(job.result?.linked),
    extra: (job.result ?? {}) as ArchiveResultExtra,
  };
}

/** The archive's own words when they say more than its counts (issue 0130): why it added no more, or the date it
 *  stopped at. Null otherwise. */
function resultNote(run: RunView): string | null {
  const unreached = run.extra?.unreached;
  const explains = Boolean(run.extra?.until_reached)
    || Boolean(unreached && ((unreached.stored ?? 0) + (unreached.no_post ?? 0) + (unreached.unreadable ?? 0) > 0
      || (run.inserted === 0 && run.status === 'success')));
  if (!explains || !run.message) return null;
  return run.message.replace(/^Archive completed with \d+ posts; /, '');
}

function resultLine(run: RunView): string {
  // A linked fetch's own words say what it read and what it could not store (issue 0084 B).
  if (run.linked && run.message && run.status !== 'running' && !run.waiting) return run.message;
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

function Progress({ run, now, onStop, stopping }: { run: RunView; now: Date; onStop?: () => void; stopping?: boolean }) {
  const percent = Math.max(0, Math.min(100, Math.round(run.progress ?? 0)));
  return (
    <div className="space-y-1.5" role="status">
      <div className="flex items-center justify-between gap-3 text-[0.8125rem]">
        <StatusGlyph status="running" label={run.linked ? 'fetching linked pages…' : 'archiving…'} />
        <span className="tabular-nums text-fg">{percent}%</span>
      </div>
      <ArchiveProgressBar percent={percent} />
      {run.lastEvent ? <p className="text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]">{run.lastEvent}</p> : null}
      {run.startedAt ? <p className="text-[0.75rem] text-fg-3">started {formatRelativeTime(run.startedAt, now)}</p> : null}
      {onStop ? (
        <Button variant="secondary" size="sm" onClick={onStop} disabled={stopping} aria-busy={stopping}>
          {stopping ? 'Stopping after this page…' : 'Stop archive'}
        </Button>
      ) : null}
    </div>
  );
}

/**
 * The source sheet's archive: what is stored, what the source has (worded by what
 * the source can tell, and when it was measured), the plan (where the archive
 * continues from and how much is older), then run or resume with progress and the
 * last result. An archive fetches everything older than what is stored. A source
 * that cannot archive is one quiet line.
 * With `pacing` (the ingestion tab's backfill) it also sets the page delay, batch
 * size and batch cooldown the plan and the run use.
 */
export default function ArchiveSection({ sourceId, pacing = false }: { sourceId: string; pacing?: boolean }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: [...archiveStatusKey(sourceId)],
    queryFn: () => api.getSourceArchive(sourceId),
  });
  // Its own request: counting reads every stored post's links (about a second on a large source).
  const linked = useQuery({
    queryKey: [...linkedKey(sourceId)],
    queryFn: () => api.getLinkedPages(sourceId),
    retry: false,
  });
  const onChanged = () => {
    void queryClient.invalidateQueries({ queryKey: [...archiveStatusKey(sourceId)] });
    void queryClient.invalidateQueries({ queryKey: [...linkedKey(sourceId)] });
    void queryClient.invalidateQueries({ queryKey: [...SOURCES_HEALTH_KEY] });
    void queryClient.invalidateQueries({ queryKey: [...ARCHIVE_CATALOG_KEY] });
  };

  if (status.isPending) return <p className="text-[0.75rem] text-fg-3">Loading archive…</p>;
  if (status.isError) {
    return <p className="text-[0.75rem] text-fg-3">Archive status unavailable: {errorMessage(status.error)}</p>;
  }
  const support = supportOf(status.data);
  if (!support.archivable) {
    // A feed with nothing older to archive can still read the pages its posts link (issue 0084 B).
    return (
      <div className="space-y-3">
        <p className="text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">No archive: {support.reason}</p>
        <ArchiveControls sourceId={sourceId} status={status.data} support={support} pacing={false}
          linked={linked.data ?? null} onChanged={onChanged} linkedOnly />
      </div>
    );
  }
  return (
    <ArchiveControls
      sourceId={sourceId}
      status={status.data}
      support={support}
      pacing={pacing}
      linked={linked.data ?? null}
      onChanged={onChanged}
    />
  );
}

/** "Linked by your posts, not stored: 17 · Fetch them", or the archive first, or only the count. */
function LinkedLine({ linked, busy, onFetch }: { linked: LinkedPagesSummary | null; busy: boolean; onFetch: () => void }) {
  const said = linked ? describeLinked(linked, formatEstimate(linked.estimated_seconds)) : null;
  if (!said) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem]" aria-label="Linked pages">
      <span className="tabular-nums text-fg">{said.line}</span>
      {said.fetch ? (
        <Button variant="secondary" size="sm" onClick={onFetch} disabled={busy} aria-busy={busy}>Fetch them</Button>
      ) : null}
      {said.note ? <span className="text-[0.75rem] text-fg-3">{said.note}</span> : null}
    </div>
  );
}

function ArchiveControls({ sourceId, status, support, pacing, linked, onChanged, linkedOnly = false }: {
  sourceId: string;
  status: ArchiveStatusResponse;
  support: ArchiveSupport;
  pacing: boolean;
  linked: LinkedPagesSummary | null;
  onChanged: () => void;
  /** No archive (a feed with nothing older): only the linked pages and their fetch's progress. */
  linkedOnly?: boolean;
}) {
  const api = useApi();
  const ids = useId();
  const archive = status.archive ?? {};
  const stored = archive.stored_posts ?? 0;
  const [plan, setPlan] = useState<ArchivePlan | null>(null);
  // The plan's own count wins once there is one: it is a fresh measurement.
  const available = plan ? plan.available_posts : archive.available_posts ?? null;
  const basis = plan?.available_basis ?? support.available_basis;
  const availableText = describeAvailable({ available, basis, stored });

  const resumeReady = Boolean(archive.resume_ready);
  const [resume, setResume] = useState(resumeReady);
  const [pace, setPace] = useState<PacingText>(() => pacingText(archive.rate_limit));
  // The sheet sends no pacing at all, so the kind's saved values apply untouched.
  const rateArgs: [ArchivePacing?] = pacing ? [pacingOverrides(pace)] : [];
  const [plannedFor, setPlannedFor] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const latest = status.latest_job ?? null;
  // A waiting archive is followed too: the scheduler continues it on the same job (issue 0107).
  const [jobId, setJobId] = useState<string | null>(
    latest?.status === 'running' || latest?.status === 'waiting' || latest?.status === 'queued' ? latest.id : null);
  const job = useOperationJob(jobId);
  const run: RunView | null = job.data ? fromJob(job.data) : latest ? fromSummary(latest) : null;
  const running = run?.status === 'running';
  // Back to a date (issue 0130 C): a kind whose pages go newest first; blank: the whole history.
  const [until, setUntil] = useState(DEFAULT_UNTIL);
  const horizon = support.until ? until.trim() || null : null;
  const now = new Date();

  // When the followed job finishes, the stored count and the checkpoint have moved.
  const finished = Boolean(jobId && job.data && job.data.status !== 'running' && job.data.status !== 'queued');
  useEffect(() => {
    if (finished) onChanged();
  }, [finished]); // eslint-disable-line react-hooks/exhaustive-deps -- once per finish

  const planKey = `${resume}:${pacing ? JSON.stringify(pacingOverrides(pace)) : ''}`;
  const planCurrent = plan !== null && plannedFor === planKey;

  const requestPlan = async () => {
    setPlanning(true);
    setError(null);
    try {
      const next = await api.planSourceArchive(sourceId, resume, ...rateArgs);
      setPlan(next);
      setPlannedFor(planKey);
    } catch (err) {
      setPlan(null);
      setError(errorMessage(err));
    } finally {
      setPlanning(false);
    }
  };

  const start = async (fromCheckpoint = resume) => {
    setStarting(true);
    setError(null);
    try {
      // Back to a date (issue 0130 C) goes through the queue's call; without one, the archive as before. Either way a
      // Telegram or X archive while another of its kind runs is queued (the job says so).
      const { job_id: started } = horizon
        ? await archiveQueueApi.startArchive(sourceId, fromCheckpoint, horizon, ...rateArgs)
        : await api.startSourceArchive(sourceId, fromCheckpoint, ...rateArgs);
      setJobId(started);
      setPlan(null);
      setPlannedFor(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  };

  // v10.13.9: stop the running archive after its current page (whichever process runs it); what it stored stays.
  const [stopping, setStopping] = useState(false);
  const stopArchive = async () => {
    setStopping(true);
    setError(null);
    try {
      await archiveQueueApi.stopArchive(sourceId);
    } catch (err) {
      setError(errorMessage(err));
      setStopping(false);
    }
  };
  useEffect(() => {
    if (!running) setStopping(false);
  }, [running]);

  const fetchLinked = async () => {
    setStarting(true);
    setError(null);
    try {
      const { job_id: started } = await api.fetchLinkedPages(sourceId);
      setJobId(started);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  };
  // A waiting job continues on what it was reading: the archive, or the linked list.
  const continueRun = () => void (run?.linked ? fetchLinked() : start(true));

  const label = 'block text-[0.75rem] text-fg-3';
  const checkpoint = archive.checkpoint;
  const estimate = plan ? formatEstimate(plan.estimated_seconds) : null;
  const rate = plan ? describeRate(plan.rate_limit) : null;

  const note = run ? resultNote(run) : null;
  const lastRun = run && !running ? (
    run.status === 'queued' ? (
      <Notice tone="status" title="Queued"
        message="It starts when the archive of its kind ahead of it ends: one Telegram and one X archive run at a time." />
    ) : run.status === 'failed' ? (
      <Notice tone="error" title={run.linked ? 'The last fetch of linked pages failed' : 'The last archive failed'}
        message={run.message || 'No reason was recorded.'} />
    ) : run.waiting ? (
      <Notice
        tone="warning"
        title={waitingLine(run.waiting, now)}
        message={resultLine(run)}
        action={starting ? undefined : { label: 'Continue now', onClick: continueRun }}
      />
    ) : run.pausedReason ? (
      <Notice
        tone="warning"
        title={`Paused: ${run.pausedReason}`}
        message={resultLine(run)}
        action={starting ? undefined : { label: 'Resume', onClick: continueRun }}
      />
    ) : (
      <p className="text-[0.75rem] text-fg-2">
        <StatusGlyph status="ok" label="last run" />
        <span className="tabular-nums">
          {' '}{run.finishedAt ? `${formatRelativeTime(run.finishedAt, now)}: ` : ''}{resultLine(run)}
        </span>
        {note ? <span className="block text-fg-3 [overflow-wrap:anywhere]">{note}</span> : null}
      </p>
    )
  ) : null;

  if (linkedOnly) {
    return (
      <div className="space-y-3">
        {running && run ? <Progress run={run} now={now} onStop={run.linked ? undefined : () => void stopArchive()} stopping={stopping} /> : <LinkedLine linked={linked} busy={starting} onFetch={() => void fetchLinked()} />}
        {error ? <Notice tone="error" title={error} /> : null}
        {lastRun}
      </div>
    );
  }

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
          {!plan ? (
            <dd className="text-[0.75rem] text-fg-3">
              {archive.last_inspected_at ? `measured ${formatRelativeTime(archive.last_inspected_at, now)}` : 'not measured yet'}
            </dd>
          ) : null}
        </div>
      </dl>
      {/* A feed the smart archiver measured (issue 0143): its coverage, not "nothing older is reachable". */}
      {archive.coverage ? (
        <ArchiveCoverageLine sourceId={sourceId} coverage={archive.coverage} onChanged={onChanged} />
      ) : availableText.note ? <p className="text-[0.75rem] text-fg-2">{availableText.note}</p> : null}

      {running && run ? <Progress run={run} now={now} onStop={run.linked ? undefined : () => void stopArchive()} stopping={stopping} /> : (
        <>
          <LinkedLine linked={linked} busy={starting || planning} onFetch={() => void fetchLinked()} />
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

          {support.until ? (
            <div className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-fg-2">
              <label htmlFor={`${ids}-until`}>Back to</label>
              <Input id={`${ids}-until`} type="date" value={until} onChange={(e) => setUntil(e.target.value)}
                className="w-40 tabular-nums" />
              <span className="text-[0.75rem] text-fg-3">
                {horizon ? 'It stops once its pages pass this date.' : 'Blank: the whole history.'}
              </span>
            </div>
          ) : null}

          {pacing ? (
            <fieldset>
              <legend className="mb-1.5 text-[0.8125rem] font-medium text-fg">Pacing</legend>
              <div className="flex flex-wrap gap-3">
                {PACING.map(({ key, label: text, min }) => (
                  <div key={key}>
                    <label htmlFor={`${ids}-${key}`} className={label}>{text}</label>
                    <Input
                      id={`${ids}-${key}`}
                      inputMode="numeric"
                      value={pace[key]}
                      placeholder={plan?.rate_limit?.[key] !== undefined ? String(plan.rate_limit[key]) : 'default'}
                      onChange={(e) => setPace((prev) => ({ ...prev, [key]: e.target.value.replace(/[^\d]/g, '') }))}
                      onBlur={() => setPace((prev) => (prev[key] === '' ? prev : { ...prev, [key]: String(Math.max(min, Number(prev[key]))) }))}
                      className="mt-1 w-24 tabular-nums"
                    />
                  </div>
                ))}
              </div>
              <p className="mt-1 text-[0.75rem] text-fg-3">Slower is politer to the source. A blank field keeps the source's own value.</p>
            </fieldset>
          ) : null}

          {planCurrent && plan ? (
            <div className="space-y-0.5 border-l border-line-strong pl-3 text-[0.8125rem]" aria-label="Archive plan">
              <p className="tabular-nums text-fg">{describePlan(plan, estimate)}</p>
              {rate ? <p className="text-fg-3">{rate}</p> : null}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => void requestPlan()} disabled={planning || starting} aria-busy={planning}>
              {planning ? 'Planning…' : 'Plan'}
            </Button>
            {planCurrent && plan && plan.older_posts !== 0 ? (
              <Button variant="primary" size="sm" onClick={() => void start()} disabled={starting} aria-busy={starting}>
                {starting ? 'Starting…' : `${plan.resume ? 'Resume archive' : 'Run archive'}${horizon ? ` back to ${horizon}` : ''}`}
              </Button>
            ) : null}
            {planning ? <span className="text-[0.75rem] text-fg-3">Asking the source; a large channel can take minutes.</span> : null}
          </div>
        </>
      )}

      {error ? <Notice tone="error" title={error} /> : null}

      {lastRun}
    </div>
  );
}
