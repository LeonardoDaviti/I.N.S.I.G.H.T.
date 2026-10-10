import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiService } from '../services/api';
import type { SourceWithSettings, Folder } from '../services/api';
import { useApi } from '../services/ApiContext';
import { SOURCES_HEALTH_KEY, useSourcesHealth } from '../hooks/useSourcesHealth';
import { errorMessage } from '../lib/apiError';
import CadenceOverrideEditor from './ops/CadenceOverrideEditor';
import { Button, FilterChip, Input, Sheet, SheetContent, Switch } from './ui';
import { Notice } from './states';
import { sourceLabel } from '../lib/sourceLabel';
import { UNREAD_COUNTS_KEY } from '../hooks/useFeed';
import { getPlatformLabel } from '../lib/sourcePresentation';

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
      void queryClient.invalidateQueries({ queryKey: [...UNREAD_COUNTS_KEY] });
    } catch (err) {
      setInMainDigest(!next);
      setError(errorMessage(err));
    } finally {
      setSavingDigest(false);
    }
  };

  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const label = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';
  const hint = (bad: boolean) => `mt-1 text-[0.75rem] ${bad ? 'font-semibold text-fg' : 'text-fg-3'}`;
  const name = sourceLabel(source.settings.display_name, source.handle_or_url);

  return (
    <Sheet open onOpenChange={(open) => { if (!open && !isSaving) onClose(); }}>
      <SheetContent
        title={name}
        description={(
          <span className="block min-w-0 [overflow-wrap:anywhere]">
            {getPlatformLabel(source.platform)} · {source.handle_or_url}
          </span>
        )}
        className="w-[min(32rem,100vw)]"
      >
        {/* A div, not a form: the cadence editor below is its own form and forms cannot nest. */}
        <div className="space-y-6">
          <div>
            <label htmlFor="display_name" className={label}>Name</label>
            <Input
              id="display_name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={sourceLabel(source.handle_or_url)}
            />
            <p className={hint(false)}>Leave empty to derive it from the URL.</p>
          </div>

          <fieldset>
            <legend className={label}>Tracks</legend>
            {foldersLoading ? (
              <p className="text-[0.75rem] text-fg-3">Loading tracks…</p>
            ) : folders.length === 0 ? (
              <p className="text-[0.75rem] text-fg-3">No tracks yet. Create one on the Sources page.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {folders.map((f) => (
                  <FilterChip key={f.id} selected={memberFolderIds.has(f.id)} onClick={() => toggleFolder(f.id)}>
                    {f.name}
                  </FilterChip>
                ))}
              </div>
            )}
            <p className={hint(false)}>Select a track to add this source to it. Saves instantly.</p>
          </fieldset>

          <div className="flex items-start justify-between gap-4">
            <div>
              <div id="main_digest_label" className="text-[0.8125rem] font-medium text-fg">In the main feed and digest</div>
              <p className="mt-0.5 text-[0.75rem] text-fg-3">
                Off keeps it fetched and readable through its tracks, but out of the feed and the daily briefing. Saves instantly.
              </p>
            </div>
            <Switch
              checked={mainDigest ?? false}
              aria-labelledby="main_digest_label"
              disabled={mainDigest === null || savingDigest}
              onCheckedChange={() => void toggleMainDigest()}
              className="mt-0.5"
            />
          </div>

          <div className="rounded-md border border-line p-3">
            {healthRow ? (
              <CadenceOverrideEditor row={healthRow} />
            ) : (
              <p className="text-[0.75rem] text-fg-3">
                {health.isError ? `Cadence unavailable: ${errorMessage(health.error)}` : 'Loading cadence…'}
              </p>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="fetch_delay" className={label}>Fetch delay (seconds)</label>
              <Input
                id="fetch_delay"
                inputMode="numeric"
                value={fetchDelayText}
                onChange={(e) => setFetchDelayText(e.target.value)}
                aria-invalid={'error' in fetchDelay}
                aria-describedby="fetch_delay_help"
                className="tabular-nums"
              />
              <p id="fetch_delay_help" className={hint('error' in fetchDelay)}>
                {'error' in fetchDelay ? `× ${fetchDelay.error}` : '0 to 60 seconds after each fetch.'}
              </p>
            </div>
            <div>
              <label htmlFor="priority" className={label}>Priority</label>
              <Input
                id="priority"
                inputMode="numeric"
                value={priorityText}
                onChange={(e) => setPriorityText(e.target.value)}
                aria-invalid={'error' in priority}
                aria-describedby="priority_help"
                className="tabular-nums"
              />
              <p id="priority_help" className={hint('error' in priority)}>
                {'error' in priority ? `× ${priority.error}` : '1 to 9999; lower is fetched first.'}
              </p>
            </div>
            <div>
              <label htmlFor="max_posts" className={label}>Max posts per fetch</label>
              <Input id="max_posts" type="number" value={maxPostsPerFetch} readOnly disabled className="tabular-nums" />
              <p className={hint(false)}>Not enforced yet.</p>
            </div>
          </div>

          {error ? <Notice tone="error" title={error} /> : null}

          <div className="sticky bottom-0 -mx-5 -mb-4 flex justify-end gap-2 border-t border-line bg-bg px-5 py-3">
            <Button variant="ghost" onClick={onClose} disabled={isSaving}>Cancel</Button>
            <Button variant="primary" onClick={() => void handleSave()} disabled={isSaving || !formValid}>
              {isSaving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
