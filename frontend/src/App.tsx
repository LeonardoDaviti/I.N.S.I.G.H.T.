import { Suspense, lazy, type ReactNode } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './components/ThemeProvider';
import AppErrorBoundary from './components/AppErrorBoundary';
import AppShell from './components/layout/AppShell';
import { LoadingState } from './components/states';
import { ApiProvider } from './services/ApiContext';

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
const TrackPage = lazy(() => import('./pages/TrackPage'));

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
 * Routes (design doc §9). `/` is the reader feed: the Mark VIII hub is gone and
 * `/hub` redirects home. Every route renders inside the AppShell top bar.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<ReaderPage />} />
      <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
      <Route path="/hub" element={<Navigate to="/" replace />} />
      <Route path="/briefing" element={<DailyBriefing />} />
      <Route path="/briefing/vertical" element={<VerticalBriefingPage />} />
      <Route path="/briefing/vertical/source/:sourceId" element={<VerticalBriefingPage />} />
      <Route path="/briefing/topics" element={<DailyBriefing />} />
      <Route path="/ingestion" element={<IngestionControl />} />
      <Route path="/ingestion/:tab" element={<IngestionControl />} />
      <Route path="/stories" element={<StoriesExplorerPage />} />
      <Route path="/inbox" element={<AnalystInboxPage />} />
      <Route path="/posts/:postId" element={<PostDetailPage />} />
      <Route path="/settings/sources" element={<SourcesConfig />} />
      <Route path="/tracks" element={<ExpertsPage />} />
      <Route path="/experts" element={<ExpertsPage />} />
      <Route path="/tracks/:trackId" element={<TrackPage />} />
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
