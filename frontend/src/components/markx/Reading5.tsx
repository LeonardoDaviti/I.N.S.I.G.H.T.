import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import { request } from '../../lib/request';
import { errorMessage } from '../../lib/apiError';
import { TextLink } from '../ui';

/** 0212 (v10.21): ent-v5, one reading of a post, in Shadow: its switch and the comparison of its readings with what
 *  the same posts have now (/api/markx/reading5). The calls live in this chunk (not api.ts); a test's fake api may
 *  provide them. */

export type Reading5Side = {
  kind: string | null; events: string | null; event_type: string | null; origin: string | null;
  headline: string | null; entities: string[];
};
export type Reading5Post = {
  post: string; title: string | null; at: string | null;
  v5: Reading5Side; current: Reading5Side & { entities_guide?: string | null };
  entities_jaccard: number | null;
};
export type Reading5 = {
  mode: 'off' | 'shadow' | 'on';
  posts: Reading5Post[];
  agree: Record<string, { same: number; of: number }>;
  entities_jaccard?: number | null;
};

type Api = { getMarkxReading5: () => Promise<Reading5>; setMarkxReadingGuide: (mode: string) => Promise<unknown> };

function reading5Api(api: object): Api {
  const a = api as Partial<Api>;
  return {
    getMarkxReading5: typeof a.getMarkxReading5 === 'function' ? a.getMarkxReading5
      : () => request<Reading5>('/api/markx/reading5'),
    setMarkxReadingGuide: typeof a.setMarkxReadingGuide === 'function' ? a.setMarkxReadingGuide
      : (mode) => request('/api/markx/settings/reading-guide', { method: 'POST', body: { mode } }),
  };
}

const KEY = ['markx-reading5'] as const;
const MODES: { mode: Reading5['mode']; label: string }[] = [
  { mode: 'off', label: 'off' },
  { mode: 'shadow', label: 'Shadow (beside the old kinds)' },
  { mode: 'on', label: 'on (ent-v5 first)' },
];
const FIELDS = ['kind', 'events', 'event_type', 'origin'] as const;

function Cell({ mine, now }: { mine: string | null; now: string | null }) {
  const differs = mine != null && now != null && mine !== now;
  return (
    <td className={`py-1 pr-3 align-top ${differs ? 'text-fg' : 'text-fg-2'}`}>
      {mine ?? '–'}{differs ? <span className="text-fg-2"> (now {now})</span> : null}
    </td>
  );
}

export function Reading5Shadow() {
  const api = reading5Api(useApi());
  const queryClient = useQueryClient();
  const got = useQuery({ queryKey: [...KEY], queryFn: () => api.getMarkxReading5() });
  const save = useMutation({
    mutationFn: (mode: string) => api.setMarkxReadingGuide(mode),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: [...KEY] }); },
  });
  if (got.isPending) return null;
  if (got.isError) return <section aria-label="One reading (ent-v5)"><p className="text-[0.8125rem]">× {errorMessage(got.error)}</p></section>;
  const data = got.data;
  const chosen = save.isPending ? save.variables : data.mode;
  return (
    <section aria-label="One reading (ent-v5)">
      <h2 className="text-[0.9375rem] font-semibold text-fg">One reading (ent-v5)</h2>
      <p className="mt-3 text-[0.8125rem] text-fg-2">
        One call reads a new post’s kind, events, event type, origin and entities. In Shadow it is stored beside the old
        readings and nothing reads it but this table; on, it comes first. Older posts keep their readings.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[0.8125rem]" role="radiogroup" aria-label="ent-v5 switch">
        {MODES.map((m) => (
          <label key={m.mode} className="flex items-center gap-1.5 text-fg">
            <input type="radio" name="markx-reading5" checked={chosen === m.mode} disabled={save.isPending}
                   onChange={() => save.mutate(m.mode)} />
            {m.label}
          </label>
        ))}
        {save.isError ? <span className="text-fg">× {errorMessage(save.error)}</span> : null}
      </div>
      {data.posts.length === 0 ? (
        <p className="mt-3 text-[0.8125rem] text-fg-2">No post read by ent-v5 yet.</p>
      ) : (
        <>
          <p className="mt-3 text-[0.8125rem] text-fg-2" aria-label="Agreement">
            Same as now: {FIELDS.map((f) => {
              const a = data.agree[f];
              return a && a.of ? `${f.replace('_', ' ')} ${a.same} of ${a.of}` : null;
            }).filter(Boolean).join(' · ')}
            {data.entities_jaccard != null ? ` · entity names in common ${Math.round(data.entities_jaccard * 100)}%` : ''}
          </p>
          <table className="mt-2 w-full text-left text-[0.8125rem]">
            <thead className="text-fg-2">
              <tr><th className="pr-3">Post</th><th className="pr-3">Kind</th><th className="pr-3">Events</th>
                <th className="pr-3">Event type</th><th className="pr-3">Origin</th><th>Entities in common</th></tr>
            </thead>
            <tbody>
              {data.posts.map((p) => (
                <tr key={p.post}>
                  <td className="py-1 pr-3 align-top text-fg">
                    <TextLink to={`/posts/${encodeURIComponent(p.post)}`}>{p.title || p.v5.headline || '(no title)'}</TextLink>
                  </td>
                  {FIELDS.map((f) => <Cell key={f} mine={p.v5[f]} now={p.current[f]} />)}
                  <td className="py-1 align-top text-fg-2">
                    {p.entities_jaccard == null ? '–' : `${Math.round(p.entities_jaccard * 100)}%`}
                    {' '}({p.v5.entities.length} / {p.current.entities.length})
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
