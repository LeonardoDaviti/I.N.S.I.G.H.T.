import type { RunReport } from '../../services/api';
import { summarizeRunReport, type RunReportTone } from '../../lib/runReport';
import { formatCount } from '../../lib/format';

const TONE_CLASS: Record<RunReportTone, string> = {
  status: 'border-[var(--background-modifier-border)] bg-[var(--background-secondary)]',
  completion: 'border-[var(--background-modifier-border)] bg-[var(--background-primary)]',
  warning: 'border-[var(--background-modifier-border)] bg-[var(--text-highlight-bg)]',
  error: 'border-[var(--text-error)] bg-[var(--background-primary)]',
};

const STAGE_LABELS: Record<string, string> = {
  fetch: 'fetch',
  save: 'save',
  connector: 'connector',
  upsert: 'save',
  discarded: 'discarded',
};

function Count({ label, value, emphasis = false }: { label: string; value: number; emphasis?: boolean }) {
  return (
    <li className="min-w-0 rounded-lg bg-[var(--background-secondary)] px-3 py-2">
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
      <div className={`tabular-nums ${emphasis ? 'text-lg font-semibold text-[var(--text-normal)]' : 'text-base font-medium text-[var(--text-normal)]'}`}>
        {formatCount(value)}
      </div>
    </li>
  );
}

function formatDuration(seconds: number | undefined): string | null {
  if (seconds === undefined || !Number.isFinite(seconds)) return null;
  if (seconds < 1) return '<1s';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

/**
 * A run report, readable (spec §F.3): the headline ("48 new posts"), what was
 * fetched and skipped, the counts, the failures and where the new posts came
 * from. The raw JSON is kept, but only behind a closed "Raw report" disclosure.
 */
export default function RunReportSummary({
  report,
  title,
  className = '',
}: {
  report: RunReport;
  /** Optional context above the headline ("Track: AI engineering"). */
  title?: string;
  className?: string;
}) {
  const summary = summarizeRunReport(report);
  const duration = formatDuration(report.duration_s);
  const topSources = [...report.inserted_by_source].sort((a, b) => b.inserted - a.inserted).slice(0, 8);

  return (
    <section
      data-tone={summary.tone}
      aria-label="Run report"
      className={`min-w-0 rounded-xl border p-4 text-sm ${TONE_CLASS[summary.tone]} ${className}`}
    >
      {title ? <p className="break-words text-xs text-[var(--text-muted)]">{title}</p> : null}
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className={`break-words text-base font-semibold tracking-[-0.01em] ${summary.tone === 'error' ? 'text-[var(--text-error)]' : 'text-[var(--text-normal)]'}`}>
          {summary.headline}
        </h3>
        {duration ? <span className="shrink-0 text-xs tabular-nums text-[var(--text-muted)]">{duration}</span> : null}
      </div>
      {summary.lines.length ? (
        <ul className="mt-1 space-y-0.5 text-[var(--text-muted)]">
          {summary.lines.map((line) => <li key={line} className="break-words">{line}</li>)}
        </ul>
      ) : null}

      <ul aria-label="Run counts" className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Count label="New posts" value={report.posts_inserted} emphasis />
        <Count label="Updated" value={report.posts_updated} />
        <Count label="Fetched posts" value={report.posts_fetched} />
        <Count label="Sources fetched" value={report.sources_fetched} />
        <Count label="Sources failed" value={report.sources_failed} />
        <Count label="Posts not saved" value={report.posts_failed} />
      </ul>

      {report.failures.length ? (
        <div className="mt-3">
          <h4 className="text-xs font-medium text-[var(--text-muted)]">Failed sources</h4>
          <ul aria-label="Failed sources" className="mt-1 space-y-1.5">
            {report.failures.map((failure, index) => (
              <li key={`${failure.source_id}-${index}`} className="min-w-0 rounded-lg bg-[var(--background-secondary)] px-3 py-2">
                <div className="flex min-w-0 items-baseline gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium text-[var(--text-normal)]" title={failure.display_name}>
                    {failure.display_name}
                  </span>
                  <span className="shrink-0 text-xs text-[var(--text-muted)]">{STAGE_LABELS[failure.stage] ?? failure.stage}</span>
                </div>
                <p className="mt-0.5 line-clamp-2 text-xs text-[var(--text-error)] [overflow-wrap:anywhere]" title={failure.error || undefined}>
                  {failure.error || 'No error message'}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.post_failures.length ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          {formatCount(report.post_failures.length)} post{report.post_failures.length === 1 ? '' : 's'} could not be saved; see the raw report.
        </p>
      ) : null}

      {topSources.length ? (
        <div className="mt-3">
          <h4 className="text-xs font-medium text-[var(--text-muted)]">New posts by source</h4>
          <ul aria-label="New posts by source" className="mt-1 divide-y divide-[var(--background-modifier-border)]">
            {topSources.map((source) => (
              <li key={source.source_id} className="flex min-w-0 items-baseline gap-3 py-1">
                <span className="min-w-0 flex-1 truncate text-[var(--text-normal)]" title={source.display_name}>
                  {source.display_name}
                </span>
                <span className="shrink-0 tabular-nums text-[var(--text-muted)]">{formatCount(source.inserted)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <details className="mt-3">
        <summary className="cursor-pointer select-none text-xs text-[var(--text-muted)] hover:text-[var(--text-normal)]">Raw report</summary>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-[var(--background-secondary)] p-3 text-xs leading-5 text-[var(--text-normal)] [overflow-wrap:anywhere]">
          {JSON.stringify(report, null, 2)}
        </pre>
      </details>
    </section>
  );
}
