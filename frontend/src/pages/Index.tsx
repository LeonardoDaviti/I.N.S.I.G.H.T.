import { Link } from 'react-router-dom';

export default function Index() {
  return (
    <div className="flex h-screen bg-background">
      {/* Navigation Panel */}
      <div className="w-80 bg-card border-r border-border p-6">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-foreground">INSIGHT</h1>
          <p className="text-sm text-muted-foreground">Intelligence Platform</p>
        </div>
        
        <div className="space-y-4">
          <div className="bg-primary/10 p-3 rounded-lg">
            <p className="text-sm text-muted-foreground">Welcome to INSIGHT Mark I</p>
          </div>
          
          <Link 
            to="/briefing" 
            className="block w-full p-3 bg-primary text-primary-foreground rounded-lg text-center hover:bg-primary/90 transition-colors"
          >
            Access Daily Briefing
          </Link>

          <Link 
            to="/settings/sources" 
            className="block w-full p-3 bg-card text-foreground border border-border rounded-lg text-center hover:bg-accent transition-colors"
          >
            Configure Sources
          </Link>

          <Link
            to="/ingestion"
            className="block w-full p-3 bg-card text-foreground border border-border rounded-lg text-center hover:bg-accent transition-colors"
          >
            Ingestion Control
          </Link>
        </div>
      </div>
      
      {/* Main Content */}
      <div className="flex-1 p-8">
        <div className="max-w-2xl mx-auto">
          <h2 className="text-3xl font-bold mb-4">Intelligence Gathering Platform</h2>
          <p className="text-muted-foreground mb-6">
            INSIGHT Mark I provides AI-powered intelligence briefings from multiple sources.
          </p>
          
          <div className="bg-card p-6 rounded-lg border border-border">
            <h3 className="text-xl font-semibold mb-3">Getting Started</h3>
            <ul className="space-y-2 text-muted-foreground">
              <li>• Configure your intelligence sources</li>
              <li>• Select date for briefing generation</li>
              <li>• Generate AI-powered briefings</li>
            </ul>
          </div>
          
          <div className="mt-8 p-4 bg-blue-50 dark:bg-blue-950 rounded-lg">
            <p className="text-sm text-blue-600 dark:text-blue-400">
              ✅ Backend API is ready and tested
            </p>
          </div>
        </div>
      </div>
    </div>
  );
} 
