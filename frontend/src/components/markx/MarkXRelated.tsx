import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { MarkxRelated as Related } from '../../services/markx';
import { TextLink } from '../ui';
import { postBylineTime } from '../../lib/dates';
import { bylineText } from '../../lib/byline';

/**
 * The post page's "Related reading" (v10.36): the posts nearest this one by its stored vector, guides and explainers
 * on its subject as well as its news, each line title · source · date opening its post page. Folded, and asked only
 * when opened: the list is a scan of every stored vector (~1.5 s), so the page never waits for it. v10.37: the page a
 * short report is about first ("the page it reports"); when few are close, the nearest under "loosely related".
 */
export default function MarkXRelated({ postId }: { postId: string }) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const query = useQuery({ queryKey: ['markx-related', postId], queryFn: () => api.getMarkxRelated(postId), enabled: open,
    staleTime: 5 * 60_000 });
  const data = query.data;
  const close = data?.items.filter((r) => !r.loose) ?? [];
  const loose = data?.items.filter((r) => r.loose) ?? [];

  return (
    <details data-related className="group mt-4 rounded-md border border-line text-[0.8125rem] leading-5"
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
      <summary className="flex cursor-pointer list-none items-baseline gap-3 px-4 py-2.5 font-medium text-fg-2 [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="inline-block h-5 w-3 shrink-0 self-start text-center leading-5 text-fg-3 group-open:rotate-90">›</span>
        Related reading
        <span className="font-normal text-fg-3">nearest by meaning, in any language</span>
      </summary>
      <div className="border-t border-line px-4 py-3 text-fg-2">
        {query.isPending ? <p className="text-fg-3">Finding related posts…</p> : null}
        {query.isError ? <p className="text-fg">× Could not load related reading.</p> : null}
        {data && !data.vector ? <p className="text-fg-3">Not embedded yet: the worker embeds the newest posts first.</p> : null}
        {data?.vector && !data.items.length ? <p className="text-fg-3">Nothing close enough.</p> : null}
        {close.length ? <RelatedList items={close} /> : null}
        {loose.length ? (
          <>
            <p data-loose className={`${close.length ? 'mt-3 ' : ''}mb-1.5 text-[0.75rem] text-fg-3`}>loosely related</p>
            <RelatedList items={loose} />
          </>
        ) : null}
      </div>
    </details>
  );
}

function Tag({ children }: { children: string }) {
  return <> <span className="rounded-sm border border-line px-1 text-[0.6875rem] text-fg-3">{children}</span></>;
}

function RelatedList({ items }: { items: Related['items'] }) {
  return (
    <ul className="space-y-1.5">
      {items.map((r) => (
        <li key={r.id} className="[overflow-wrap:anywhere]">
          <TextLink to={`/posts/${encodeURIComponent(r.id)}`} muted>{r.title || 'a post'}</TextLink>
          <span className="text-fg-3">
            {r.source ? ` · ${bylineText(r.byline, r.source)}` : ''}{r.at ? ` · ${postBylineTime(r.at)}` : ''}
          </span>
          {r.about ? <Tag>the page it reports</Tag> : null}
          {r.guide ? <Tag>guide</Tag> : null}
        </li>
      ))}
    </ul>
  );
}
