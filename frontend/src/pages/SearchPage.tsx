import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { X } from 'lucide-react';

import type { SearchFilter, SearchOrder } from '../services/api';
import { PostList } from '../components/reader/FeedList';
import { ReaderToolbar } from '../components/reader/FeedToolbar';
import ReaderNavRail from '../components/reader/ReaderNavRail';
import SearchField from '../components/reader/SearchField';
import SlashChoice from '../components/reader/SlashChoice';
import { LiveRegionProvider } from '../components/reader/LiveRegion';
import { FilterChip } from '../components/ui/Chip';
import { useUnreadCounts } from '../hooks/useFeed';
import { scopeLabel, useReaderDirectory } from '../hooks/useReaderDirectory';
import { useSearch } from '../hooks/useSearch';
import { middleTruncate } from '../lib/format';
import { SEARCH_DAYS, isNarrowed, parseSearch, searchHref, searchOrder, type SearchState } from '../lib/search';
import SearchEntities from '../components/reader/SearchEntities';

const ShortcutHelp = lazy(() => import('../components/reader/ShortcutHelp'));
const ClassicsList = lazy(() => import('../components/reader/ClassicsList'));

/** The chips that narrow to a list, one at a time (issue 0056 adds News and Classics). */
const LISTS: ReadonlyArray<{ value: SearchFilter; label: string }> = [
  { value: 'later', label: 'Later' },
  { value: 'starred', label: 'Kept' },
  { value: 'history', label: 'History' },   // what you opened, last open first (issue 0139)
  { value: 'news', label: 'News, last 30 days' },   // the stories job's window, not any date (issue 0070)
  { value: 'classics', label: 'Classics' },
];

const ORDERS: ReadonlyArray<{ value: SearchOrder; label: string }> = [
  { value: 'newest', label: 'Newest' },
  { value: 'best', label: 'Best match' },
];

/**
 * Search across every post (issue 0040), the reader's one results view: `/search?q=…`.
 * The rail and the toolbar are the reader's; the field holds the words, the chips beside
 * it narrow them (the scope searched from first, then Later, Kept, News or Classics, and a
 * date), and a rail link narrows the search to that track or source. The results are the
 * reader's rows with their matching line, so read, Later and Keep work on them as anywhere
 * else; a story shows once, at its best-matching post, with its "covered by" line, as the Main
 * feed folds it (issue 0056). History searches what you opened, last open first (issue 0139); while Mark X is
 * on, a post also matches by Mark X's English reading of it, and up to 3 entity cards the words name lead the
 * results. With no order chosen, 2+ words list the best match first. News searches the News stories of the last 30 days (issue 0070); Classics, the classics'
 * titles and addresses, as their list shows them.
 */
