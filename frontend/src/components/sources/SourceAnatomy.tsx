import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { SourceAnatomyRow } from '../../services/api';
import { useNow } from '../../hooks/useNow';
import { SOURCE_ANATOMY_KEY } from '../../lib/ingestionNavigation';
import { formatCount } from '../../lib/format';
import {
  ANATOMY_HINTS,
  ANATOMY_LABELS,
  DEFAULT_ANATOMY_SORT,
  GIVES_COLUMNS,
  anatomyKindLabel,
  anatomyName,
  conditionalCell,
  fullTextCell,
  lastFetchCell,
  lastFetchFailed,
  nextAnatomySort,
  scheduleCell,
  sortAnatomy,
  watchCell,
  type AnatomySort,
  type Cell,
} from '../../lib/sourceAnatomy';
import { cn } from '../../lib/utils';
import { DIR_ARROWS, DIR_WORDS } from './sourceList';
import { EmptyState, ErrorState, LoadingState } from '../states';

const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg';
const TH = 'h-7 whitespace-nowrap px-2 text-[0.6875rem] font-normal text-fg-3';
const TD = 'h-9 whitespace-nowrap px-2 text-[0.75rem] coarse:h-11';
/** The name column stays in view while the table scrolls sideways (a phone). */
const STICKY = 'sticky left-0 z-[1] bg-bg';

const READ_COLUMNS = ['kind', 'fullText', 'watch', 'conditional', 'schedule', 'lastFetch'] as const;

function Header({ column, sort, dir, onSort, numeric = false }: {
  column: AnatomySort; sort: AnatomySort; dir: 'asc' | 'desc'; onSort: (column: AnatomySort) => void; numeric?: boolean;
}) {
  const active = column === sort;
  const label = ANATOMY_LABELS[column];
  return (
    <th
      scope="col"
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : undefined}
      className={cn(TH, numeric ? 'text-right' : 'text-left', column === 'name' && cn(STICKY, 'min-w-[9rem] pl-3 sm:min-w-[12rem]'))}
    >
      <button
        type="button"
        onClick={() => onSort(column)}
        aria-pressed={active}
        aria-label={active ? `Sort by ${label}, ${DIR_WORDS[dir]}` : `Sort by ${label}`}
        title={ANATOMY_HINTS[column]}
        className={cn('inline-flex items-center gap-0.5 rounded-sm hover:text-fg', FOCUS, active && 'font-medium text-fg')}
      >
        {label}
        {active ? <span aria-hidden="true">{DIR_ARROWS[dir]}</span> : null}
      </button>
    </th>
  );
}

function Word({ cell, className }: { cell: Cell; className?: string }) {
  return <td className={cn(TD, 'text-fg-2', cell.text === '—' && 'text-fg-3', className)} title={cell.title}>{cell.text}</td>;
}

function Row({ row, now, onOpen }: { row: SourceAnatomyRow; now: Date; onOpen: (id: string) => void }) {
  const name = anatomyName(row);
  const failed = lastFetchFailed(row);
  return (
    // The row opens the sheet on a click anywhere; the name is its keyboard control.
    <tr onClick={() => onOpen(row.source_id)} className="group/row cursor-pointer border-b border-line hover:bg-surface">
      <td className={cn(TD, STICKY, 'max-w-[10rem] pl-3 sm:max-w-[16rem] group-hover/row:bg-surface')}>
        <button
          type="button"
          onClick={(event) => { event.stopPropagation(); onOpen(row.source_id); }}
          title={row.display_name ? row.address : `No name of its own: ${row.address}`}
          dir="auto"
          className={cn(
            'block max-w-full truncate rounded-sm text-left text-[0.875rem]', FOCUS,
            // Named from its address: a quieter tone says it has no name of its own.
            row.display_name ? 'font-semibold text-fg' : 'text-fg-2',
            !row.enabled && 'font-normal text-fg-3',
          )}
        >
          {name}
          {row.display_name ? null : <span className="sr-only"> (no name of its own)</span>}
        </button>
      </td>
      <td className={cn(TD, 'text-fg-2')}>{anatomyKindLabel(row)}</td>
      <Word cell={fullTextCell(row)} />
      <Word cell={watchCell(row)} />
      <Word cell={conditionalCell(row)} />
      <Word cell={scheduleCell(row, now)} className="text-right tabular-nums" />
      <Word
        cell={lastFetchCell(row, now)}
        className={cn('max-w-[11rem] truncate tabular-nums', failed && 'font-medium text-fg')}
      />
      {GIVES_COLUMNS.map((key) => (
        <td
          key={key}
          className={cn(TD, 'text-right tabular-nums', row.recent[key] ? 'text-fg-2' : 'text-fg-3', key === 'posts' && 'pl-4')}
          title={`All time: ${formatCount(row.all[key])}`}
        >
          {formatCount(row.recent[key])}
        </td>
      ))}
    </tr>
  );
}

