import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, Plus, Settings, Trash2, FolderPlus, Sparkles, Rss, Send, MessageSquare, Youtube } from 'lucide-react';
import { apiService } from '../services/api';
import type { SourceWithSettings, Folder, Expert } from '../services/api';
import AddSourceModal from '../components/AddSourceModal';
import SourceSettingsEditor from '../components/SourceSettingsEditor';

interface SourcesConfigProps {
  embedded?: boolean;
  onClose?: () => void;
}

const platformIcon: Record<string, ReactNode> = {
  rss: <Rss className="w-3.5 h-3.5" />,
  telegram: <Send className="w-3.5 h-3.5" />,
  reddit: <MessageSquare className="w-3.5 h-3.5" />,
  youtube: <Youtube className="w-3.5 h-3.5" />,
};

function SourceRow({
  source,
  onToggle,
  onSettings,
  onRemove,
}: {
  source: SourceWithSettings;
  onToggle: () => void;
  onSettings: () => void;
  onRemove: () => void;
}) {
  const name = source.settings?.display_name || source.handle_or_url;
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 bg-white">
      <button
        onClick={onToggle}
        title={source.enabled ? 'Enabled — click to disable' : 'Disabled — click to enable'}
        className={`shrink-0 w-9 h-5 rounded-full transition-colors relative ${source.enabled ? 'bg-green-500' : 'bg-gray-300'}`}
      >
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${source.enabled ? 'left-4' : 'left-0.5'}`} />
      </button>
      <span className="shrink-0 text-gray-400" title={source.platform}>
        {platformIcon[source.platform] || <Rss className="w-3.5 h-3.5" />}
      </span>
      <span className="flex-1 min-w-0 truncate text-sm text-gray-800" title={source.handle_or_url}>{name}</span>
      <button onClick={onSettings} className="shrink-0 text-gray-400 hover:text-gray-700" aria-label="Settings">
        <Settings className="w-4 h-4" />
      </button>
      <button onClick={onRemove} className="shrink-0 text-gray-400 hover:text-red-600" aria-label="Delete source">
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  );
}

export default function SourcesConfig({ embedded = false, onClose }: SourcesConfigProps) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [sources, setSources] = useState<SourceWithSettings[]>([]);
  const [experts, setExperts] = useState<Expert[]>([]);
  const [sourceFolderMap, setSourceFolderMap] = useState<Record<string, string[]>>({});
  const [newFolderName, setNewFolderName] = useState('');
  const [showAddSource, setShowAddSource] = useState(false);
  const [editingSource, setEditingSource] = useState<SourceWithSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [fRes, sRes, eRes] = await Promise.all([
      apiService.getFolders(),
      apiService.getSourcesWithSettings(),
      apiService.getExperts(),
    ]);
    const sl = sRes.success ? sRes.sources : [];
    const memberships = await Promise.all(
      sl.map((s) => apiService.getSourceFolders(s.id).then((r) => [s.id, r.success ? r.folder_ids : []] as const)),
    );
    const map: Record<string, string[]> = {};
    memberships.forEach(([id, fids]) => { map[id] = fids; });
    setFolders(fRes.success ? fRes.folders : []);
    setSources(sl);
    setExperts(eRes.success ? eRes.experts : []);
    setSourceFolderMap(map);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const sourcesInFolder = (fid: string) => sources.filter((s) => (sourceFolderMap[s.id] || []).includes(fid));
  const unassigned = sources.filter((s) => (sourceFolderMap[s.id] || []).length === 0);
  const expertsForFolder = (fid: string) => experts.filter((e) => e.folder_id === fid);

  const addFolder = async () => {
    const name = newFolderName.trim();
    if (!name) return;
    const r = await apiService.createFolder({ name });
    if (r.success) { setNewFolderName(''); load(); } else setError(r.error || 'Failed to create folder');
  };
  const removeFolder = async (id: string) => {
    const r = await apiService.deleteFolder(id);
    if (r.success) load(); else setError(r.error || 'Failed to delete folder');
  };
  const toggleEnabled = async (s: SourceWithSettings) => {
    setSources((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled: !s.enabled } : x)));
    const r = await apiService.setSourceEnabled(s.id, !s.enabled);
    if (!r.success) { setSources((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled: s.enabled } : x))); setError(r.error || 'Failed'); }
  };
  const removeSource = async (id: string) => {
    const r = await apiService.deleteSource(id);
    if (r.success) load(); else setError(r.error || 'Failed to delete source');
  };
  const handleAddSource = async (data: { handle_or_url: string; display_name: string; fetch_delay_seconds: number; priority: number; max_posts_per_fetch: number; state: string }) => {
    const r = await apiService.addSource({ platform: 'rss', ...data });
    setShowAddSource(false);
    if (r.success) load(); else setError(r.error || 'Failed to add source');
  };

  const renderSource = (s: SourceWithSettings) => (
    <SourceRow
      key={s.id}
      source={s}
      onToggle={() => toggleEnabled(s)}
      onSettings={() => setEditingSource(s)}
      onRemove={() => removeSource(s.id)}
    />
  );

  return (
    <div className={embedded ? 'app-shell' : 'app-shell min-h-screen'}>
      <div className={embedded ? 'max-w-4xl mx-auto p-6' : 'max-w-4xl mx-auto p-8'}>
        {!embedded && (
          <button onClick={() => navigate('/briefing')} className="mb-3 inline-flex items-center text-sm text-gray-600 hover:text-gray-900">
            <ChevronLeft className="w-4 h-4 mr-1" /> Back to Briefing
          </button>
        )}

        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Sources</h1>
          <div className="flex items-center gap-2">
            <button onClick={() => navigate('/experts')} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 text-sm">
              <Sparkles className="w-4 h-4" /> Experts
            </button>
            <button onClick={() => navigate('/ingestion')} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 text-sm">
              <Settings className="w-4 h-4" /> Ingestion
            </button>
            <button onClick={() => setShowAddSource(true)} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 text-sm">
              <Plus className="w-4 h-4" /> Add Source
            </button>
          </div>
        </div>

        {error && <div className="mb-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-2">{error}</div>}

        {/* Create folder */}
        <div className="mb-5 flex items-center gap-2">
          <input
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addFolder()}
            placeholder="New folder name"
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm w-56 focus:ring-2 focus:ring-blue-500"
          />
          <button onClick={addFolder} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-300 text-blue-600 hover:bg-blue-50 text-sm">
            <FolderPlus className="w-4 h-4" /> Create Folder
          </button>
        </div>

        {loading && <div className="text-sm text-gray-400">Loading…</div>}

        {/* Folders */}
        <div className="space-y-4">
          {folders.map((f) => {
            const fSources = sourcesInFolder(f.id);
            const fExperts = expertsForFolder(f.id);
            return (
              <div key={f.id} className="rounded-xl border border-gray-200 bg-white shadow-sm">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
                  <h2 className="text-base font-semibold text-gray-900">{f.name}</h2>
                  <span className="text-xs text-gray-400">{fSources.length} source{fSources.length === 1 ? '' : 's'}</span>
                  {fExperts.length > 0 && (
                    <button
                      onClick={() => navigate('/experts')}
                      className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
                      title="Open in Experts"
                    >
                      <Sparkles className="w-3.5 h-3.5" /> {fExperts.map((e) => e.name).join(', ')}
                    </button>
                  )}
                  <button onClick={() => removeFolder(f.id)} className="ml-auto text-gray-300 hover:text-red-600" aria-label="Delete folder">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
                <div className="p-3 space-y-2">
                  {fSources.length === 0 ? (
                    <div className="text-xs text-gray-400 px-1">No sources yet. Use a source's gear menu to add it here.</div>
                  ) : (
                    fSources.map(renderSource)
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Unassigned */}
        <div className="mt-6">
          <div className="flex items-center gap-2 mb-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500">Unassigned</h2>
            <span className="text-xs text-gray-400">{unassigned.length}</span>
          </div>
          <div className="space-y-2">
            {unassigned.length === 0 ? (
              <div className="text-xs text-gray-400">Every source is in a folder.</div>
            ) : (
              unassigned.map(renderSource)
            )}
          </div>
        </div>

        {embedded && onClose && (
          <div className="mt-6">
            <button onClick={onClose} className="text-sm text-gray-600 hover:text-gray-900">Close</button>
          </div>
        )}
      </div>

      {showAddSource && (
        <AddSourceModal
          platform="rss"
          onClose={() => setShowAddSource(false)}
          onAdd={handleAddSource}
        />
      )}

      {editingSource && (
        <SourceSettingsEditor
          source={editingSource}
          onClose={() => setEditingSource(null)}
          onSave={() => { setEditingSource(null); load(); }}
        />
      )}
    </div>
  );
}
