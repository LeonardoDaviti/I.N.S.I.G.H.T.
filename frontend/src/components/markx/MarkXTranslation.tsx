import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import { markxTranslationApi, type MarkxTranslationAnswer, type MarkxTranslationView } from '../../services/api';
import { Button } from '../ui';
import { errorMessage } from '../../lib/apiError';

const LANGS: Record<string, string> = {
  ru: 'Russian', uk: 'Ukrainian', de: 'German', fr: 'French', es: 'Spanish', pt: 'Portuguese', it: 'Italian',
  zh: 'Chinese', ja: 'Japanese', ko: 'Korean', pl: 'Polish', nl: 'Dutch', tr: 'Turkish', ka: 'Georgian',
};
const langName = (lang: string | null) => (lang ? LANGS[lang] ?? lang : 'another language');

/**
 * 0130 D (Stealth v10.5): a non-English post's translation by Haiku, only while Mark X is on (its own chunk).
 * `where="post"`, under the original on the post page: the Translate button, then "asked" until the next worker run
 * answers it, then the English, marked "Translated by Haiku", with ✓ / ✗ (stored as Mark X labels; tap again to take
 * it back). `where="panel"`, in the Mark X panel: the same button and state in one line; the English shows under the
 * post. Nothing at all on an English post or one whose language is unknown.
 */
export default function MarkXTranslation({ postId, where = 'post' }: { postId: string; where?: 'post' | 'panel' }) {
  const api = markxTranslationApi(useApi());
  const client = useQueryClient();
  const key = ['markx-translation', postId];
  const query = useQuery({ queryKey: key, queryFn: () => api.getMarkxTranslation(postId), staleTime: 60_000, retry: false });
  const put = (view: MarkxTranslationView) => client.setQueryData(key, view);
  const ask = useMutation({ mutationFn: () => api.askMarkxTranslation(postId), onSuccess: (got) => put(got.view) });
  const tap = useMutation({ mutationFn: (a: MarkxTranslationAnswer) => api.labelMarkxTranslation(postId, a), onSuccess: put });
  const data = query.data;
  if (!data || !data.foreign) return null;

  const task = data.task;
  const tr = data.translation;
  const error = ask.isError ? ask.error : tap.isError ? tap.error : null;
  const askButton = (words: string) => (
    <Button size="sm" variant="ghost" disabled={ask.isPending} onClick={() => ask.mutate()} className="text-[0.75rem]">{words}</Button>
  );
  let state;
  if (tr) {
    state = where === 'panel'
      ? <span>Translated by Haiku ({tr.guide}), shown under the post{data.label ? ` · you: ${data.label === 'right' ? '✓ right' : '✗ wrong'}` : ''}</span>
      : null;
  } else if (!task) {
    state = <>{askButton('Translate')}<span className="text-fg-3">{langName(data.lang)}: Haiku translates it on the next worker run</span></>;
  } else if (task.status === 'failed') {
    state = <>{askButton('Ask again')}<span className="text-fg-3">Haiku could not translate it{task.error ? `: ${task.error}` : ''}</span></>;
  } else {
    state = <span className="text-fg-3">Translation asked: the next worker run answers it.</span>;
  }

  if (where === 'panel') {
    return (
      <section aria-label="Translation">
        <h3 className="text-[0.75rem] font-medium text-fg-3">Translation</h3>
        <p className="mt-1 flex flex-wrap items-center gap-2 [overflow-wrap:anywhere]">{state}</p>
        {error ? <p role="alert" className="text-[0.75rem] text-fg">{errorMessage(error)}</p> : null}
      </section>
    );
  }
  return (
    <section data-markx-translation aria-label="Translation" className="mt-6 text-fg-2">
      {tr ? (
        <div lang="en" className="rounded-md border border-line px-4 py-3">
          <p className="text-[0.75rem] text-fg-3">Translated by Haiku from {langName(data.lang)} · Mark X, in shadow</p>
          {tr.title_en ? <p className="mt-2 font-semibold text-fg [overflow-wrap:anywhere]">{tr.title_en}</p> : null}
          <div className="mt-2 whitespace-pre-wrap text-[0.9375rem] leading-[1.6] text-fg [overflow-wrap:anywhere]">{tr.text_en}</div>
          <span className="mt-3 flex flex-wrap items-center gap-2 text-[0.75rem]" role="group" aria-label="Is the translation right?">
            {(['right', 'wrong'] as const).map((a) => {
              const chosen = data.label === a;
              return (
                <Button key={a} size="sm" variant="ghost" disabled={tap.isPending} aria-pressed={chosen}
                  onClick={() => tap.mutate(chosen ? 'undo' : a)}
                  className={chosen ? 'text-[0.75rem] font-semibold text-fg' : 'text-[0.75rem]'}>
                  {a === 'right' ? '✓ right' : '✗ wrong'}
                </Button>
              );
            })}
            {data.label ? <span className="text-fg-3">tap again to take it back</span> : null}
          </span>
        </div>
      ) : (
        <p className="flex flex-wrap items-center gap-2 text-[0.8125rem]">{state}</p>
      )}
      {error ? <p role="alert" className="mt-1 text-[0.75rem] text-fg">{errorMessage(error)}</p> : null}
    </section>
  );
}
