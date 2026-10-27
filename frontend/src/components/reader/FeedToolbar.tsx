import type { ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

import type { FeedFilter, FeedView } from '../../services/api';
import { useFlowPreference, type FeedDensity, type ReadingFlow } from '../../hooks/useShortcutPreference';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';
import SlashChoice from './SlashChoice';
import TextLink from '../ui/TextLink';

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
const FLOWS: ReadonlyArray<{ value: ReadingFlow; label: string }> = [
  { value: 'continuous', label: 'Continuous' },
  { value: 'single', label: 'One at a time' },
];

/** A quiet text action in the slash-nav language: a lowercase word, underlined on hover. */
const TEXT_ACTION = `inline-flex min-h-[2rem] items-center gap-1.5 whitespace-nowrap rounded-sm px-1 text-[0.875rem] lowercase text-fg-2 underline decoration-transparent decoration-1 underline-offset-[0.22em] hover:text-fg hover:decoration-fg-3 disabled:opacity-60 coarse:min-h-[2.75rem] ${PRESS_FEEDBACK} ${FOCUS_RING}`;

export interface FeedToolbarProps {
  title: string;
  /** Where this scope is managed (Sources); the title links there, quietly. */
  titleHref?: string | null;
  /** e.g. "248 unread" (already formatted). */
  subtitle?: string | null;
  filter: FeedFilter;
  onFilterChange: (filter: FeedFilter) => void;
  view: FeedView;
  onViewChange: (view: FeedView) => void;
  density: FeedDensity;
  onDensityChange: (density: FeedDensity) => void;
  /** Below md the title is the button that opens the drawer of the main feed, tracks and sources. */
  onOpenNav: () => void;
  onOpenHelp: () => void;
  /** One source's posts: no View (nothing to group by source) and no Posts flow choice. */
  oneSource?: boolean;
  /** The "N new posts" pill, when there are any. */
  pill?: ReactNode;
}

/**
 * The reader's sticky toolbar, under the app's one top bar: the scope title and
 * its unread count and the shortcut help as a labelled text action (fetching is
 * an ingestion job and lives in Sources), then the filter, view, density and how
 * the post page flows (stored here, read there) as slash-separated words; one
 * source's posts show neither the view nor the flow choice. The
 * theme toggle, the wordmark and the app menu live in the top bar only. Below md the title opens
 * the drawer of the main feed, tracks and sources (a chevron says so), so there is no second hamburger. From md
 * up, a source or track title links to where it is managed in Sources.
 */
export default function FeedToolbar({
  title, titleHref, subtitle, filter, onFilterChange, view, onViewChange, density, onDensityChange,
  onOpenNav, onOpenHelp, oneSource = false, pill,
}: FeedToolbarProps) {
  const [flow, setFlow] = useFlowPreference();
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
            {titleHref ? (
              // A quiet link: the text colour, underlined only on hover.
              <TextLink to={titleHref} className={`${heading} hidden decoration-transparent hover:decoration-fg-3 md:block`}>{title}</TextLink>
            ) : (
              <span className={`${heading} hidden md:block`}>{title}</span>
            )}
            {subtitle ? <span className="hidden shrink-0 whitespace-nowrap text-[0.8125rem] font-normal tabular-nums text-fg-3 sm:inline">{subtitle}</span> : null}
          </h1>
          <div className="flex shrink-0 items-center gap-3">
            <button type="button" onClick={onOpenHelp} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)" className={`${TEXT_ACTION} hidden sm:inline-flex`}>
              shortcuts
              <kbd aria-hidden="true" className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-[0.25rem] border border-line-strong px-1 font-sans text-[0.75rem] not-italic text-fg-2 no-underline">?</kbd>
            </button>
          </div>
        </div>
        {subtitle ? <p className="-mt-1 text-[0.8125rem] tabular-nums text-fg-3 sm:hidden">{subtitle}</p> : null}
        <div className="-ml-1 mt-2 flex flex-wrap items-center gap-x-4 gap-y-0">
          <SlashChoice label="Show" value={filter} options={FILTERS} onChange={onFilterChange} />
          {oneSource ? null : <SlashChoice label="View" value={view} options={VIEWS} onChange={onViewChange} />}
          <div className="hidden md:block"><SlashChoice label="Density" value={density} options={DENSITIES} onChange={onDensityChange} /></div>
          {oneSource ? null : <SlashChoice label="Posts" value={flow} options={FLOWS} onChange={setFlow} />}
          {pill ? <div className="ml-auto">{pill}</div> : null}
        </div>
      </div>
    </div>
  );
}
