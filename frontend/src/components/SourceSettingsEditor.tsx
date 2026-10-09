import { useState, useRef, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { X, Save, AlertCircle } from 'lucide-react';
import { apiService } from '../services/api';
import type { SourceWithSettings, Folder } from '../services/api';
import { useApi } from '../services/ApiContext';
import { SOURCES_HEALTH_KEY, useSourcesHealth } from '../hooks/useSourcesHealth';
import { errorMessage } from '../lib/apiError';
import CadenceOverrideEditor from './ops/CadenceOverrideEditor';

interface SourceSettingsEditorProps {
  source: SourceWithSettings;
  onClose: () => void;
  onSave: () => void;
}

/** Whole numbers in [min, max]; anything else is a field error (no silent `|| 0`). */
function parseWhole(text: string, min: number, max: number, label: string): { value: number } | { error: string } {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return { error: `${label} must be a whole number between ${min} and ${max}.` };
  const value = Number(trimmed);
  if (value < min || value > max) return { error: `${label} must be between ${min} and ${max}.` };
  return { value };
}

export default function SourceSettingsEditor({ source, onClose, onSave }: SourceSettingsEditorProps) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState(source.settings.display_name || '');
  const [fetchDelayText, setFetchDelayText] = useState(String(source.settings.fetch_delay_seconds ?? 1));
  const [priorityText, setPriorityText] = useState(String(source.settings.priority ?? 999));
  const maxPostsPerFetch = source.settings.max_posts_per_fetch ?? 50;
  const fetchDelay = parseWhole(fetchDelayText, 0, 60, 'Fetch delay');
  const priority = parseWhole(priorityText, 1, 9999, 'Priority');
  const formValid = 'value' in fetchDelay && 'value' in priority;

  // Cadence and the main-digest flag come from the health row (one cached query for all sources).
  const health = useSourcesHealth();
  const healthRow = health.data?.rows.find((row) => row.source_id === source.id) ?? null;
  const [inMainDigest, setInMainDigest] = useState<boolean | null>(null);
  const mainDigest = inMainDigest ?? healthRow?.in_main_digest ?? null;
  const [savingDigest, setSavingDigest] = useState(false);

  const toggleMainDigest = async () => {
    if (mainDigest === null) return;
    const next = !mainDigest;
    setInMainDigest(next);
    setSavingDigest(true);
    try {
      await api.setSourceMainDigest(source.id, next);
      void queryClient.invalidateQueries({ queryKey: [...SOURCES_HEALTH_KEY] });
      void queryClient.invalidateQueries({ queryKey: ['unread-counts'] });
    } catch (err) {
      setInMainDigest(!next);
      setError(errorMessage(err));
    } finally {
      setSavingDigest(false);
    }
  };

  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  const [folders, setFolders] = useState<Folder[]>([]);
  const [memberFolderIds, setMemberFolderIds] = useState<Set<string>>(new Set());
  const [foldersLoading, setFoldersLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      const [allRes, mineRes] = await Promise.all([
        apiService.getFolders(),
        apiService.getSourceFolders(source.id),
      ]);
      if (!mounted) return;
      if (allRes.success) setFolders(allRes.folders);
      if (mineRes.success) setMemberFolderIds(new Set(mineRes.folder_ids));
      setFoldersLoading(false);
    })();
    return () => { mounted = false; };
  }, [source.id]);

  const toggleFolder = async (folderId: string) => {
    const isMember = memberFolderIds.has(folderId);
    setMemberFolderIds((prev) => {
      const next = new Set(prev);
      if (isMember) next.delete(folderId); else next.add(folderId);
      return next;
    });
    const res = isMember
      ? await apiService.removeSourceFromFolder(folderId, source.id)
      : await apiService.addSourceToFolder(folderId, source.id);
    if (!res.success) {
      setMemberFolderIds((prev) => {
        const next = new Set(prev);
        if (isMember) next.add(folderId); else next.delete(folderId);
        return next;
      });
      setError(res.error || 'Failed to update folders');
    }
  };

  // Handle click outside to close
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(event.target as Node)) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose]);

  const handleSave = async () => {
    if (!('value' in fetchDelay) || !('value' in priority)) return;
    setIsSaving(true);
    setError(null);

    try {
      // Only send non-empty display_name, otherwise send null to use default
      const settingsToSave = {
        display_name: displayName.trim() || undefined,
        fetch_delay_seconds: fetchDelay.value,
        priority: priority.value,
        max_posts_per_fetch: maxPostsPerFetch,
      };

      const response = await apiService.updateSourceSettings(source.id, settingsToSave);

      if (response.success) {
        onSave();
        onClose();
      } else {
        setError(response.error || 'Failed to save settings');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error occurred');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div ref={modalRef} className="bg-white rounded-lg shadow-xl max-w-md w-full">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Source Settings</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Source Info */}
          <div className="bg-gray-50 p-3 rounded-md border border-gray-200">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Source</div>
            <div className="text-sm font-medium text-gray-900">{source.handle_or_url}</div>
            <div className="text-xs text-gray-500 mt-1">{source.platform.toUpperCase()}</div>
          </div>

          {/* Folders */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Folders</label>
            {foldersLoading ? (
              <div className="text-xs text-gray-400">Loading folders…</div>
            ) : folders.length === 0 ? (
              <div className="text-xs text-gray-400">No folders yet. Create one on the Sources page.</div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {folders.map((f) => {
                  const active = memberFolderIds.has(f.id);
                  return (
                    <button
                      key={f.id}
                      type="button"
                      onClick={() => toggleFolder(f.id)}
                      className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                        active
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400'
                      }`}
                    >
                      {active ? '✓ ' : '+ '}{f.name}
                    </button>
                  );
                })}
              </div>
            )}
            <p className="text-xs text-gray-500 mt-1">Click a folder to add/remove this source. Saves instantly.</p>
          </div>

          {/* Main feed */}
          <div className="flex items-start justify-between gap-3">
            <div>
              <div id="main_digest_label" className="text-sm font-medium text-gray-700">In the main feed and digest</div>
              <p className="text-xs text-gray-500 mt-0.5">
                Off keeps it fetched and readable through its tracks, but out of Home and the daily briefing. Saves instantly.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={mainDigest ?? false}
              aria-labelledby="main_digest_label"
              disabled={mainDigest === null || savingDigest}
              onClick={() => void toggleMainDigest()}
              className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors duration-150 disabled:opacity-50 ${mainDigest ? 'bg-[var(--interactive-accent)]' : 'bg-[var(--background-modifier-border)]'}`}
            >
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-150 ease-out motion-reduce:transition-none ${mainDigest ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
          </div>

          {/* Cadence */}
          <div className="rounded-md border border-gray-200 p-3">
            {healthRow ? (
              <CadenceOverrideEditor row={healthRow} />
            ) : (
              <p className="text-xs text-gray-500">
                {health.isError ? `Cadence unavailable: ${errorMessage(health.error)}` : 'Loading cadence…'}
              </p>
            )}
          </div>

          {/* Display Name */}
          <div>
            <label htmlFor="display_name" className="block text-sm font-medium text-gray-700 mb-1">
              Display Name
            </label>
            <input
              id="display_name"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={source.handle_or_url}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
            />
            <p className="text-xs text-gray-500 mt-1">
              Leave empty to use the default URL/handle
            </p>
          </div>

          {/* Fetch Delay */}
          <div>
            <label htmlFor="fetch_delay" className="block text-sm font-medium text-gray-700 mb-1">
              Fetch Delay (seconds)
            </label>
            <input
              id="fetch_delay"
              type="text"
              inputMode="numeric"
              value={fetchDelayText}
              onChange={(e) => setFetchDelayText(e.target.value)}
              aria-invalid={'error' in fetchDelay}
              aria-describedby="fetch_delay_help"
              className={`w-full px-3 py-2 border rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm tabular-nums ${'error' in fetchDelay ? 'border-[var(--text-error)]' : 'border-gray-300'}`}
            />
            <p id="fetch_delay_help" className={`text-xs mt-1 ${'error' in fetchDelay ? 'text-[var(--text-error)]' : 'text-gray-500'}`}>
              {'error' in fetchDelay ? fetchDelay.error : 'Time to wait after fetching from this source (0 to 60 seconds)'}
            </p>
          </div>

          {/* Priority */}
          <div>
            <label htmlFor="priority" className="block text-sm font-medium text-gray-700 mb-1">
              Priority
            </label>
            <input
              id="priority"
              type="text"
              inputMode="numeric"
              value={priorityText}
              onChange={(e) => setPriorityText(e.target.value)}
              aria-invalid={'error' in priority}
              aria-describedby="priority_help"
              className={`w-full px-3 py-2 border rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm tabular-nums ${'error' in priority ? 'border-[var(--text-error)]' : 'border-gray-300'}`}
            />
            <p id="priority_help" className={`text-xs mt-1 ${'error' in priority ? 'text-[var(--text-error)]' : 'text-gray-500'}`}>
              {'error' in priority ? priority.error : 'Lower number = higher priority (fetched first), 1 to 9999'}
            </p>
          </div>

          {/* Max Posts Per Fetch */}
          <div>
            <label htmlFor="max_posts" className="block text-sm font-medium text-gray-700 mb-1">
              Max Posts Per Fetch
            </label>
            <input
              id="max_posts"
              type="number"
              min="1"
              max="200"
              value={maxPostsPerFetch}
              readOnly
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
              disabled
            />
            <p className="text-xs text-gray-500 mt-1">
              ⚠️ Not enforced (future feature)
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-md">
              <AlertCircle className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 p-4 border-t border-gray-200 bg-gray-50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || !formValid}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isSaving ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                Save Settings
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

