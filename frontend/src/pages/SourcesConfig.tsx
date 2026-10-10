import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Plus } from 'lucide-react';

import { useApi } from '../services/ApiContext';
import type { HealthStatus, SourceHealthRow, SourceWithSettings, SourcesHealthResponse } from '../services/api';
import AddSourceModal from '../components/AddSourceModal';
import SourceSettingsEditor from '../components/SourceSettingsEditor';
import ConfirmDialog from '../components/ops/ConfirmDialog';
import DevDataSwitch from '../components/ops/DevDataSwitch';
import { HEALTH_FIXTURE_NAMES, healthFixture, isHealthFixtureName } from '../components/ops/fixtures';
import SourceList from '../components/sources/SourceList';
import SourcesToolbar from '../components/sources/SourcesToolbar';
import BulkActionBar from '../components/sources/BulkActionBar';
import { useListKeys } from '../components/sources/useListKeys';
import {
  filterSources,
  groupSources,
  readSourcesView,
  rowName,
  stepActive,
  toggleInSet,
  visibleRowKeys,
  writeSourcesView,
  type SourcesView,
} from '../components/sources/sourceList';
import { Button, Dialog, DialogContent, DialogFooter, Input, Page, PageHeader } from '../components/ui';
import { EmptyState, ErrorState, LoadingState, Notice } from '../components/states';
import { SOURCES_HEALTH_KEY, useSourcesHealth } from '../hooks/useSourcesHealth';
import { FOLDERS_KEY, useReaderDirectory } from '../hooks/useReaderDirectory';
import { useShortcutPreference } from '../hooks/useShortcutPreference';
import { HEALTH_STATUS_ORDER, filterHealthRows, withEffectiveStatus } from '../lib/sourceSchedule';
import { errorMessage } from '../lib/apiError';
import { formatRelativeTime } from '../lib/dates';
import { plural } from '../lib/format';

export const SOURCES_WITH_SETTINGS_KEY = ['sources-with-settings'] as const;

type PendingDelete =
  | { kind: 'sources'; ids: string[]; name: string }
  | { kind: 'folder'; id: string; name: string }
  | null;

/** Re-render once a minute so "fetched 3h ago" stays true; paused while hidden. */
function useMinuteClock(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') setNow(new Date());
    }, 60_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

/** A SourceWithSettings for the sheet when only the health row is known (fixtures, a slow list). */
function fromHealthRow(row: SourceHealthRow): SourceWithSettings {
  return {
    id: row.source_id,
    platform: row.platform,
    handle_or_url: String(row.display_name),
    enabled: row.enabled,
    post_count: row.stored_posts,
    settings: { display_name: String(row.display_name) },
  };
}

/**
 * Settings → Sources: every source on one dense list (spec §9, reading-first).
 * The old Sources and Health tabs are one view now: the toolbar searches,
 * filters by status and groups (by track, status or platform); a row opens the
 * detail sheet (settings, cadence, fetch now, delete); checkboxes select for
 * the bulk bar. `?tab=health` still works: it opens the list grouped by status.
 */
