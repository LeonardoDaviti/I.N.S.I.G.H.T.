import { Fragment, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2, RefreshCw, SlidersHorizontal, Zap } from 'lucide-react';

import type { HealthStatus, SourceHealthRow } from '../../services/api';
import { useSourcesHealth } from '../../hooks/useSourcesHealth';
import { useIngestionRun } from '../../hooks/useIngestionRun';
import {
  HEALTH_STATUS_LABELS,
  HEALTH_STATUS_ORDER,
  backoffLabel,
  filterHealthRows,
  formatDue,
  intervalLabel,
  sortHealthRows,
  tierHint,
  tierLabel,
} from '../../lib/sourceSchedule';
import { formatRelativeTime } from '../../lib/dates';
import { formatCount, middleTruncate, plural } from '../../lib/format';
import { EmptyState, ErrorState, LoadingState, FOCUS_RING, PRESS_FEEDBACK } from '../states';
import CadenceOverrideEditor from './CadenceOverrideEditor';
import DevDataSwitch from './DevDataSwitch';
import { HEALTH_FIXTURE_NAMES, healthFixture, isHealthFixtureName } from './fixtures';

type SortKey = 'status' | 'name' | 'next_due' | 'last_success';

const SORT_LABELS: Record<SortKey, string> = {
  status: 'Status (worst first)',
  name: 'Name',
  next_due: 'Next due',
  last_success: 'Last success (oldest first)',
};

const PAGE = 100;

const STATUS_BADGE: Record<HealthStatus, string> = {
  error: 'border-[var(--text-error)] text-[var(--text-error)]',
  backoff: 'border-[var(--text-error)] text-[var(--text-error)] bg-[var(--text-highlight-bg)]',
  unavailable: 'border-[var(--background-modifier-border)] text-[var(--text-normal)] bg-[var(--text-highlight-bg)]',
  due: 'border-[var(--accent-main)] text-[var(--text-accent)]',
  deferred: 'border-[var(--background-modifier-border)] text-[var(--text-muted)]',
  disabled: 'border-dashed border-[var(--background-modifier-border)] text-[var(--text-faint)]',
};

/** Filter chips; `error` is "failing" (error + backoff), like the "N source errors" chip. */
const FILTERS: { value: HealthStatus | null; label: string }[] = [
  { value: null, label: 'All' },
  { value: 'error', label: 'Failing' },
  { value: 'backoff', label: 'Backoff' },
  { value: 'unavailable', label: 'Unavailable' },
  { value: 'due', label: 'Due' },
  { value: 'deferred', label: 'Scheduled' },
  { value: 'disabled', label: 'Disabled' },
];

function sortRows(rows: SourceHealthRow[], key: SortKey): SourceHealthRow[] {
  if (key === 'status') return sortHealthRows(rows);
  const byName = (a: SourceHealthRow, b: SourceHealthRow) =>
    String(a.display_name).localeCompare(String(b.display_name), undefined, { sensitivity: 'base' });
  const copy = [...rows];
  if (key === 'name') return copy.sort(byName);
  if (key === 'next_due') {
    return copy.sort((a, b) => (a.next_due_at || '~').localeCompare(b.next_due_at || '~') || byName(a, b));
  }
  // Oldest success first; never-succeeded sources lead.
  return copy.sort((a, b) => (a.last_success_at || '').localeCompare(b.last_success_at || '') || byName(a, b));
}

/** Re-render once a minute so "in 3h" stays true; paused while the tab is hidden. */
function useMinuteClock(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') setNow(new Date());
    }, 60_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

function countFor(rows: SourceHealthRow[], status: HealthStatus | null): number {
  return filterHealthRows(rows, status).length;
}

/**
 * Settings → Sources → Health (spec §F.4): every source's schedule as the next run
 * sees it, worst first. Tier, interval and its basis, next due, backoff, last
 * success and last error, with Fetch now and the cadence override per row.
 * `?status=` filters (error = failing); the dev-only `?data=` swaps in fixtures.
 */
