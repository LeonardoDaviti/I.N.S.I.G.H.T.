import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FolderPlus, Play, RefreshCw, Trash2, Plus, ChevronDown, ChevronRight } from 'lucide-react';
import { apiService } from '../services/api';
import type { Folder, Expert, ExpertRunResult } from '../services/api';
import MarkdownRenderer from './ui/MarkdownRenderer';

export default function FoldersExpertsPanel() {
  const navigate = useNavigate();
  const [folders, setFolders] = useState<Folder[]>([]);
  const [experts, setExperts] = useState<Expert[]>([]);
  const [loading, setLoading] = useState(true);

  const [newFolderName, setNewFolderName] = useState('');
  const [showExpertForm, setShowExpertForm] = useState(false);
  const [expertForm, setExpertForm] = useState({
    name: '',
    folder_id: '',
    system_prompt: '',
    focus_instructions: '',
    lookback_days: 7,
    schedule: '',
  });

  const [running, setRunning] = useState<Set<string>>(new Set());
  const [briefings, setBriefings] = useState<Record<string, ExpertRunResult>>({});
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    const [fRes, eRes] = await Promise.all([apiService.getFolders(), apiService.getExperts()]);
    if (fRes.success) setFolders(fRes.folders);
    if (eRes.success) {
      setExperts(eRes.experts);
      const map: Record<string, ExpertRunResult> = {};
      await Promise.all(
        eRes.experts.map(async (ex) => {
          const b = await apiService.getExpertBriefing(ex.id);
          if (b.success) map[ex.id] = b;
        }),
      );
      setBriefings(map);
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const folderName = (id: string) => folders.find((f) => f.id === id)?.name || 'unknown';

  const addFolder = async () => {
    const name = newFolderName.trim();
    if (!name) return;
    const res = await apiService.createFolder({ name });
    if (res.success) { setNewFolderName(''); await load(); }
    else setError(res.error || 'Failed to create folder');
  };

  const removeFolder = async (id: string) => {
    const res = await apiService.deleteFolder(id);
    if (res.success) await load();
    else setError(res.error || 'Failed to delete folder');
  };

  const createExpert = async () => {
    if (!expertForm.name.trim() || !expertForm.folder_id || !expertForm.system_prompt.trim()) {
      setError('Expert needs a name, a folder, and a system prompt');
      return;
    }
    const res = await apiService.createExpert(expertForm);
    if (res.success) {
      setShowExpertForm(false);
      setExpertForm({ name: '', folder_id: '', system_prompt: '', focus_instructions: '', lookback_days: 7, schedule: '' });
      await load();
    } else setError(res.error || 'Failed to create expert');
  };

  const removeExpert = async (id: string) => {
    const res = await apiService.deleteExpert(id);
    if (res.success) await load();
    else setError(res.error || 'Failed to delete expert');
  };

  const run = async (id: string, refresh: boolean) => {
    setRunning((p) => new Set(p).add(id));
    setError(null);
    const res = await apiService.runExpert(id, { refresh });
    setRunning((p) => { const n = new Set(p); n.delete(id); return n; });
    if (res.success) {
      setBriefings((p) => ({ ...p, [id]: res }));
      setOpen((p) => new Set(p).add(id));
    } else setError(res.error || 'Failed to run expert');
  };

  const toggleOpen = (id: string) =>
    setOpen((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return (
    <div className="mb-8 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900">Folders &amp; Experts</h2>
        <button
          onClick={() => setShowExpertForm((v) => !v)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700"
        >
          <Plus className="w-4 h-4" /> New Expert
        </button>
      </div>

      {error && <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-2">{error}</div>}

      {/* Folders */}
      <div className="mb-4">
        <div className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Folders</div>
        <div className="flex flex-wrap items-center gap-2">
          {folders.map((f) => (
            <span key={f.id} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-gray-100 border border-gray-200 text-sm text-gray-800">
              <button
                onClick={() => navigate(`/tracks/${f.id}`)}
                className="font-medium hover:text-blue-700 hover:underline"
                title="Open reading view"
              >
                {f.name}
              </button>
              {f.kind === 'track' && (
                <span className="px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-medium">track</span>
              )}
              <span className="text-xs text-gray-500">{f.source_count ?? 0}s · {f.post_count ?? 0}p</span>
              <button onClick={() => removeFolder(f.id)} className="text-gray-400 hover:text-red-600" aria-label="Delete folder">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </span>
          ))}
          <span className="inline-flex items-center gap-1">
            <input
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addFolder()}
              placeholder="New folder name"
              className="px-2.5 py-1 border border-gray-300 rounded-full text-sm w-40 focus:ring-2 focus:ring-blue-500"
            />
            <button onClick={addFolder} className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800">
              <FolderPlus className="w-4 h-4" /> Add
            </button>
          </span>
        </div>
        <p className="text-xs text-gray-500 mt-2">Assign sources to folders from each source's settings menu (gear icon).</p>
      </div>

      {/* New expert form */}
      {showExpertForm && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <input
              value={expertForm.name}
              onChange={(e) => setExpertForm({ ...expertForm, name: e.target.value })}
              placeholder="Expert name"
              className="px-2.5 py-1.5 border border-gray-300 rounded-md text-sm"
            />
            <select
              value={expertForm.folder_id}
              onChange={(e) => setExpertForm({ ...expertForm, folder_id: e.target.value })}
              className="px-2.5 py-1.5 border border-gray-300 rounded-md text-sm bg-white"
            >
              <option value="">Select folder…</option>
              {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          </div>
          <textarea
            value={expertForm.system_prompt}
            onChange={(e) => setExpertForm({ ...expertForm, system_prompt: e.target.value })}
            placeholder="System prompt — the expert's voice and priorities"
            rows={3}
            className="w-full px-2.5 py-1.5 border border-gray-300 rounded-md text-sm"
          />
          <textarea
            value={expertForm.focus_instructions}
            onChange={(e) => setExpertForm({ ...expertForm, focus_instructions: e.target.value })}
            placeholder="Focus instructions (optional) — what to prioritize"
            rows={2}
            className="w-full px-2.5 py-1.5 border border-gray-300 rounded-md text-sm"
          />
          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-600">Lookback days
              <input
                type="number" min={1} max={90}
                value={expertForm.lookback_days}
                onChange={(e) => setExpertForm({ ...expertForm, lookback_days: parseInt(e.target.value) || 7 })}
                className="ml-2 w-16 px-2 py-1 border border-gray-300 rounded-md text-sm"
              />
            </label>
            <label className="text-sm text-gray-600">Schedule
              <input
                value={expertForm.schedule}
                onChange={(e) => setExpertForm({ ...expertForm, schedule: e.target.value })}
                placeholder="daily (optional)"
                className="ml-2 w-28 px-2 py-1 border border-gray-300 rounded-md text-sm"
              />
            </label>
            <button onClick={createExpert} className="ml-auto px-3 py-1.5 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700">
              Create Expert
            </button>
          </div>
        </div>
      )}

      {/* Experts */}
      <div className="space-y-3">
        {loading && <div className="text-sm text-gray-400">Loading…</div>}
        {!loading && experts.length === 0 && <div className="text-sm text-gray-400">No experts yet. Create one above.</div>}
        {experts.map((ex) => {
          const b = briefings[ex.id];
          const isOpen = open.has(ex.id);
          const isRunning = running.has(ex.id);
          return (
            <div key={ex.id} className="rounded-lg border border-gray-200">
              <div className="flex items-center gap-2 p-3">
                <button onClick={() => toggleOpen(ex.id)} className="text-gray-400 hover:text-gray-600">
                  {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                </button>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-900">{ex.name}</div>
                  <div className="text-xs text-gray-500">
                    {folderName(ex.folder_id)} · {ex.lookback_days}d{ex.schedule ? ` · ${ex.schedule}` : ''}
                    {b?.cached && <span className="ml-2 text-emerald-600">cached</span>}
                  </div>
                </div>
                <button
                  onClick={() => run(ex.id, false)}
                  disabled={isRunning}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-blue-600 text-white text-xs hover:bg-blue-700 disabled:opacity-50"
                >
                  {isRunning ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />} Run
                </button>
                <button
                  onClick={() => run(ex.id, true)}
                  disabled={isRunning}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-gray-300 text-gray-700 text-xs hover:bg-gray-50 disabled:opacity-50"
                  title="Force regenerate"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
                <button onClick={() => removeExpert(ex.id)} className="text-gray-400 hover:text-red-600" aria-label="Delete expert">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>

              {isOpen && (
                <div className="border-t border-gray-100 p-3">
                  {!b && <div className="text-sm text-gray-400">No briefing yet — hit Run.</div>}
                  {b && (
                    <div>
                      <div className="text-xs text-gray-500 mb-2">
                        {b.posts_processed ?? 0} posts · {b.start_date} → {b.end_date}
                      </div>
                      <MarkdownRenderer content={b.briefing || ''} className="prose prose-sm max-w-none" />
                      {(b.topics || []).length > 0 && (
                        <div className="mt-3 space-y-1">
                          {b.topics!.map((t, i) => (
                            <div key={i} className="text-sm">
                              <span className="font-medium text-gray-900">{t.title}</span>
                              <span className="text-xs text-gray-500"> · {t.post_ids.length} posts</span>
                              <div className="text-gray-600">{t.summary}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
