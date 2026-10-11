import { Suspense, lazy, type ReactNode } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './components/ThemeProvider';
import AppErrorBoundary from './components/AppErrorBoundary';
import AppShell from './components/layout/AppShell';
import { LoadingState } from './components/states';
import { ApiProvider } from './services/ApiContext';
import { useAnalysis } from './hooks/useAnalysis';
import { sourcesIngestionHref } from './lib/ingestionNavigation';

const queryClient = new QueryClient();
const ReaderPage = lazy(() => import('./pages/ReaderPage'));
const DailyBriefing = lazy(() => import('./pages/DailyBriefing'));
const StoriesExplorerPage = lazy(() => import('./pages/StoriesExplorerPage'));
const VerticalBriefingPage = lazy(() => import('./pages/VerticalBriefingPage'));
const AnalystInboxPage = lazy(() => import('./pages/AnalystInboxPage'));
const IngestionControl = lazy(() => import('./pages/IngestionControl'));
const PostDetailPage = lazy(() => import('./pages/PostDetailPage'));
const SourcesConfig = lazy(() => import('./pages/SourcesConfig'));
const ExpertsPage = lazy(() => import('./pages/ExpertsPage'));
// Its own chunk: the reader's initial JS must not grow for it (Design Studio D8, scripts/bundle-check.mjs).
const DesignStudio = lazy(() => import('./design/DesignStudio'));

/** The error boundary resets when the route changes, so leaving a broken page recovers. */
function RouteErrorBoundary({ children }: { children: ReactNode }) {
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
 * An analysis surface (briefings, stories, inbox, experts, the tracks list):
 * rendered with analysis on, sent to the feed without it (reading-finish R3,
 * Decision 2), replacing the history entry so Back doesn't bounce. It waits for
 * GET /api/config first, so a deep link isn't redirected before the runtime
 * value (which wins over the build flag) is known.
 */
function AnalysisOnly({ children }: { children: ReactNode }) {
  const { enabled, settled } = useAnalysis();
  if (!settled) return <RouteFallback />;
  return enabled ? children : <Navigate to="/" replace />;
}

/**
 * The old ingestion page: itself with analysis on; reading-only it moved to the
 * ingestion tab under sources (reading-finish R3), carrying the tab and query.
 */
function IngestionRoute() {
  const { enabled, settled } = useAnalysis();
  const { tab } = useParams();
  const location = useLocation();
  if (!settled) return <RouteFallback />;
  return enabled ? <IngestionControl /> : <Navigate to={sourcesIngestionHref(tab, location.search)} replace />;
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
 * Reading-only, the app is feed / sources / post. `/tracks/:id` redirects to
 * the reader scoped to the track (Design Studio D5). `/design/*` is the Design
 * Studio, reached from ⌘K only, with analysis on or off.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<ReaderPage />} />
      <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
      <Route path="/hub" element={<Navigate to="/" replace />} />
      <Route path="/briefing" element={<AnalysisOnly><DailyBriefing /></AnalysisOnly>} />
      <Route path="/briefing/vertical" element={<AnalysisOnly><VerticalBriefingPage /></AnalysisOnly>} />
      <Route path="/briefing/vertical/source/:sourceId" element={<AnalysisOnly><VerticalBriefingPage /></AnalysisOnly>} />
      <Route path="/briefing/topics" element={<AnalysisOnly><DailyBriefing /></AnalysisOnly>} />
      <Route path="/ingestion" element={<IngestionRoute />} />
      <Route path="/ingestion/:tab" element={<IngestionRoute />} />
      <Route path="/stories" element={<AnalysisOnly><StoriesExplorerPage /></AnalysisOnly>} />
      <Route path="/inbox" element={<AnalysisOnly><AnalystInboxPage /></AnalysisOnly>} />
      <Route path="/posts/:postId" element={<PostDetailPage />} />
      <Route path="/settings/sources" element={<SourcesConfig />} />
      <Route path="/tracks" element={<AnalysisOnly><ExpertsPage /></AnalysisOnly>} />
      <Route path="/experts" element={<AnalysisOnly><ExpertsPage /></AnalysisOnly>} />
      <Route path="/tracks/:trackId" element={<TrackRedirect />} />
      <Route path="/design/*" element={<DesignStudio />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
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
