import { useCallback, useEffect, useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { ChevronRight, RefreshCw, Trash2 } from 'lucide-react';
import MarkdownRenderer from './ui/MarkdownRenderer';
import {
  Button,
  Chip,
  Dialog,
  DialogContent,
  DialogFooter,
  Field,
  Input,
  PageHeader,
  Select,
  StatusGlyph,
  TextLink,
  Textarea,
} from './ui';
import { StatusIcon } from './ui/StatusGlyph';
import { EmptyState, ErrorState, LoadingState, Notice } from './states';
import DevDataSwitch from './ops/DevDataSwitch';
import { Section } from './analysis/parts';
import { shortDate } from './analysis/format';
import { useDevFixtureApi } from './analysis/useDevFixtureApi';
import { formatCount, plural } from '../lib/format';
import { cn } from '../lib/utils';
import type { Expert, ExpertRunResult, Folder } from '../services/api';
import { TRACKS_FIXTURE_NAMES, tracksFixtureApi } from '../pages/ExpertsPage.fixtures';
import { folderReadPath } from '../lib/feedContext';

/**
 * Tracks & experts (design docs parked/experts-tracks.md): the folders and tracks as smol-style rows
 * (kind column, bold name, counts, unread), and the experts that write briefings
 * on them, each a disclosure row with Run / Regenerate / Delete. Deleting asks
 * first (apple: confirm only what is destructive and irreversible).
 */

const EMPTY_FORM = { name: '', folder_id: '', system_prompt: '', focus_instructions: '', lookback_days: 7, schedule: '' };

type PendingDelete =
  | { kind: 'folder'; id: string; name: string; isTrack: boolean; expertCount: number }
  | { kind: 'expert'; id: string; name: string }
  | null;

/** What a delete takes with it (the database cascades: experts, a track's milestone lanes). */
function deleteConsequence(pending: NonNullable<PendingDelete>): string {
  if (pending.kind === 'expert') return 'Its saved briefings stop updating. This cannot be undone.';
  const word = pending.isTrack ? 'track' : 'folder';
  const experts = pending.expertCount
    ? `Its ${plural(pending.expertCount, 'expert')} and their briefings are deleted with it, as are the ${word}’s own milestone lanes.`
    : `The ${word}’s own milestone lanes are deleted with it.`;
  return `${experts} Its sources stay; they are only unassigned. This cannot be undone.`;
}

function ConfirmDelete({ pending, onConfirm, onCancel }: { pending: PendingDelete; onConfirm: () => void; onCancel: () => void }) {
  const word = pending?.kind === 'folder' ? (pending.isTrack ? 'track' : 'folder') : 'expert';
  return (
    <Dialog open={pending !== null} onOpenChange={(open) => { if (!open) onCancel(); }}>
      {pending ? (
        <DialogContent
          role="alertdialog"
          title={`Delete ${word} “${pending.name}”?`}
          description={deleteConsequence(pending)}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            (event.currentTarget as HTMLElement | null)?.querySelector<HTMLButtonElement>('[data-cancel]')?.focus();
          }}
        >
          <DialogFooter>
            <Button variant="ghost" data-cancel onClick={onCancel}>Cancel</Button>
            <Button variant="danger" onClick={onConfirm}>Delete {word}</Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

function FolderRow({ folder, unread, onDelete }: { folder: Folder; unread: number; onDelete: () => void }) {
  return (
    <li className="relative flex min-w-0 items-start gap-4 rounded-md border border-line bg-bg px-4 py-3 hover:border-line-strong hover:bg-surface">
      <span className="hidden w-[3.25rem] shrink-0 pt-px text-[0.8125rem] text-fg-3 sm:block">{folder.kind === 'track' ? 'track' : 'folder'}</span>
      <div className="min-w-0 flex-1">
        <Link
          to={folderReadPath(folder.id)}
          className="line-clamp-2 break-words font-semibold text-fg [overflow-wrap:anywhere] after:absolute after:inset-0 after:rounded-md focus-visible:outline-none focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:outline-offset-2 focus-visible:after:outline-fg"
        >
          <span dir="auto">{folder.name?.trim() || 'Untitled folder'}</span>
        </Link>
        {folder.description ? (
          <p className="mt-0.5 line-clamp-2 break-words text-[0.8125rem] text-fg-2">{folder.description}</p>
        ) : null}
        <p className="mt-1 text-[0.75rem] tabular-nums text-fg-3">
          <span className="sm:hidden">{folder.kind === 'track' ? 'track' : 'folder'} · </span>
          {plural(folder.source_count ?? 0, 'source')} · {plural(folder.post_count ?? 0, 'post')}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {unread > 0 ? (
          <span className="mr-1 inline-flex items-center gap-1.5 whitespace-nowrap pt-px text-[0.8125rem] font-semibold tabular-nums text-fg">
            <StatusIcon status="unread" />
            {formatCount(unread)}
            <span className="sr-only"> unread</span>
          </span>
        ) : null}
        <Button
          variant="ghost"
          size="icon"
          className="relative z-10 -my-1.5"
          aria-label={`Delete ${folder.kind === 'track' ? 'track' : 'folder'} ${folder.name}`}
          onClick={onDelete}
        >
          <Trash2 aria-hidden="true" />
        </Button>
      </div>
    </li>
  );
}

function BriefingBody({ briefing }: { briefing: ExpertRunResult | undefined }) {
  if (!briefing) {
    return <p className="text-[0.875rem] text-fg-3">No briefing yet. Run the expert to write one.</p>;
  }
  const range = briefing.start_date || briefing.end_date ? `${shortDate(briefing.start_date)} → ${shortDate(briefing.end_date)}` : null;
  const topics = briefing.topics || [];
  return (
    <div className="space-y-5">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.75rem] tabular-nums text-fg-3">
        <span>{plural(briefing.posts_processed ?? 0, 'post')}</span>
        {range ? <span>{range}</span> : null}
        {briefing.generator && briefing.generator !== 'fallback' ? <span>{briefing.generator}</span> : null}
      </p>
      {briefing.generator === 'fallback' ? (
        <Notice tone="warning" title="Fallback summary, not analysis" message="The model was unavailable, so this is the deterministic stub. Regenerate to try again." />
      ) : null}
      <div className="prose prose-sm max-w-[68ch] break-words [overflow-wrap:anywhere]">
        <MarkdownRenderer content={briefing.briefing || ''} />
      </div>
      {topics.length ? (
        <div>
          <h4 className="mb-2 text-[0.8125rem] font-semibold text-fg">Topics <span className="font-normal tabular-nums text-fg-3">{topics.length}</span></h4>
          <ul className="divide-y divide-line rounded-md border border-line">
            {topics.map((topic, index) => (
              <li key={`${topic.title}-${index}`} className="px-3 py-2.5 text-[0.8125rem]">
                <span className="break-words font-medium text-fg [overflow-wrap:anywhere]">{topic.title || 'Untitled topic'}</span>
                <span className="tabular-nums text-fg-3"> · {plural(topic.post_ids.length, 'post')}</span>
                {topic.summary ? <p className="mt-0.5 break-words text-fg-2">{topic.summary}</p> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function ExpertRow({
  expert,
  folderName,
  briefing,
  open,
  running,
  onToggle,
  onRun,
  onDelete,
}: {
  expert: Expert;
  folderName: string | null;
  briefing: ExpertRunResult | undefined;
  open: boolean;
  running: boolean;
  onToggle: () => void;
  onRun: (refresh: boolean) => void;
  onDelete: () => void;
}) {
  const bodyId = useId();
  const state = running ? (
    <StatusGlyph status="running" label="running…" />
  ) : briefing ? (
    <span className="inline-flex items-center gap-1.5 text-fg-2">
      <StatusIcon status={briefing.generator === 'fallback' ? 'backoff' : 'ok'} />
      {briefing.generator === 'fallback' ? 'fallback briefing' : briefing.end_date ? `briefed ${shortDate(briefing.end_date)}` : 'briefed'}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-fg-3"><StatusIcon status="scheduled" />no briefing</span>
  );

  return (
    <li className={cn('rounded-md border', open ? 'border-line-strong' : 'border-line')}>
      <div className="flex min-w-0 flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3 sm:flex-nowrap">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={bodyId}
          className="-m-1 flex min-w-0 flex-1 basis-[14rem] items-start gap-2 rounded-sm p-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg"
        >
          <ChevronRight aria-hidden="true" className={cn('mt-[0.2rem] h-4 w-4 shrink-0 text-fg-3', open && 'rotate-90')} />
          <span className="min-w-0">
            <span className="line-clamp-2 break-words font-semibold text-fg [overflow-wrap:anywhere]">{expert.name}</span>
            <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem] text-fg-2">
              {folderName ? (
                <span className="break-words [overflow-wrap:anywhere]">{folderName}</span>
              ) : (
                <Chip variant="dashed">folder missing</Chip>
              )}
              <span className="tabular-nums">{expert.lookback_days}-day lookback</span>
              {expert.schedule ? <span className="break-words">{expert.schedule}</span> : null}
              {state}
            </span>
          </span>
        </button>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          <Button size="sm" variant="secondary" onClick={() => onRun(false)} disabled={running}>
            {running ? 'Running…' : 'Run'}
          </Button>
          <Button size="icon" variant="ghost" aria-label={`Regenerate the briefing for ${expert.name}`} title="Regenerate (ignore the cached briefing)" onClick={() => onRun(true)} disabled={running}>
            <RefreshCw aria-hidden="true" />
          </Button>
          <Button size="icon" variant="ghost" aria-label={`Delete expert ${expert.name}`} onClick={onDelete}>
            <Trash2 aria-hidden="true" />
          </Button>
        </div>
      </div>
      {open ? (
        <div id={bodyId} className="border-t border-line px-4 py-4">
          <BriefingBody briefing={briefing} />
        </div>
      ) : null}
    </li>
  );
}

function NewExpertDialog({
  open,
  onOpenChange,
  folders,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  folders: Folder[];
  onCreate: (form: typeof EMPTY_FORM) => Promise<string | null>;
}) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const id = useId();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.name.trim() || !form.folder_id || !form.system_prompt.trim()) {
      setFormError('An expert needs a name, a folder and a system prompt.');
      return;
    }
    setSaving(true);
    const error = await onCreate(form);
    setSaving(false);
    if (error) {
      setFormError(error);
      return;
    }
    setForm(EMPTY_FORM);
    setFormError(null);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="New expert" description="An expert writes a briefing from one folder’s posts." className="w-[min(36rem,calc(100vw-2rem))]">
        <form onSubmit={(e) => void submit(e)} className="mt-5 space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" htmlFor={`${id}-name`}>
              <Input id={`${id}-name`} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Agentic News" />
            </Field>
            <Field label="Folder" htmlFor={`${id}-folder`}>
              <Select id={`${id}-folder`} value={form.folder_id} onChange={(e) => setForm({ ...form, folder_id: e.target.value })} className="w-full">
                <option value="">Choose a folder…</option>
                {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </Select>
            </Field>
          </div>
          <Field label="System prompt" htmlFor={`${id}-prompt`} hint="The expert’s voice and priorities.">
            <Textarea id={`${id}-prompt`} rows={4} value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} />
          </Field>
          <Field label="Focus (optional)" htmlFor={`${id}-focus`} hint="What to prioritise this time.">
            <Textarea id={`${id}-focus`} rows={2} value={form.focus_instructions} onChange={(e) => setForm({ ...form, focus_instructions: e.target.value })} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Lookback (days)" htmlFor={`${id}-lookback`}>
              <Input
                id={`${id}-lookback`}
                type="number"
                min={1}
                max={90}
                value={form.lookback_days}
                onChange={(e) => setForm({ ...form, lookback_days: parseInt(e.target.value, 10) || 7 })}
                className="tabular-nums"
              />
            </Field>
            <Field label="Schedule (optional)" htmlFor={`${id}-schedule`}>
              <Input id={`${id}-schedule`} value={form.schedule} onChange={(e) => setForm({ ...form, schedule: e.target.value })} placeholder="daily" />
            </Field>
          </div>
          {formError ? <Notice tone="error" title={formError} /> : null}
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={saving}>{saving ? 'Creating…' : 'Create expert'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function FoldersExpertsPanel() {
  const { api } = useDevFixtureApi(tracksFixtureApi);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [experts, setExperts] = useState<Expert[]>([]);
  const [unread, setUnread] = useState<Record<string, number>>({});
  const [briefings, setBriefings] = useState<Record<string, ExpertRunResult>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState('');
  const [addingFolder, setAddingFolder] = useState(false);
  const [creatingExpert, setCreatingExpert] = useState(false);
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>(null);
  const folderInputId = useId();

  const load = useCallback(async () => {
    setLoadError(null);
    const [fRes, eRes] = await Promise.all([api.getFolders(), api.getExperts()]);
    if (!fRes.success) {
      setLoadError(fRes.error || 'Failed to load folders');
      setLoading(false);
      return;
    }
    setFolders(fRes.folders);
    // Unread counts are a nicety: a failure leaves the rows without them.
    api.getUnreadCounts().then((counts) => setUnread(counts?.by_folder ?? {}), () => setUnread({}));
    if (eRes.success) {
      setExperts(eRes.experts);
      const map: Record<string, ExpertRunResult> = {};
      await Promise.all(
        eRes.experts.map(async (ex) => {
          const b = await api.getExpertBriefing(ex.id).catch(() => null);
          if (b?.success) map[ex.id] = b;
        }),
      );
      setBriefings(map);
    } else {
      setError(eRes.error || 'Failed to load experts');
    }
    setLoading(false);
  }, [api]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  const folderName = (id: string) => folders.find((f) => f.id === id)?.name ?? null;

  const addFolder = async (event: FormEvent) => {
    event.preventDefault();
    const name = newFolderName.trim();
    if (!name) return;
    setAddingFolder(true);
    const res = await api.createFolder({ name });
    setAddingFolder(false);
    if (res.success) {
      setNewFolderName('');
      await load();
    } else setError(res.error || 'Failed to create the folder');
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const { kind, id } = pendingDelete;
    setPendingDelete(null);
    const res = kind === 'folder' ? await api.deleteFolder(id) : await api.deleteExpert(id);
    if (res.success) await load();
    else setError(res.error || `Failed to delete the ${kind}`);
  };

  const createExpert = async (form: typeof EMPTY_FORM): Promise<string | null> => {
    const res = await api.createExpert(form);
    if (!res.success) return res.error || 'Failed to create the expert';
    await load();
    return null;
  };

  const run = async (expert: Expert, refresh: boolean) => {
    setRunning((p) => new Set(p).add(expert.id));
    setError(null);
    const res = await api.runExpert(expert.id, { refresh });
    setRunning((p) => {
      const n = new Set(p);
      n.delete(expert.id);
      return n;
    });
    if (res.success) {
      setBriefings((p) => ({ ...p, [expert.id]: res }));
      setOpen((p) => new Set(p).add(expert.id));
      toast(res.cached ? 'Cached briefing loaded' : 'Briefing written', { description: expert.name });
    } else setError(res.error || 'Failed to run the expert');
  };

  const toggleOpen = (id: string) =>
    setOpen((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const tracks = folders.filter((f) => f.kind === 'track').length;
  const meta = loading
    ? 'loading…'
    : `${plural(tracks, 'track')} · ${plural(folders.length - tracks, 'folder')} · ${plural(experts.length, 'expert')}`;

  return (
    <>
      <PageHeader
        title="Tracks"
        meta={meta}
        actions={
          <Button variant="primary" onClick={() => setCreatingExpert(true)} disabled={loading || !!loadError}>
            New expert
          </Button>
        }
      />

      {error ? <Notice tone="error" title="Something went wrong" message={error} action={{ label: 'Dismiss', onClick: () => setError(null) }} className="mb-6" /> : null}

      {loadError ? (
        <ErrorState error={loadError} title="Couldn’t load tracks" onRetry={() => { setLoading(true); void load(); }} />
      ) : loading ? (
        <LoadingState label="Loading tracks" rows={4} />
      ) : (
        <div className="space-y-10">
          <Section title="Tracks & folders" meta={folders.length || undefined} id="tracks-folders">
            {folders.length ? (
              <ul className="space-y-2">
                {folders.map((f) => (
                  <FolderRow
                    key={f.id}
                    folder={f}
                    unread={unread[f.id] ?? 0}
                    onDelete={() => setPendingDelete({
                      kind: 'folder', id: f.id, name: f.name, isTrack: f.kind === 'track',
                      expertCount: experts.filter((ex) => ex.folder_id === f.id).length,
                    })}
                  />
                ))}
              </ul>
            ) : (
              <EmptyState title="No tracks yet" description="Create a folder below, then assign sources to it from the sources page." />
            )}
            <form onSubmit={(e) => void addFolder(e)} className="mt-4 flex flex-wrap items-end gap-2">
              <div className="min-w-0 flex-1 basis-[14rem]">
                <label htmlFor={folderInputId} className="sr-only">New folder name</label>
                <Input id={folderInputId} value={newFolderName} onChange={(e) => setNewFolderName(e.target.value)} placeholder="New folder name" />
              </div>
              <Button type="submit" variant="secondary" disabled={!newFolderName.trim() || addingFolder}>
                {addingFolder ? 'Adding…' : 'Add folder'}
              </Button>
            </form>
            <p className="mt-2 text-[0.75rem] text-fg-3">
              Assign sources to a folder from each source’s settings on the <TextLink to="/settings/sources" muted>sources</TextLink> page.
            </p>
          </Section>

          <Section title="Experts" meta={experts.length || undefined} id="tracks-experts">
            {experts.length ? (
              <ul className="space-y-2">
                {experts.map((ex) => (
                  <ExpertRow
                    key={ex.id}
                    expert={ex}
                    folderName={folderName(ex.folder_id)}
                    briefing={briefings[ex.id]}
                    open={open.has(ex.id)}
                    running={running.has(ex.id)}
                    onToggle={() => toggleOpen(ex.id)}
                    onRun={(refresh) => void run(ex, refresh)}
                    onDelete={() => setPendingDelete({ kind: 'expert', id: ex.id, name: ex.name })}
                  />
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No experts yet"
                description={folders.length ? 'An expert reads one folder and writes a briefing on it.' : 'Create a folder first; an expert briefs on one folder.'}
              />
            )}
          </Section>
        </div>
      )}

      <NewExpertDialog open={creatingExpert} onOpenChange={setCreatingExpert} folders={folders} onCreate={createExpert} />
      <ConfirmDelete pending={pendingDelete} onConfirm={() => void confirmDelete()} onCancel={() => setPendingDelete(null)} />
      <DevDataSwitch options={TRACKS_FIXTURE_NAMES} />
    </>
  );
}
