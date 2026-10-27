import { Suspense, lazy, type ReactNode } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './components/ThemeProvider';
import AppErrorBoundary from './components/AppErrorBoundary';
import AppShell from './components/layout/AppShell';
import { LoadingState } from './components/states';
import { ApiProvider } from './services/ApiContext';
import { sourcesIngestionHref } from './lib/ingestionNavigation';

const queryClient = new QueryClient();
const ReaderPage = lazy(() => import('./pages/ReaderPage'));
const PostDetailPage = lazy(() => import('./pages/PostDetailPage'));
const SourcesConfig = lazy(() => import('./pages/SourcesConfig'));
const BlogPage = lazy(() => import('./pages/BlogPage'));
const SavePage = lazy(() => import('./pages/SavePage'));
// Its own chunk: the reader's initial JS must not grow for it (Design Studio D8, scripts/bundle-check.mjs).
const DesignStudio = lazy(() => import('./design/DesignStudio'));
const DesignFrame = lazy(() => import('./design/frame/FrameApp'));

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
 * the history entry. `/save` saves any page (the bookmarklet's and ⌘K's, issue 0031). `/blog` is the engineering blog. `/design/*` is the Design
 * Studio, reached from ⌘K only.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<ReaderPage />} />
      <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
      <Route path="/hub" element={<Navigate to="/" replace />} />
      <Route path="/ingestion" element={<IngestionRedirect />} />
      <Route path="/ingestion/:tab" element={<IngestionRedirect />} />
      <Route path="/posts/:postId" element={<PostDetailPage />} />
      <Route path="/settings/sources" element={<SourcesConfig />} />
      <Route path="/tracks/:trackId" element={<TrackRedirect />} />
      <Route path="/save" element={<SavePage />} />
      <Route path="/blog" element={<BlogPage />} />
      <Route path="/blog/:slug" element={<BlogPage />} />
      <Route path="/design/*" element={<DesignStudio />} />
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
  if (window.location.pathname.startsWith('/design/frame/')) {
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
