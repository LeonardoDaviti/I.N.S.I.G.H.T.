import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { Navigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import type { FeedFilter, FeedView } from '../services/api';
import FeedList from '../components/reader/FeedList';
import FeedToolbar from '../components/reader/FeedToolbar';
import NewPostsPill from '../components/reader/NewPostsPill';
import ReaderNavRail from '../components/reader/ReaderNavRail';
import { LiveRegionProvider } from '../components/reader/LiveRegion';
import { FEED_FIXTURE_NAMES, feedFixture, isFeedFixtureName } from '../components/reader/fixtures';
import DevDataSwitch from '../components/ops/DevDataSwitch';
import type { EmptyStateAction } from '../components/states';
import { feedKey, scopeUnreadCount, useUnreadCounts } from '../hooks/useFeed';
import { useDensityPreference } from '../hooks/useShortcutPreference';
import { scopeLabel, useReaderDirectory } from '../hooks/useReaderDirectory';
import { useIngestionRun, type IngestionTarget } from '../hooks/useIngestionRun';
import { isFeedFilter, scopeFromRoute } from '../lib/feedContext';
import { formatCount } from '../lib/format';

/**
 * How many posts arrived since the feed was loaded, from the scope's unread count.
 * The baseline follows the count down (reads elsewhere, our own mark-read) and is
 * shifted by our own mark-unread, so only real arrivals raise the pill.
 */
function useNewPosts(current: number | null, resetKey: string) {
  const state = useRef<{ key: string; baseline: number | null }>({ key: resetKey, baseline: current });
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  if (state.current.key !== resetKey) state.current = { key: resetKey, baseline: current };
  if (current !== null && (state.current.baseline === null || current < state.current.baseline)) {
    state.current.baseline = current;
  }
  const count = current !== null && state.current.baseline !== null ? Math.max(0, current - state.current.baseline) : 0;
  const onUnreadDelta = useCallback((delta: number) => {
    if (state.current.baseline !== null) state.current.baseline = Math.max(0, state.current.baseline + delta);
  }, []);
  const reset = useCallback((value: number | null) => {
    state.current.baseline = value;
    rerender();
  }, []);
  return { count, onUnreadDelta, reset };
}

/**
 * The reader-first home (spec §F.3): `/` and `/read/:scopeKind/:scopeId?`. It
 * opens on the unread main feed. The rail picks the scope, the toolbar the filter,
 * view and density (all in the URL except density, which persists locally). It
 * owns the live region, the shortcut help and the "N new posts" pill.
 */
export default function ReaderPage() {
  const { scopeKind, scopeId } = useParams();
  const scope = scopeFromRoute(scopeKind, scopeId);
  if (!scope) return <Navigate to="/" replace />;
  return <Reader key={scope} scope={scope} />;
}

function Reader({ scope }: { scope: string }) {
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const rawFilter = params.get('filter');
  const filter: FeedFilter = isFeedFilter(rawFilter) ? rawFilter : 'unread';
  const view: FeedView = params.get('view') === 'by_source' ? 'by_source' : 'stream';
  const dataName = import.meta.env.DEV ? params.get('data') : null;
  const fixture = useMemo(() => (isFeedFixtureName(dataName) ? feedFixture(dataName) : null), [dataName]);
  const [density, setDensity] = useDensityPreference();
  const [navOpen, setNavOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const counts = useUnreadCounts(fixture);
  const { folders, sourceNames } = useReaderDirectory();
  const title = scopeLabel(scope, folders.data, sourceNames);
  const scopeCount = scopeUnreadCount(counts.data, scope);

  const currentKey = useMemo(() => feedKey(scope, filter, view, fixture?.name), [filter, fixture?.name, scope, view]);
  const newPosts = useNewPosts(scopeCount, JSON.stringify(currentKey));

  useEffect(() => {
    document.title = `${title} · INSIGHT`;
  }, [title]);

  const setParam = useCallback((name: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(name);
    else next.set(name, value);
    setParams(next, { replace: true });
  }, [params, setParams]);

  const railSearch = useMemo(() => {
    const keep = new URLSearchParams();
    if (filter !== 'unread' && filter !== 'starred') keep.set('filter', filter);
    if (view !== 'stream') keep.set('view', view);
    if (dataName) keep.set('data', dataName);
    const text = keep.toString();
    return text ? `?${text}` : '';
  }, [dataName, filter, view]);

  // ---- fetch this scope ----
  const ingestion = useIngestionRun();
  const target: IngestionTarget = useMemo(() => {
    if (scope === 'all') return { kind: 'all' };
    const [kind, id] = scope.split(':');
    return kind === 'folder' ? { kind: 'folder', id, name: title } : { kind: 'source', id, name: title };
  }, [scope, title]);
  const fetchLabel = scope === 'all' ? 'Fetch due sources' : scope.startsWith('folder:') ? 'Fetch this track' : 'Fetch this source';
  const fetchScope = useCallback(() => {
    if (fixture) {
      toast('Demo data is showing; fetching is off. Switch to Live first.');
      return;
    }
    if (ingestion.isRunning(target)) return;
    void ingestion.run(target);
  }, [fixture, ingestion, target]);

  const showNewPosts = useCallback(() => {
    void queryClient.resetQueries({ queryKey: currentKey, exact: true });
    newPosts.reset(scopeCount);
    window.scrollTo({ top: 0 });
  }, [currentKey, newPosts, queryClient, scopeCount]);

  // ---- empty state, per filter and scope ----
  let emptyTitle: string;
  let emptyDescription: string | undefined;
  let emptyAction: EmptyStateAction | undefined;
  if (filter === 'unread') {
    emptyTitle = 'You’re all caught up';
    emptyDescription = 'Nothing unread from the last 30 days.';
    emptyAction = { label: 'Show all', onClick: () => setParam('filter', 'all') };
  } else if (filter === 'starred') {
    emptyTitle = 'No starred posts';
    emptyDescription = 'Press s on a post, or its star button, to keep it here.';
    emptyAction = { label: 'Show all', onClick: () => setParam('filter', 'all') };
  } else if (scope === 'all') {
    emptyTitle = 'No posts yet';
    emptyDescription = 'Add a source and fetch it to start reading.';
    emptyAction = { label: 'Add a source', href: '/settings/sources' };
  } else {
    emptyTitle = 'No posts here yet';
    emptyAction = { label: fetchLabel, onClick: fetchScope, disabled: ingestion.isRunning(target) };
  }

  const subtitle = scopeCount !== null ? `${formatCount(scopeCount)} unread` : null;

  return (
    <LiveRegionProvider>
      <div className="flex min-h-[calc(100dvh-var(--topbar-h))] bg-bg text-fg">
        <ReaderNavRail
          scope={scope}
          filter={filter}
          counts={counts.data}
          search={railSearch}
          drawerOpen={navOpen}
          onDrawerOpenChange={setNavOpen}
        />
        <div className="min-w-0 flex-1">
          <FeedToolbar
            title={filter === 'starred' && scope === 'all' ? 'Starred' : title}
            subtitle={subtitle}
            filter={filter}
            onFilterChange={(value) => setParam('filter', value === 'unread' ? null : value)}
            view={view}
            onViewChange={(value) => setParam('view', value === 'stream' ? null : value)}
            density={density}
            onDensityChange={setDensity}
            onFetch={fetchScope}
            fetching={ingestion.isRunning(target)}
            fetchLabel={fetchLabel}
            onOpenNav={() => setNavOpen(true)}
            onOpenHelp={() => setHelpOpen(true)}
            pill={<NewPostsPill count={newPosts.count} onShow={showNewPosts} />}
          />
          <div className="w-full max-w-5xl px-3 pb-32 pt-3 sm:px-6 lg:px-8">
            <FeedList
              scope={scope}
              filter={filter}
              view={view}
              density={density}
              fixture={fixture}
              emptyTitle={emptyTitle}
              emptyDescription={emptyDescription}
              emptyAction={emptyAction}
              onFetch={fetchScope}
              helpOpen={helpOpen}
              onHelpOpenChange={setHelpOpen}
              onUnreadDelta={newPosts.onUnreadDelta}
            />
          </div>
        </div>
      </div>
      <DevDataSwitch options={FEED_FIXTURE_NAMES} />
    </LiveRegionProvider>
  );
}
