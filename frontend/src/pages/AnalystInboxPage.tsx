import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { Button, ExternalLink, Input, PageHeader, Page, Select, TextLink } from '../components/ui';
import { EmptyState, ErrorState, LoadingState, Notice } from '../components/states';
import DevDataSwitch from '../components/ops/DevDataSwitch';
import { MetaList, Section, SelectRow, StateWord } from '../components/analysis/parts';
import { dateTime, humanize, percent, shortDate } from '../components/analysis/format';
import { useDevFixtureApi } from '../components/analysis/useDevFixtureApi';
import { formatRelativeTime } from '../lib/dates';
import { formatCount, middleTruncate, plural } from '../lib/format';
import type { InboxAction, InboxBatch, InboxItem, InboxItemDetail, SourceWithSettings } from '../services/api';
import type { Status } from '../components/ui/styles';
import { INBOX_FIXTURE_NAMES, inboxFixtureApi } from './AnalystInboxPage.fixtures';

/**
 * Inbox (design docs parked/inbox.md): triage of generated candidates. The batch is a filter
 * like the others, so the page is the same master/detail as Stories: a ranked
 * list of candidates on the left, the selected one on the right with its scores,
 * reasons, the triage actions and the action history.
 */

const STATUS_OPTIONS = ['pending', 'accepted', 'saved', 'snoozed', 'rejected_noise', 'blocked_source'] as const;

const STATUS_GLYPH: Record<string, Status> = {
  pending: 'due',
  accepted: 'ok',
  saved: 'starred',
  snoozed: 'scheduled',
  rejected_noise: 'disabled',
  blocked_source: 'unavailable',
  ready: 'ok',
  done: 'read',
};

const ACTIONS: Array<{ type: string; label: string; done: string }> = [
  { type: 'accept', label: 'Accept', done: 'accepted' },
  { type: 'save', label: 'Save', done: 'saved' },
  { type: 'snooze', label: 'Snooze', done: 'snoozed' },
  { type: 'reject_noise', label: 'Reject as noise', done: 'rejected as noise' },
  { type: 'block_source', label: 'Block source', done: 'source blocked' },
];

function ItemStatus({ status, strong }: { status?: string | null; strong?: boolean }) {
  if (!status) return null;
  const key = status.toLowerCase();
  return <StateWord glyph={STATUS_GLYPH[key] ?? 'scheduled'} word={humanize(status)} strong={strong ?? key === 'pending'} />;
}

type PreviewRecord = Record<string, unknown>;

function asRecord(value: unknown): PreviewRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as PreviewRecord) : null;
}

