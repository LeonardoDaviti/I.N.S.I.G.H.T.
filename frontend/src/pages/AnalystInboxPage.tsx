import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  CheckCircle2,
  Clock3,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Save,
  Ban,
} from 'lucide-react';
import { apiService } from '../services/api';
import type {
  InboxAction,
  InboxBatch,
  InboxItem,
  InboxItemDetail,
  SourceWithSettings,
} from '../services/api';

function formatDate(value?: string | null) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatShortDate(value?: string | null) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString();
}

function formatScore(value?: number | null, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return 'n/a';
  }
  return Number(value).toFixed(digits);
}

function percent(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return 'n/a';
  }
  const numeric = Number(value);
  if (numeric > 1) {
    return `${Math.round(numeric)}%`;
  }
  return `${Math.round(numeric * 100)}%`;
}

function statusTone(status?: string) {
  switch ((status || '').toLowerCase()) {
    case 'pending':
      return 'border-amber-200 bg-amber-50 text-amber-700';
    case 'accepted':
    case 'saved':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    case 'rejected_noise':
      return 'border-rose-200 bg-rose-50 text-rose-700';
    case 'snoozed':
      return 'border-sky-200 bg-sky-50 text-sky-700';
    case 'blocked_source':
      return 'border-slate-200 bg-slate-50 text-slate-600';
    default:
      return 'border-[var(--background-modifier-border)] bg-[var(--background-secondary)] text-[var(--text-muted)]';
  }
}

function targetTone(targetType?: string) {
  switch ((targetType || '').toLowerCase()) {
    case 'story':
      return 'border-indigo-200 bg-indigo-50 text-indigo-700';
    case 'post':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    default:
      return 'border-slate-200 bg-slate-50 text-slate-700';
  }
}

