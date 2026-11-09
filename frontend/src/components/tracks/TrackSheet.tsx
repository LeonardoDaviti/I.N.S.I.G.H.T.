import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import { tracksApi, type SubtopicEdit, type TrackPage, type TrackSubtopic } from '../../services/tracks';
import { Button, Field, Input, Sheet, SheetContent, Textarea, TextLink } from '../ui';
import { FOLDERS_KEY } from '../../hooks/useReaderDirectory';
import { trackSettingsHref } from '../../lib/feedContext';
import { errorMessage } from '../../lib/apiError';

const topicKey = (id: string) => ['markx-track', id] as const;

function SubtopicRow({ page, sub, others }: { page: TrackPage; sub: TrackSubtopic; others: TrackSubtopic[] }) {
  const client = useQueryClient();
  const [mode, setMode] = useState<'rename' | 'split' | null>(null);
  const [name, setName] = useState(sub.name);
  const [keys, setKeys] = useState<string[]>([]);
  const edit = useMutation({
    mutationFn: (e: SubtopicEdit) => tracksApi.editSubtopics(page.track.id, e),
    onSuccess: () => {
      setMode(null);
      void client.invalidateQueries({ queryKey: topicKey(page.track.id) });
    },
  });
  return (
    <li className="border-b border-line py-2 text-[0.8125rem]" data-subtopic={sub.id}>
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-semibold text-fg">{sub.name}</span>
        <span className="text-fg-3">{sub.count ?? 0} · {sub.locked ? 'locked' : 'proposed by INSIGHT'}</span>
      </p>
      {sub.definition ? <p className="text-[0.75rem] text-fg-3">{sub.definition}</p> : null}
      <p className="mt-1 flex flex-wrap gap-1">
        <Button size="sm" variant="ghost" className="text-[0.75rem]" onClick={() => setMode(mode === 'rename' ? null : 'rename')}>rename</Button>
        {sub.keys.length > 1 ? (
          <Button size="sm" variant="ghost" className="text-[0.75rem]" onClick={() => setMode(mode === 'split' ? null : 'split')}>split</Button>
        ) : null}
        {others.map((o) => (
          <Button key={o.id} size="sm" variant="ghost" className="text-[0.75rem]" disabled={edit.isPending}
            onClick={() => edit.mutate({ action: 'merge', id: sub.id, ids: [o.id] })}>take in {o.name}</Button>
        ))}
        <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={edit.isPending}
          onClick={() => edit.mutate({ action: sub.locked ? 'unlock' : 'lock', id: sub.id })}>{sub.locked ? 'unlock' : 'lock'}</Button>
      </p>
      {mode === 'rename' ? (
        <form className="mt-1 flex gap-2" onSubmit={(e) => { e.preventDefault(); edit.mutate({ action: 'rename', id: sub.id, name }); }}>
          <Input aria-label={`New name for ${sub.name}`} value={name} onChange={(e) => setName(e.target.value)} />
          <Button size="sm" type="submit" disabled={!name.trim() || edit.isPending}>Rename</Button>
        </form>
      ) : null}
      {mode === 'split' ? (
        <form className="mt-1" onSubmit={(e) => { e.preventDefault(); edit.mutate({ action: 'split', id: sub.id, name, keys }); }}>
          <p className="text-[0.75rem] text-fg-2">The judge’s words that go to the new sub-topic:</p>
          {sub.keys.map((k) => (
            <label key={k} className="mr-3 inline-flex items-center gap-1 text-[0.75rem]">
              <input type="checkbox" checked={keys.includes(k)}
                onChange={(e) => setKeys(e.target.checked ? [...keys, k] : keys.filter((x) => x !== k))} />
              {k}
            </label>
          ))}
          <div className="mt-1 flex gap-2">
            <Input aria-label="The new sub-topic's name" value={name} onChange={(e) => setName(e.target.value)} />
            <Button size="sm" type="submit" disabled={!name.trim() || !keys.length || edit.isPending}>Split</Button>
          </div>
        </form>
      ) : null}
      {edit.isError ? <p role="alert" className="text-fg">× {errorMessage(edit.error)}</p> : null}
    </li>
  );
}