export default function SearchPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const state = useMemo(() => parseSearch(params), [params]);
  const [navOpen, setNavOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const counts = useUnreadCounts();
  const { folders, sourceNames } = useReaderDirectory();
  const results = useSearch(state);

  // New words are a new entry in the history (Back returns to the last search); a chip or the order replaces it.
  const go = useCallback((next: Partial<SearchState>, { push = false } = {}) => {
    navigate(searchHref({ ...state, ...next }), { replace: !push });
  }, [navigate, state]);

  useEffect(() => {
    document.title = state.q ? `${state.q} · Search · INSIGHT` : 'Search · INSIGHT';
  }, [state.q]);

  const scopeName = state.scope ? scopeLabel(state.scope, folders.data, sourceNames) : null;
  const days = SEARCH_DAYS.find((choice) => choice.days === state.days);
  const narrowed = isNarrowed(state);
  const list = LISTS.find((choice) => choice.value === state.filter);
  const chips = [
    scopeName ? `In ${scopeName}` : null,
    list?.label ?? null,
    days?.label ?? null,
  ].filter(Boolean).join(' · ');
  const searchEverything = useCallback(() => go({ scope: null, filter: 'all', days: null }), [go]);
  const emptyAction = useMemo(() => (narrowed ? { label: 'Search everything', onClick: searchEverything } : undefined), [narrowed, searchEverything]);
  // No order chosen: best match for 2+ words, newest for one (issue 0139).
  const order = searchOrder(state);
  const classics = useMemo(() => ({ q: state.q, scope: state.scope, days: state.days, order, emptyAction }),
    [emptyAction, state.days, order, state.q, state.scope]);

  return (
    <LiveRegionProvider>
      <div className="flex min-h-[calc(100dvh-var(--topbar-h))] bg-bg text-fg">
        <ReaderNavRail
          scope={state.scope ?? ''}
          counts={counts.data}
          search=""
          scopeHref={(scope) => searchHref({ ...state, scope })}
          drawerOpen={navOpen}
          onDrawerOpenChange={setNavOpen}
        />
        <div className="min-w-0 flex-1">
          <ReaderToolbar title="Search" onOpenNav={() => setNavOpen(true)} onOpenHelp={() => setHelpOpen(true)}>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <SearchField
                key={state.q}
                label="Search posts"
                initial={state.q}
                onSearch={(q) => go({ q }, { push: true })}
                autoFocus={!state.q}
                className="w-full sm:w-80"
              />
              {scopeName ? (
                // The scope searched from: pressed, and pressing it searches every post.
                <FilterChip selected onClick={() => go({ scope: null })} title="Search every post instead">
                  <span className="inline-flex items-center gap-1" title={scopeName}>
                    {middleTruncate(scopeName, 32)}
                    <X aria-hidden="true" className="h-3 w-3" />
                  </span>
                </FilterChip>
              ) : null}
              {LISTS.map((choice) => (
                <FilterChip
                  key={choice.value}
                  selected={state.filter === choice.value}
                  onClick={() => go({ filter: state.filter === choice.value ? 'all' : choice.value })}
                >
                  {choice.label}
                </FilterChip>
              ))}
              {SEARCH_DAYS.map((choice) => (
                <FilterChip
                  key={choice.days}
                  selected={state.days === choice.days}
                  onClick={() => go({ days: state.days === choice.days ? null : choice.days })}
                >
                  {choice.label}
                </FilterChip>
              ))}
            </div>
            <div className="-ml-1 mt-1 flex flex-wrap items-center gap-x-4 gap-y-0">
              <SlashChoice label="Order" value={order} options={ORDERS} onChange={(chosen) => go({ order: chosen })} />
            </div>
          </ReaderToolbar>
          <div className="w-full max-w-5xl px-3 pb-32 pt-3 sm:px-6 lg:px-8">
            {state.q && state.filter === 'classics' ? (
              <Suspense fallback={null}>
                <ClassicsList scope={state.scope ?? 'all'} search={classics} />
              </Suspense>
            ) : state.q ? (
              <>
              {results.entities.length ? <SearchEntities entities={results.entities} /> : null}
              <PostList
                feed={results}
                scope={state.scope ?? 'all'}
                filter={state.filter === 'later' || state.filter === 'starred' ? state.filter : 'all'}
                view="stream"
                search
                emptyTitle={state.filter === 'news' ? `No News stories match “${state.q}”` : `No posts match “${state.q}”`}
                emptyDescription={narrowed ? chips : 'Try other words, or fewer of them.'}
                emptyAction={emptyAction}
                helpOpen={helpOpen}
                onHelpOpenChange={setHelpOpen}
              />
              </>
            ) : (
              <p className="px-1 text-[0.875rem] text-fg-2">
                Search every post: its title, its text and its source. Word forms count in English and Russian;
                “quoted phrases” and -word work, and “kimi 3.1” finds Kimi K3.1. Two words or more list the best
                match first. History searches what you opened; News, the stories many of your sources covered;
                Classics, the pages they keep citing.
              </p>
            )}
          </div>
        </div>
      </div>
      {!state.q && helpOpen ? (
        <Suspense fallback={null}><ShortcutHelp open onOpenChange={setHelpOpen} /></Suspense>
      ) : null}
    </LiveRegionProvider>
  );
}
