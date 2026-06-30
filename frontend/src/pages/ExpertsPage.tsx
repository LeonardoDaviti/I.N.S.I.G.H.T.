import { useNavigate } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';
import FoldersExpertsPanel from '../components/FoldersExpertsPanel';

export default function ExpertsPage() {
  const navigate = useNavigate();
  return (
    <div className="app-shell min-h-screen">
      <div className="max-w-4xl mx-auto p-8">
        <button
          onClick={() => navigate('/settings/sources')}
          className="mb-3 inline-flex items-center text-sm text-gray-600 hover:text-gray-900"
        >
          <ChevronLeft className="w-4 h-4 mr-1" /> Back to Sources
        </button>
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Experts</h1>
        <FoldersExpertsPanel />
      </div>
    </div>
  );
}
