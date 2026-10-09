import { useCallback, useEffect, useId, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Plus, Settings, Trash2 } from 'lucide-react';
import { apiService } from '../services/api';
import type { SourceWithSettings, Folder, Expert } from '../services/api';
import AddSourceModal from '../components/AddSourceModal';
import SourceSettingsEditor from '../components/SourceSettingsEditor';
import SourceHealthTable from '../components/ops/SourceHealthTable';
import ConfirmDialog from '../components/ops/ConfirmDialog';
import { Button, Input, Page, PageHeader, Tabs, TabsContent, TabsList, TabsTrigger, TextLink } from '../components/ui';
import { EmptyState, LoadingState, Notice } from '../components/states';
import { middleTruncate, plural, sourceLabel } from '../lib/format';
import { getPlatformLabel } from '../lib/sourcePresentation';

type SourcesTab = 'sources' | 'health';
type PendingDelete = { kind: 'source' | 'folder'; id: string; name: string } | null;

function sourceName(source: SourceWithSettings): string {
  return sourceLabel(source.settings?.display_name, source.handle_or_url);
}

/** The on/off switch: an inverted pill when on, a hairline when off (no green). */
function EnabledSwitch({ enabled, name, onToggle }: { enabled: boolean; name: string; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={`${enabled ? 'Disable' : 'Enable'} ${name}`}
      title={enabled ? 'Enabled' : 'Disabled'}
      onClick={onToggle}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-[120ms] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg motion-reduce:transition-none ${
        enabled ? 'border-inverse bg-inverse' : 'border-line-strong bg-transparent'
      }`}
    >
      <span
        aria-hidden="true"
        className={`absolute h-3.5 w-3.5 rounded-full transition-transform duration-[120ms] ease-out motion-reduce:transition-none ${
          enabled ? 'translate-x-[1.125rem] bg-inverse-fg' : 'translate-x-[0.1875rem] bg-fg-3'
        }`}
      />
    </button>
  );
}

/** One smol-style bordered row: switch, readable name, platform + handle, actions. */
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
  const name = sourceName(source);
  const handle = source.handle_or_url && source.handle_or_url !== name ? source.handle_or_url : null;
  return (
    <li className="flex min-w-0 items-center gap-3 rounded-md border border-line bg-surface px-3 py-2.5 coarse:py-3">
      <EnabledSwitch enabled={source.enabled} name={name} onToggle={onToggle} />
      <div className="min-w-0 flex-1">
        <div
          className={`truncate text-[0.9375rem] font-semibold ${source.enabled ? 'text-fg' : 'text-fg-3'}`}
          title={source.handle_or_url}
          dir="auto"
        >
          {name}
        </div>
        <div className="flex min-w-0 gap-1.5 text-[0.75rem] text-fg-3">
          <span className="shrink-0">{getPlatformLabel(source.platform)}</span>
          {!source.enabled ? <span className="shrink-0">· disabled</span> : null}
          {handle ? (
            <span className="min-w-0 truncate" title={handle}>· {middleTruncate(handle, 56)}</span>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center">
        <Button variant="ghost" size="icon" onClick={onSettings} aria-label={`Settings for ${name}`} title="Settings">
          <Settings aria-hidden="true" />
        </Button>
        <Button variant="ghost" size="icon" onClick={onRemove} aria-label={`Delete source ${name}`} title="Delete">
          <Trash2 aria-hidden="true" />
        </Button>
      </div>
    </li>
  );
}

export default function SourcesConfig() {
  const [searchParams, setSearchParams] = useSearchParams();
  const newTrackId = useId();
  // The Health tab lives at ?tab=health, where its ?status= filter owns the URL.
  const tab: SourcesTab = searchParams.get('tab') === 'health' ? 'health' : 'sources';
  const setTab = (next: SourcesTab) => {
    const params = new URLSearchParams(searchParams);
    if (next === 'health') params.set('tab', 'health');
    else {
      params.delete('tab');
      params.delete('status');
      params.delete('data');
    }
    setSearchParams(params, { replace: true });
  };
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>(null);
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
    if (!sRes.success) setError(sRes.error || 'Could not load sources');
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const sourcesInFolder = (fid: string) => sources.filter((s) => (sourceFolderMap[s.id] || []).includes(fid));
  const unassigned = sources.filter((s) => (sourceFolderMap[s.id] || []).length === 0);
  const expertsForFolder = (fid: string) => experts.filter((e) => e.folder_id === fid);
  const enabledCount = sources.filter((s) => s.enabled).length;

  const addFolder = async () => {
    const name = newFolderName.trim();
    if (!name) return;
    const r = await apiService.createFolder({ name });
    if (r.success) { setNewFolderName(''); load(); } else setError(r.error || 'Could not create the track');
  };
  const removeFolder = async (id: string) => {
    const r = await apiService.deleteFolder(id);
    if (r.success) load(); else setError(r.error || 'Could not delete the track');
  };
  const toggleEnabled = async (s: SourceWithSettings) => {
    setSources((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled: !s.enabled } : x)));
    const r = await apiService.setSourceEnabled(s.id, !s.enabled);
    if (!r.success) {
      setSources((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled: s.enabled } : x)));
      setError(r.error || `Could not ${s.enabled ? 'disable' : 'enable'} ${sourceName(s)}`);
    }
  };
  const removeSource = async (id: string) => {
    const r = await apiService.deleteSource(id);
    if (r.success) load(); else setError(r.error || 'Could not delete the source');
  };
  const handleAddSource = async (data: { handle_or_url: string; display_name: string; fetch_delay_seconds: number; priority: number; max_posts_per_fetch: number; state: string }) => {
    const r = await apiService.addSource({ platform: 'rss', ...data });
    setShowAddSource(false);
    if (r.success) load(); else setError(r.error || 'Could not add the source');
  };

  const renderSources = (list: SourceWithSettings[]) => (
    <ul className="space-y-2">
      {list.map((s) => (
        <SourceRow
          key={s.id}
          source={s}
          onToggle={() => toggleEnabled(s)}
          onSettings={() => setEditingSource(s)}
          onRemove={() => setPendingDelete({ kind: 'source', id: s.id, name: sourceName(s) })}
        />
      ))}
    </ul>
  );

  const meta = loading && !sources.length
    ? 'Loading…'
    : `${plural(sources.length, 'source')} · ${plural(enabledCount, 'enabled', 'enabled')} · ${plural(folders.length, 'track')}`;

  return (
    <Page width="wide">
      <PageHeader
        title="Sources"
        meta={meta}
        actions={(
          <Button variant="primary" onClick={() => setShowAddSource(true)}>
            <Plus aria-hidden="true" /> Add source
          </Button>
        )}
      />

      {error ? (
        <Notice tone="error" title={error} action={{ label: 'Dismiss', onClick: () => setError(null) }} className="mb-6" />
      ) : null}

      <Tabs value={tab} onValueChange={(value) => setTab(value as SourcesTab)}>
        <TabsList aria-label="Sources settings">
          <TabsTrigger value="sources">sources &amp; tracks</TabsTrigger>
          <TabsTrigger value="health">health &amp; cadence</TabsTrigger>
        </TabsList>

        <TabsContent value="health">
          <SourceHealthTable />
        </TabsContent>

        <TabsContent value="sources">
          <form
            className="mb-10 flex flex-wrap items-end gap-2"
            onSubmit={(event) => { event.preventDefault(); void addFolder(); }}
          >
            <div className="min-w-0 flex-1 basis-[14rem] space-y-1.5">
              <label htmlFor={newTrackId} className="block text-[0.8125rem] font-medium text-fg">New track</label>
              <Input
                id={newTrackId}
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="For example: AR glasses"
                maxLength={120}
              />
            </div>
            <Button type="submit" variant="secondary" disabled={!newFolderName.trim()}>
              Create track
            </Button>
          </form>

          {loading && !sources.length ? <LoadingState label="Loading sources" rows={5} /> : null}

          {!loading && !sources.length && !error ? (
            <EmptyState
              title="No sources yet"
              description="Add an RSS feed, a subreddit, a Telegram channel or a YouTube channel to start reading."
              action={{ label: 'Add source', onClick: () => setShowAddSource(true) }}
            />
          ) : null}

          <div className="space-y-10">
            {folders.map((f) => {
              const fSources = sourcesInFolder(f.id);
              const fExperts = expertsForFolder(f.id);
              return (
                <section key={f.id} aria-labelledby={`track-${f.id}`}>
                  <div className="mb-3 flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
                    <h2 id={`track-${f.id}`} className="min-w-0 break-words text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">
                      <TextLink to={`/tracks/${f.id}`} className="no-underline hover:underline">{f.name}</TextLink>
                    </h2>
                    <span className="text-[0.8125rem] tabular-nums text-fg-3">{plural(fSources.length, 'source')}</span>
                    {fExperts.length > 0 ? (
                      <span className="min-w-0 truncate text-[0.8125rem] text-fg-2" title={fExperts.map((e) => e.name).join(', ')}>
                        {fExperts.length === 1 ? 'expert' : 'experts'}: {fExperts.map((e) => e.name).join(', ')}
                      </span>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      onClick={() => setPendingDelete({ kind: 'folder', id: f.id, name: f.name })}
                      aria-label={`Delete track ${f.name}`}
                    >
                      Delete track
                    </Button>
                  </div>
                  {fSources.length === 0 ? (
                    <p className="rounded-md border border-dashed border-line px-3 py-3 text-[0.8125rem] text-fg-3">
                      No sources yet. Open a source&rsquo;s settings to add it to this track.
                    </p>
                  ) : (
                    renderSources(fSources)
                  )}
                </section>
              );
            })}

            {sources.length > 0 ? (
              <section aria-labelledby="track-unassigned">
                <div className="mb-3 flex items-baseline gap-3">
                  <h2 id="track-unassigned" className="text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">
                    Not in a track
                  </h2>
                  <span className="text-[0.8125rem] tabular-nums text-fg-3">{plural(unassigned.length, 'source')}</span>
                </div>
                {unassigned.length === 0 ? (
                  <p className="text-[0.8125rem] text-fg-3">Every source is in a track.</p>
                ) : (
                  renderSources(unassigned)
                )}
              </section>
            ) : null}
          </div>
        </TabsContent>
      </Tabs>

      {showAddSource && (
        <AddSourceModal
          platform="rss"
          onClose={() => setShowAddSource(false)}
          onAdd={handleAddSource}
        />
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={pendingDelete?.kind === 'folder' ? `Delete the track "${pendingDelete.name}"?` : `Delete "${pendingDelete?.name ?? ''}"?`}
        description={pendingDelete?.kind === 'folder'
          ? 'The track, its experts and its milestones are deleted. Its sources and their posts stay (they move to "Not in a track" if they are in no other track).'
          : 'The source and every post collected from it are deleted. This cannot be undone; disabling it keeps its posts.'}
        confirmLabel={pendingDelete?.kind === 'folder' ? 'Delete track' : 'Delete source'}
        destructive
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          const target = pendingDelete;
          setPendingDelete(null);
          if (!target) return;
          if (target.kind === 'folder') void removeFolder(target.id);
          else void removeSource(target.id);
        }}
      />

      {editingSource && (
        <SourceSettingsEditor
          source={editingSource}
          onClose={() => setEditingSource(null)}
          onSave={() => { setEditingSource(null); load(); }}
        />
      )}
    </Page>
  );
}
