import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import Index from './pages/Index';
import DailyBriefing from './pages/DailyBriefing';
import IngestionControl from './pages/IngestionControl';
import SourcesConfig from './pages/SourcesConfig';
import TopicsBriefing from './pages/TopicsBriefing';

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <div className="min-h-screen bg-background text-foreground">
          <Routes>
            <Route path="/" element={<Index />} />
            <Route path="/briefing" element={<DailyBriefing />} />
            <Route path="/ingestion" element={<IngestionControl />} />
            <Route path="/briefing/topics" element={<TopicsBriefing />} />
            <Route path="/settings/sources" element={<SourcesConfig />} />
          </Routes>
          <Toaster />
        </div>
      </Router>
    </QueryClientProvider>
  );
}

export default App;