/**
 * The track sheet (issue 0145): its name, what belongs and what doesn't (the owner's words), its active sources,
 * the examples so far (the owner's ✓ and ✗) and its sub-topics (rename, split, merge, lock). Saving new words is a
 * new version: the track's posts are judged again and its history read once more.
 */
export default function TrackSheet({ open, onOpenChange, page }: { open: boolean; onOpenChange: (open: boolean) => void; page: TrackPage }) {
  const api = useApi();
  const client = useQueryClient();
  const t = page.track;
  const [name, setName] = useState(t.name);
  const [description, setDescription] = useState(t.description ?? '');
  const [excludes, setExcludes] = useState(t.excludes ?? '');
  const save = useMutation({
    mutationFn: async () => {
      if (name.trim() && name.trim() !== t.name) {
        await api.renameTrack(t.id, name.trim());
        void client.invalidateQueries({ queryKey: [...FOLDERS_KEY] });
      }
      return tracksApi.describe(t.id, { description, excludes });
    },
    onSuccess: (got) => {
      client.setQueryData(topicKey(t.id), got);
      onOpenChange(false);
    },
  });
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title={t.topic ? `Edit ${t.name}` : `Describe ${t.name}`}
        description="INSIGHT judges every post against these words. Changing them judges the track again.">
        <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label="Name" htmlFor="track-name">
            <Input id="track-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="What belongs" htmlFor="track-description" hint="In your own words: what you want here, and why.">
            <Textarea id="track-description" value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Things worth 3D printing: useful prints, what to print and why" />
          </Field>
          <Field label="What doesn’t" htmlFor="track-excludes" hint="Optional.">
            <Textarea id="track-excludes" value={excludes} onChange={(e) => setExcludes(e.target.value)}
              placeholder="e.g. printer reviews, filament sales" />
          </Field>
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={save.isPending}>Save</Button>
            {save.isError ? <span role="alert" className="text-[0.8125rem] text-fg">× {errorMessage(save.error)}</span> : null}
          </div>
        </form>
        <section aria-label="Active sources" className="mt-6">
          <h3 className="text-[0.8125rem] font-semibold text-fg-2">Active sources</h3>
          <p className="text-[0.75rem] text-fg-3">Every post of these is judged; every other source is read for matches too.</p>
          <ul className="mt-1 text-[0.8125rem] text-fg">
            {t.sources.length ? t.sources.map((s) => <li key={s.id}>{s.name}</li>) : <li className="text-fg-2">None yet.</li>}
          </ul>
          <TextLink to={trackSettingsHref(t.id)} muted className="text-[0.75rem]">Change them in Sources</TextLink>
        </section>
        {t.topic ? (
          <section aria-label="Examples so far" className="mt-6">
            <h3 className="text-[0.8125rem] font-semibold text-fg-2">Examples so far</h3>
            <p className="text-[0.75rem] text-fg-3">Your ✓ and ✗: the newest teach the judge, all of them shape what it reads.</p>
            <ul className="mt-1 text-[0.8125rem]">
              {page.examples.in.map((e) => <li key={e.post_id}>✓ {e.title}</li>)}
              {page.examples.out.map((e) => <li key={e.post_id} className="text-fg-2">✗ {e.title}</li>)}
              {!page.examples.in.length && !page.examples.out.length ? <li className="text-fg-2">None yet.</li> : null}
            </ul>
          </section>
        ) : null}
        {page.subtopics.length ? (
          <section aria-label="Sub-topics" className="mt-6">
            <h3 className="text-[0.8125rem] font-semibold text-fg-2">Sub-topics</h3>
            <p className="text-[0.75rem] text-fg-3">INSIGHT proposes them weekly; what you rename, split, merge or lock stays.</p>
            <ul>
              {page.subtopics.map((s) => <SubtopicRow key={s.id} page={page} sub={s} others={page.subtopics.filter((o) => o.id !== s.id)} />)}
            </ul>
          </section>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