export default function SourceHealthTable({ className = '' }: { className?: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const dataParam = searchParams.get('data');
  const fixtureName = import.meta.env.DEV && isHealthFixtureName(dataParam) ? dataParam : null;
  const query = useSourcesHealth(fixtureName ? () => healthFixture(fixtureName) : undefined, fixtureName ?? undefined);
  const { run, isRunning } = useIngestionRun();
  const now = useMinuteClock();
  const [sortKey, setSortKey] = useState<SortKey>('status');
  const [editing, setEditing] = useState<string | null>(null);
  const [limit, setLimit] = useState(PAGE);

  const statusParam = searchParams.get('status');
  const activeFilter = HEALTH_STATUS_ORDER.includes(statusParam as HealthStatus) ? (statusParam as HealthStatus) : null;
  const allRows = useMemo(() => query.data?.rows ?? [], [query.data]);
  const rows = useMemo(() => sortRows(filterHealthRows(allRows, activeFilter), sortKey), [allRows, activeFilter, sortKey]);

  const setFilter = (value: HealthStatus | null) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set('status', value);
    else next.delete('status');
    setSearchParams(next, { replace: true });
    setLimit(PAGE);
  };

  const button = `inline-flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-lg px-2.5 text-sm ${PRESS_FEEDBACK} ${FOCUS_RING}`;

  let body;
  if (query.isPending) {
    body = <LoadingState label="Loading source health" rows={4} />;
  } else if (query.isError) {
    body = <ErrorState title="Could not load source health" error={query.error} onRetry={() => void query.refetch()} />;
  } else if (!allRows.length) {
    body = (
      <EmptyState
        title="No sources yet"
        description="Add a feed, channel or subreddit and its schedule shows up here."
        action={{ label: 'Add a source', href: '/settings/sources' }}
      />
    );
  } else if (!rows.length) {
    body = (
      <EmptyState
        title={`No ${(FILTERS.find((f) => f.value === activeFilter)?.label ?? '').toLowerCase()} sources`}
        description="Nothing matches this filter right now."
        action={{ label: 'Show all', onClick: () => setFilter(null) }}
      />
    );
  } else {
    const visible = rows.slice(0, limit);
    body = (
      <>
        <div className="max-h-[70vh] overflow-auto rounded-xl border border-[var(--background-modifier-border)]">
          <table className="w-full min-w-[60rem] border-collapse text-left text-sm">
            <thead className="ops-sticky-material sticky top-0 z-10 text-xs text-[var(--text-muted)] shadow-[0_1px_0_var(--background-modifier-border)]">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Source</th>
                <th scope="col" className="px-3 py-2 font-medium">Status</th>
                <th scope="col" className="px-3 py-2 font-medium">Cadence</th>
                <th scope="col" className="px-3 py-2 font-medium">Next due</th>
                <th scope="col" className="px-3 py-2 font-medium">Backoff</th>
                <th scope="col" className="px-3 py-2 font-medium">Last success</th>
                <th scope="col" className="px-3 py-2 font-medium">Last error</th>
                <th scope="col" className="px-3 py-2 font-medium"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => {
                const name = String(row.display_name || row.source_id);
                const fetchTarget = { kind: 'source' as const, id: row.source_id, name };
                const fetching = isRunning(fetchTarget);
                const backoff = backoffLabel(row, now);
                const meta = `${row.platform} · ${row.kind}`;
                return (
                  <Fragment key={row.source_id}>
                    <tr data-source-id={row.source_id} className="border-t border-[var(--background-modifier-border)] align-top">
                      <td className="min-w-[14rem] max-w-[18rem] px-3 py-2.5">
                        <div className="line-clamp-2 break-words font-medium text-[var(--text-normal)]" title={name}>
                          {name}
                        </div>
                        <div className="mt-0.5 text-xs text-[var(--text-muted)]" title={meta}>{middleTruncate(meta, 40)}</div>
                        <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-[var(--text-faint)]">
                          <span className="tabular-nums">{plural(row.stored_posts, 'post')}</span>
                          {row.backlog_posts ? <span className="tabular-nums">{formatCount(row.backlog_posts)} in backlog</span> : null}
                          {row.folders.length ? (
                            <span title={row.folders.map((folder) => folder.name).join(', ')}>{plural(row.folders.length, 'track')}</span>
                          ) : null}
                          {!row.in_main_digest ? <span>not in main feed</span> : null}
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className={`inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[row.status] ?? STATUS_BADGE.deferred}`}>
                          {HEALTH_STATUS_LABELS[row.status] ?? row.status}
                        </span>
                        {row.status === 'unavailable' && row.decision_detail ? (
                          <p className="mt-1 line-clamp-3 max-w-[14rem] text-xs text-[var(--text-muted)] [overflow-wrap:anywhere]" title={row.decision_detail}>
                            {row.decision_detail}
                          </p>
                        ) : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5">
                        <div className="text-[var(--text-normal)]" title={tierHint(row.tier)}>{tierLabel(row.tier)}</div>
                        <div className="text-xs tabular-nums text-[var(--text-muted)]"><span>{intervalLabel(row)}</span></div>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 tabular-nums" title={row.next_due_at ?? undefined}>
                        {row.enabled ? formatDue(row.next_due_at, now) : '—'}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 tabular-nums">
                        {backoff ? (
                          <>
                            <div className="text-[var(--text-error)]">{backoff}</div>
                            <div className="text-xs text-[var(--text-muted)]">{plural(row.consecutive_failures, 'failure')}</div>
                          </>
                        ) : <span className="text-[var(--text-faint)]">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 tabular-nums" title={row.last_success_at ?? undefined}>
                        {row.last_success_at ? formatRelativeTime(row.last_success_at, now) : <span className="text-[var(--text-faint)]">never</span>}
                        {row.last_outcome === 'empty' ? <div className="text-xs text-[var(--text-muted)]">last fetch empty</div> : null}
                      </td>
                      <td className="max-w-[16rem] px-3 py-2.5">
                        {row.last_error ? (
                          <>
                            <p className="line-clamp-2 text-xs text-[var(--text-error)] [overflow-wrap:anywhere]" title={row.last_error}>{row.last_error}</p>
                            {row.last_error_at ? (
                              <p className="text-xs tabular-nums text-[var(--text-faint)]">{formatRelativeTime(row.last_error_at, now)}</p>
                            ) : null}
                          </>
                        ) : <span className="text-[var(--text-faint)]">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-right">
                        <button
                          type="button"
                          onClick={() => void run(fetchTarget)}
                          disabled={fetching}
                          aria-busy={fetching}
                          aria-label={`Fetch ${name} now`}
                          title="Fetch now (ignores cadence and backoff)"
                          className={`${button} border border-[var(--background-modifier-border)] bg-[var(--background-primary)] text-[var(--text-normal)] hover:bg-[var(--background-secondary)] disabled:opacity-60`}
                        >
                          {fetching
                            ? <Loader2 aria-hidden="true" className="h-4 w-4 motion-safe:animate-spin" />
                            : <Zap aria-hidden="true" className="h-4 w-4" />}
                          <span aria-hidden="true">Fetch now</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditing((current) => (current === row.source_id ? null : row.source_id))}
                          aria-expanded={editing === row.source_id}
                          aria-label={`Edit cadence for ${name}`}
                          title="Cadence override"
                          className={`${button} ml-1 text-[var(--text-muted)] hover:bg-[var(--background-secondary)] hover:text-[var(--text-normal)]`}
                        >
                          <SlidersHorizontal aria-hidden="true" className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                    {editing === row.source_id ? (
                      <tr className="bg-[var(--background-secondary)]">
                        <td colSpan={8} className="px-3 py-3">
                          <CadenceOverrideEditor row={row} onSaved={() => setEditing(null)} onCancel={() => setEditing(null)} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        {rows.length > limit ? (
          <button
            type="button"
            onClick={() => setLimit((value) => value + PAGE)}
            className={`${button} mt-3 w-full border border-[var(--background-modifier-border)] bg-[var(--background-primary)] text-[var(--text-normal)] hover:bg-[var(--background-secondary)]`}
          >
            Show {formatCount(Math.min(PAGE, rows.length - limit))} more of {formatCount(rows.length - limit)}
          </button>
        ) : null}
      </>
    );
  }

  return (
    <section aria-label="Source health" className={`min-w-0 ${className}`}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-1.5">
          {FILTERS.map((filter) => {
            const active = filter.value === activeFilter;
            const count = query.data ? countFor(allRows, filter.value) : null;
            return (
              <button
                key={filter.label}
                type="button"
                aria-pressed={active}
                onClick={() => setFilter(filter.value)}
                className={`inline-flex min-h-[36px] items-center gap-1.5 rounded-full border px-3 text-xs font-medium ${PRESS_FEEDBACK} ${FOCUS_RING} ${
                  active
                    ? 'border-[var(--interactive-accent)] bg-[var(--interactive-accent)] text-[var(--text-on-accent)]'
                    : 'border-[var(--background-modifier-border)] bg-[var(--background-primary)] text-[var(--text-normal)] hover:bg-[var(--background-secondary)]'
                }`}
              >
                {filter.label}
                {count !== null ? <span className="tabular-nums opacity-80">{formatCount(count)}</span> : null}
              </button>
            );
          })}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
            Sort by
            <select
              value={sortKey}
              onChange={(event) => setSortKey(event.target.value as SortKey)}
              className={`min-h-[36px] rounded-lg border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-2 text-sm text-[var(--text-normal)] ${FOCUS_RING}`}
            >
              {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
                <option key={key} value={key}>{SORT_LABELS[key]}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => void query.refetch()}
            aria-label="Refresh source health"
            className={`${button} text-[var(--text-muted)] hover:bg-[var(--background-secondary)] hover:text-[var(--text-normal)]`}
          >
            <RefreshCw aria-hidden="true" className={`h-4 w-4 ${query.isFetching ? 'motion-safe:animate-spin' : ''}`} />
          </button>
        </div>
      </div>
      {query.data?.generated_at ? (
        <p className="mb-2 text-xs tabular-nums text-[var(--text-faint)]">
          {plural(allRows.length, 'source')} · as of {formatRelativeTime(query.data.generated_at, now)}
          {fixtureName ? ` · fixture: ${fixtureName}` : ''}
        </p>
      ) : null}
      {body}
      <DevDataSwitch options={HEALTH_FIXTURE_NAMES} />
    </section>
  );
}
