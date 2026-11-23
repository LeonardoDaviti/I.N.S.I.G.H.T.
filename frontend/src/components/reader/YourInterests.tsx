import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { FEED_ROOT_KEY } from '../../hooks/useFeed';
import { errorMessage } from '../../lib/apiError';
import { plural } from '../../lib/format';
import { interestHref, interestLabel, interestsApi, type TaughtInterest } from '../../services/interests';
import type { InterestAnswer, InterestDim } from '../../services/api';
import { Button, Input, TextLink } from '../ui';

export const INTERESTS_KEY = ['markx-interests'] as const;

const GROUPS: { answer: InterestAnswer; title: string }[] = [
  { answer: 'more', title: 'More of' },
  { answer: 'less', title: 'Less of' },
  { answer: 'none', title: 'Not a reason' },
];

/**
 * v10.43: "Your interests", under News' order line: every thing, kind of news and source you raised or lowered
 * (each its newest tap), × to remove it (back to what INSIGHT learned from your reads), and a box to add a thing as
 * "more" from the entity picker. News is ordered by it at once.
 */
export default function YourInterests() {
  const client = useQueryClient();
  const [q, setQ] = useState('');
  const words = q.trim();
  const list = useQuery({ queryKey: [...INTERESTS_KEY], queryFn: () => interestsApi.list(), staleTime: 30_000 });
  const found = useQuery({
    queryKey: [...INTERESTS_KEY, 'find', words],
    queryFn: () => interestsApi.find(words),
    enabled: words.length >= 2, staleTime: 60_000,
  });
  const teach = useMutation({
    mutationFn: (t: { dim: InterestDim; key: string; name?: string | null; answer: InterestAnswer }) => interestsApi.teach(t),
    onSuccess: () => {
      setQ('');
      void client.invalidateQueries({ queryKey: [...INTERESTS_KEY] });
      void client.invalidateQueries({ queryKey: [...FEED_ROOT_KEY, 'news'] });
    },
  });
  const taught = list.data?.taught ?? [];
  const has = new Set(taught.filter((t) => t.dim === 'thing' && t.answer === 'more').map((t) => t.key));
  const remove = (t: TaughtInterest) => teach.mutate({ dim: t.dim, key: t.key, name: t.name, answer: 'undo' });
  return (
    <section aria-label="Your interests" data-your-interests className="mb-3 rounded border border-line p-3 text-[0.8125rem]">
      <h3 className="font-semibold text-fg-2">Your interests</h3>
      <p className="text-[0.75rem] text-fg-3">What you raised or lowered. Remove one and INSIGHT goes back to what it learned from your reading.</p>
      {list.isError ? <p className="mt-2 text-fg-2">Could not read your interests.</p> : null}
      {list.data && !taught.length ? <p className="mt-2 text-fg-2">Nothing yet. Add a thing below, or use Teach on a News row.</p> : null}
      {GROUPS.map(({ answer, title }) => {
        const rows = taught.filter((t) => t.answer === answer);
        if (!rows.length) return null;
        return (
          <div key={answer} className="mt-2">
            <h4 className="text-[0.75rem] font-medium text-fg-3">{title}</h4>
            <ul className="mt-1 flex flex-wrap gap-1.5" aria-label={title}>
              {rows.map((t) => {
                const href = interestHref(t);
                const label = interestLabel(t);
                return (
                  <li key={`${t.dim}:${t.key}`} data-interest={`${t.dim}:${t.key}`}
                    className="flex items-center gap-1 rounded border border-line px-2 py-0.5">
                    {href ? <TextLink to={href}>{label}</TextLink> : <span>{label}</span>}
                    {t.origin === 'seed' ? <span className="text-fg-3">(stated)</span> : null}
                    <Button size="sm" variant="ghost" className="h-auto px-1 text-[0.75rem]" aria-label={`Remove ${label}`}
                      disabled={teach.isPending} onClick={() => remove(t)}>×</Button>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      <Input className="mt-2" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Add a thing you follow (a model, a company, a project)"
        aria-label="Find a thing to follow" />
      {words.length >= 2 && found.data ? (
        <ul className="mt-1" aria-label="Things found">
          {found.data.filter((t) => !has.has(t.id)).map((t) => (
            <li key={t.id}>
              <Button size="sm" variant="ghost" className="text-[0.8125rem]" disabled={teach.isPending}
                onClick={() => teach.mutate({ dim: 'thing', key: t.id, name: t.name, answer: 'more' })}>
                + {t.name}<span className="ml-1 text-fg-3">{t.type ?? ''} · {plural(t.mentions, 'mention')}</span>
              </Button>
            </li>
          ))}
          {!found.data.length ? <li className="text-fg-2">No thing by that name yet.</li> : null}
        </ul>
      ) : null}
      {teach.isError ? <p role="alert" className="mt-1 text-[0.75rem] text-fg">× not saved: {errorMessage(teach.error)}</p> : null}
    </section>
  );
}