function textValue(value: unknown, fallback = '') {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function describeTargetPreview(targetType: string, preview: PreviewRecord | null | undefined) {
  if (!preview) return targetType === 'story' ? 'Story without a preview' : 'Post without a preview';
  if (targetType === 'story') {
    const anchorPost = asRecord(preview.anchor_post);
    return textValue(preview.canonical_title) || textValue(preview.title) || textValue(anchorPost?.title) || textValue(preview.id) || 'Untitled story';
  }
  return (
    textValue(preview.title) ||
    textValue(preview.display_title) ||
    textValue(preview.canonical_title) ||
    textValue(preview.source_display_name) ||
    textValue(preview.id) ||
    'Untitled post'
  );
}

function previewSource(targetType: string, preview: PreviewRecord | null | undefined): string | null {
  if (!preview) return null;
  if (targetType === 'story') return humanize(textValue(preview.story_kind, 'story'));
  const source = textValue(preview.source_display_name) || textValue(preview.source);
  const platform = textValue(preview.platform);
  return [source, platform].filter(Boolean).join(' · ') || null;
}

function score(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return new Intl.NumberFormat('en', { maximumFractionDigits: 1, minimumFractionDigits: 1 }).format(Number(value));
}

function batchLabel(batch: InboxBatch): string {
  const pending = batch.pending_count ?? 0;
  return `${shortDate(batch.generated_for_date)} · ${humanize(batch.scope_type)} · ${formatCount(pending)} pending`;
}

function FilterField({ label, htmlFor, children, className }: { label: string; htmlFor: string; children: ReactNode; className?: string }) {
  return (
    <div className={`min-w-0 space-y-1 ${className ?? ''}`}>
      <label htmlFor={htmlFor} className="block text-[0.75rem] font-medium text-fg-3">
        {label}
      </label>
      {children}
    </div>
  );
}

function ItemDetail({
  item,
  target,
  actions,
  submitting,
  lastAction,
  onAction,
}: {
  item: InboxItem;
  target: PreviewRecord | null;
  actions: InboxAction[];
  submitting: string | null;
  lastAction: { label: string; sideEffects: Record<string, unknown>[] } | null;
  onAction: (type: string) => void;
}) {
  const title = describeTargetPreview(item.target_type, target);
  const source = previewSource(item.target_type, target);
  const targetId = textValue(target?.id);
  const targetUrl = textValue(target?.url);
  const anchorPostId = textValue(asRecord(target?.anchor_post)?.id);
  const reasons = (item.reasons || []) as Array<Record<string, unknown>>;

  return (
    <article aria-labelledby="inbox-item-title" className="min-w-0 space-y-8">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem] text-fg-2">
          <span>{humanize(item.target_type)}</span>
          <ItemStatus status={item.status} />
        </div>
        <h2 id="inbox-item-title" dir="auto" className="break-words text-[1.375rem] font-semibold leading-[1.25] tracking-[-0.02em] text-fg [overflow-wrap:anywhere]">
          {title}
        </h2>
        <p className="text-[0.8125rem] tabular-nums text-fg-2">
          {source ? <span title={source}>{middleTruncate(source, 64)} · </span> : null}
          surfaced {formatRelativeTime(item.surfaced_at)} · priority {score(item.priority_score)}
        </p>
        {targetId || anchorPostId || targetUrl ? (
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
            {targetId && item.target_type === 'post' ? <TextLink to={`/posts/${encodeURIComponent(targetId)}`}>Open post</TextLink> : null}
            {anchorPostId ? <TextLink to={`/posts/${encodeURIComponent(anchorPostId)}`}>Open anchor post</TextLink> : null}
            {targetUrl ? <ExternalLink href={targetUrl} title={targetUrl}>Original ↗</ExternalLink> : null}
          </p>
        ) : null}
      </header>

      <div role="group" aria-label="Triage" className="flex flex-wrap gap-2">
        {ACTIONS.map((action, index) => (
          <Button
            key={action.type}
            size="sm"
            variant={index === 0 ? 'primary' : 'secondary'}
            onClick={() => onAction(action.type)}
            disabled={submitting !== null}
            aria-busy={submitting === action.type || undefined}
          >
            {submitting === action.type ? `${action.label}…` : action.label}
          </Button>
        ))}
      </div>

      {lastAction ? (
        <Notice tone="completion" title={`Recorded: ${lastAction.label}`} message={lastAction.sideEffects.length ? `${plural(lastAction.sideEffects.length, 'side effect')}` : undefined}>
          {lastAction.sideEffects.length ? (
            <ul className="mt-2 space-y-1 font-mono text-[0.75rem] text-fg-2">
              {lastAction.sideEffects.map((effect, index) => (
                <li key={index} className="break-words [overflow-wrap:anywhere]">{JSON.stringify(effect)}</li>
              ))}
            </ul>
          ) : null}
        </Notice>
      ) : null}

      {item.reason_summary ? <p className="max-w-[68ch] break-words text-[0.9375rem] leading-[1.6] text-fg [overflow-wrap:anywhere]">{item.reason_summary}</p> : null}

      <Section title="Scores" id="inbox-scores">
        <MetaList
          items={[
            ['Priority', score(item.priority_score)],
            ['Novelty', percent(item.novelty_score)],
            ['Evidence', percent(item.evidence_score)],
            ['Source priority', percent(item.source_priority_score)],
            ['Duplication penalty', percent(item.duplication_penalty)],
          ]}
        />
      </Section>

      <Section title="Reasons" meta={reasons.length || undefined} id="inbox-reasons">
        {reasons.length ? (
          <ul className="divide-y divide-line rounded-md border border-line">
            {reasons.map((reason, index) => (
              <li key={`${textValue(reason.code) || index}`} className="flex min-w-0 items-start gap-4 px-3 py-2.5 text-[0.8125rem]">
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-fg">{textValue(reason.label, 'Reason')}</span>
                  {textValue(reason.detail) ? (
                    <span className="mt-0.5 block break-words text-fg-2 [overflow-wrap:anywhere]">{textValue(reason.detail)}</span>
                  ) : null}
                </span>
                <span className="shrink-0 whitespace-nowrap tabular-nums text-fg-3">
                  weight {typeof reason.weight === 'number' ? reason.weight.toFixed(2) : '—'}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[0.875rem] text-fg-3">No reasons were stored with this item.</p>
        )}
      </Section>

      <Section title="History" meta={actions.length || undefined} id="inbox-history">
        {actions.length ? (
          <ol className="divide-y divide-line rounded-md border border-line">
            {actions.map((action) => {
              const actor = action.actor_id || action.created_by || 'analyst';
              return (
                <li key={action.id} className="flex min-w-0 items-start gap-4 px-3 py-2.5 text-[0.8125rem]">
                  <span className="w-[5.5rem] shrink-0 whitespace-nowrap tabular-nums text-fg-3" title={dateTime(action.created_at)}>
                    {shortDate(action.created_at)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="font-medium text-fg">{humanize(action.action_type)}</span>
                    <span className="text-fg-2" title={actor}> · {middleTruncate(actor, 40)}</span>
                    {action.payload && Object.keys(action.payload).length ? (
                      <span className="mt-0.5 block break-words font-mono text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">{JSON.stringify(action.payload)}</span>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="text-[0.875rem] text-fg-3">No actions recorded for this item yet.</p>
        )}
      </Section>

      <details className="group rounded-md border border-line">
        <summary className="cursor-pointer list-none rounded-md px-3 py-2.5 text-[0.8125rem] text-fg-2 hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg [&::-webkit-details-marker]:hidden">
          <span className="group-open:hidden">Show raw target data</span>
          <span className="hidden group-open:inline">Hide raw target data</span>
        </summary>
        <pre className="max-h-[20rem] overflow-auto border-t border-line px-3 py-3 font-mono text-[0.75rem] leading-[1.5] text-fg-2">
          {JSON.stringify(target || item.target_preview || {}, null, 2)}
        </pre>
      </details>
    </article>
  );
}

export default function AnalystInboxPage() {
  const { api } = useDevFixtureApi(inboxFixtureApi);
  const [searchParams, setSearchParams] = useSearchParams();
  const detailRef = useRef<HTMLDivElement>(null);

  const initialLimit = Number(searchParams.get('limit') || '25');
  const [sources, setSources] = useState<SourceWithSettings[]>([]);
  const [batches, setBatches] = useState<InboxBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState(searchParams.get('batchId') || '');
  const [batchSnapshot, setBatchSnapshot] = useState<InboxBatch | null>(null);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [selectedItemId, setSelectedItemId] = useState(searchParams.get('itemId') || '');
  const [itemDetail, setItemDetail] = useState<InboxItemDetail | null>(null);
  const [itemActions, setItemActions] = useState<InboxAction[]>([]);
  const [statusFilter, setStatusFilter] = useState(searchParams.get('status') || '');
  const [targetTypeFilter, setTargetTypeFilter] = useState(searchParams.get('targetType') || '');
  const [sourceFilter, setSourceFilter] = useState(searchParams.get('sourceId') || '');
  const [generatedForDate, setGeneratedForDate] = useState(searchParams.get('generatedForDate') || '');
  const [limit, setLimit] = useState(initialLimit > 0 ? initialLimit : 25);
  const [loadingBatches, setLoadingBatches] = useState(true);
  const [batchesError, setBatchesError] = useState<string | null>(null);
  const [loadingItems, setLoadingItems] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastAction, setLastAction] = useState<{ label: string; sideEffects: Record<string, unknown>[] } | null>(null);

  const selectedRefs = useRef({ batch: selectedBatchId, item: selectedItemId });
  selectedRefs.current = { batch: selectedBatchId, item: selectedItemId };

  const syncSearchParams = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          Object.entries(patch).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)));
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const selectedBatch = useMemo(
    () => batchSnapshot || batches.find((b) => b.id === selectedBatchId) || null,
    [batches, selectedBatchId, batchSnapshot],
  );
  const selectedItem = itemDetail?.item || items.find((i) => i.id === selectedItemId) || null;
  const selectedTarget = (itemDetail?.target || selectedItem?.target_preview || null) as PreviewRecord | null;
  const selectedActions = itemActions.length ? itemActions : itemDetail?.actions || [];

  const loadSources = useCallback(async () => {
    const response = await api.getSourcesWithSettings();
    if (response.success) setSources(response.sources || []);
  }, [api]);

  const loadBatches = useCallback(async () => {
    setLoadingBatches(true);
    setBatchesError(null);
    const response = await api.getInboxBatches(50, 0);
    if (!response.success) {
      setBatches([]);
      setBatchesError(response.error || 'Failed to load inbox batches');
      setLoadingBatches(false);
      return;
    }
    const next = response.batches || [];
    setBatches(next);
    if (!selectedRefs.current.batch && next[0]) {
      setSelectedBatchId(next[0].id);
      syncSearchParams({ batchId: next[0].id });
    }
    setLoadingBatches(false);
  }, [api, syncSearchParams]);

  const loadBatchItems = useCallback(
    async (batchId: string) => {
      if (!batchId) return;
      setLoadingItems(true);
      setError(null);
      const [batchResponse, itemsResponse] = await Promise.all([
        api.getInbox(batchId, limit),
        api.getInboxItems({
          batchId,
          status: statusFilter || undefined,
          targetType: targetTypeFilter || undefined,
          sourceId: sourceFilter || undefined,
          generatedForDate: generatedForDate || undefined,
          limit,
          offset: 0,
        }),
      ]);
      if (batchResponse.success) setBatchSnapshot(batchResponse.batch || null);
      const next = itemsResponse.success ? itemsResponse.items || batchResponse.items || [] : batchResponse.items || [];
      setItems(next);
      setLoadingItems(false);
      if (!selectedRefs.current.item && next[0]) {
        setSelectedItemId(next[0].id);
        syncSearchParams({ itemId: next[0].id });
      }
      if (!itemsResponse.success && itemsResponse.error) setError(itemsResponse.error);
    },
    [api, limit, statusFilter, targetTypeFilter, sourceFilter, generatedForDate, syncSearchParams],
  );

  const loadItemDetail = useCallback(
    async (itemId: string) => {
      setError(null);
      setLoadingDetail(true);
      const [detailResponse, actionsResponse] = await Promise.all([
        api.getInboxItem(itemId),
        api.getInboxActions({ inboxItemId: itemId, limit: 20 }),
      ]);
      if (!detailResponse.success || !detailResponse.item) {
        setItemDetail(null);
        setItemActions([]);
        setLoadingDetail(false);
        setError(detailResponse.error || 'Failed to load the inbox item');
        return;
      }
      setItemDetail(detailResponse);
      setItemActions(actionsResponse.actions || detailResponse.actions || []);
      if (!selectedRefs.current.batch && detailResponse.item.batch_id) {
        setSelectedBatchId(detailResponse.item.batch_id);
        syncSearchParams({ batchId: detailResponse.item.batch_id });
      }
      setLoadingDetail(false);
    },
    [api, syncSearchParams],
  );

  useEffect(() => {
    void loadSources();
    void loadBatches();
  }, [loadSources, loadBatches]);

  useEffect(() => {
    if (selectedBatchId) void loadBatchItems(selectedBatchId);
  }, [selectedBatchId, loadBatchItems]);

  useEffect(() => {
    if (!selectedItemId) {
      setItemDetail(null);
      setItemActions([]);
      return;
    }
    setLastAction(null);
    void loadItemDetail(selectedItemId);
  }, [selectedItemId, loadItemDetail]);

  const selectBatch = (batchId: string) => {
    setSelectedBatchId(batchId);
    setBatchSnapshot(null);
    setSelectedItemId('');
    syncSearchParams({ batchId, itemId: null });
  };

  const selectItem = (itemId: string) => {
    setSelectedItemId(itemId);
    syncSearchParams({ itemId });
    if (typeof window !== 'undefined' && window.matchMedia && !window.matchMedia('(min-width: 1280px)').matches) {
      detailRef.current?.scrollIntoView?.({ block: 'start' });
    }
  };

  const setFilter = (key: string, value: string, set: (v: string) => void) => {
    set(value);
    syncSearchParams({ [key]: value || null });
  };

  const refreshAll = async () => {
    await Promise.all([loadSources(), loadBatches()]);
    if (selectedBatchId) await loadBatchItems(selectedBatchId);
    if (selectedItemId) await loadItemDetail(selectedItemId);
  };

  const rebuild = async () => {
    setRebuilding(true);
    const response = await api.rebuildInbox({
      generatedForDate: generatedForDate || selectedBatch?.generated_for_date || undefined,
      scopeType: selectedBatch?.scope_type,
      scopeValue: selectedBatch?.scope_value || undefined,
      limit,
      actorId: 'frontend',
    });
    setRebuilding(false);
    if (!response.success) {
      setError(response.error || 'Failed to rebuild the inbox');
      return;
    }
    await refreshAll();
  };

  const submitAction = async (actionType: string) => {
    if (!selectedItemId) return;
    setSubmitting(actionType);
    const response = await api.recordInboxAction(selectedItemId, { actionType, actorId: 'frontend' });
    setSubmitting(null);
    if (!response.success) {
      setError(response.error || 'Failed to record the action');
      return;
    }
    const label = ACTIONS.find((a) => a.type === actionType)?.done ?? humanize(actionType);
    if (response.item) {
      setItemDetail({ success: true, item: response.item, target: itemDetail?.target || selectedTarget, actions: selectedActions });
    }
    await Promise.all([selectedBatchId ? loadBatchItems(selectedBatchId) : Promise.resolve(), loadItemDetail(selectedItemId), loadBatches()]);
    setLastAction({ label, sideEffects: response.side_effects || [] });
  };

  const filtered = Boolean(statusFilter || targetTypeFilter || sourceFilter || generatedForDate);
  const clearFilters = () => {
    setStatusFilter('');
    setTargetTypeFilter('');
    setSourceFilter('');
    setGeneratedForDate('');
    syncSearchParams({ status: null, targetType: null, sourceId: null, generatedForDate: null });
  };

  const meta = loadingBatches && !batches.length
    ? 'loading…'
    : `${plural(batches.length, 'batch', 'batches')}${selectedBatch ? ` · ${formatCount(selectedBatch.pending_count ?? 0)} pending in this batch` : ''}`;

  const noBatches = !loadingBatches && !batchesError && !batches.length;

  return (
    <Page width="wide">
      <PageHeader
        title="Inbox"
        meta={meta}
        actions={
          <>
            <Button variant="ghost" onClick={() => void refreshAll()} disabled={loadingBatches || loadingItems}>
              <RefreshCw aria-hidden="true" />
              Refresh
            </Button>
            {noBatches ? null : (
              <Button variant="secondary" onClick={() => void rebuild()} disabled={rebuilding}>
                {rebuilding ? 'Rebuilding…' : 'Rebuild inbox'}
              </Button>
            )}
          </>
        }
      >
        {noBatches ? null : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-[minmax(0,1.6fr)_repeat(3,minmax(0,1fr))_minmax(0,9.5rem)_5rem]">
            <FilterField label="batch" htmlFor="inbox-batch" className="col-span-2 sm:col-span-3 lg:col-span-1">
              <Select id="inbox-batch" value={selectedBatchId} onChange={(e) => selectBatch(e.target.value)} disabled={!batches.length} className="w-full">
                {batches.map((b) => (
                  <option key={b.id} value={b.id}>{batchLabel(b)}</option>
                ))}
              </Select>
            </FilterField>
            <FilterField label="status" htmlFor="inbox-status">
              <Select id="inbox-status" value={statusFilter} onChange={(e) => setFilter('status', e.target.value, setStatusFilter)} className="w-full">
                <option value="">all</option>
                {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
              </Select>
            </FilterField>
            <FilterField label="target" htmlFor="inbox-target">
              <Select id="inbox-target" value={targetTypeFilter} onChange={(e) => setFilter('targetType', e.target.value, setTargetTypeFilter)} className="w-full">
                <option value="">all</option>
                <option value="post">post</option>
                <option value="story">story</option>
              </Select>
            </FilterField>
            <FilterField label="source" htmlFor="inbox-source">
              <Select id="inbox-source" value={sourceFilter} onChange={(e) => setFilter('sourceId', e.target.value, setSourceFilter)} className="w-full">
                <option value="">all</option>
                {sources.map((s) => {
                  const label = s.settings?.display_name || s.handle_or_url || s.id;
                  return <option key={s.id} value={s.id}>{middleTruncate(label, 48)}</option>;
                })}
              </Select>
            </FilterField>
            <FilterField label="generated for" htmlFor="inbox-date">
              <Input id="inbox-date" type="date" value={generatedForDate} onChange={(e) => setFilter('generatedForDate', e.target.value, setGeneratedForDate)} />
            </FilterField>
            <FilterField label="limit" htmlFor="inbox-limit">
              <Input id="inbox-limit" type="number" min={5} max={200} value={limit} onChange={(e) => setLimit(Number(e.target.value) || 25)} className="tabular-nums" />
            </FilterField>
          </div>
        )}
      </PageHeader>

      {error ? <Notice tone="error" title="Something went wrong" message={error} action={{ label: 'Dismiss', onClick: () => setError(null) }} className="mb-6" /> : null}

      {batchesError ? (
        <ErrorState error={batchesError} title="Couldn’t load the inbox" onRetry={() => void loadBatches()} />
      ) : loadingBatches && !batches.length ? (
        <LoadingState label="Loading the inbox" rows={5} />
      ) : noBatches ? (
        <EmptyState
          title="The inbox is empty"
          description="No batches have been generated yet. Rebuild the inbox to rank today’s posts and stories."
          action={{ label: rebuilding ? 'Rebuilding…' : 'Rebuild inbox', onClick: () => void rebuild(), disabled: rebuilding }}
        />
      ) : (
        <div className="grid gap-x-10 gap-y-10 xl:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
          <nav aria-label="Inbox items" className="min-w-0 xl:sticky xl:top-[calc(var(--topbar-h)+1rem)] xl:max-h-[calc(100dvh-var(--topbar-h)-2rem)] xl:self-start xl:overflow-y-auto xl:pr-1">
            <div className="mb-2 flex items-baseline justify-between text-[0.75rem] tabular-nums text-fg-3">
              <span>{plural(items.length, 'item')}{filtered ? ' · filtered' : ''}</span>
              <span>priority</span>
            </div>
            {loadingItems && !items.length ? (
              <LoadingState label="Loading items" rows={5} />
            ) : items.length ? (
              <ol className="space-y-2" aria-busy={loadingItems || undefined}>
                {items.map((entry) => {
                  const preview = (entry.target_preview || null) as PreviewRecord | null;
                  const source = previewSource(entry.target_type, preview);
                  return (
                    <li key={entry.id}>
                      <SelectRow
                        selected={entry.id === selectedItemId}
                        onSelect={() => selectItem(entry.id)}
                        meta={score(entry.priority_score)}
                        title={describeTargetPreview(entry.target_type, preview)}
                        description={entry.reason_summary || undefined}
                        footer={
                          <>
                            <ItemStatus status={entry.status} />
                            <span>{humanize(entry.target_type)}</span>
                            {source ? <span title={source}>{middleTruncate(source, 32)}</span> : null}
                            <span>novelty {percent(entry.novelty_score)}</span>
                          </>
                        }
                      />
                    </li>
                  );
                })}
              </ol>
            ) : filtered ? (
              <EmptyState title="No items match these filters" action={{ label: 'Show all', onClick: clearFilters }} />
            ) : (
              <EmptyState title="This batch has no items" description="Pick another batch or rebuild the inbox." />
            )}
          </nav>

          <div ref={detailRef} className="min-w-0 scroll-mt-[calc(var(--topbar-h)+1rem)]">
            {selectedItem ? (
              <ItemDetail
                item={selectedItem}
                target={selectedTarget}
                actions={selectedActions}
                submitting={submitting}
                lastAction={lastAction}
                onAction={(type) => void submitAction(type)}
              />
            ) : loadingDetail ? (
              <LoadingState label="Loading item" rows={3} />
            ) : items.length ? (
              <p className="rounded-md border border-dashed border-line-strong px-4 py-10 text-center text-[0.875rem] text-fg-2">
                Select an item to see its scores, reasons and history.
              </p>
            ) : null}
          </div>
        </div>
      )}
      <DevDataSwitch options={INBOX_FIXTURE_NAMES} />
    </Page>
  );
}
