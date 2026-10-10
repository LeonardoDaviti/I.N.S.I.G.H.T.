import type { ReactNode } from 'react';
import { ChevronDown, RefreshCw } from 'lucide-react';

import type { FeedFilter, FeedView } from '../../services/api';
import type { FeedDensity } from '../../hooks/useShortcutPreference';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';
import SlashChoice from './SlashChoice';

const FILTERS: ReadonlyArray<{ value: FeedFilter; label: string }> = [
  { value: 'unread', label: 'Unread' },
  { value: 'starred', label: 'Starred' },
  { value: 'all', label: 'All' },
];
const VIEWS: ReadonlyArray<{ value: FeedView; label: string }> = [
  { value: 'stream', label: 'Stream' },
  { value: 'by_source', label: 'By source' },
];
const DENSITIES: ReadonlyArray<{ value: FeedDensity; label: string }> = [
  { value: 'comfortable', label: 'Comfortable' },
  { value: 'compact', label: 'Compact' },
];

/** A quiet text action in the slash-nav language: a lowercase word, underlined on hover. */
const TEXT_ACTION = `inline-flex min-h-[2rem] items-center gap-1.5 whitespace-nowrap rounded-sm px-1 text-[0.875rem] lowercase text-fg-2 underline decoration-transparent decoration-1 underline-offset-[0.22em] hover:text-fg hover:decoration-fg-3 disabled:opacity-60 coarse:min-h-[2.75rem] ${PRESS_FEEDBACK} ${FOCUS_RING}`;

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
 * its unread count, the scope fetch and the shortcut help as labelled text
 * actions, then the filter, view and density as slash-separated words. The theme toggle, the
 * wordmark and the app menu live in the top bar only. Below md the title opens
 * the feeds drawer (a chevron says so), so there is no second hamburger.
 */
export default function FeedToolbar({
  title, subtitle, filter, onFilterChange, view, onViewChange, density, onDensityChange,
  onFetch, fetching = false, fetchLabel, onOpenNav, onOpenHelp, pill,
}: FeedToolbarProps) {
  const heading = 'truncate text-xl font-semibold leading-tight tracking-[-0.02em] text-fg';
  return (
    <div className="reader-material reader-edge sticky top-topbar z-30">
      <div className="w-full max-w-5xl px-4 pb-2 pt-4 sm:px-6 lg:px-8">
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
          <div className="flex shrink-0 items-center gap-3">
            {onFetch ? (
              <button type="button" onClick={onFetch} disabled={fetching} aria-label={fetchLabel} title={`${fetchLabel} (f)`} className={TEXT_ACTION}>
                <RefreshCw aria-hidden="true" className={`h-3.5 w-3.5 ${fetching ? 'motion-safe:animate-spin' : ''}`} />
                <span className="sm:hidden">{fetching ? 'fetching…' : 'fetch'}</span>
                <span className="hidden sm:inline">{fetching ? 'fetching…' : fetchLabel}</span>
              </button>
            ) : null}
            <button type="button" onClick={onOpenHelp} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)" className={`${TEXT_ACTION} hidden sm:inline-flex`}>
              shortcuts
              <kbd aria-hidden="true" className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-[0.25rem] border border-line-strong px-1 font-sans text-[0.75rem] not-italic text-fg-2 no-underline">?</kbd>
            </button>
          </div>
        </div>
        {subtitle ? <p className="-mt-1 text-[0.8125rem] tabular-nums text-fg-3 sm:hidden">{subtitle}</p> : null}
        <div className="-ml-1 mt-2 flex flex-wrap items-center gap-x-4 gap-y-0">
          <SlashChoice label="Show" value={filter} options={FILTERS} onChange={onFilterChange} />
          <SlashChoice label="View" value={view} options={VIEWS} onChange={onViewChange} />
          <div className="hidden md:block"><SlashChoice label="Density" value={density} options={DENSITIES} onChange={onDensityChange} /></div>
          {pill ? <div className="ml-auto">{pill}</div> : null}
        </div>
      </div>
    </div>
  );
}