function SectionCard({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="app-panel p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text-normal)]">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-[var(--text-muted)]">{subtitle}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

type PreviewRecord = Record<string, unknown>;

function asRecord(value: unknown): PreviewRecord | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as PreviewRecord;
}

function textValue(value: unknown, fallback = '') {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function describeTargetPreview(targetType: string, preview: PreviewRecord | null | undefined) {
  if (!preview) {
    return targetType === 'story' ? 'No story preview available' : 'No preview available';
  }

  if (targetType === 'story') {
    const anchorPost = asRecord(preview.anchor_post);
    return textValue(preview.canonical_title)
      || textValue(preview.title)
      || textValue(anchorPost?.title)
      || textValue(preview.id)
      || 'Untitled story';
  }

  return textValue(preview.title)
    || textValue(preview.display_title)
    || textValue(preview.canonical_title)
    || textValue(preview.source_display_name)
    || textValue(preview.id)
    || 'Untitled post';
}

function previewSubtitle(targetType: string, preview: PreviewRecord | null | undefined) {
  if (!preview) return null;
  if (targetType === 'story') {
    return `${textValue(preview.story_kind, 'story')} • ${textValue(preview.status, 'unknown status')}`;
  }
  return `${textValue(preview.source_display_name) || textValue(preview.source, 'unknown source')} • ${textValue(preview.platform, 'post')}`;
}

export default function AnalystInboxPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const initialBatchId = searchParams.get('batchId') || '';
  const initialItemId = searchParams.get('itemId') || '';
  const initialStatus = searchParams.get('status') || '';
  const initialTargetType = searchParams.get('targetType') || '';
  const initialSourceId = searchParams.get('sourceId') || '';
  const initialGeneratedForDate = searchParams.get('generatedForDate') || '';
  const initialLimit = Number(searchParams.get('limit') || '25');

  const [sources, setSources] = useState<SourceWithSettings[]>([]);
  const [batches, setBatches] = useState<InboxBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState(initialBatchId);
  const [selectedBatchSnapshot, setSelectedBatchSnapshot] = useState<InboxBatch | null>(null);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [selectedItemId, setSelectedItemId] = useState(initialItemId);
  const [selectedItemDetail, setSelectedItemDetail] = useState<InboxItemDetail | null>(null);
  const [selectedItemActions, setSelectedItemActions] = useState<InboxAction[]>([]);
  const [statusFilter, setStatusFilter] = useState(initialStatus);
  const [targetTypeFilter, setTargetTypeFilter] = useState(initialTargetType);
  const [sourceFilter, setSourceFilter] = useState(initialSourceId);
  const [generatedForDate, setGeneratedForDate] = useState(initialGeneratedForDate);
  const [limit, setLimit] = useState(initialLimit > 0 ? initialLimit : 25);
  const [loadingSources, setLoadingSources] = useState(true);
  const [loadingBatches, setLoadingBatches] = useState(true);
  const [loadingItems, setLoadingItems] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [submittingAction, setSubmittingAction] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sideEffects, setSideEffects] = useState<Record<string, unknown>[]>([]);

  const selectedBatch = useMemo(
    () => selectedBatchSnapshot || batches.find((batch) => batch.id === selectedBatchId) || null,
    [batches, selectedBatchId, selectedBatchSnapshot],
  );
  const selectedItem = useMemo(
    () => selectedItemDetail?.item || items.find((item) => item.id === selectedItemId) || null,
    [items, selectedItemDetail, selectedItemId],
  );
  const selectedTarget = (selectedItemDetail?.target || selectedItem?.target_preview || null) as PreviewRecord | null;
  const selectedTargetId = textValue(selectedTarget?.id);
  const selectedTargetUrl = textValue(selectedTarget?.url);
  const selectedAnchorPost = asRecord(selectedTarget?.anchor_post);
  const selectedAnchorPostId = textValue(selectedAnchorPost?.id);
  const selectedActions = selectedItemActions.length ? selectedItemActions : selectedItemDetail?.actions || [];

  const syncSearchParams = (patch: Record<string, string | null | undefined>) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([key, value]) => {
      if (!value) {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    });
    setSearchParams(next, { replace: true });
  };

  const loadSources = async () => {
    setLoadingSources(true);
    setError(null);
    const response = await apiService.getSourcesWithSettings();
    if (!response.success) {
      setError(response.error || 'Failed to load sources');
      setLoadingSources(false);
      return;
    }
    setSources(response.sources || []);
    setLoadingSources(false);
  };

  const loadBatches = async () => {
    setLoadingBatches(true);
    setError(null);
    const response = await apiService.getInboxBatches(50, 0);
    if (!response.success) {
      setError(response.error || 'Failed to load inbox batches');
      setBatches([]);
      setLoadingBatches(false);
      return;
    }

    const nextBatches = response.batches || [];
    setBatches(nextBatches);
    if (!selectedBatchId && nextBatches[0]) {
      setSelectedBatchId(nextBatches[0].id);
      syncSearchParams({ batchId: nextBatches[0].id });
    }
    setLoadingBatches(false);
  };

  const loadBatchItems = async (batchId: string) => {
    if (!batchId) return;
    setLoadingItems(true);
    setError(null);

    const [batchResponse, itemsResponse] = await Promise.all([
      apiService.getInbox(batchId, limit),
      apiService.getInboxItems({
        batchId,
        status: statusFilter.trim() || undefined,
        targetType: targetTypeFilter.trim() || undefined,
        sourceId: sourceFilter.trim() || undefined,
        generatedForDate: generatedForDate.trim() || undefined,
        limit,
        offset: 0,
      }),
    ]);

    if (batchResponse.success) {
      setSelectedBatchSnapshot(batchResponse.batch || null);
    }

    const nextItems = itemsResponse.success ? (itemsResponse.items || batchResponse.items || []) : (batchResponse.items || []);
    setItems(nextItems);
    setLoadingItems(false);

    if (!selectedItemId && nextItems[0]) {
      setSelectedItemId(nextItems[0].id);
      syncSearchParams({ itemId: nextItems[0].id });
    }

    if (!itemsResponse.success && itemsResponse.error) {
      setError(itemsResponse.error);
    }
  };

  const loadItemDetail = async (itemId: string) => {
    if (!itemId) {
      setSelectedItemDetail(null);
      setSelectedItemActions([]);
      setSideEffects([]);
      return;
    }

    setError(null);
    setLoadingDetail(true);
    const [detailResponse, actionsResponse] = await Promise.all([
      apiService.getInboxItem(itemId),
      apiService.getInboxActions({ inboxItemId: itemId, limit: 20 }),
    ]);

    if (!detailResponse.success || !detailResponse.item) {
      setSelectedItemDetail(null);
      setSelectedItemActions([]);
      setLoadingDetail(false);
      setError(detailResponse.error || 'Failed to load inbox item');
      return;
    }

    setSelectedItemDetail(detailResponse);
    setSelectedItemActions(actionsResponse.actions || detailResponse.actions || []);
    setSideEffects([]);

    const detailItem = detailResponse.item;
    if (!selectedBatchId && detailItem.batch_id) {
      setSelectedBatchId(detailItem.batch_id);
      syncSearchParams({ batchId: detailItem.batch_id });
    }

    setLoadingDetail(false);
  };

  useEffect(() => {
    void loadSources();
    void loadBatches();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedBatchId) return;
    void loadBatchItems(selectedBatchId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBatchId, statusFilter, targetTypeFilter, sourceFilter, generatedForDate, limit]);

  useEffect(() => {
    if (!selectedItemId) return;
    void loadItemDetail(selectedItemId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedItemId]);

  const selectBatch = (batchId: string) => {
    setSelectedBatchId(batchId);
    setSelectedItemId('');
    setSelectedItemDetail(null);
    setSelectedItemActions([]);
    syncSearchParams({ batchId, itemId: null });
  };

  const selectItem = (itemId: string) => {
    setSelectedItemId(itemId);
    syncSearchParams({ itemId });
  };

  const refreshAll = async () => {
    await Promise.all([loadSources(), loadBatches()]);
    if (selectedBatchId) {
      await loadBatchItems(selectedBatchId);
    }
    if (selectedItemId) {
      await loadItemDetail(selectedItemId);
    }
  };

  const applyRebuild = async () => {
    setRebuilding(true);
    const response = await apiService.rebuildInbox({
      generatedForDate: generatedForDate.trim() || selectedBatch?.generated_for_date || undefined,
      scopeType: selectedBatch?.scope_type,
      scopeValue: selectedBatch?.scope_value || undefined,
      limit,
      actorId: 'frontend',
    });
    if (!response.success) {
      setError(response.error || 'Failed to rebuild inbox');
      setRebuilding(false);
      return;
    }

    setRebuilding(false);
    await refreshAll();
  };

  const submitAction = async (actionType: string) => {
    if (!selectedItemId) return;
    setSubmittingAction(actionType);
    const response = await apiService.recordInboxAction(selectedItemId, {
      actionType,
      actorId: 'frontend',
    });
    setSubmittingAction(null);

    if (!response.success) {
      setError(response.error || 'Failed to record action');
      return;
    }

    setSideEffects(response.side_effects || []);
    if (response.item) {
      setSelectedItemDetail({
        success: true,
        item: response.item,
        target: selectedItemDetail?.target || selectedTarget,
        actions: selectedActions,
      });
    }

    await Promise.all([
      selectedBatchId ? loadBatchItems(selectedBatchId) : Promise.resolve(),
      loadItemDetail(selectedItemId),
      loadBatches(),
    ]);
  };

  const sourceLabel = (sourceId?: string | null) => {
    if (!sourceId) return 'All sources';
    return sources.find((source) => source.id === sourceId)?.settings?.display_name
      || sources.find((source) => source.id === sourceId)?.handle_or_url
      || sourceId;
  };

  const itemTargetTitle = describeTargetPreview(selectedItem?.target_type || '', selectedTarget);
  const itemTargetSubtitle = previewSubtitle(selectedItem?.target_type || '', selectedTarget);

  return (
    <div className="app-shell min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="app-panel overflow-hidden">
          <div className="grid gap-0 lg:grid-cols-[1.12fr_0.88fr]">
            <div className="relative p-6 sm:p-8 lg:p-10">
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(76,141,255,0.16),transparent_42%),radial-gradient(circle_at_bottom_left,rgba(29,78,216,0.10),transparent_34%)]" />
              <div className="relative space-y-5">
                <button
                  type="button"
                  onClick={() => navigate('/')}
                  className="inline-flex items-center gap-2 text-sm text-[var(--text-muted)] transition hover:text-[var(--text-normal)]"
                >
                  <ArrowLeft className="h-4 w-4" />
                  Back to hub
                </button>
                <div className="inline-flex rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[var(--text-faint)]">
                  Analyst Inbox
                </div>
                <div className="space-y-3">
                  <h1 className="text-3xl font-bold tracking-tight text-[var(--text-normal)] sm:text-4xl">
                    Triage generated candidates without leaving the browser.
                  </h1>
                  <p className="max-w-2xl text-sm leading-7 text-[var(--text-muted)] sm:text-base">
                    Browse batches, filter items, inspect reasons, and record durable analyst actions. Every row here comes from the backend inbox pipeline you already built.
                  </p>
                </div>
                <div className="flex flex-wrap gap-3">
                  <button type="button" onClick={applyRebuild} className="app-inline-button app-inline-button--primary">
                    <Sparkles className="h-4 w-4" />
                    Rebuild Inbox
                  </button>
                  <button type="button" onClick={() => void refreshAll()} className="app-inline-button">
                    <RefreshCw className={`h-4 w-4 ${(loadingSources || loadingBatches || loadingItems) ? 'animate-spin' : ''}`} />
                    Refresh View
                  </button>
                  <Link to="/stories" className="app-inline-button">
                    <CheckCircle2 className="h-4 w-4" />
                    Open Stories
                  </Link>
                </div>
              </div>
            </div>

            <div className="border-t border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-6 lg:border-l lg:border-t-0">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-faint)]">Current batch</div>
                  <div className="mt-2 text-lg font-semibold text-[var(--text-normal)]">
                    {selectedBatch?.scope_type || 'No batch selected'}
                  </div>
                  <div className="mt-1 text-sm text-[var(--text-muted)]">
                    {selectedBatch?.generated_for_date ? formatShortDate(selectedBatch.generated_for_date) : 'Choose a batch from the list'}
                  </div>
                </div>
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-faint)]">Current item</div>
                  <div className="mt-2 text-lg font-semibold text-[var(--text-normal)]">
                    {selectedItem ? `${selectedItem.target_type} • ${selectedItem.status}` : 'No item selected'}
                  </div>
                  <div className="mt-1 text-sm text-[var(--text-muted)]">
                    {selectedItem ? formatDate(selectedItem.surfaced_at) : 'Pick an item to inspect its reasons and action history.'}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </header>

        {error && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
          </div>
        )}

        <section className="app-panel p-5">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
            <div className="grid gap-3 md:grid-cols-5">
              <label className="space-y-2 text-sm">
                <span className="text-[var(--text-muted)]">Status</span>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="workspace-editor py-3 font-sans"
                >
                  <option value="">All statuses</option>
                  <option value="pending">pending</option>
                  <option value="accepted">accepted</option>
                  <option value="saved">saved</option>
                  <option value="rejected_noise">rejected_noise</option>
                  <option value="snoozed">snoozed</option>
                  <option value="blocked_source">blocked_source</option>
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span className="text-[var(--text-muted)]">Target</span>
                <select
                  value={targetTypeFilter}
                  onChange={(e) => setTargetTypeFilter(e.target.value)}
                  className="workspace-editor py-3 font-sans"
                >
                  <option value="">All targets</option>
                  <option value="post">post</option>
                  <option value="story">story</option>
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span className="text-[var(--text-muted)]">Source</span>
                <select
                  value={sourceFilter}
                  onChange={(e) => setSourceFilter(e.target.value)}
                  className="workspace-editor py-3 font-sans"
                  disabled={loadingSources}
                >
                  <option value="">All sources</option>
                  {sources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.settings?.display_name || source.handle_or_url || source.id}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span className="text-[var(--text-muted)]">Generated for date</span>
                <input
                  type="date"
                  value={generatedForDate}
                  onChange={(e) => setGeneratedForDate(e.target.value)}
                  className="workspace-editor py-3 font-sans"
                />
              </label>
              <label className="space-y-2 text-sm">
                <span className="text-[var(--text-muted)]">Limit</span>
                <input
                  type="number"
                  min={5}
                  max={200}
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value) || 25)}
                  className="workspace-editor py-3 font-sans"
                />
              </label>
            </div>

            <div className="flex flex-wrap items-end justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                  {batches.length} batches
                </span>
                <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                  {items.length} items
                </span>
                <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                  source {sourceLabel(sourceFilter)}
                </span>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => void refreshAll()} className="app-inline-button">
                  <Loader2 className={`h-4 w-4 ${loadingSources || loadingBatches || loadingItems ? 'animate-spin' : ''}`} />
                  Reload
                </button>
                <button type="button" onClick={applyRebuild} className="app-inline-button app-inline-button--primary">
                  <Ban className={`h-4 w-4 ${rebuilding ? 'animate-spin' : ''}`} />
                  Rebuild
                </button>
              </div>
            </div>
          </div>
        </section>

        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="space-y-6">
            <SectionCard
              title="Batches"
              subtitle={loadingBatches ? 'Loading batches...' : 'Latest queue snapshots from the backend.'}
              actions={loadingBatches ? <Loader2 className="h-4 w-4 animate-spin text-[var(--text-faint)]" /> : null}
            >
              <div className="max-h-[40rem] space-y-2 overflow-y-auto pr-1">
                {batches.length ? batches.map((batch) => {
                  const isSelected = batch.id === selectedBatchId;
                  return (
                    <button
                      key={batch.id}
                      type="button"
                      onClick={() => selectBatch(batch.id)}
                      className={`block w-full rounded-2xl border p-4 text-left transition ${
                        isSelected
                          ? 'border-[var(--accent-strong)] bg-[var(--text-highlight-bg)] shadow-[0_14px_30px_rgba(76,141,255,0.12)]'
                          : 'border-[var(--background-modifier-border)] bg-[var(--background-primary)] hover:border-[var(--accent-strong)] hover:bg-[var(--background-primary-alt)]'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-[var(--text-normal)]">{batch.scope_type}</div>
                          <div className="mt-1 text-xs text-[var(--text-muted)]">
                            {batch.generated_for_date ? formatShortDate(batch.generated_for_date) : 'No date'}
                          </div>
                        </div>
                        <Clock3 className="h-4 w-4 text-[var(--text-faint)]" />
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-[var(--text-muted)]">
                        <span>{batch.item_count || 0} items</span>
                        <span>{batch.pending_count || 0} pending</span>
                        <span>{batch.acted_count || 0} acted</span>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <span className={`rounded-full border px-2 py-0.5 text-xs ${statusTone(batch.status)}`}>
                          {batch.status || 'unknown'}
                        </span>
                      </div>
                    </button>
                  );
                }) : (
                  <div className="rounded-2xl border border-dashed border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4 text-sm text-[var(--text-muted)]">
                    {loadingBatches ? 'Loading batches...' : 'No inbox batches have been generated yet.'}
                  </div>
                )}
              </div>
            </SectionCard>

            <SectionCard
              title="Source filters"
              subtitle="Quick reference for the source selector."
              actions={loadingSources ? <Loader2 className="h-4 w-4 animate-spin text-[var(--text-faint)]" /> : null}
            >
              <div className="space-y-2">
                <div className="text-sm text-[var(--text-muted)]">
                  {sourceFilter ? `Filtering to ${sourceLabel(sourceFilter)}.` : 'Showing items across all sources.'}
                </div>
                <div className="text-xs text-[var(--text-faint)]">
                  The item list updates immediately when you change the source, status, target, or date filters.
                </div>
              </div>
            </SectionCard>
          </aside>

          <main className="space-y-6">
            <SectionCard
              title={selectedBatch ? `Batch ${selectedBatch.scope_type}` : 'Current batch'}
              subtitle={selectedBatch ? `${selectedBatch.item_count || 0} candidate(s) in the current snapshot.` : 'Select a batch from the sidebar.'}
              actions={loadingItems ? <Loader2 className="h-4 w-4 animate-spin text-[var(--text-faint)]" /> : null}
            >
              {selectedBatch ? (
                <div className="grid gap-3 md:grid-cols-4">
                  <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Scope</div>
                    <div className="mt-2 text-sm font-semibold text-[var(--text-normal)]">{selectedBatch.scope_type}</div>
                    <div className="mt-1 text-xs text-[var(--text-muted)]">{selectedBatch.scope_value || 'no scope value'}</div>
                  </div>
                  <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Generated for</div>
                    <div className="mt-2 text-sm font-semibold text-[var(--text-normal)]">
                      {selectedBatch.generated_for_date ? formatShortDate(selectedBatch.generated_for_date) : 'N/A'}
                    </div>
                    <div className="mt-1 text-xs text-[var(--text-muted)]">Batch {selectedBatch.id.slice(0, 8)}</div>
                  </div>
                  <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Pending</div>
                    <div className="mt-2 text-3xl font-bold text-[var(--text-normal)]">{selectedBatch.pending_count || 0}</div>
                  </div>
                  <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Acted</div>
                    <div className="mt-2 text-3xl font-bold text-[var(--text-normal)]">{selectedBatch.acted_count || 0}</div>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-[var(--text-muted)]">Choose a batch to load its items.</div>
              )}
            </SectionCard>

            <SectionCard
              title={`Inbox items (${items.length})`}
              subtitle={loadingItems ? 'Loading filtered queue items...' : 'Select an item to inspect the target preview and action history.'}
            >
              <div className="space-y-3">
                {items.length ? items.map((item) => {
                  const isSelected = item.id === selectedItemId;
                  const preview = item.target_preview || null;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => selectItem(item.id)}
                      className={`block w-full rounded-2xl border p-4 text-left transition ${
                        isSelected
                          ? 'border-[var(--accent-strong)] bg-[var(--text-highlight-bg)] shadow-[0_14px_30px_rgba(76,141,255,0.12)]'
                          : 'border-[var(--background-modifier-border)] bg-[var(--background-primary)] hover:border-[var(--accent-strong)] hover:bg-[var(--background-primary-alt)]'
                      }`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`rounded-full border px-2 py-0.5 text-xs ${targetTone(item.target_type)}`}>
                              {item.target_type}
                            </span>
                            <span className={`rounded-full border px-2 py-0.5 text-xs ${statusTone(item.status)}`}>
                              {item.status}
                            </span>
                          </div>
                          <div className="mt-2 text-sm font-semibold text-[var(--text-normal)]">
                            {describeTargetPreview(item.target_type, preview)}
                          </div>
                          {previewSubtitle(item.target_type, preview) && (
                            <div className="mt-1 text-xs text-[var(--text-muted)]">
                              {previewSubtitle(item.target_type, preview)}
                            </div>
                          )}
                        </div>
                        <div className="flex flex-col items-end gap-1 text-xs text-[var(--text-faint)]">
                          <span>{formatScore(item.priority_score)}</span>
                          <span>{formatDate(item.surfaced_at)}</span>
                        </div>
                      </div>

                      <div className="mt-3 grid gap-2 md:grid-cols-4">
                        <div className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-2 text-xs text-[var(--text-muted)]">
                          priority {formatScore(item.priority_score)}
                        </div>
                        <div className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-2 text-xs text-[var(--text-muted)]">
                          novelty {percent(item.novelty_score)}
                        </div>
                        <div className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-2 text-xs text-[var(--text-muted)]">
                          evidence {percent(item.evidence_score)}
                        </div>
                        <div className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-2 text-xs text-[var(--text-muted)]">
                          penalty {percent(item.duplication_penalty)}
                        </div>
                      </div>

                      {item.reason_summary && (
                        <div className="mt-3 text-sm leading-6 text-[var(--text-muted)]">
                          {item.reason_summary}
                        </div>
                      )}

                      {item.reasons?.length ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {item.reasons.slice(0, 3).map((reason, index) => (
                            <span
                              key={`${item.id}-${reason.code || index}`}
                              className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-2 py-0.5 text-xs text-[var(--text-muted)]"
                            >
                              {reason.label}: {reason.detail}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </button>
                  );
                }) : (
                  <div className="rounded-2xl border border-dashed border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4 text-sm text-[var(--text-muted)]">
                    {loadingItems ? 'Loading items...' : 'No items matched the current filters.'}
                  </div>
                )}
              </div>
            </SectionCard>

            <SectionCard
              title={itemTargetTitle}
              subtitle={itemTargetSubtitle || 'Inspect the selected item and decide what to do with it.'}
              actions={
                selectedItem ? (
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void submitAction('accept')}
                      disabled={submittingAction !== null}
                      className="app-inline-button app-inline-button--primary"
                    >
                      {submittingAction === 'accept' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ThumbsUp className="h-4 w-4" />}
                      Accept
                    </button>
                    <button
                      type="button"
                      onClick={() => void submitAction('save')}
                      disabled={submittingAction !== null}
                      className="app-inline-button"
                    >
                      {submittingAction === 'save' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => void submitAction('snooze')}
                      disabled={submittingAction !== null}
                      className="app-inline-button"
                    >
                      {submittingAction === 'snooze' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Clock3 className="h-4 w-4" />}
                      Snooze
                    </button>
                    <button
                      type="button"
                      onClick={() => void submitAction('reject_noise')}
                      disabled={submittingAction !== null}
                      className="app-inline-button"
                    >
                      {submittingAction === 'reject_noise' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ThumbsDown className="h-4 w-4" />}
                      Reject noise
                    </button>
                    <button
                      type="button"
                      onClick={() => void submitAction('block_source')}
                      disabled={submittingAction !== null}
                      className="app-inline-button"
                    >
                      {submittingAction === 'block_source' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />}
                      Block source
                    </button>
                  </div>
                ) : null
              }
            >
              {selectedItem ? (
                <div className="space-y-5">
                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Target type</div>
                      <div className="mt-2 text-sm font-semibold text-[var(--text-normal)]">{selectedItem.target_type}</div>
                      <div className="mt-1 text-xs text-[var(--text-muted)]">{selectedItem.target_id}</div>
                    </div>
                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Target status</div>
                      <div className="mt-2 text-sm font-semibold text-[var(--text-normal)]">{selectedItem.status}</div>
                      <div className="mt-1 text-xs text-[var(--text-muted)]">Surfaced {formatDate(selectedItem.surfaced_at)}</div>
                    </div>
                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Batch</div>
                      <div className="mt-2 text-sm font-semibold text-[var(--text-normal)]">{selectedItem.batch_scope_type || selectedItem.batch_id}</div>
                      <div className="mt-1 text-xs text-[var(--text-muted)]">{selectedItem.batch_generated_for_date || 'No generated date'}</div>
                    </div>
                  </div>

                  <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Target preview</div>
                      <div className="mt-2 text-xl font-semibold text-[var(--text-normal)]">
                        {itemTargetTitle}
                      </div>
                      {itemTargetSubtitle && (
                        <div className="mt-1 text-sm text-[var(--text-muted)]">
                          {itemTargetSubtitle}
                        </div>
                      )}
                      <div className="mt-4 flex flex-wrap gap-2">
                        {selectedTargetId && selectedItem.target_type === 'post' && (
                          <Link to={`/posts/${encodeURIComponent(selectedTargetId)}`} className="app-inline-button">
                            Open post
                          </Link>
                        )}
                        {selectedAnchorPostId && (
                          <Link to={`/posts/${encodeURIComponent(selectedAnchorPostId)}`} className="app-inline-button">
                            Open anchor post
                          </Link>
                        )}
                        {selectedTargetUrl && (
                          <a href={selectedTargetUrl} target="_blank" rel="noreferrer" className="app-inline-button">
                            Open original
                          </a>
                        )}
                      </div>
                      {selectedItem.reason_summary && (
                        <div className="mt-4 rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4 text-sm leading-7 text-[var(--text-normal)]">
                          {selectedItem.reason_summary}
                        </div>
                      )}
                    </div>

                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Scores and reasons</div>
                      <div className="mt-3 grid gap-2 md:grid-cols-2">
                        <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm text-[var(--text-muted)]">
                          priority {formatScore(selectedItem.priority_score)}
                        </div>
                        <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm text-[var(--text-muted)]">
                          novelty {percent(selectedItem.novelty_score)}
                        </div>
                        <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm text-[var(--text-muted)]">
                          evidence {percent(selectedItem.evidence_score)}
                        </div>
                        <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm text-[var(--text-muted)]">
                          source priority {percent(selectedItem.source_priority_score)}
                        </div>
                      </div>
                      <div className="mt-4 space-y-2">
                        {(selectedItem.reasons || []).length ? (selectedItem.reasons || []).map((reason, index) => (
                          <div key={`${selectedItem.id}-${reason.code || index}`} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium text-[var(--text-normal)]">{reason.label}</span>
                              <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
                                weight {formatScore(reason.weight, 2)}
                              </span>
                            </div>
                            <div className="mt-1 text-sm text-[var(--text-muted)]">{reason.detail}</div>
                          </div>
                        )) : (
                          <div className="text-sm text-[var(--text-muted)]">No explicit reasons were stored with this item.</div>
                        )}
                      </div>
                    </div>
                  </div>

                  {sideEffects.length ? (
                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Last action side effects</div>
                      <div className="mt-3 space-y-2">
                        {sideEffects.map((effect, index) => (
                          <div key={`${selectedItem.id}-effect-${index}`} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm text-[var(--text-normal)]">
                            {JSON.stringify(effect)}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Target metadata</div>
                      <pre className="mt-3 max-h-[20rem] overflow-auto rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4 text-xs text-[var(--text-normal)]">
                        {JSON.stringify(selectedTarget || selectedItem.target_preview || {}, null, 2)}
                      </pre>
                    </div>

                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Action history</div>
                      <div className="mt-3 space-y-2">
                        {selectedActions.length ? selectedActions.map((action) => (
                          <div key={action.id} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium text-[var(--text-normal)]">{action.action_type}</span>
                              <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
                                {action.actor_id || action.created_by || 'analyst'}
                              </span>
                            </div>
                            <div className="mt-1 text-xs text-[var(--text-faint)]">{formatDate(action.created_at)}</div>
                            {action.payload && (
                              <pre className="mt-2 max-h-[10rem] overflow-auto rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-2 text-[11px] text-[var(--text-muted)]">
                                {JSON.stringify(action.payload, null, 2)}
                              </pre>
                            )}
                          </div>
                        )) : (
                          <div className="text-sm text-[var(--text-muted)]">No action history found for this item yet.</div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ) : loadingDetail ? (
                <div className="flex items-center gap-2 py-8 text-sm text-[var(--text-muted)]">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading inbox item...
                </div>
              ) : (
                <div className="text-sm text-[var(--text-muted)]">
                  Select an item from the list to see its target preview, ranking reasons, and action history.
                </div>
              )}
            </SectionCard>
          </main>
        </div>
      </div>
    </div>
  );
}
