import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Plus } from 'lucide-react';

import { useApi } from '../services/ApiContext';
import type { Envelope, SourceHealthRow, SourceWithSettings, SourcesHealthResponse } from '../services/api';
import AddSourceModal from '../components/AddSourceModal';
import SourceSettingsEditor from '../components/SourceSettingsEditor';
import ConfirmDialog from '../components/ops/ConfirmDialog';
import DevDataSwitch from '../components/ops/DevDataSwitch';
import { HEALTH_FIXTURE_NAMES, isHealthFixtureName } from '../components/ops/fixtureNames';
import SourceList, { type TrackActions } from '../components/sources/SourceList';
import SourcesToolbar from '../components/sources/SourcesToolbar';
import BulkActionBar from '../components/sources/BulkActionBar';
import IngestionPanel from '../components/sources/IngestionPanel';
import { useListKeys } from '../components/sources/useListKeys';
import {
  STATUS_FILTERS,
  filterByStatus,
  filterSources,
  groupSources,
  nextSort,
  rangeIds,
  readSourcesView,
  rowName,
  stepActive,
  toggleInSet,
  visibleRowKeys,
  writeSourcesView,
  type SourcesView,
  type StatusFilter,
} from '../components/sources/sourceList';
import { Button, Dialog, DialogContent, DialogFooter, Input, Page, PageHeader, Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui';
import { ConnectionsPanel } from '../components/connections';
import { EmptyState, ErrorState, LoadingState, Notice } from '../components/states';
import { SOURCES_HEALTH_KEY, useSourcesHealth } from '../hooks/useSourcesHealth';
import { FOLDERS_KEY, useReaderDirectory } from '../hooks/useReaderDirectory';
import { useShortcutPreference } from '../hooks/useShortcutPreference';
import { useIngestionRun } from '../hooks/useIngestionRun';
import { useNow } from '../hooks/useNow';
import { UNREAD_COUNTS_KEY } from '../hooks/useFeed';
import { filterHealthRows, withEffectiveStatus } from '../lib/sourceSchedule';
import { errorMessage } from '../lib/apiError';
import { formatRelativeTime } from '../lib/dates';
import { plural } from '../lib/format';
import { sourceLabel } from '../lib/sourceLabel';

export const SOURCES_WITH_SETTINGS_KEY = ['sources-with-settings'] as const;

type PendingDelete =
  | { kind: 'sources'; ids: string[]; name: string }
  | { kind: 'folder'; id: string; name: string }
  | null;

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

/** History state on an entry the sheet pushed, so closing it goes Back instead of stacking entries. */
/** The dev-only `?data=` health fixtures, imported on demand: a production build drops them. */
const loadHealthFixtures = import.meta.env.DEV ? () => import('../components/ops/fixtures') : null;

const SHEET_PUSHED = 'sourceSheetPushed';
/** How long a deep-linked track group stays highlighted. */
const TRACK_HIGHLIGHT_MS = 1600;

/** The tabs besides the list (`?tab=`); any other value is a legacy URL. */
const EXTRA_TABS = ['connections', 'ingestion'] as const;
type ExtraTab = (typeof EXTRA_TABS)[number];
const isExtraTab = (value: string | null): value is ExtraTab => (EXTRA_TABS as readonly (string | null)[]).includes(value);

/**
 * Settings → Sources: every source on one dense list (spec §9, reading-first).
 * The old Sources and Health tabs are one view now: the toolbar searches,
 * filters by status and groups (by track or platform), the column headers sort;
 * a row opens the detail sheet (settings, cadence, fetch now, delete) or the
 * reader on that source; checkboxes select for the bulk bar. `?tab=health`
 * still works: it opens the list, keeping its status filter.
 */
export default function SourcesConfig() {
  const api = useApi();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const view = readSourcesView(searchParams);
  const setView = (next: SourcesView) => setSearchParams(writeSourcesView(searchParams, next), { replace: true });

  // Three tabs: the list, Connections (?tab=connections, spec §10.1) and
  // Ingestion (?tab=ingestion, reading-finish R3). The legacy Health tab URL
  // becomes the list view (readSourcesView).
  const tabParam = searchParams.get('tab');
  const tab = isExtraTab(tabParam) ? tabParam : 'sources';
  useEffect(() => {
    const legacy = searchParams.get('tab');
    if (legacy !== null && !isExtraTab(legacy)) setSearchParams(writeSourcesView(searchParams, readSourcesView(searchParams)), { replace: true });
  }, [searchParams, setSearchParams]);
  const setTab = (next: string) => {
    const params = new URLSearchParams(searchParams);
    params.delete('provider');
    params.delete('sub');
    params.delete('job');
    params.delete('source');
    params.delete('track');
    if (isExtraTab(next)) params.set('tab', next);
    else params.delete('tab');
    setSearchParams(params, { replace: true });
  };

  const dataParam = searchParams.get('data');
  const fixtureName = import.meta.env.DEV && isHealthFixtureName(dataParam) ? dataParam : null;
  const health = useSourcesHealth(
    fixtureName && loadHealthFixtures ? () => loadHealthFixtures().then((module) => module.healthFixture(fixtureName)) : undefined,
    fixtureName ?? undefined,
  );
  const { folders: foldersQuery } = useReaderDirectory();
  const sourcesQuery = useQuery({
    queryKey: [...SOURCES_WITH_SETTINGS_KEY],
    queryFn: async () => {
      const response = await api.getSources();
      return response.sources;
    },
    staleTime: 30_000,
  });

  // Once a minute, so "fetched 3h ago" stays true.
  const now = useNow(60_000);
  const [shortcutsOn] = useShortcutPreference();
  const searchRef = useRef<HTMLInputElement>(null);
  const { run: runFetch, isRunning } = useIngestionRun();
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const [activeKey, setActiveKey] = useState<string | null>(null);
  // Where a shift-click range starts: the last row checked or unchecked without Shift (or with x).
  const [anchorKey, setAnchorKey] = useState<string | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>(null);

  // The URL owns the sheet (issue 0003): `?source=<id>` opens it, so a reader can
  // link straight to a source's settings. Opening pushes a history entry (Back
  // closes it); closing pops that entry, or drops the parameter of a deep link.
  // A link out of the sheet ("add in Connections") switches the tab: the sheet closes with it.
  const location = useLocation();
  const navigate = useNavigate();
  const openId = tab === 'sources' ? searchParams.get('source') : null;
  const latestParams = useRef(searchParams);
  latestParams.current = searchParams;
  const latestState = useRef(location.state);
  latestState.current = location.state;
  const openSheet = (id: string) => {
    const params = new URLSearchParams(searchParams);
    params.set('source', id);
    setSearchParams(params, { state: { [SHEET_PUSHED]: true } });
  };
  // Reads the latest URL, so a close after an await never goes Back twice.
  const closeSheet = () => {
    const params = new URLSearchParams(latestParams.current);
    if (!params.has('source')) return;
    const state = latestState.current as Record<string, unknown> | null;
    if (state?.[SHEET_PUSHED]) {
      navigate(-1);
      return;
    }
    params.delete('source');
    setSearchParams(params, { replace: true });
  };
  const dropParam = (name: 'source' | 'track') => {
    const params = new URLSearchParams(latestParams.current);
    params.delete(name);
    setSearchParams(params, { replace: true });
  };
  const [showAddSource, setShowAddSource] = useState(false);
  const [newTrackOpen, setNewTrackOpen] = useState(false);
  const [newTrackName, setNewTrackName] = useState('');
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [renameText, setRenameText] = useState('');
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
    () => groupSources(rows, view.group, folders, { keepEmpty: !filtering, sort: view.sort, dir: view.dir }),
    [rows, view.group, view.sort, view.dir, folders, filtering],
  );
  const counts = useMemo(() => {
    const searched = filterSources(allRows, { q: view.q, status: null });
    const out: Partial<Record<StatusFilter, number>> = {};
    STATUS_FILTERS.forEach(({ value }) => { out[value] = filterByStatus(searched, value).length; });
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
  const each = async (ids: string[], call: (id: string) => Promise<Envelope>, verb: string) => {
    setBusy(true);
    const results = await Promise.all(ids.map(call));
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
    if (openId && ids.includes(openId)) closeSheet();
  };

  const removeFromTrack = async (ids: string[], folderId: string) => {
    const folder = folders.find((f) => f.id === folderId);
    // Only the selected sources that are in the track: the others have nothing to remove.
    const members = ids.filter((id) => allRows.find((row) => row.source_id === id)?.folders.some((f) => f.id === folderId));
    const ok = await each(members, (id) => api.removeSourceFromFolder(folderId, id), 'remove');
    if (ok) toast(`Removed ${plural(members.length, 'source')} from ${folder?.name ?? 'the track'}`);
  };

  const setMainDigest = async (ids: string[], on: boolean) => {
    const ok = await each(ids, async (id) => {
      await api.setSourceMainDigest(id, on);
      return { success: true };
    }, on ? 'show in the Main feed' : 'leave out of the Main feed');
    void queryClient.invalidateQueries({ queryKey: [...UNREAD_COUNTS_KEY] });
    if (ok) toast(`${plural(ids.length, 'source')} ${on ? 'shown in' : 'left out of'} the Main feed`);
  };

  const trackActions: TrackActions = {
    fetch: (id, name) => void runFetch({ kind: 'folder', id, name }),
    isFetching: (id) => isRunning({ kind: 'folder', id }),
    rename: (id, name) => { setRenameText(name); setRenaming({ id, name }); },
    // From the member sources, the only place the main feed reads: mixed when they differ.
    inMainDigest: (id) => {
      const members = allRows.filter((row) => row.folders.some((f) => f.id === id));
      if (!members.length) return null;
      const inMain = members.filter((row) => row.in_main_digest).length;
      return inMain === members.length ? true : inMain === 0 ? false : 'mixed';
    },
    setMainDigest: (id, name, on) => {
      void (async () => {
        try {
          await api.setTrackMainDigest(id, on);
          toast(`${name}: ${on ? 'shown in' : 'left out of'} the Main feed`);
        } catch (err) {
          setError(`Could not change ${name}: ${errorMessage(err)}`);
        }
        invalidate();
        void queryClient.invalidateQueries({ queryKey: [...UNREAD_COUNTS_KEY] });
      })();
    },
    remove: (id, name) => setPendingDelete({ kind: 'folder', id, name }),
  };

  const submitRename = async () => {
    const name = renameText.trim();
    if (!renaming || !name) return;
    const target = renaming;
    setRenaming(null);
    if (name === target.name) return;
    try {
      await api.renameTrack(target.id, name);
    } catch (err) {
      setError(`Could not rename ${target.name}: ${errorMessage(err)}`);
    }
    invalidate();
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

  const handleAddSource = async (data: { handle_or_url: string; display_name: string; fetch_delay_seconds: number; state: string }) => {
    const r = await api.addSource({ platform: 'rss', ...data });
    setShowAddSource(false);
    if (!r.success) setError(r.error || 'Could not add the source');
    invalidate();
    // A new source is read right away, not at the next scheduler tick. Fetch-now forces a
    // fetch, so a source added disabled is left alone.
    if (r.success && r.source_id && data.state === 'enabled') {
      void runFetch({ kind: 'source', id: r.source_id, name: sourceLabel(data.display_name, data.handle_or_url) }, { startText: 'Added — fetching now' });
    }
  };

  const selectIds = (ids: string[], on: boolean) => setSelected((prev) => {
    const next = new Set(prev);
    ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
    return next;
  });
  /** A row checkbox: Shift extends from the anchor (the range takes the clicked row's new state). */
  const selectRow = (key: string, id: string, on: boolean, shift: boolean) => {
    if (shift && anchorKey) selectIds(rangeIds(keys, anchorKey, key), on);
    else selectIds([id], on);
    setAnchorKey(key);
  };
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
    x: activeId ? () => { setSelected((prev) => toggleInSet(prev, activeId)); setAnchorKey(activeKey); } : undefined,
    o: activeId ? () => openSheet(activeId) : undefined,
    Enter: activeId ? () => openSheet(activeId) : undefined,
    Escape: selected.size ? () => setSelected(new Set()) : undefined,
  }, shortcutsOn && tab === 'sources' && !openId && !showAddSource && !newTrackOpen && !renaming && pendingDelete === null);

  const openRow = openId ? allRows.find((row) => row.source_id === openId) ?? null : null;
  const openSource = openId
    ? sourcesQuery.data?.find((s) => s.id === openId) ?? (openRow ? fromHealthRow(openRow) : null)
    : null;
  // A deep link to a source or track that is gone: the list, with a quiet note.
  const missingSource = Boolean(openId && health.data && !openSource && !sourcesQuery.isPending);
  const trackParam = tab === 'sources' ? searchParams.get('track') : null;
  const foldersKnown = Boolean(fixtureName ? health.data : foldersQuery.data);
  const missingTrack = Boolean(trackParam && foldersKnown && !folders.some((folder) => folder.id === trackParam));

  // `?track=<id>`: scroll to that track's group once it is on screen and highlight it briefly.
  const [highlightTrack, setHighlightTrack] = useState<string | null>(null);
  const scrolledTo = useRef<string | null>(null);
  const trackGroupShown = Boolean(trackParam && groups.some((group) => group.folderId === trackParam));
  useEffect(() => {
    if (!trackParam) {
      scrolledTo.current = null;
      return undefined;
    }
    if (!trackGroupShown || scrolledTo.current === trackParam) return undefined;
    const section = document.querySelector<HTMLElement>(`section[data-folder-id="${CSS.escape(trackParam)}"]`);
    if (!section) return undefined;
    scrolledTo.current = trackParam;
    const reduced = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    section.scrollIntoView?.({ block: 'start', behavior: reduced ? 'auto' : 'smooth' });
    setHighlightTrack(trackParam);
    return undefined;
  }, [trackParam, trackGroupShown]);
  useEffect(() => {
    if (!highlightTrack) return undefined;
    const timer = window.setTimeout(() => setHighlightTrack(null), TRACK_HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [highlightTrack]);

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
        onSelectRow={selectRow}
        activeKey={activeKey}
        onActivate={setActiveKey}
        onOpen={openSheet}
        highlightFolderId={highlightTrack}
        onToggleEnabled={(row) => void setEnabled([row.source_id], !row.enabled)}
        track={trackActions}
        now={now}
        sort={view.sort}
        dir={view.dir}
        onSort={(column) => setView(nextSort(view, column))}
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

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList aria-label="Sources page" className="mb-4">
          <TabsTrigger value="sources">sources</TabsTrigger>
          <TabsTrigger value="connections">connections</TabsTrigger>
          <TabsTrigger value="ingestion">ingestion</TabsTrigger>
        </TabsList>
        <TabsContent value="sources" className="pt-0">
          <div className="pb-24">
            {missingSource ? (
              <Notice tone="status" title="That source no longer exists" action={{ label: 'Dismiss', onClick: () => dropParam('source') }} className="mb-3" />
            ) : null}
            {missingTrack ? (
              <Notice tone="status" title="That track no longer exists" action={{ label: 'Dismiss', onClick: () => dropParam('track') }} className="mb-3" />
            ) : null}
            {allRows.length ? <SourcesToolbar ref={searchRef} view={view} counts={counts.byStatus} total={counts.total} onChange={setView} /> : null}
            {body}
          </div>
        </TabsContent>
        <TabsContent value="connections" className="pt-2">
          <div className="pb-24">
            <ConnectionsPanel initialOpen={searchParams.get('provider')} />
          </div>
        </TabsContent>
        <TabsContent value="ingestion" className="pt-2">
          <div className="pb-24">
            <IngestionPanel />
          </div>
        </TabsContent>
      </Tabs>

      {tab === 'sources' ? <BulkActionBar
        count={selectedVisible.length}
        folders={folders}
        memberFolders={folders.filter((folder) => allRows.some((row) => selectedVisible.includes(row.source_id) && row.folders.some((f) => f.id === folder.id)))}
        busy={busy}
        onEnable={(enabled) => void setEnabled(selectedVisible, enabled)}
        onAddToTrack={(folderId) => void addToTrack(selectedVisible, folderId)}
        onRemoveFromTrack={(folderId) => void removeFromTrack(selectedVisible, folderId)}
        onMainDigest={(on) => void setMainDigest(selectedVisible, on)}
        onDelete={() => setPendingDelete({
          kind: 'sources',
          ids: selectedVisible,
          name: selectedVisible.length === 1
            ? rowName(allRows.find((row) => row.source_id === selectedVisible[0]) ?? { display_name: '', source_id: selectedVisible[0] })
            : plural(selectedVisible.length, 'source'),
        })}
        onClear={() => setSelected(new Set())}
      /> : null}

      {showAddSource ? (
        <AddSourceModal
          platform="rss"
          existingAddresses={sourcesQuery.data?.map((source) => source.handle_or_url)}
          onClose={() => setShowAddSource(false)}
          onAdd={handleAddSource}
        />
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

      <Dialog open={renaming !== null} onOpenChange={(open) => { if (!open) setRenaming(null); }}>
        <DialogContent title="Rename track" description={renaming ? `Now “${renaming.name}”.` : undefined}>
          <form
            className="mt-4 space-y-4"
            onSubmit={(event) => { event.preventDefault(); void submitRename(); }}
          >
            <Input
              aria-label="Track name"
              value={renameText}
              onChange={(event) => setRenameText(event.target.value)}
              maxLength={120}
              autoFocus
            />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setRenaming(null)}>Cancel</Button>
              <Button type="submit" variant="primary" disabled={!renameText.trim()}>Rename</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={pendingDelete?.kind === 'folder' ? `Delete the track "${pendingDelete.name}"?` : `Delete ${pendingDelete?.kind === 'sources' && pendingDelete.ids.length === 1 ? `"${pendingDelete.name}"` : pendingDelete?.name ?? ''}?`}
        description={pendingDelete?.kind === 'folder'
          ? 'The track is deleted. Its sources and their posts stay.'
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
          onClose={closeSheet}
          onSave={invalidate}
          onToggleEnabled={(enabled) => void setEnabled([openSource.id], enabled)}
          onDelete={() => {
            closeSheet();
            setPendingDelete({ kind: 'sources', ids: [openSource.id], name: openRow ? rowName(openRow) : openSource.handle_or_url });
          }}
        />
      ) : null}

      <DevDataSwitch options={HEALTH_FIXTURE_NAMES} />
    </Page>
  );
}
