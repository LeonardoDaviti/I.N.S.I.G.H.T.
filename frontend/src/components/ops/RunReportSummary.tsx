import type { RunReport } from '../../services/api';
import { summarizeRunReport, type RunReportTone } from '../../lib/runReport';
import { formatCount, plural } from '../../lib/format';
import { formatElapsed } from '../../lib/duration';
import { sourceReadPath } from '../../lib/feedContext';
import { sourceLabel } from '../../lib/sourceLabel';
import { StatusIcon, TextLink } from '../ui';
import type { Status } from '../ui';

/** Monochrome tone (design docs system/status.md): border style and a glyph, never hue. */
const TONE: Record<RunReportTone, { box: string; glyph: Status }> = {
  status: { box: 'border-line', glyph: 'running' },
  completion: { box: 'border-line-strong', glyph: 'ok' },
  warning: { box: 'border-dashed border-line-strong', glyph: 'backoff' },
  error: { box: 'border-fg', glyph: 'failing' },
};

/**
 * A run report, readable (issue 0021): what the run delivered in words ("34 new
 * posts from 5 sources"), the sources that delivered, each linked to read it,
 * and the sources that failed, one line each with the reason. No zero counts.
 */
export default function RunReportSummary({ report, className = '' }: { report: RunReport; className?: string }) {
  const summary = summarizeRunReport(report);
  const duration = formatElapsed(report.duration_s, { hours: false });
  const delivered = [...report.inserted_by_source].sort((a, b) => b.inserted - a.inserted);
  const more = (report.sources_with_new ?? delivered.length) - delivered.length;

  return (
    <section
      data-tone={summary.tone}
      aria-label="Run report"
      className={`min-w-0 rounded-md border bg-bg p-4 text-[0.875rem] ${TONE[summary.tone].box} ${className}`}
    >
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
      {summary.lines.map((line) => <p key={line} className="mt-1 break-words text-fg-2">{line}</p>)}

      {delivered.length ? (
        <ul aria-label="New posts by source" className="mt-3 divide-y divide-line">
          {delivered.map((source) => (
            <li key={source.source_id} className="flex min-w-0 items-baseline gap-3 py-1">
              <TextLink to={sourceReadPath(source.source_id)} className="min-w-0 flex-1 truncate" title={source.display_name} dir="auto">
                {sourceLabel(source.display_name)}
              </TextLink>
              <span className="shrink-0 tabular-nums text-fg-2">{formatCount(source.inserted)}</span>
            </li>
          ))}
          {more > 0 ? <li className="py-1 text-fg-3">and {plural(more, 'more source')}</li> : null}
        </ul>
      ) : null}

      {report.failures.length ? (
        <ul aria-label="Failed sources" className="mt-3 divide-y divide-line border-t border-line">
          {report.failures.map((failure, index) => (
            <li key={`${failure.source_id}-${index}`} className="flex min-w-0 items-baseline gap-2 py-1.5">
              <span aria-hidden="true" className="shrink-0 font-semibold text-fg">×</span>
              <span className="max-w-[40%] shrink-0 truncate font-medium text-fg" title={failure.display_name} dir="auto">
                {sourceLabel(failure.display_name)}
              </span>
              <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-fg-2" title={failure.error || undefined}>
                {failure.error || 'No error message'}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
