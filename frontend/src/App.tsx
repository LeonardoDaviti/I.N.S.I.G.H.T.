import { Suspense, lazy, type ReactNode } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './components/ThemeProvider';
import AppErrorBoundary from './components/AppErrorBoundary';
import AppShell from './components/layout/AppShell';
import { LoadingState } from './components/states';
import { ApiProvider } from './services/ApiContext';
import { sourcesIngestionHref } from './lib/ingestionNavigation';
import { useMarkxState } from './hooks/useMarkxOn';

const queryClient = new QueryClient();
const ReaderPage = lazy(() => import('./pages/ReaderPage'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const PostDetailPage = lazy(() => import('./pages/PostDetailPage'));
const SourcesConfig = lazy(() => import('./pages/SourcesConfig'));
const SavePage = lazy(() => import('./pages/SavePage'));
// Dev-only (v10.17, issue 0190): the blog and the Design Studio are never in the production bundle. Vite makes
// `import.meta.env.DEV` false in `vite build`, so these imports are dead code there and their chunks are not built
// (scripts/bundle-check.mjs fails if one is); `npm run dev` serves them as before.
const BlogPage = import.meta.env.DEV ? lazy(() => import('./pages/BlogPage')) : null;
const DesignStudio = import.meta.env.DEV ? lazy(() => import('./design/DesignStudio')) : null;
const DesignFrame = import.meta.env.DEV ? lazy(() => import('./design/frame/FrameApp')) : null;
// Mark X Shadow's page (issue 0086 E): its own chunk, so the feed and the post route don't grow for it.
const MarkXPage = lazy(() => import('./pages/MarkXPage'));
const MarkXEntityPage = lazy(() => import('./pages/MarkXEntityPage'));   // 0119 A3
const MarkXStoryPage = lazy(() => import('./pages/MarkXStoryPage'));     // 0119 B6
const MarkXSourcesPage = lazy(() => import('./components/markx/sources/MarkXSourcesPage'));   // 0132 B
const MarkXSourcePage = lazy(() => import('./components/markx/sources/MarkXSourcePage'));     // 0132 B
const ResearchPage = lazy(() => import('./pages/ResearchPage'));   // 0162

/** The error boundary resets when the route changes, so leaving a broken page recovers. */
export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <AppErrorBoundary resetKey={location.pathname}>{children}</AppErrorBoundary>;
}

/** While a route's code loads: a quiet skeleton in the page column, not a blank screen. */
function RouteFallback() {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 pt-10 sm:px-6">
      <LoadingState label="Loading page" rows={4} />
    </div>
  );
}

/** `/markx` only while Mark X is on (INSIGHT_MARKX): while asking, the page skeleton; off, the feed. */
function MarkXRoute({ page }: { page?: 'entity' | 'story' | 'sources' | 'source' | 'research' }) {
  const on = useMarkxState();
  if (on === undefined) return <RouteFallback />;
  if (!on) return <Navigate to="/" replace />;
  if (page === 'story') return <MarkXStoryPage />;
  if (page === 'sources') return <MarkXSourcesPage />;   // 0132 B
  if (page === 'source') return <MarkXSourcePage />;
  if (page === 'research') return <ResearchPage />;
  return page === 'entity' ? <MarkXEntityPage /> : <MarkXPage />;
}

/**
 * The old ingestion page moved to the ingestion tab under sources
 * (reading-finish R3), carrying the tab and query.
 */
function IngestionRedirect() {
  const { tab } = useParams();
  const location = useLocation();
  return <Navigate to={sourcesIngestionHref(tab, location.search)} replace />;
}

/** The reader params a track link may carry; the old page's `?days=` window has no reader equivalent. */
const TRACK_KEPT_PARAMS = ['filter', 'view'] as const;

/**
 * The retired track page (Design Studio D5): `/tracks/:id` is the reader scoped
 * to that folder, replacing the history entry so Back doesn't bounce.
 */
