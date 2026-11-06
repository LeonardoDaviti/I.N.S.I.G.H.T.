import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import { TextLink } from '../ui';
import { judged, relationWords, whyWords } from '../../lib/markx';
import { plural } from '../../lib/format';

/**
 * The post page's "Mark X" panel (issue 0086 E), folded, loaded only when opened (its own chunk, and only while
 * Mark X is on): the post's reading, its entities and their roles, its Mark X stories with why it is in each, and
 * its connections, each with its reason.
 */
export default function MarkXPanel({ postId }: { postId: string }) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const query = useQuery({ queryKey: ['markx-post', postId], queryFn: () => api.getMarkxPost(postId), enabled: open, staleTime: 60_000 });
  const data = query.data;

  return (
    <details data-markx className="group mt-8 rounded-md border border-line text-[0.8125rem] leading-5"
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
      <summary className="flex cursor-pointer list-none items-baseline gap-3 px-4 py-2.5 font-medium text-fg-2 [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="inline-block h-5 w-3 shrink-0 self-start text-center leading-5 text-fg-3 group-open:rotate-90">›</span>
        Mark X
        <span className="font-normal text-fg-3">Haiku’s reading, in shadow</span>
      </summary>
      <div className="space-y-4 border-t border-line px-4 py-3 text-fg-2">
        {query.isPending ? <p className="text-fg-3">Loading…</p> : null}
        {query.isError ? <p className="text-fg">× Could not load Mark X for this post.</p> : null}
        {data ? (
          <>
            <section aria-label="Reading">
              <h3 className="text-[0.75rem] font-medium text-fg-3">Reading</h3>
              {data.reading ? (
                <p className="mt-1 [overflow-wrap:anywhere]">
                  <span className="text-fg">{data.reading.kind}</span>
                  {data.reading.events ? ` · events: ${data.reading.events}` : ''}
                  {data.reading.lang ? ` · ${data.reading.lang}` : ''}
                  {data.reading.headline ? <span className="block text-fg">{data.reading.headline}</span> : null}
                  {data.reading.mentions.length ? (
                    <span className="block text-fg-3">mentions: {data.reading.mentions.map((m) => `${m.name} (${m.role})`).join(', ')}</span>
                  ) : null}
                </p>
              ) : <p className="mt-1 text-fg-3">Not read yet: the worker reads the newest posts first.</p>}
            </section>
            <section aria-label="Entities">
              <h3 className="text-[0.75rem] font-medium text-fg-3">Entities</h3>
              {data.entities.length ? (
                <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                  {data.entities.map((e, n) => (
                    <li key={n} className="[overflow-wrap:anywhere]">
                      {e.entity_id ? (
                        <TextLink to={`/markx/entities/${encodeURIComponent(e.entity_id)}`}
                                  className={e.role === 'subject' ? 'font-semibold text-fg' : 'text-fg'}>{e.name}</TextLink>
                      ) : <span className={e.role === 'subject' ? 'font-semibold text-fg' : 'text-fg'}>{e.name}</span>}
                      <span className="text-fg-3"> {e.type}{e.version ? ` ${e.version}` : ''} · {e.role}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-1 text-fg-3">None read yet.</p>}
            </section>
            <section aria-label="Mark X stories">
              <h3 className="text-[0.75rem] font-medium text-fg-3">Mark X story</h3>
              {data.stories.length ? (
                <ul className="mt-1 space-y-1.5">
                  {data.stories.map((s) => (
                    <li key={s.id} className="[overflow-wrap:anywhere]">
                      {s.headline ? (
                        <>
                          <span className="text-fg">{s.headline}</span>
                          <span className="text-fg-3"> · {plural(s.posts, 'post')}</span>
                        </>
                      ) : <span className="text-fg">A story of {plural(s.posts, 'post')}</span>}
                      <span className="block">{whyWords(s)}{s.words ? <span className="text-fg-3"> — {s.words}</span> : null}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-1 text-fg-3">In no Mark X story.</p>}
            </section>
            {data.connections.length ? (
              <section aria-label="Connections">
                <h3 className="text-[0.75rem] font-medium text-fg-3">Connections</h3>
                <ul className="mt-1 space-y-1">
                  {data.connections.map((c, n) => (
                    <li key={n} className="[overflow-wrap:anywhere]">
                      <span className="text-fg">{relationWords(c.relation)}</span>{' '}
                      {c.other_kind === 'post' ? (
                        <TextLink to={`/posts/${encodeURIComponent(c.other)}`} muted>{c.title || 'a post'}</TextLink>
                      ) : <span>“{c.title || 'a story'}”</span>}
                      <span className="text-fg-3"> · {c.rule ? `rule ${c.rule}` : judged(c.relation, c.p)}{c.reason ? ` — ${c.reason}` : ''}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
    </details>
  );
}
