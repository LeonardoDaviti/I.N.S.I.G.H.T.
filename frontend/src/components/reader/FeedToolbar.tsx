import type { ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

import type { FeedFilter, ReaderView } from '../../services/api';
import { useFlowPreference, type ReadingFlow } from '../../hooks/useShortcutPreference';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';
import SearchField from './SearchField';
import SlashChoice from './SlashChoice';
import TextLink from '../ui/TextLink';

/** Kept is the star (`starred` in the URL and the API, issue 0022); History, what you opened (issue 0052). */
const FILTERS: ReadonlyArray<{ value: FeedFilter; label: string }> = [
  { value: 'unread', label: 'Unread' },
  { value: 'later', label: 'Later' },
  { value: 'starred', label: 'Kept' },
  { value: 'all', label: 'All' },
  { value: 'history', label: 'History' },
];
/** A source that watches its pages offers its updates as one more Show choice (issue 0039). */
const UPDATED = { value: 'updated' as const, label: 'Updated' };
/** News and Classics are views next to the feed (issue 0051), of the Main feed, a track or one source (0077). */
const VIEWS: ReadonlyArray<{ value: ReaderView; label: string }> = [
  { value: 'stream', label: 'Stream' },
  { value: 'by_source', label: 'By source' },
  { value: 'news', label: 'News' },
  { value: 'classics', label: 'Classics' },
];
/** One source has nothing to group by source. */
const SOURCE_VIEWS = VIEWS.filter((option) => option.value !== 'by_source');
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
  /** e.g. "248 unread", or "Later · 6 posts · 52 min" (already formatted). */
  subtitle?: string | null;
  filter: FeedFilter;
  onFilterChange: (filter: FeedFilter) => void;
  view: ReaderView;
  onViewChange: (view: ReaderView) => void;
  /** Below md the title is the button that opens the drawer of the main feed, tracks and sources. */
  onOpenNav: () => void;
  onOpenHelp: () => void;
  /** One source's posts: View is Stream / News / Classics (nothing to group by source), and no Posts flow choice. */
  oneSource?: boolean;
  /** The "N new posts" pill, when there are any. */
  pill?: ReactNode;
  /** Search what is on screen (issue 0040): the field's Enter, with its words. */
  onSearch: (query: string) => void;
  /** Offer Show Updated: one source that watches its pages for changes (issue 0039). */
  updates?: boolean;
}

/**
 * The reader's sticky toolbar, under the app's one top bar: the scope title and
 * its unread count, a search field scoped to it (issue 0040),
 * and the shortcut help as a labelled text action (fetching is
 * an ingestion job and lives in Sources), then the filter, view and how
 * the post page flows (stored here, read there) as slash-separated words; one
 * source's view is Stream / News / Classics (issue 0077), with no flow choice. The
 * theme toggle, the wordmark and the app menu live in the top bar only.
 */
export default function FeedToolbar({
  title, titleHref, subtitle, filter, onFilterChange, view, onViewChange,
  onOpenNav, onOpenHelp, oneSource = false, pill, onSearch, updates = false,
}: FeedToolbarProps) {
  const [flow, setFlow] = useFlowPreference();
  // News and Classics rank stories and pages: Show (a read-state filter) and Posts say nothing there.
  const ranked = view === 'news' || view === 'classics';
  return (
    <ReaderToolbar
      title={title}
      titleHref={titleHref}
      subtitle={subtitle}
      onOpenNav={onOpenNav}
      onOpenHelp={onOpenHelp}
      field={<SearchField label={`Search ${title}`} onSearch={onSearch} className="w-32 sm:w-48 lg:w-56" />}
    >
      <div className="-ml-1 mt-2 flex flex-wrap items-center gap-x-4 gap-y-0">
        {ranked ? null : <SlashChoice label="Show" value={filter} options={updates ? [...FILTERS, UPDATED] : FILTERS} onChange={onFilterChange} />}
        <SlashChoice label="View" value={view} options={oneSource ? SOURCE_VIEWS : VIEWS} onChange={onViewChange} />
        {oneSource || ranked ? null : <SlashChoice label="Posts" value={flow} options={FLOWS} onChange={setFlow} />}
        {pill ? <div className="ml-auto">{pill}</div> : null}
      </div>
    </ReaderToolbar>
  );
}

/**
 * The toolbar's frame, shared by the reader and the search page: the title row (a
 * `field` beside the shortcut help) and the rows below it (`children`). Below md the
 * title opens the drawer of the main feed, tracks and sources (a chevron says so), so
 * there is no second hamburger. From md up, a source or track title links to where it
 * is managed in Sources.
 */
export function ReaderToolbar({ title, titleHref, subtitle, onOpenNav, onOpenHelp, field, children }: {
  title: string;
  titleHref?: string | null;
  subtitle?: string | null;
  onOpenNav: () => void;
  onOpenHelp: () => void;
  field?: ReactNode;
  children: ReactNode;
}) {
  const heading = 'truncate text-xl font-semibold leading-tight tracking-[-0.02em] text-fg';
  // Below sm only the title row sticks (issue 0070): the frame's boxes give way (`contents`), so the
  // rows under the title scroll away with the feed and leave the screen to reading.
  return (
    <div className="reader-material reader-edge sticky top-topbar z-30 max-sm:contents">
      <div className="w-full max-w-5xl px-4 pb-2 pt-4 max-sm:contents sm:px-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-2 max-sm:reader-material max-sm:reader-edge max-sm:sticky max-sm:top-topbar max-sm:z-30 max-sm:px-4 max-sm:pb-1 max-sm:pt-3">
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
            {field}
            <button type="button" onClick={onOpenHelp} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)" className={`${TEXT_ACTION} hidden sm:inline-flex`}>
              shortcuts
              <kbd aria-hidden="true" className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-[0.25rem] border border-line-strong px-1 font-sans text-[0.75rem] not-italic text-fg-2 no-underline">?</kbd>
            </button>
          </div>
        </div>
        {subtitle ? <p className="mt-1 px-4 text-[0.8125rem] tabular-nums text-fg-3 sm:hidden">{subtitle}</p> : null}
        <div className="max-sm:px-4 max-sm:pb-2">{children}</div>
      </div>
    </div>
  );
}
