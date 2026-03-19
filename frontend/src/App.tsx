import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import Index from './pages/Index';
import DailyBriefing from './pages/DailyBriefing';
import IngestionControl from './pages/IngestionControl';
import PostDetailPage from './pages/PostDetailPage';
import SourcesConfig from './pages/SourcesConfig';
import ThemeToggle from './components/ThemeToggle';
import { ThemeProvider } from './components/ThemeProvider';

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <Router>
          <div className="min-h-screen bg-background text-foreground">
            <div className="fixed right-4 top-4 z-50">
              <ThemeToggle />
            </div>
            <Routes>
              <Route path="/" element={<Index />} />
              <Route path="/briefing" element={<DailyBriefing />} />
              <Route path="/ingestion" element={<IngestionControl />} />
              <Route path="/briefing/topics" element={<DailyBriefing />} />
              <Route path="/posts/:postId" element={<PostDetailPage />} />
              <Route path="/settings/sources" element={<SourcesConfig />} />
            </Routes>
            <Toaster />
          </div>
        </Router>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