export default function SourcesConfig() {
  const api = useApi();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const view = readSourcesView(searchParams);
  const setView = (next: SourcesView) => setSearchParams(writeSourcesView(searchParams, next), { replace: true });

  // The legacy Health tab URL becomes the status grouping it stood for.
  useEffect(() => {
    if (searchParams.get('tab') !== null) setSearchParams(writeSourcesView(searchParams, readSourcesView(searchParams)), { replace: true });
  }, [searchParams, setSearchParams]);

  const dataParam = searchParams.get('data');
  const fixtureName = import.meta.env.DEV && isHealthFixtureName(dataParam) ? dataParam : null;
  const health = useSourcesHealth(fixtureName ? () => healthFixture(fixtureName) : undefined, fixtureName ?? undefined);
  const { folders: foldersQuery } = useReaderDirectory();
  const sourcesQuery = useQuery({
    queryKey: [...SOURCES_WITH_SETTINGS_KEY],
    queryFn: async () => {
      const response = await api.getSourcesWithSettings();
      if (!response.success) throw new Error(response.error || 'Could not load sources.');
      return response.sources;
    },
    staleTime: 30_000,
  });

  const now = useMinuteClock();
  const [shortcutsOn] = useShortcutPreference();
  const searchRef = useRef<HTMLInputElement>(null);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>(null);
  const [showAddSource, setShowAddSource] = useState(false);
  const [newTrackOpen, setNewTrackOpen] = useState(false);
  const [newTrackName, setNewTrackName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A dev fixture brings its own tracks (its rows name them); otherwise the real ones.
  const folders = useMemo(() => {
    if (!fixtureName) return foldersQuery.data ?? [];
    const seen = new Map<string, { id: string; name: string; sort_order: number }>();
    (health.data?.rows ?? []).forEach((row) => row.folders.forEach((f) => seen.set(f.id, { ...f, sort_order: seen.size })));
    return [...seen.values()];
  }, [fixtureName, foldersQuery.data, health.data]);
  const allRows = useMemo(() => withEffectiveStatus(health.data?.rows ?? [], now), [health.data, now]);
  const rows = useMemo(() => filterSources(allRows, view), [allRows, view.q, view.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const filtering = Boolean(view.q.trim() || view.status);
  const groups = useMemo(
    () => groupSources(rows, view.group, folders, { keepEmpty: !filtering }),
    [rows, view.group, folders, filtering],
  );
  const counts = useMemo(() => {
    const searched = filterSources(allRows, { q: view.q, status: null });
    const out: Partial<Record<HealthStatus, number>> = {};
    HEALTH_STATUS_ORDER.forEach((status) => { out[status] = filterHealthRows(searched, status).length; });
    return { byStatus: out, total: searched.length };
  }, [allRows, view.q]);
  const keys = useMemo(() => visibleRowKeys(groups, collapsed), [groups, collapsed]);
  const visibleIds = useMemo(() => new Set(rows.map((row) => row.source_id)), [rows]);

  // Selection only holds sources that still exist.
  useEffect(() => {
    if (!health.data) return;
    const ids = new Set(allRows.map((row) => row.source_id));
    setSelected((prev) => ([...prev].every((id) => ids.has(id)) ? prev : new Set([...prev].filter((id) => ids.has(id)))));
  }, [allRows, health.data]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: [...SOURCES_HEALTH_KEY] });
    void queryClient.invalidateQueries({ queryKey: [...SOURCES_WITH_SETTINGS_KEY] });
    void queryClient.invalidateQueries({ queryKey: [...FOLDERS_KEY] });
  };

  /** Optimistic on/off in every cached health response; rolled back by the refetch on failure. */
  const patchEnabled = (ids: ReadonlySet<string>, enabled: boolean) => {
    queryClient.setQueriesData<SourcesHealthResponse>({ queryKey: [...SOURCES_HEALTH_KEY] }, (current) => (
      current ? { ...current, rows: current.rows.map((row) => (ids.has(row.source_id) ? { ...row, enabled, status: enabled ? row.status === 'disabled' ? 'due' : row.status : 'disabled' } : row)) } : current
    ));
  };

  /** Run one call per source; report the failures in one line. */
  const each = async (ids: string[], call: (id: string) => Promise<{ success: boolean; error?: string }>, verb: string) => {
    setBusy(true);
    const results = await Promise.all(ids.map((id) => call(id).catch((err: unknown) => ({ success: false, error: errorMessage(err) }))));
    setBusy(false);
    const failed = results.filter((r) => !r.success);
    if (failed.length) setError(`Could not ${verb} ${plural(failed.length, 'source')}: ${failed[0].error || 'unknown error'}`);
    invalidate();
    return failed.length === 0;
  };

  const setEnabled = async (ids: string[], enabled: boolean) => {
    patchEnabled(new Set(ids), enabled);
    const ok = await each(ids, (id) => api.setSourceEnabled(id, enabled), enabled ? 'enable' : 'disable');
    if (ok && ids.length > 1) toast(`${enabled ? 'Enabled' : 'Disabled'} ${plural(ids.length, 'source')}`);
  };

  const addToTrack = async (ids: string[], folderId: string) => {
    const folder = folders.find((f) => f.id === folderId);
    const ok = await each(ids, (id) => api.addSourceToFolder(folderId, id), 'add');
    if (ok) toast(`Added ${plural(ids.length, 'source')} to ${folder?.name ?? 'the track'}`);
  };

  const deleteSources = async (ids: string[]) => {
    const ok = await each(ids, (id) => api.deleteSource(id), 'delete');
    if (ok) toast(`Deleted ${plural(ids.length, 'source')}`);
    setSelected((prev) => new Set([...prev].filter((id) => !ids.includes(id))));
    if (openId && ids.includes(openId)) setOpenId(null);
  };

  const deleteFolder = async (id: string) => {
    const r = await api.deleteFolder(id);
    if (!r.success) setError(r.error || 'Could not delete the track');
    invalidate();
  };

  const createTrack = async () => {
    const name = newTrackName.trim();
    if (!name) return;
    const r = await api.createFolder({ name });
    if (!r.success) { setError(r.error || 'Could not create the track'); return; }
    setNewTrackOpen(false);
    setNewTrackName('');
    invalidate();
  };

  const handleAddSource = async (data: { handle_or_url: string; display_name: string; fetch_delay_seconds: number; priority: number; max_posts_per_fetch: number; state: string }) => {
    const r = await api.addSource({ platform: 'rss', ...data });
    setShowAddSource(false);
    if (!r.success) setError(r.error || 'Could not add the source');
    invalidate();
  };

  const selectIds = (ids: string[], on: boolean) => setSelected((prev) => {
    const next = new Set(prev);
    ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
    return next;
  });
  const activeId = keys.find((k) => k.key === activeKey)?.id ?? null;
  const move = (delta: 1 | -1) => {
    const next = stepActive(keys.map((k) => k.key), activeKey, delta);
    if (next) { setActiveKey(next); setFocusToken((t) => t + 1); }
  };
  // The bulk bar acts on what is selected and still visible (a filter never deletes hidden rows).
  const selectedVisible = [...selected].filter((id) => visibleIds.has(id));

  useListKeys({
    j: () => move(1),
    k: () => move(-1),
    x: activeId ? () => setSelected((prev) => toggleInSet(prev, activeId)) : undefined,
    o: activeId ? () => setOpenId(activeId) : undefined,
    Enter: activeId ? () => setOpenId(activeId) : undefined,
    Escape: selected.size ? () => setSelected(new Set()) : undefined,
    '/': () => searchRef.current?.focus(),
  }, shortcutsOn && !openId && !showAddSource && !newTrackOpen && pendingDelete === null);

  const openRow = openId ? allRows.find((row) => row.source_id === openId) ?? null : null;
  const openSource = openId
    ? sourcesQuery.data?.find((s) => s.id === openId) ?? (openRow ? fromHealthRow(openRow) : null)
    : null;
  const enabledCount = allRows.filter((row) => row.enabled).length;
  const failingCount = filterHealthRows(allRows, 'error').length;

  const meta = health.isPending
    ? 'Loading…'
    : [
      plural(allRows.length, 'source'),
      `${enabledCount} on`,
      failingCount ? `${failingCount} failing` : null,
      plural(folders.length, 'track'),
      health.data?.generated_at ? `as of ${formatRelativeTime(health.data.generated_at, now)}` : null,
      fixtureName ? `fixture: ${fixtureName}` : null,
    ].filter(Boolean).join(' · ');

  let body;
  if (health.isPending) body = <LoadingState label="Loading sources" rows={8} />;
  else if (health.isError && !health.data) {
    body = <ErrorState title="Could not load sources" error={health.error} onRetry={() => void health.refetch()} />;
  } else if (!allRows.length) {
    body = (
      <EmptyState
        title="No sources yet"
        description="Add an RSS feed, a subreddit, a Telegram channel or a YouTube channel to start reading."
        action={{ label: 'Add source', onClick: () => setShowAddSource(true) }}
      />
    );
  } else if (!rows.length) {
    body = (
      <EmptyState
        title="No sources match"
        description={view.q ? `Nothing matches “${view.q}”${view.status ? ' with this status' : ''}.` : 'No source has this status right now.'}
        action={{ label: 'Clear filters', onClick: () => setView({ ...view, q: '', status: null }) }}
      />
    );
  } else {
    body = (
      <SourceList
        groups={groups}
        collapsed={collapsed}
        onToggleGroup={(key) => setCollapsed((prev) => toggleInSet(prev, key))}
        selected={selected}
        onSelect={selectIds}
        activeKey={activeKey}
        onActivate={setActiveKey}
        onOpen={setOpenId}
        onToggleEnabled={(row) => void setEnabled([row.source_id], !row.enabled)}
        onDeleteTrack={(id, name) => setPendingDelete({ kind: 'folder', id, name })}
        now={now}
        showHeaders={view.group !== 'none'}
        focusToken={focusToken}
      />
    );
  }

  return (
    <Page width="wide">
      <PageHeader
        title="Sources"
        meta={meta}
        actions={(
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => setNewTrackOpen(true)}>New track</Button>
            <Button variant="primary" onClick={() => setShowAddSource(true)}>
              <Plus aria-hidden="true" /> Add source
            </Button>
          </div>
        )}
      />

      {error ? (
        <Notice tone="error" title={error} action={{ label: 'Dismiss', onClick: () => setError(null) }} className="mb-4" />
      ) : null}
      {health.isError && health.data ? (
        <Notice
          tone="warning"
          title="Could not refresh sources"
          message={`${errorMessage(health.error)} The list shows the last loaded state.`}
          action={{ label: 'Retry', onClick: () => void health.refetch() }}
          className="mb-4"
        />
      ) : null}

      <div className="pb-24">
        {allRows.length ? <SourcesToolbar ref={searchRef} view={view} counts={counts.byStatus} total={counts.total} onChange={setView} /> : null}
        {body}
      </div>

      <BulkActionBar
        count={selectedVisible.length}
        folders={folders}
        busy={busy}
        onEnable={(enabled) => void setEnabled(selectedVisible, enabled)}
        onAddToTrack={(folderId) => void addToTrack(selectedVisible, folderId)}
        onDelete={() => setPendingDelete({
          kind: 'sources',
          ids: selectedVisible,
          name: selectedVisible.length === 1
            ? rowName(allRows.find((row) => row.source_id === selectedVisible[0]) ?? { display_name: '', source_id: selectedVisible[0] })
            : plural(selectedVisible.length, 'source'),
        })}
        onClear={() => setSelected(new Set())}
      />

      {showAddSource ? (
        <AddSourceModal platform="rss" onClose={() => setShowAddSource(false)} onAdd={handleAddSource} />
      ) : null}

      <Dialog open={newTrackOpen} onOpenChange={setNewTrackOpen}>
        <DialogContent title="New track" description="A track groups sources into their own reading view.">
          <form
            className="mt-4 space-y-4"
            onSubmit={(event) => { event.preventDefault(); void createTrack(); }}
          >
            <Input
              aria-label="Track name"
              value={newTrackName}
              onChange={(event) => setNewTrackName(event.target.value)}
              placeholder="For example: AR glasses"
              maxLength={120}
              autoFocus
            />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setNewTrackOpen(false)}>Cancel</Button>
              <Button type="submit" variant="primary" disabled={!newTrackName.trim()}>Create track</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={pendingDelete?.kind === 'folder' ? `Delete the track "${pendingDelete.name}"?` : `Delete ${pendingDelete?.kind === 'sources' && pendingDelete.ids.length === 1 ? `"${pendingDelete.name}"` : pendingDelete?.name ?? ''}?`}
        description={pendingDelete?.kind === 'folder'
          ? 'The track, its experts and its milestones are deleted. Its sources and their posts stay (they move to "Not in a track" if they are in no other track).'
          : 'Every post collected from them is deleted too. This cannot be undone; disabling keeps the posts.'}
        confirmLabel={pendingDelete?.kind === 'folder' ? 'Delete track' : pendingDelete?.kind === 'sources' && pendingDelete.ids.length > 1 ? `Delete ${pendingDelete.ids.length} sources` : 'Delete source'}
        destructive
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          const target = pendingDelete;
          setPendingDelete(null);
          if (!target) return;
          if (target.kind === 'folder') void deleteFolder(target.id);
          else void deleteSources(target.ids);
        }}
      />

      {openSource ? (
        <SourceSettingsEditor
          key={openSource.id}
          source={openSource}
          healthRow={openRow}
          onClose={() => setOpenId(null)}
          onSave={invalidate}
          onToggleEnabled={(enabled) => void setEnabled([openSource.id], enabled)}
          onDelete={() => {
            setOpenId(null);
            setPendingDelete({ kind: 'sources', ids: [openSource.id], name: openRow ? rowName(openRow) : openSource.handle_or_url });
          }}
        />
      ) : null}

      <DevDataSwitch options={HEALTH_FIXTURE_NAMES} />
    </Page>
  );
}
