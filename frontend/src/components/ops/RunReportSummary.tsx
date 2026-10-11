import type { RunReport } from '../../services/api';
import { summarizeRunReport, type RunReportTone } from '../../lib/runReport';
import { formatCount } from '../../lib/format';
import { formatElapsed } from '../../lib/duration';
import { sourceLabel } from '../../lib/sourceLabel';
import { StatusIcon } from '../ui';
import type { Status } from '../ui';

/** Monochrome tone (design docs system/status.md): border style and a glyph, never hue. */
const TONE: Record<RunReportTone, { box: string; glyph: Status }> = {
  status: { box: 'border-line', glyph: 'running' },
  completion: { box: 'border-line-strong', glyph: 'ok' },
  warning: { box: 'border-dashed border-line-strong', glyph: 'backoff' },
  error: { box: 'border-fg', glyph: 'failing' },
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
    <li className="min-w-0 border-l border-line pl-3">
      <div className="truncate whitespace-nowrap text-[0.75rem] text-fg-3" title={label}>{label}</div>
      <div className={`tabular-nums text-fg ${emphasis ? 'text-[1.0625rem] font-semibold' : 'text-[0.9375rem]'}`}>
        {formatCount(value)}
      </div>
    </li>
  );
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
  const duration = formatElapsed(report.duration_s, { hours: false });
  const topSources = [...report.inserted_by_source].sort((a, b) => b.inserted - a.inserted).slice(0, 8);

  return (
    <section
      data-tone={summary.tone}
      aria-label="Run report"
      className={`min-w-0 rounded-md border bg-bg p-4 text-[0.875rem] ${TONE[summary.tone].box} ${className}`}
    >
      {title ? <p className="break-words text-[0.75rem] text-fg-3">{title}</p> : null}
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="flex min-w-0 items-center gap-2 break-words text-[1.0625rem] font-semibold tracking-[-0.01em] text-fg">
          <span
            aria-hidden="true"
            className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-sm ${summary.tone === 'error' ? 'bg-inverse text-inverse-fg' : ''}`}
          >
            <StatusIcon status={TONE[summary.tone].glyph} />
          </span>
          {summary.headline}
        </h3>
        {duration ? <span className="shrink-0 text-[0.75rem] tabular-nums text-fg-3">{duration}</span> : null}
      </div>
      {summary.lines.length ? (
        <ul className="mt-1 space-y-0.5 text-fg-2">
          {summary.lines.map((line) => <li key={line} className="break-words">{line}</li>)}
        </ul>
      ) : null}

      <ul aria-label="Run counts" className="mt-4 grid grid-cols-2 gap-x-2 gap-y-3 sm:grid-cols-3">
        <Count label="New posts" value={report.posts_inserted} emphasis />
        <Count label="Updated" value={report.posts_updated} />
        <Count label="Fetched posts" value={report.posts_fetched} />
        <Count label="Sources fetched" value={report.sources_fetched} />
        <Count label="Sources failed" value={report.sources_failed} />
        <Count label="Posts not saved" value={report.posts_failed} />
      </ul>

      {report.failures.length ? (
        <div className="mt-3">
          <h4 className="text-[0.75rem] font-medium text-fg-3">Failed sources</h4>
          <ul aria-label="Failed sources" className="mt-1 divide-y divide-line border-y border-line">
            {report.failures.map((failure, index) => (
              <li key={`${failure.source_id}-${index}`} className="min-w-0 py-2">
                <div className="flex min-w-0 items-baseline gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium text-fg" title={failure.display_name} dir="auto">
                    {sourceLabel(failure.display_name)}
                  </span>
                  <span className="shrink-0 text-[0.75rem] text-fg-3">{STAGE_LABELS[failure.stage] ?? failure.stage}</span>
                </div>
                <p className="mt-0.5 line-clamp-2 text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]" title={failure.error || undefined}>
                  <span aria-hidden="true" className="mr-1 font-semibold text-fg">×</span>
                  {failure.error || 'No error message'}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.post_failures.length ? (
        <p className="mt-2 text-[0.75rem] text-fg-2">
          {formatCount(report.post_failures.length)} post{report.post_failures.length === 1 ? '' : 's'} could not be saved; see the raw report.
        </p>
      ) : null}

      {topSources.length ? (
        <div className="mt-3">
          <h4 className="text-[0.75rem] font-medium text-fg-3">New posts by source</h4>
          <ul aria-label="New posts by source" className="mt-1 divide-y divide-line">
            {topSources.map((source) => (
              <li key={source.source_id} className="flex min-w-0 items-baseline gap-3 py-1">
                <span className="min-w-0 flex-1 truncate text-fg" title={source.display_name} dir="auto">
                  {sourceLabel(source.display_name)}
                </span>
                <span className="shrink-0 tabular-nums text-fg-2">{formatCount(source.inserted)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <details className="mt-3">
        <summary className="cursor-pointer select-none text-[0.75rem] text-fg-3 hover:text-fg">Raw report</summary>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-surface p-3 font-mono text-[0.75rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
          {JSON.stringify(report, null, 2)}
        </pre>
      </details>
    </section>
  );
}
