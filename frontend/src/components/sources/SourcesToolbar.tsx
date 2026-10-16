import { Fragment, forwardRef, useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';

import { FilterChip, Select } from '../ui';
import SortButton from './SortButton';
import {
  DIR_ARROWS,
  DIR_WORDS,
  GROUP_BY,
  GROUP_BY_LABELS,
  SORT_BY,
  SORT_BY_LABELS,
  STATUS_FILTERS,
  nextSort,
  type GroupBy,
  type SourcesView,
  type StatusFilter,
} from './sourceList';

/**
 * The one toolbar above the list (sticky, translucent): search, status chips
 * and group-by. The primary chips (all, enabled, disabled, failing,
 * unavailable) always show; the secondary ones (backoff, due, scheduled) only
 * with sources or while selected. Below md, where columns hide, "Sort: Added ↓"
 * opens the column headers' sort buttons as a row. Its height is published as
 * `--sources-toolbar-h` so group headers stick right under it.
 */
const SourcesToolbar = forwardRef<HTMLInputElement, {
  view: SourcesView;
  counts: Partial<Record<StatusFilter, number>>;
  total: number;
  onChange: (view: SourcesView) => void;
}>(function SourcesToolbar({ view, counts, total, onChange }, searchRef) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [sorting, setSorting] = useState(false);

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return undefined;
    // On phones the toolbar scrolls away (it is three lines there), so headers stick to the top bar.
    const publish = () => {
      const sticky = getComputedStyle(el).position === 'sticky';
      el.parentElement?.style.setProperty('--sources-toolbar-h', `${sticky ? el.offsetHeight : 0}px`);
    };
    publish();
    window.addEventListener('resize', publish);
    if (typeof ResizeObserver === 'undefined') return () => window.removeEventListener('resize', publish);
    const observer = new ResizeObserver(publish);
    observer.observe(el);
    return () => { observer.disconnect(); window.removeEventListener('resize', publish); };
  }, []);

  const chips = STATUS_FILTERS.filter((chip) => !chip.secondary || (counts[chip.value] ?? 0) > 0 || chip.value === view.status);
  const select = '[&_select]:min-h-[2rem] [&_select]:py-1 [&_select]:text-[0.8125rem]';

  return (
    <div
      ref={rootRef}
      className="material relative z-20 sm:sticky sm:top-[var(--topbar-h)] -mx-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-2 sm:mx-0 sm:px-0"
    >
      <label className="relative flex min-w-0 flex-1 basis-[12rem] items-center sm:max-w-[18rem]">
        <span className="sr-only">Search sources</span>
        <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 h-4 w-4 text-fg-3" />
        <input
          ref={searchRef}
          type="search"
          value={view.q}
          onChange={(event) => onChange({ ...view, q: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === 'Escape' && view.q) { event.preventDefault(); onChange({ ...view, q: '' }); }
            if (event.key === 'Escape' && !view.q) event.currentTarget.blur();
          }}
          placeholder="Search sources"
          className="h-8 w-full min-w-0 rounded-md border border-line bg-transparent pl-8 pr-8 text-[0.8125rem] text-fg placeholder:text-fg-3 hover:border-line-strong focus:border-line-strong focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-fg coarse:h-11 [&::-webkit-search-cancel-button]:hidden"
        />
        {view.q ? (
          <button
            type="button"
            onClick={() => onChange({ ...view, q: '' })}
            aria-label="Clear search"
            className="absolute right-1.5 inline-flex h-6 w-6 items-center justify-center rounded-sm text-fg-3 hover:text-fg"
          >
            <X aria-hidden="true" className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </label>

      <div role="group" aria-label="Filter by status" className="flex min-w-0 flex-nowrap gap-1.5 overflow-x-auto">
        <FilterChip selected={view.status === null} count={total} onClick={() => onChange({ ...view, status: null })} className="min-h-[1.75rem] px-2">
          All
        </FilterChip>
        {chips.map((chip, index) => (
          <Fragment key={chip.value}>
            {/* A hairline before the first secondary chip: the primary set reads as one group. */}
            {chip.secondary && !chips[index - 1]?.secondary ? <span aria-hidden="true" className="my-1.5 w-px shrink-0 self-stretch bg-line" /> : null}
            <FilterChip
              selected={view.status === chip.value}
              count={counts[chip.value] ?? 0}
              onClick={() => onChange({ ...view, status: view.status === chip.value ? null : chip.value })}
              className="min-h-[1.75rem] px-2"
            >
              {chip.label}
            </FilterChip>
          </Fragment>
        ))}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        <label htmlFor="sources-group" className="text-[0.75rem] text-fg-3">Group</label>
        <Select
          id="sources-group"
          value={view.group}
          onChange={(event) => onChange({ ...view, group: event.target.value as GroupBy })}
          className={select}
        >
          {GROUP_BY.map((key) => <option key={key} value={key}>{GROUP_BY_LABELS[key]}</option>)}
        </Select>
        <button
          type="button"
          onClick={() => setSorting((open) => !open)}
          aria-expanded={sorting}
          aria-controls="sources-sort"
          aria-label={`Sort: ${SORT_BY_LABELS[view.sort]}, ${DIR_WORDS[view.dir]}`}
          className="whitespace-nowrap rounded-sm text-[0.75rem] text-fg-3 hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg md:hidden"
        >
          Sort: {SORT_BY_LABELS[view.sort]} {DIR_ARROWS[view.dir]}
        </button>
      </div>

      {sorting ? (
        <div id="sources-sort" role="group" aria-label="Sort by" className="flex basis-full flex-wrap gap-x-4 gap-y-2 text-[0.8125rem] text-fg-3 md:hidden">
          {SORT_BY.map((column) => (
            <SortButton
              key={column}
              column={column}
              sort={view.sort}
              dir={view.dir}
              onSort={(next) => { onChange(nextSort(view, next)); setSorting(false); }}
              className="coarse:min-h-[2.75rem]"
            />
          ))}
        </div>
      ) : null}
    </div>
  );
});

export default SourcesToolbar;
