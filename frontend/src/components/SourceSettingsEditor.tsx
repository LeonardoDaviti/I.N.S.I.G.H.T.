import { useState, useEffect, useRef } from 'react';
import { Check, Copy } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import type { SourceHealthRow, SourceWithSettings, Folder } from '../services/api';
import { useApi } from '../services/ApiContext';
import { SOURCES_HEALTH_KEY, useSourcesHealth } from '../hooks/useSourcesHealth';
import { errorMessage } from '../lib/apiError';
import CadenceOverrideEditor from './ops/CadenceOverrideEditor';
import { useIngestionRun } from '../hooks/useIngestionRun';
import { HEALTH_STATUS_LABELS, backoffLabel, formatDue } from '../lib/sourceSchedule';
import { formatRelativeTime } from '../lib/dates';
import { formatCount, plural } from '../lib/format';
import { STATUS_GLYPH } from './sources/sourceList';
import { Button, FilterChip, Input, Sheet, SheetContent, StatusGlyph, Switch } from './ui';
import { Notice } from './states';
import { getPlatformLabel, sourceLabel } from '../lib/sourceLabel';
import { UNREAD_COUNTS_KEY } from '../hooks/useFeed';
import { ConnectionsLink } from './connections';
import { writeToClipboard } from '../lib/clipboard';
import ArchiveSection from './sources/ArchiveSection';

/** The source's address, whole (it wraps, never truncates) with a copy button. */
function SourceAddress({ value }: { value: string }) {
  const [copied, setCopied] = useState<'yes' | 'failed' | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await writeToClipboard(value);
      setCopied('yes');
    } catch {
      setCopied('failed');
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(null), 1600);
  };
  return (
    <div className="flex min-w-0 items-start gap-2">
      <p className="min-w-0 flex-1 pt-1.5 text-[0.8125rem] text-fg-2 [overflow-wrap:anywhere]" dir="ltr">{value}</p>
      <Button variant="ghost" size="icon" onClick={() => void copy()} aria-label="Copy URL" title="Copy URL" className="shrink-0">
        {copied === 'yes' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      </Button>
      <span role="status" className="sr-only">
        {copied === 'yes' ? 'URL copied' : copied === 'failed' ? 'Could not copy the URL' : ''}
      </span>
    </div>
  );
}

interface SourceSettingsEditorProps {
  source: SourceWithSettings;
  onClose: () => void;
  onSave: () => void;
  /** The row to show (the page passes it so fixtures and the list agree); else the cached health query. */
  healthRow?: SourceHealthRow | null;
  /** On/off and delete live in the sheet when the page provides them. */
  onToggleEnabled?: (enabled: boolean) => void;
  onDelete?: () => void;
}

/** Whole numbers in [min, max]; anything else is a field error (no silent `|| 0`). */
function parseWhole(text: string, min: number, max: number, label: string): { value: number } | { error: string } {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return { error: `${label} must be a whole number between ${min} and ${max}.` };
  const value = Number(trimmed);
  if (value < min || value > max) return { error: `${label} must be between ${min} and ${max}.` };
  return { value };
}

/** The source's state in words: status, what happens next, the last success and error. */
function HealthSummary({ row, now }: { row: SourceHealthRow; now: Date }) {
  const status = row.enabled ? row.status : 'disabled';
  const backoff = backoffLabel(row, now);
  const facts = [
    row.enabled && !backoff && row.next_due_at ? `next ${formatDue(row.next_due_at, now)}` : null,
    backoff ? `${backoff} · ${plural(row.consecutive_failures, 'failure')}` : null,
    row.last_success_at ? `fetched ${formatRelativeTime(row.last_success_at, now)}` : 'never fetched',
    plural(row.stored_posts, 'post'),
    row.backlog_posts ? `${formatCount(row.backlog_posts)} in backlog` : null,
  ].filter(Boolean);
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem]">
        <StatusGlyph status={STATUS_GLYPH[status] ?? 'scheduled'} label={HEALTH_STATUS_LABELS[status] ?? status} />
        <span className="tabular-nums text-fg-3">{facts.join(' · ')}</span>
      </div>
      {row.status === 'unavailable' && row.decision_detail ? (
        <p className="text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]">{row.decision_detail}</p>
      ) : null}
      <ConnectionsLink row={row} />
      {row.last_error ? (
        <p className="text-[0.75rem] text-fg [overflow-wrap:anywhere]">
          <span aria-hidden="true" className="mr-1 font-semibold">×</span>
          {row.last_error}
          {row.last_error_at ? <span className="text-fg-3"> · {formatRelativeTime(row.last_error_at, now)}</span> : null}
        </p>
      ) : null}
    </div>
  );
}

export default function SourceSettingsEditor({ source, onClose, onSave, healthRow: givenRow, onToggleEnabled, onDelete }: SourceSettingsEditorProps) {
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
  const healthRow = givenRow ?? health.data?.rows.find((row) => row.source_id === source.id) ?? null;
  const { run, isRunning } = useIngestionRun();
  const fetchTarget = { kind: 'source' as const, id: source.id, name: sourceLabel(source.settings.display_name, source.handle_or_url) };
  const fetching = isRunning(fetchTarget);
  const enabled = healthRow?.enabled ?? source.enabled;
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
        api.getFolders(),
        api.getSourceFolders(source.id),
      ]);
      if (!mounted) return;
      if (allRes.success) setFolders(allRes.folders);
      if (mineRes.success) setMemberFolderIds(new Set(mineRes.folder_ids));
      setFoldersLoading(false);
    })();
    return () => { mounted = false; };
  }, [api, source.id]);

  const toggleFolder = async (folderId: string) => {
    const isMember = memberFolderIds.has(folderId);
    setMemberFolderIds((prev) => {
      const next = new Set(prev);
      if (isMember) next.delete(folderId); else next.add(folderId);
      return next;
    });
    const res = isMember
      ? await api.removeSourceFromFolder(folderId, source.id)
      : await api.addSourceToFolder(folderId, source.id);
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

      const response = await api.updateSourceSettings(source.id, settingsToSave);

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
        description={getPlatformLabel(source.platform)}
        className="w-[min(32rem,100vw)]"
      >
        {/* A div, not a form: the cadence editor below is its own form and forms cannot nest. */}
        <div className="space-y-6">
          <div className="space-y-3">
            <SourceAddress value={source.handle_or_url} />
            {healthRow ? <HealthSummary row={healthRow} now={new Date()} /> : null}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void run(fetchTarget)}
                disabled={fetching || !enabled}
                aria-busy={fetching}
                title="Fetch now (ignores cadence and backoff)"
              >
                {fetching ? 'Fetching…' : 'Fetch now'}
              </Button>
              {onToggleEnabled ? (
                <label className="ml-auto inline-flex items-center gap-2 text-[0.8125rem] text-fg-2">
                  {enabled ? 'On' : 'Off'}
                  <Switch checked={enabled} onCheckedChange={(next) => onToggleEnabled(next)} aria-label={enabled ? 'Disable this source' : 'Enable this source'} />
                </label>
              ) : null}
            </div>
          </div>

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
                Off keeps it fetched and readable through its tracks, but out of the feed. Saves instantly.
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

          <div className="rounded-md border border-line p-3">
            <ArchiveSection sourceId={source.id} />
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
            {onDelete ? (
              <Button variant="danger" onClick={onDelete} disabled={isSaving} className="mr-auto">Delete source…</Button>
            ) : null}
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
