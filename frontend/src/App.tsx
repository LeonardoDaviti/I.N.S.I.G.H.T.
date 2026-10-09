import { Suspense, lazy, type ReactNode } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import ThemeToggle from './components/ThemeToggle';
import { ThemeProvider } from './components/ThemeProvider';
import AppErrorBoundary from './components/AppErrorBoundary';
import { ApiProvider } from './services/ApiContext';

const queryClient = new QueryClient();
const Index = lazy(() => import('./pages/Index'));
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

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider>
        <ThemeProvider>
          <Router>
            <div className="min-h-screen bg-background text-foreground">
              <div className="fixed bottom-4 right-4 z-50">
                <ThemeToggle />
              </div>
              <RouteErrorBoundary>
                <Suspense fallback={<div className="min-h-screen bg-background" />}>
                  <Routes>
                    <Route path="/" element={<Index />} />
                    <Route path="/briefing" element={<DailyBriefing />} />
                    <Route path="/briefing/vertical" element={<VerticalBriefingPage />} />
                    <Route path="/briefing/vertical/source/:sourceId" element={<VerticalBriefingPage />} />
                    <Route path="/ingestion" element={<IngestionControl />} />
                    <Route path="/ingestion/:tab" element={<IngestionControl />} />
                    <Route path="/briefing/topics" element={<DailyBriefing />} />
                    <Route path="/stories" element={<StoriesExplorerPage />} />
                    <Route path="/inbox" element={<AnalystInboxPage />} />
                    <Route path="/posts/:postId" element={<PostDetailPage />} />
                    <Route path="/settings/sources" element={<SourcesConfig />} />
                    <Route path="/experts" element={<ExpertsPage />} />
                    <Route path="/tracks/:trackId" element={<TrackPage />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </Suspense>
              </RouteErrorBoundary>
              <Toaster />
            </div>
          </Router>
        </ThemeProvider>
      </ApiProvider>
    </QueryClientProvider>
  );
}

export default App;
