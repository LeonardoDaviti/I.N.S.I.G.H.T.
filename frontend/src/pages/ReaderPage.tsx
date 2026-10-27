import { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';

import type { FeedFilter, FeedView } from '../services/api';
import FeedList from '../components/reader/FeedList';
import FeedToolbar from '../components/reader/FeedToolbar';
import NewPostsPill from '../components/reader/NewPostsPill';
import ReaderNavRail from '../components/reader/ReaderNavRail';
import { LiveRegionProvider } from '../components/reader/LiveRegion';
import { FEED_FIXTURE_NAMES, isFeedFixtureName, type FeedFixtureName } from '../components/reader/fixtureNames';
import IngestionStatusNotice from '../components/ops/IngestionStatusNotice';
import { LoadingState } from '../components/states';
import DevDataSwitch from '../components/ops/DevDataSwitch';
import type { EmptyStateAction } from '../components/states';
import { feedKey, scopeUnreadCount, useUnreadCounts, type FeedFixture } from '../hooks/useFeed';
import { useDensityPreference } from '../hooks/useShortcutPreference';
import { scopeLabel, useReaderDirectory } from '../hooks/useReaderDirectory';
import { scopeDelta, type UnreadChange } from '../hooks/useReaderMutations';
import { isFeedFilter, scopeFromRoute, scopeSettingsHref } from '../lib/feedContext';
import { formatCount } from '../lib/format';
import { formatRelativeTime } from '../lib/dates';
import { ingestionActivity } from '../lib/ingestionHealth';

/**
 * How many posts arrived since the feed was loaded, from the scope's unread count.
 * The baseline follows the count down (reads elsewhere) and is shifted by every
 * change we applied to that scope's cached count ourselves, so only real arrivals
 * raise the pill. Kept in state and adjusted with the "derive from the previous
 * render" pattern, so rendering stays pure.
 */
function useNewPosts(current: number | null, resetKey: string, scope: string) {
  const [state, setState] = useState<{ key: string; baseline: number | null }>({ key: resetKey, baseline: current });
  let baseline = state.baseline;
  if (state.key !== resetKey) baseline = current;
  else if (current !== null && (baseline === null || current < baseline)) baseline = current;
  if (state.key !== resetKey || baseline !== state.baseline) setState({ key: resetKey, baseline });

  const count = current !== null && baseline !== null ? Math.max(0, current - baseline) : 0;
  const onUnreadDelta = useCallback((change: UnreadChange) => {
    const delta = scopeDelta(change, scope);
    if (!delta) return;
    setState((prev) => (prev.baseline === null ? prev : { ...prev, baseline: Math.max(0, prev.baseline + delta) }));
  }, [scope]);
  const reset = useCallback((value: number | null) => {
    setState((prev) => ({ ...prev, baseline: value }));
  }, []);
  return { count, onUnreadDelta, reset };
}

/**
 * The dev-only `?data=` fixture, imported on demand: in a production build
 * `import.meta.env.DEV` is false, so the import (and the fixture data) is dropped.
 * `pending` while the module loads, so the live feed is not fetched meanwhile.
 */
const loadFeedFixtures = import.meta.env.DEV ? () => import('../components/reader/fixtures') : null;

function useDevFeedFixture(name: FeedFixtureName | null): { fixture: FeedFixture | null; pending: boolean } {
  const [loaded, setLoaded] = useState<{ name: FeedFixtureName; fixture: FeedFixture } | null>(null);
  useEffect(() => {
    if (!name || !loadFeedFixtures || loaded?.name === name) return undefined;
    let live = true;
    void loadFeedFixtures().then((module) => {
      if (live) setLoaded({ name, fixture: module.feedFixture(name) });
    });
    return () => {
      live = false;
    };
  }, [loaded?.name, name]);
  const fixture = name && loaded?.name === name ? loaded.fixture : null;
  return { fixture, pending: Boolean(name && loadFeedFixtures) && !fixture };
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
  // One source has nothing to group by source, so it is always a stream.
  const oneSource = scope.startsWith('source:');
  const view: FeedView = !oneSource && params.get('view') === 'by_source' ? 'by_source' : 'stream';
  const dataName = import.meta.env.DEV ? params.get('data') : null;
  const { fixture, pending: fixturePending } = useDevFeedFixture(isFeedFixtureName(dataName) ? dataName : null);
  const [density, setDensity] = useDensityPreference();
  const [navOpen, setNavOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const counts = useUnreadCounts(fixture);
  const { folders, sourceNames, health } = useReaderDirectory();
  // The live feed only: fixtures have no health rows to read it from.
  const activity = fixture ? null : ingestionActivity(health.data?.rows);
  const stopped = activity?.stopped ?? false;
  const title = scopeLabel(scope, folders.data, sourceNames);
  const scopeCount = scopeUnreadCount(counts.data, scope);

  const currentKey = useMemo(() => feedKey(scope, filter, view, fixture?.name), [filter, fixture?.name, scope, view]);
  const newPosts = useNewPosts(scopeCount, JSON.stringify(currentKey), scope);

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

  const showNewPosts = useCallback(() => {
    void queryClient.resetQueries({ queryKey: currentKey, exact: true });
    newPosts.reset(scopeCount);
    window.scrollTo({ top: 0 });
  }, [currentKey, newPosts, queryClient, scopeCount]);

  // ---- empty state, per filter and scope ----
  // Memoised with the handlers below: FeedList is memo()ised, so a counts refetch
  // or a read patch re-renders the toolbar and the rail, not every row.
  const showAll = useCallback(() => setParam('filter', 'all'), [setParam]);
  const empty = useMemo((): { title: string; description?: string; action?: EmptyStateAction } => {
    if (filter === 'unread' && stopped) {
      // An empty unread feed with nothing fetching is not "caught up" (the notice above says why).
      return { title: 'No new posts: ingestion has stopped', description: 'Nothing has been fetched for over a day, so nothing new can arrive.', action: { label: 'Show all', onClick: showAll } };
    }
    if (filter === 'unread') {
      return { title: 'You’re all caught up', description: 'Nothing unread.', action: { label: 'Show all', onClick: showAll } };
    }
    if (filter === 'starred') {
      return { title: 'No starred posts', description: 'Press s on a post, or its star button, to keep it here.', action: { label: 'Show all', onClick: showAll } };
    }
    if (scope === 'all') {
      return { title: 'No posts yet', description: 'Add a source to start reading. Ingestion collects its posts.', action: { label: 'Add a source', href: '/settings/sources' } };
    }
    // Fetching is an ingestion job, not part of reading: point at Sources, quietly.
    return {
      title: 'No posts here yet',
      description: 'Posts appear once ingestion collects them.',
      action: { label: scope.startsWith('folder:') ? 'This track in Sources' : 'This source in Sources', href: scopeSettingsHref(scope) ?? '/settings/sources', quiet: true },
    };
  }, [filter, scope, showAll, stopped]);

  const subtitle = scopeCount !== null ? `${formatCount(scopeCount)} unread` : null;

  return (
    <LiveRegionProvider>
      <div className="flex min-h-[calc(100dvh-var(--topbar-h))] bg-bg text-fg">
        <ReaderNavRail
          scope={scope}
          counts={counts.data}
          search={railSearch}
          drawerOpen={navOpen}
          onDrawerOpenChange={setNavOpen}
        />
        <div className="min-w-0 flex-1">
          <FeedToolbar
            title={title}
            titleHref={scopeSettingsHref(scope)}
            subtitle={subtitle}
            filter={filter}
            onFilterChange={(value) => setParam('filter', value === 'unread' ? null : value)}
            view={view}
            onViewChange={(value) => setParam('view', value === 'stream' ? null : value)}
            density={density}
            onDensityChange={setDensity}
            onOpenNav={() => setNavOpen(true)}
            onOpenHelp={() => setHelpOpen(true)}
            oneSource={oneSource}
            pill={<NewPostsPill count={newPosts.count} onShow={showNewPosts} />}
          />
          <div className="w-full max-w-5xl px-3 pb-32 pt-3 sm:px-6 lg:px-8">
            <div className="min-w-0">
              {stopped ? (
                <IngestionStatusNotice
                  state="stopped"
                  testId="reader-ingestion-stopped"
                  linkToIngestion
                  className="mb-3"
                  message={activity?.lastAttemptAt
                    ? `The last fetch was ${formatRelativeTime(activity.lastAttemptAt)}. New posts arrive only once ingestion runs again.`
                    : 'No source has been fetched yet. New posts arrive only once ingestion runs.'}
                />
              ) : null}
              {fixturePending ? <LoadingState label="Loading demo data" rows={6} /> : (
              <FeedList
                scope={scope}
                filter={filter}
                view={view}
                density={density}
                fixture={fixture}
                emptyTitle={empty.title}
                emptyDescription={empty.description}
                emptyAction={empty.action}
                helpOpen={helpOpen}
                onHelpOpenChange={setHelpOpen}
                onUnreadDelta={newPosts.onUnreadDelta}
              />
              )}
            </div>
          </div>
        </div>
      </div>
      <DevDataSwitch options={FEED_FIXTURE_NAMES} />
    </LiveRegionProvider>
  );
}
