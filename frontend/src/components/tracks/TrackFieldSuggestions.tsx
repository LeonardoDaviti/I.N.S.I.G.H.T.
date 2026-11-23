import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { briefApi, OWNER_FIELDS, type FieldSuggestion, type FieldSuggestions } from '../../services/tracks';
import { Button } from '../ui';
import { errorMessage } from '../../lib/apiError';
import { fieldWord, kindWord, schemaKey, suggestionsKey, withField } from './briefWords';

/** "Suggested fields": fields INSIGHT suggests a track's kinds add, from its rows and posts. Never applied by INSIGHT:
 *  Add is the owner's schema edit; Dismiss keeps a field from being suggested again. Hidden when there are none. */
export default function TrackFieldSuggestions({ trackId }: { trackId: string }) {
  const client = useQueryClient();
  const sugg = useQuery({ queryKey: suggestionsKey(trackId), queryFn: () => briefApi.suggestions(trackId), staleTime: 60_000, retry: false });
  const schema = useQuery({ queryKey: schemaKey(trackId), queryFn: () => briefApi.schema(trackId), staleTime: 60_000, retry: false });
  const add = useMutation({
    mutationFn: (s: FieldSuggestion) => briefApi.saveSchema(trackId, withField(schema.data?.schema?.kinds ?? [], s)),
    onSuccess: (got) => {
      client.setQueryData(schemaKey(trackId), got);
      void client.invalidateQueries({ queryKey: suggestionsKey(trackId) });
    },
  });
  const dismiss = useMutation({
    mutationFn: (s: FieldSuggestion) => briefApi.dismissField(trackId, s.kind, s.name),
    onSuccess: (got: FieldSuggestions) => client.setQueryData(suggestionsKey(trackId), got),
  });
  const fields = sugg.data?.on ? sugg.data.fields : [];
  const kinds = schema.data?.schema?.kinds ?? [];
  if (!fields.length || !kinds.length) return null;
  const busy = add.isPending || dismiss.isPending;
  return (
    <section aria-label="Suggested fields" className="mb-4 rounded border border-line p-3">
      <h3 className="text-[0.8125rem] font-semibold text-fg-2">Suggested fields</h3>
      <p className="text-[0.75rem] text-fg-3">What this track’s posts keep saying that no column holds. Adding one reads the track’s posts again.</p>
      <ul className="mt-2 space-y-2">
        {fields.map((s) => {
          const full = (kinds.find((k) => k.kind === s.kind)?.fields.length ?? 0) >= OWNER_FIELDS;
          return (
            <li key={`${s.kind}.${s.name}`} className="text-[0.8125rem]" data-suggested-field={`${s.kind}.${s.name}`}>
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-semibold text-fg">{fieldWord(s.name)}</span>
                <span className="text-fg-3">{kindWord(s.kind)} · {s.type}{s.unit ? ` (${s.unit})` : ''}{s.values?.length ? `: ${s.values.join(', ')}` : ''}</span>
              </p>
              {s.about ? <p className="text-[0.75rem] text-fg-2">{s.about}</p> : null}
              <p className="text-[0.75rem] text-fg-3">{s.why}</p>
              <p className="mt-1 flex gap-1">
                <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={busy || full}
                  aria-label={`Add ${fieldWord(s.name)} to ${kindWord(s.kind)}`} onClick={() => add.mutate(s)}>Add</Button>
                <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={busy}
                  aria-label={`Dismiss ${fieldWord(s.name)}`} onClick={() => dismiss.mutate(s)}>Dismiss</Button>
                {full ? <span className="text-[0.75rem] text-fg-3">this kind is full ({OWNER_FIELDS} fields)</span> : null}
              </p>
            </li>
          );
        })}
      </ul>
      {add.isError ? <p role="alert" className="text-[0.75rem] text-fg">× {errorMessage(add.error)}</p> : null}
      {dismiss.isError ? <p role="alert" className="text-[0.75rem] text-fg">× {errorMessage(dismiss.error)}</p> : null}
    </section>
  );
}
