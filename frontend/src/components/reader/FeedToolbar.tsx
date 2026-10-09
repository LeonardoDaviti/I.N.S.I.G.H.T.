import { Fragment, type ReactNode } from 'react';
import { ChevronDown, HelpCircle, RefreshCw, Rows3, Rows4 } from 'lucide-react';

import type { FeedFilter, FeedView } from '../../services/api';
import type { FeedDensity } from '../../hooks/useShortcutPreference';
import { iconButtonClass } from '../ui/styles';
import { FOCUS_RING } from '../states';

/**
 * A radio group drawn as the top bar's language: lowercase words separated by
 * slashes, the current one bold and underlined. No pills, no fills.
 */
function SlashChoice<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (value: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex shrink-0 items-center gap-1.5 text-[0.875rem]">
      {options.map((option, index) => {
        const active = option.value === value;
        return (
          <Fragment key={option.value}>
            {index > 0 ? <span aria-hidden="true" className="select-none text-fg-3">/</span> : null}
            <button
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(option.value)}
              className={`inline-flex min-h-[2rem] items-center whitespace-nowrap rounded-sm lowercase underline decoration-1 underline-offset-[0.22em] coarse:min-h-[2.75rem] ${active ? 'font-semibold text-fg decoration-fg' : 'text-fg-2 decoration-transparent hover:text-fg hover:decoration-fg-3'} ${FOCUS_RING}`}
            >
              {option.label}
            </button>
          </Fragment>
        );
      })}
    </div>
  );
}

/** Two icon toggles in one hairline box (density is a mode, not a word). */
function DensityToggle({ value, onChange }: { value: FeedDensity; onChange: (value: FeedDensity) => void }) {
  const options = [
    { value: 'comfortable' as const, label: 'Comfortable', icon: <Rows3 aria-hidden="true" className="h-4 w-4" /> },
    { value: 'compact' as const, label: 'Compact (titles only)', icon: <Rows4 aria-hidden="true" className="h-4 w-4" /> },
  ];
  return (
    <div role="radiogroup" aria-label="Density" className="inline-flex shrink-0 rounded-md border border-line p-0.5">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={option.label}
            title={option.label}
            onClick={() => onChange(option.value)}
            className={`inline-flex h-7 w-8 items-center justify-center rounded-[0.25rem] coarse:h-10 coarse:w-11 ${active ? 'bg-inverse text-inverse-fg' : 'text-fg-3 hover:text-fg'} ${FOCUS_RING}`}
          >
            {option.icon}
          </button>
        );
      })}
    </div>
  );
}

const FILTERS: ReadonlyArray<{ value: FeedFilter; label: string }> = [
  { value: 'unread', label: 'Unread' },
  { value: 'starred', label: 'Starred' },
  { value: 'all', label: 'All' },
];
const VIEWS: ReadonlyArray<{ value: FeedView; label: string }> = [
  { value: 'stream', label: 'Stream' },
  { value: 'by_source', label: 'By source' },
];

export interface FeedToolbarProps {
  title: string;
  /** e.g. "248 unread" (already formatted). */
  subtitle?: string | null;
  filter: FeedFilter;
  onFilterChange: (filter: FeedFilter) => void;
  view: FeedView;
  onViewChange: (view: FeedView) => void;
  density: FeedDensity;
  onDensityChange: (density: FeedDensity) => void;
  onFetch?: () => void;
  fetching?: boolean;
  fetchLabel: string;
  /** Below md the title is the button that opens the feeds drawer. */
  onOpenNav: () => void;
  onOpenHelp: () => void;
  /** The "N new posts" pill, when there are any. */
  pill?: ReactNode;
}

/**
 * The reader's sticky toolbar, under the app's one top bar: the scope title and
 * its unread count, the scope fetch and the shortcut help, then the filter and
 * view as slash-separated words and the density toggle. The theme toggle, the
 * wordmark and the app menu live in the top bar only. Below md the title opens
 * the feeds drawer (a chevron says so), so there is no second hamburger.
 */
export default function FeedToolbar({
  title, subtitle, filter, onFilterChange, view, onViewChange, density, onDensityChange,
  onFetch, fetching = false, fetchLabel, onOpenNav, onOpenHelp, pill,
}: FeedToolbarProps) {
  const heading = 'truncate text-xl font-semibold leading-tight tracking-[-0.02em] text-fg';
  return (
    <div className="reader-material reader-edge sticky top-0 z-30">
      <div className="mx-auto w-full max-w-3xl px-4 pb-2 pt-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-2">
          <h1 className="flex min-w-0 flex-1 items-baseline gap-2" title={title}>
            <button
              type="button"
              onClick={onOpenNav}
              aria-haspopup="dialog"
              className={`-ml-1 inline-flex min-h-[2.75rem] min-w-0 items-center gap-1 rounded-md px-1 md:hidden ${FOCUS_RING}`}
            >
              <span className={heading}>{title}</span>
              <ChevronDown aria-hidden="true" className="h-4 w-4 shrink-0 text-fg-3" />
              <span className="sr-only">, open navigation</span>
            </button>
            <span className={`${heading} hidden md:block`}>{title}</span>
            {subtitle ? <span className="hidden shrink-0 whitespace-nowrap text-[0.8125rem] font-normal tabular-nums text-fg-3 sm:inline">{subtitle}</span> : null}
          </h1>
          <div className="flex shrink-0 items-center gap-0.5">
            <div className="mr-1.5"><DensityToggle value={density} onChange={onDensityChange} /></div>
            {onFetch ? (
              <button type="button" onClick={onFetch} disabled={fetching} aria-label={fetchLabel} title={`${fetchLabel} (f)`} className={iconButtonClass}>
                <RefreshCw aria-hidden="true" className={fetching ? 'motion-safe:animate-spin' : ''} />
              </button>
            ) : null}
            <button type="button" onClick={onOpenHelp} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)" className={iconButtonClass}>
              <HelpCircle aria-hidden="true" />
            </button>
          </div>
        </div>
        {subtitle ? <p className="-mt-1 text-[0.8125rem] tabular-nums text-fg-3 sm:hidden">{subtitle}</p> : null}
        <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1">
          <SlashChoice label="Show" value={filter} options={FILTERS} onChange={onFilterChange} />
          <SlashChoice label="View" value={view} options={VIEWS} onChange={onViewChange} />
          {pill ? <div className="ml-auto">{pill}</div> : null}
        </div>
      </div>
    </div>
  );
}
