import { useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { MarkxDiscussion as View, MarkxDiscussionComment } from '../../services/markx';
import { plural } from '../../lib/format';
import { formatLocalDateTime } from '../../lib/dates';

/**
 * The post page's "Discussion" (0280): what the post's Hacker News or Lobsters thread adds beyond the post, read by
 * the worker: one line of stance, points (each with its quote and the comments it cites, expandable), the tools the
 * comments name, and the thread's link. Folded. A thread nobody asked for yet is wanted once on open of the page
 * (the jobs process fetches it).
 */
export default function MarkXDiscussion({ postId }: { postId: string }) {
  const api = useApi();
  const client = useQueryClient();
  const key = ['markx-discussion', postId];
  const query = useQuery({ queryKey: key, queryFn: () => api.getMarkxDiscussion(postId), staleTime: 60_000 });
  const data = query.data;
  const asked = useRef(false);
  useEffect(() => {
    if (!data?.thread || data.wanted || asked.current) return;
    asked.current = true;
    void api.wantMarkxDiscussion(postId).then(() => client.invalidateQueries({ queryKey: key })).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.thread, data?.wanted, postId]);
  if (!data?.thread) return null;
  const t = data.thread;
  const meta = [
    data.status === 'answered' && data.points.length ? plural(data.points.length, 'point') : null,
    t.total != null ? `${plural(t.total, 'comment')} on ${t.name}` : `on ${t.name}`,
  ].filter(Boolean).join(' · ');

  return (
    <details data-discussion className="group mt-4 rounded-md border border-line text-[0.8125rem] leading-5">
      <summary className="flex cursor-pointer list-none items-baseline gap-3 px-4 py-2.5 font-medium text-fg-2 [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="inline-block h-5 w-3 shrink-0 self-start text-center leading-5 text-fg-3 group-open:rotate-90">›</span>
        Discussion
        <span className="font-normal text-fg-3">{meta}</span>
      </summary>
      <div className="border-t border-line px-4 py-3 text-fg-2">
        {data.status === 'waiting' ? <p className="text-fg-3">Reading the thread…</p> : null}
        {data.status === 'fetched' ? <p className="text-fg-3">Comments fetched; the worker reads them next.</p> : null}
        {data.status === 'answered' && data.stance ? <p data-stance className="mb-3 text-fg">{data.stance}</p> : null}
        {data.status === 'answered' && !data.points.length ? <p className="text-fg-3">Nothing the post doesn’t say.</p> : null}
        {data.points.length ? (
          <ul className="space-y-3">
            {data.points.map((p, i) => <Point key={i} point={p} comments={data.comments} />)}
          </ul>
        ) : null}
        {data.tools.length ? (
          <p data-tools className="mt-3 text-fg-3">
            Mentioned:{' '}
            {data.tools.map((tool, i) => (
              <span key={i}>
                {i ? ', ' : ''}
                {tool.url ? <a href={tool.url} target="_blank" rel="noopener noreferrer" className="text-link">{tool.name}</a> : tool.name}
                {tool.what ? <span> ({tool.what})</span> : null}
              </span>
            ))}
          </p>
        ) : null}
        <p className="mt-3 text-[0.75rem] text-fg-3">
          <a href={t.url} target="_blank" rel="noopener noreferrer" className="text-link">the thread on {t.name}</a>
          {t.total != null ? ` · ${plural(t.total, 'comment')}` : ''}
          {t.kept != null && t.total != null && t.kept < t.total ? `, ${t.kept} read` : ''}
          {t.fetched_at ? ` · fetched ${formatLocalDateTime(t.fetched_at) ?? ''}` : ''}
        </p>
      </div>
    </details>
  );
}

function Point({ point, comments }: { point: View['points'][number]; comments: Record<string, MarkxDiscussionComment> }) {
  const cited = point.comments.map((c) => comments[c]).filter(Boolean);
  return (
    <li data-point>
      <span className="mr-1.5 rounded-sm border border-line px-1 text-[0.6875rem] text-fg-3">{point.kind}</span>
      <span className="text-fg">{point.text}</span>
      <blockquote className="mt-1 border-l border-line-strong pl-2 text-fg-3">“{point.quote}”</blockquote>
      {cited.length ? (
        <details className="mt-1">
          <summary className="cursor-pointer text-[0.75rem] text-fg-3">{plural(cited.length, 'comment')}</summary>
          <ol className="mt-1 space-y-2">
            {cited.map((c) => (
              <li key={c.id} data-comment={c.id} className="border-l border-line pl-2">
                <div className="text-[0.75rem] text-fg-3">
                  <span className="font-semibold text-fg-2">{c.author || 'unknown'}</span>
                  {' · '}
                  <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-link">open</a>
                </div>
                <div className="whitespace-pre-wrap text-fg [overflow-wrap:anywhere]">{c.text}</div>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </li>
  );
}
