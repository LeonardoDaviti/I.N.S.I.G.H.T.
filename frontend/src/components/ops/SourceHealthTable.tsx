import { Fragment, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCw, SlidersHorizontal } from 'lucide-react';

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
  withEffectiveStatus,
} from '../../lib/sourceSchedule';
import { formatRelativeTime } from '../../lib/dates';
import { formatCount, plural, sourceLabel } from '../../lib/format';
import { EmptyState, ErrorState, LoadingState } from '../states';
import { Button, FilterChip, Select, StatusGlyph, TBody, THead, Table, Td, Th, Tr } from '../ui';
import type { Status } from '../ui';
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

/** Health status -> the monochrome status vocabulary (design doc §8): shape + word. */
const STATUS_GLYPH: Record<HealthStatus, Status> = {
  error: 'failing',
  backoff: 'backoff',
  unavailable: 'unavailable',
  due: 'due',
  deferred: 'scheduled',
  disabled: 'disabled',
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

/** The command in a decision renders as code: backticked spans, or the tail after
 *  "run " ("no Telegram session at …; run scripts/telegram_login"). */
function DecisionDetail({ text }: { text: string }) {
  const run = text.includes('`') ? null : /^(.*\brun )(\S.*)$/.exec(text);
  const parts = run ? [run[1], run[2], ''] : text.split(/`([^`]+)`/);
  return (
    <>
      {parts.map((part, index) => (index % 2 === 1 ? (
        <code key={index} className="rounded-sm border border-line bg-surface px-1 py-px font-mono text-[0.6875rem] text-fg [overflow-wrap:anywhere]">
          {part}
        </code>
      ) : part))}
    </>
  );
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
  // Status comes from the last attempt: a source whose last fetch failed reads as
  // failing (or backoff) here and in the chip counts, never as due or scheduled.
  const allRows = useMemo(() => withEffectiveStatus(query.data?.rows ?? [], now), [query.data, now]);
  const rows = useMemo(() => sortRows(filterHealthRows(allRows, activeFilter), sortKey), [allRows, activeFilter, sortKey]);

  const setFilter = (value: HealthStatus | null) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set('status', value);
    else next.delete('status');
    setSearchParams(next, { replace: true });
    setLimit(PAGE);
  };

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
    // Below md the table reflows into stacked rows (one DOM, CSS only): name and
    // status on the first line, then the schedule, then the actions. Empty cells
    // ("—") are dropped there instead of taking a line each.
    const cell = 'max-md:col-span-2 max-md:p-0';
    const mobileLabel = 'text-fg-3 md:hidden';
    body = (
      <>
        {/* The frame scrolls sideways whenever the table outgrows it (it is ~1100px
            at lg), so the header is not sticky: sticky inside a scroll box would
            pin to the box and cover the first row. */}
        <div data-health-frame className="w-full rounded-md border border-line md:overflow-x-auto">
          <Table className="md:min-w-[56rem]">
            <THead className="max-md:sr-only">
              <tr>
                <Th>Source</Th>
                <Th>Status</Th>
                <Th>Cadence</Th>
                <Th>Next due</Th>
                <Th>Backoff</Th>
                <Th>Last success</Th>
                <Th>Last error</Th>
                <Th><span className="sr-only">Actions</span></Th>
              </tr>
            </THead>
            <TBody className="max-md:block">
              {visible.map((row) => {
                const raw = String(row.display_name || row.source_id);
                const name = sourceLabel(raw);
                const fetchTarget = { kind: 'source' as const, id: row.source_id, name };
                const fetching = isRunning(fetchTarget);
                const backoff = backoffLabel(row, now);
                const detail = row.status === 'unavailable' && row.decision_detail ? row.decision_detail : null;
                return (
                  <Fragment key={row.source_id}>
                    <Tr
                      data-source-id={row.source_id}
                      className={`${detail ? 'border-b-0' : ''} max-md:grid max-md:grid-cols-[minmax(0,1fr)_auto] max-md:gap-x-3 max-md:gap-y-1 max-md:px-4 max-md:py-3`}
                    >
                      <Td className="max-md:p-0 md:min-w-[12rem] md:max-w-[18rem]">
                        <div className="line-clamp-2 break-words font-semibold [overflow-wrap:anywhere]" title={raw} dir="auto">
                          {name}
                        </div>
                        <div className="mt-0.5 flex flex-wrap gap-x-2 text-[0.75rem] text-fg-3">
                          <span>{row.platform} · {row.kind}</span>
                          <span className="tabular-nums">{plural(row.stored_posts, 'post')}</span>
                          {row.backlog_posts ? <span className="tabular-nums">{formatCount(row.backlog_posts)} in backlog</span> : null}
                          {row.folders.length ? (
                            <span title={row.folders.map((folder) => folder.name).join(', ')}>{plural(row.folders.length, 'track')}</span>
                          ) : null}
                          {!row.in_main_digest ? <span>not in main feed</span> : null}
                        </div>
                      </Td>
                      <Td className="max-md:row-start-1 max-md:col-start-2 max-md:justify-self-end max-md:p-0">
                        <StatusGlyph status={STATUS_GLYPH[row.status] ?? 'scheduled'} label={HEALTH_STATUS_LABELS[row.status] ?? row.status} />
                      </Td>
                      <Td className={`whitespace-nowrap max-md:inline ${cell}`}>
                        <div className="max-md:inline" title={tierHint(row.tier)}>
                          <span className={mobileLabel}>Cadence </span>{tierLabel(row.tier)}
                        </div>
                        <div className="text-[0.75rem] text-fg-2 max-md:inline max-md:before:content-['_·_']">{intervalLabel(row)}</div>
                      </Td>
                      <Td className={`whitespace-nowrap ${cell}`} title={row.next_due_at ?? undefined}>
                        <span className={mobileLabel}>Next due </span>
                        {row.enabled ? formatDue(row.next_due_at, now) : '—'}
                      </Td>
                      <Td className={`whitespace-nowrap ${cell} ${backoff ? '' : 'max-md:hidden'}`}>
                        {backoff ? (
                          <>
                            <div className="font-semibold max-md:inline">{backoff}</div>
                            <div className="text-[0.75rem] text-fg-2 max-md:inline max-md:before:content-['_·_']">{plural(row.consecutive_failures, 'failure')}</div>
                          </>
                        ) : <span className="text-fg-3">—</span>}
                      </Td>
                      <Td className={`whitespace-nowrap ${cell}`} title={row.last_success_at ?? undefined}>
                        <span className={mobileLabel}>Last success </span>
                        {row.last_success_at ? formatRelativeTime(row.last_success_at, now) : <span className="text-fg-3">never</span>}
                        {row.last_outcome === 'empty' ? <div className="text-[0.75rem] text-fg-2 max-md:inline max-md:before:content-['_·_']">last fetch empty</div> : null}
                      </Td>
                      <Td className={`md:max-w-[16rem] ${cell} ${row.last_error ? '' : 'max-md:hidden'}`}>
                        {row.last_error ? (
                          <>
                            <p className="line-clamp-2 text-[0.75rem] text-fg [overflow-wrap:anywhere]" title={row.last_error}>
                              <span aria-hidden="true" className="mr-1 font-semibold">×</span>
                              {row.last_error}
                            </p>
                            {row.last_error_at ? (
                              <p className="text-[0.75rem] tabular-nums text-fg-3">{formatRelativeTime(row.last_error_at, now)}</p>
                            ) : null}
                          </>
                        ) : <span className="text-fg-3">—</span>}
                      </Td>
                      <Td className={`whitespace-nowrap md:py-2 md:text-right ${cell} max-md:pt-1`}>
                        <div className="inline-flex items-center gap-1">
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => void run(fetchTarget)}
                            disabled={fetching}
                            aria-busy={fetching}
                            aria-label={`Fetch ${name} now`}
                            title="Fetch now (ignores cadence and backoff)"
                          >
                            <span aria-hidden="true">{fetching ? 'Fetching…' : 'Fetch now'}</span>
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setEditing((current) => (current === row.source_id ? null : row.source_id))}
                            aria-expanded={editing === row.source_id}
                            aria-label={`Edit cadence for ${name}`}
                            title="Cadence override"
                          >
                            <SlidersHorizontal aria-hidden="true" />
                            <span aria-hidden="true" className="md:sr-only">Cadence</span>
                          </Button>
                        </div>
                      </Td>
                    </Tr>
                    {detail ? (
                      // The reason, in full: it carries the fix (for example the
                      // telegram_login command), so it is never clamped.
                      <Tr className="max-md:block">
                        <Td colSpan={8} className="pt-0 max-md:block max-md:px-4 max-md:pb-3">
                          <p className="text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]">
                            <span className="font-semibold text-fg">Unavailable: </span>
                            <DecisionDetail text={detail} />
                          </p>
                        </Td>
                      </Tr>
                    ) : null}
                    {editing === row.source_id ? (
                      <Tr className="bg-surface max-md:block">
                        <Td colSpan={8} className="max-md:block max-md:px-4 max-md:py-3">
                          <CadenceOverrideEditor row={row} onSaved={() => setEditing(null)} onCancel={() => setEditing(null)} />
                        </Td>
                      </Tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </TBody>
          </Table>
        </div>
        {rows.length > limit ? (
          <Button variant="secondary" className="mt-3 w-full" onClick={() => setLimit((value) => value + PAGE)}>
            Show {formatCount(Math.min(PAGE, rows.length - limit))} more of {formatCount(rows.length - limit)}
          </Button>
        ) : null}
      </>
    );
  }

  return (
    <section aria-label="Source health" className={`min-w-0 ${className}`}>
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div
          role="group"
          aria-label="Filter by status"
          className="-mx-4 flex min-w-0 flex-nowrap gap-1.5 overflow-x-auto px-4 pb-0.5 sm:mx-0 sm:flex-wrap sm:px-0"
        >
          {FILTERS.map((filter) => (
            <FilterChip
              key={filter.label}
              selected={filter.value === activeFilter}
              count={query.data ? countFor(allRows, filter.value) : null}
              onClick={() => setFilter(filter.value)}
            >
              {filter.label}
            </FilterChip>
          ))}
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <label htmlFor="health-sort" className="text-[0.8125rem] text-fg-2">Sort by</label>
          <Select id="health-sort" value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
            {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
              <option key={key} value={key}>{SORT_LABELS[key]}</option>
            ))}
          </Select>
          <Button variant="ghost" size="icon" onClick={() => void query.refetch()} aria-label="Refresh source health" title="Refresh">
            <RefreshCw aria-hidden="true" className={query.isFetching ? 'motion-safe:animate-spin' : undefined} />
          </Button>
        </div>
      </div>
      {query.data?.generated_at ? (
        <p className="mb-2 text-[0.75rem] tabular-nums text-fg-3">
          {plural(allRows.length, 'source')} · as of {formatRelativeTime(query.data.generated_at, now)}
          {fixtureName ? ` · fixture: ${fixtureName}` : ''}
        </p>
      ) : null}
      {body}
      <DevDataSwitch options={HEALTH_FIXTURE_NAMES} />
    </section>
  );
}
