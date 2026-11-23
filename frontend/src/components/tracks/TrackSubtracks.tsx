import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { tracksApi, type StackThing, type TrackPage } from '../../services/tracks';
import { Button, Input, TextLink } from '../ui';
import { plural } from '../../lib/format';
import { errorMessage } from '../../lib/apiError';

const trackPath = (id: string) => `/read/folder/${encodeURIComponent(id)}`;

/**
 * v10.42: a track's sub-tracks (each its own track: the parent's posts, judged under its own description and stack,
 * or the rest of them) with their first posts; on a sub-track, the parent it belongs to. Hidden when neither.
 */
export function SubTracks({ page }: { page: TrackPage }) {
  const subs = page.subtracks ?? [];
  const parent = page.track.parent;
  if (!subs.length && !parent) return null;
  return (
    <section aria-label="Sub-tracks" className="mb-4">
      {parent ? (
        <p className="mb-2 text-[0.75rem] text-fg-3">
          Part of <TextLink to={trackPath(parent.id)}>{parent.name}</TextLink>
          {page.track.rest ? ' · takes its posts no other sub-track holds' : ' · its posts, judged by this description'}
          {page.track.sort === 'news' ? ' · ordered as News ranks them' : ''}
        </p>
      ) : null}
      {subs.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {subs.map((s) => (
            <div key={s.id} className="rounded border border-line p-3" data-subtrack={s.id}>
              <h3 className="text-[0.875rem] font-semibold text-fg">
                <TextLink to={trackPath(s.id)}>{s.name}</TextLink>{' '}
                <span className="font-normal text-fg-3">· {plural(s.count, 'post')}</span>
              </h3>
              <p className="text-[0.75rem] text-fg-3">
                {s.rest ? 'The rest of this track' : s.stack.length ? `Your stack: ${s.stack.map((t) => t.name).join(', ')}` : 'Judged'}
                {s.sort === 'news' ? ' · ranked as News ranks them' : ''}
              </p>
              {s.items.length ? (
                <ul className="mt-1">
                  {s.items.map((it) => (
                    <li key={it.post_id} className="truncate text-[0.8125rem] leading-6 text-fg-2">
                      {it.title || it.url || 'Untitled'}{it.source ? <span className="text-fg-3"> · {it.source}</span> : null}
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-1 text-[0.8125rem] text-fg-2">Nothing yet.</p>}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

/**
 * v10.42: the reader's stack: the things they use (entities). A sub-track with a stack holds the parent's posts that
 * name one of them (or a thing under one) and that its judge keeps. Add from the picker, remove with ×; a change is a
 * new version (its posts asked again). Shown on a sub-track and on any track that has a stack.
 */
export function StackEditor({ page, queryKey }: { page: TrackPage; queryKey: readonly unknown[] }) {
  const client = useQueryClient();
  const stack = page.track.stack ?? [];
  const [q, setQ] = useState('');
  const words = q.trim();
  const found = useQuery({
    queryKey: ['markx-track-stack-find', page.track.id, words],
    queryFn: () => tracksApi.findThings(page.track.id, words),
    enabled: words.length >= 2, staleTime: 60_000,
  });
  const save = useMutation({
    mutationFn: (things: StackThing[]) => tracksApi.setStack(page.track.id, things.map((t) => t.id)),
    onSuccess: (got) => { client.setQueryData(queryKey, got); setQ(''); },
  });
  if (!page.track.parent && !stack.length) return null;
  const has = new Set(stack.map((t) => t.id));
  return (
    <section aria-label="Your stack" className="mb-4 rounded border border-line p-3">
      <h3 className="text-[0.8125rem] font-semibold text-fg-2">Your stack</h3>
      <p className="text-[0.75rem] text-fg-3">The things you use. Posts about them that help you act go here; changing it reads the posts again.</p>
      <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Things you use">
        {stack.map((t) => (
          <li key={t.id} className="flex items-center gap-1 rounded border border-line px-2 py-0.5 text-[0.8125rem]" data-stack-thing={t.id}>
            {t.name}
            <Button size="sm" variant="ghost" className="h-auto px-1 text-[0.75rem]" aria-label={`Remove ${t.name}`}
              disabled={save.isPending} onClick={() => save.mutate(stack.filter((x) => x.id !== t.id))}>×</Button>
          </li>
        ))}
        {!stack.length ? <li className="text-[0.8125rem] text-fg-2">Nothing yet.</li> : null}
      </ul>
      <Input className="mt-2" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Add a thing you use (GrapheneOS, a browser, a distro)"
        aria-label="Find a thing to add" />
      {words.length >= 2 && found.data ? (
        <ul className="mt-1" aria-label="Things found">
          {found.data.filter((t) => !has.has(t.id)).map((t) => (
            <li key={t.id}>
              <Button size="sm" variant="ghost" className="text-[0.8125rem]" disabled={save.isPending}
                onClick={() => save.mutate([...stack, t])}>
                + {t.name}<span className="ml-1 text-fg-3">{t.type ?? ''} · {plural(t.mentions, 'mention')}</span>
              </Button>
            </li>
          ))}
          {!found.data.length ? <li className="text-[0.8125rem] text-fg-2">No thing by that name yet.</li> : null}
        </ul>
      ) : null}
      {save.isError ? <p role="alert" className="text-[0.75rem] text-fg">× not saved: {errorMessage(save.error)}</p> : null}
    </section>
  );
}