function TrackRedirect() {
  const { trackId = '' } = useParams();
  const location = useLocation();
  const from = new URLSearchParams(location.search);
  const kept = new URLSearchParams();
  for (const name of TRACK_KEPT_PARAMS) {
    const value = from.get(name);
    if (value !== null) kept.set(name, value);
  }
  const search = kept.toString();
  return <Navigate to={`/read/folder/${encodeURIComponent(trackId)}${search ? `?${search}` : ''}`} replace />;
}

/**
 * Routes (design docs system/information-architecture.md). `/` is the reader feed: the Mark VIII hub is gone and
 * `/hub` redirects home. Every route renders inside the AppShell top bar.
 * The app is feed / sources / post. `/tracks/:id` redirects to the reader
 * scoped to the track (Design Studio D5). The retired analysis paths (briefings,
 * stories, inbox, experts, the tracks list; issue 0005) land on the feed, replacing
 * the history entry. `/search` searches every post (issue 0040). `/save` saves any page (the bookmarklet's and ⌘K's, issue 0031). `/markx` is Mark X Shadow's page, while it is on (issue 0086 E). In dev only (`npm run dev`;
 * absent from the production bundle, 0190): `/blog`, the engineering blog, and `/design/*`, the Design Studio, reached
 * from ⌘K only.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<ReaderPage />} />
      <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
      <Route path="/search" element={<SearchPage />} />
      <Route path="/hub" element={<Navigate to="/" replace />} />
      <Route path="/ingestion" element={<IngestionRedirect />} />
      <Route path="/ingestion/:tab" element={<IngestionRedirect />} />
      <Route path="/posts/:postId" element={<PostDetailPage />} />
      <Route path="/settings/sources" element={<SourcesConfig />} />
      <Route path="/tracks/:trackId" element={<TrackRedirect />} />
      <Route path="/save" element={<SavePage />} />
      {BlogPage && <Route path="/blog" element={<BlogPage />} />}
      {BlogPage && <Route path="/blog/:slug" element={<BlogPage />} />}
      {DesignStudio && <Route path="/design/*" element={<DesignStudio />} />}
      <Route path="/markx" element={<MarkXRoute />} />
      <Route path="/markx/entities/:entityId" element={<MarkXRoute page="entity" />} />
      <Route path="/markx/stories/:storyId" element={<MarkXRoute page="story" />} />
      <Route path="/markx/sources" element={<MarkXRoute page="sources" />} />
      <Route path="/markx/sources/:sourceId" element={<MarkXRoute page="source" />} />
      <Route path="/research/:runId?" element={<MarkXRoute page="research" />} />
      <Route path="/briefing" element={<Navigate to="/" replace />} />
      <Route path="/briefing/topics" element={<Navigate to="/" replace />} />
      <Route path="/briefing/vertical/*" element={<Navigate to="/" replace />} />
      <Route path="/stories" element={<Navigate to="/" replace />} />
      <Route path="/inbox" element={<Navigate to="/" replace />} />
      <Route path="/experts" element={<Navigate to="/" replace />} />
      <Route path="/tracks" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  // The Design Studio's chromeless frame (`/design/frame/:page/:state`, D4): its
  // own router, providers and fixture fetch, so it replaces the app, not a route in it.
  // The prefix is inlined (design/frame/frameUrl.ts FRAME_PREFIX) to keep the reader's JS lean (D8).
  if (DesignFrame && window.location.pathname.startsWith('/design/frame/')) {
    return <Suspense fallback={null}><DesignFrame /></Suspense>;
  }
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider>
        <ThemeProvider>
          <Router>
            <AppShell>
              <RouteErrorBoundary>
                <Suspense fallback={<RouteFallback />}>
                  <AppRoutes />
                </Suspense>
              </RouteErrorBoundary>
            </AppShell>
          </Router>
        </ThemeProvider>
      </ApiProvider>
    </QueryClientProvider>
  );
}

export default App;
