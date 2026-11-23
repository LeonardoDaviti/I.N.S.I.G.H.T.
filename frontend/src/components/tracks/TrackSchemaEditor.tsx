import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  briefApi, OWNER_FIELDS, PRACTICE_KIND, type ThingFieldDef, type ThingFieldType, type ThingKindDef, type TrackSchemaView,
} from '../../services/tracks';
import { Button, Input, Select } from '../ui';
import { errorMessage } from '../../lib/apiError';
import { FIELD_NAME, fieldKey, fieldWord, kindWord, schemaKey } from './briefWords';


/** A name while it is typed: lowercase, spaces as _, nothing else (FIELD_NAME checks it on save). */
const typedName = (s: string) => s.toLowerCase().replace(/\s/g, '_').replace(/[^a-z0-9_]/g, '').slice(0, 40);

const TYPES: ThingFieldType[] = ['text', 'number', 'money', 'link', 'enum'];

function AddField({ kind, onAdd }: { kind: string; onAdd: (f: ThingFieldDef) => void }) {
  const [name, setName] = useState('');
  const [type, setType] = useState<ThingFieldType>('text');
  const [extra, setExtra] = useState('');
  const key = fieldKey(name);
  const values = extra.split(',').map((v) => v.trim()).filter(Boolean);
  const ok = FIELD_NAME.test(key) && (type !== 'enum' || values.length >= 2);
  return (
    <form className="mt-1 flex flex-wrap items-center gap-1.5" aria-label={`Add a field to ${kindWord(kind)}`}
      onSubmit={(e) => {
        e.preventDefault();
        if (!ok) return;
        onAdd({ name: key, type, ...(type === 'number' && extra.trim() ? { unit: extra.trim() } : {}), ...(type === 'enum' ? { values } : {}) });
        setName(''); setExtra(''); setType('text');
      }}>
      <Input aria-label={`New field of ${kindWord(kind)}`} placeholder="a new field" value={name} onChange={(e) => setName(e.target.value)}
        className="h-8 w-36 text-[0.8125rem]" />
      <Select aria-label={`Its type`} value={type} onChange={(e) => setType(e.target.value as ThingFieldType)} className="text-[0.8125rem]">
        {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </Select>
      {type === 'number' || type === 'enum' ? (
        <Input aria-label={type === 'number' ? 'Its unit' : 'Its values, with commas'} value={extra} onChange={(e) => setExtra(e.target.value)}
          placeholder={type === 'number' ? 'unit (optional)' : 'values, with commas'} className="h-8 w-40 text-[0.8125rem]" />
      ) : null}
      <Button size="sm" variant="ghost" type="submit" className="text-[0.75rem]" disabled={!ok}>add</Button>
    </form>
  );
}

/** The track's kinds and fields, in the track sheet: Haiku proposed them; the owner edits fields and saves a new
 *  version (which reads the track's posts again). The code's own kind is shown, not edited. Hidden while the briefer
 *  is off or before a schema exists. */
export default function TrackSchemaEditor({ trackId }: { trackId: string }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: schemaKey(trackId), queryFn: () => briefApi.schema(trackId), staleTime: 60_000, retry: false });
  const [draft, setDraft] = useState<ThingKindDef[] | null>(null);
  const save = useMutation({
    mutationFn: (kinds: ThingKindDef[]) => briefApi.saveSchema(trackId, kinds),
    onSuccess: (got: TrackSchemaView) => {
      client.setQueryData(schemaKey(trackId), got);
      setDraft(null);
    },
  });
  const view = query.data;
  if (!view?.on || !view.schema) return null;
  const stored = view.schema.kinds.filter((k) => k.kind !== PRACTICE_KIND);
  const practice = view.schema.kinds.find((k) => k.kind === PRACTICE_KIND);
  const kinds = draft ?? stored;
  const edit = (kind: string, fields: ThingFieldDef[]) =>
    setDraft(kinds.map((k) => (k.kind === kind ? { ...k, fields } : k)));
  const bad = kinds.flatMap((k) => k.fields.filter((f) => !FIELD_NAME.test(f.name)).map((f) => `${k.kind}.${f.name || '(empty)'}`));
  const twice = kinds.flatMap((k) => k.fields.map((f) => f.name).filter((n, i, all) => all.indexOf(n) !== i).map((n) => `${k.kind}.${n}`));
  return (
    <section aria-label="Kinds and fields" className="mt-6" data-schema-version={view.version ?? undefined}>
      <h3 className="text-[0.8125rem] font-semibold text-fg-2">Kinds and fields</h3>
      <p className="text-[0.75rem] text-fg-3">
        What INSIGHT pulls out of this track’s posts{view.by === 'owner' ? ' (your edit)' : ', proposed from your words'}.
        Saving reads the track’s posts again.{view.stale ? ' New ones for your new words are on their way.' : ''}
      </p>
      {kinds.map((k) => (
        <div key={k.kind} className="mt-3" data-schema-kind={k.kind}>
          <p className="text-[0.8125rem] font-semibold text-fg">{kindWord(k.kind)}</p>
          {k.about ? <p className="text-[0.75rem] text-fg-3">{k.about}</p> : null}
          <ul className="mt-1 space-y-1">
            {k.fields.map((f, i) => (
              <li key={`${i}`} className="flex flex-wrap items-center gap-1.5 text-[0.8125rem]">
                <Input aria-label={`Field ${i + 1} of ${kindWord(k.kind)}`} value={f.name} className="h-8 w-40 text-[0.8125rem]"
                  onChange={(e) => edit(k.kind, k.fields.map((x, j) => (j === i ? { ...x, name: typedName(e.target.value) } : x)))} />
                <span className="text-fg-3">{f.type}{f.unit ? ` (${f.unit})` : ''}{f.values?.length ? `: ${f.values.join(', ')}` : ''}{i === 0 ? ' · its name' : ''}</span>
                {i > 0 ? (
                  <Button size="sm" variant="ghost" className="text-[0.75rem]" aria-label={`Remove ${fieldWord(f.name)} from ${kindWord(k.kind)}`}
                    onClick={() => edit(k.kind, k.fields.filter((_x, j) => j !== i))}>remove</Button>
                ) : null}
              </li>
            ))}
          </ul>
          {k.fields.length < OWNER_FIELDS ? <AddField kind={k.kind} onAdd={(f) => edit(k.kind, [...k.fields, f])} /> : null}
        </div>
      ))}
      {practice ? (
        <p className="mt-3 text-[0.75rem] text-fg-3">Always kept: practices and claims ({practice.fields.map((f) => f.name).join(', ')}).</p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button size="sm" disabled={!draft || save.isPending || bad.length > 0 || twice.length > 0} onClick={() => draft && save.mutate(draft)}>
          Save the fields
        </Button>
        {draft ? <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>undo the edits</Button> : null}
        {bad.length ? <span role="alert" className="text-[0.75rem] text-fg">× a name is lowercase letters, digits and _</span> : null}
        {twice.length ? <span role="alert" className="text-[0.75rem] text-fg">× a field named twice</span> : null}
        {save.isError ? <span role="alert" className="text-[0.75rem] text-fg">× {errorMessage(save.error)}</span> : null}
      </div>
    </section>
  );
}