/**
 * Sources → ingestion → sources (issue 0054): every source on one table, how it is read (kind,
 * full text, change watching, conditional fetching, schedule, last fetch) and what it gave in
 * the last 30 days (posts, read, stories, reported first, classics, outside links; all time on
 * hover). Every column sorts, the most posts first by default; a row opens the source's sheet.
 * Nothing is fetched. A lazy chunk: the reader never loads it.
 */
export default function SourceAnatomy({ onOpen }: { onOpen: (id: string) => void }) {
  const api = useApi();
  const query = useQuery({ queryKey: [...SOURCE_ANATOMY_KEY], queryFn: () => api.getSourceAnatomy(), staleTime: 60_000 });
  const [order, setOrder] = useState(DEFAULT_ANATOMY_SORT);
  const now = useNow(60_000);
  const rows = useMemo(() => sortAnatomy(query.data?.rows ?? [], order.sort, order.dir), [query.data, order]);

  if (query.isPending) return <LoadingState label="Loading sources" rows={8} />;
  if (query.isError) return <ErrorState title="Could not load the sources" error={query.error} onRetry={() => void query.refetch()} />;
  if (!rows.length) return <EmptyState title="No sources yet" description="Add a source; how it is read and what it gives show here." />;

  const days = query.data.window_days;
  const onSort = (column: AnatomySort) => setOrder((current) => nextAnatomySort(current, column));
  const header = (column: AnatomySort, numeric = false) => (
    <Header key={column} column={column} sort={order.sort} dir={order.dir} onSort={onSort} numeric={numeric} />
  );
  return (
    <section aria-labelledby="anatomy-title" className="space-y-3">
      <div>
        <h2 id="anatomy-title" className="text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">Sources</h2>
        <p className="text-[0.8125rem] text-fg-3">
          How each of your {formatCount(rows.length)} sources is read, and what it gave in the last {days} days; all time on hover. A row opens its settings.
        </p>
      </div>
      <div className="-mx-3 overflow-x-auto" data-anatomy-scroll>
        <table className="w-full min-w-max border-collapse">
          <thead>
            <tr className="text-[0.6875rem] text-fg-3">
              <th scope="colgroup" className={cn(TH, STICKY)} />
              <th scope="colgroup" colSpan={READ_COLUMNS.length} className={cn(TH, 'text-left')}>How it’s read</th>
              <th scope="colgroup" colSpan={GIVES_COLUMNS.length} className={cn(TH, 'pl-4 text-right')}>What it gave · {days} days</th>
            </tr>
            <tr className="border-b border-line">
              {header('name')}
              {READ_COLUMNS.map((column) => header(column, column === 'schedule'))}
              {GIVES_COLUMNS.map((column) => header(column, true))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => <Row key={row.source_id} row={row} now={now} onOpen={onOpen} />)}
          </tbody>
        </table>
      </div>
    </section>
  );
}
