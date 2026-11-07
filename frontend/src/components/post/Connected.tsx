import { useState } from 'react';
import { Link } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { ConnectedRow, PostConnected } from '../../services/api';
import { ExternalLink } from '../ui/TextLink';
import { FOCUS_RING } from '../states';
import { feedDateLabel, feedFullTime } from '../../lib/dates';
import { middleTruncate } from '../../lib/format';
import { sourceLabel } from '../../lib/sourceLabel';
import { LINE_NAME, LINE_TITLE } from '../../lib/story';
import { SAVE_PATH } from '../../lib/savePage';

/**
 * "Connected" on the post page (issue 0125), after the text and before its story: the author's own links, read by
 * rules, no model. Earlier: the stored posts it links, in the text's order; Later: the stored posts that link it,
 * oldest first; Outside INSIGHT: the pages it links that INSIGHT doesn't store, which open the page (Save any page
 * offers "Fetch <source>" when a followed source owns it, issue 0122: a click, nothing fetched by itself). Under a
 * row, in quotes, the line the author gave for it. Loaded after the post, never holding it; nothing shows while it
 * loads, when it fails or when the post has no connection. On a phone the groups fold, Earlier open. Its own chunk,
 * so the reader's initial JS does not grow.
 */
export default function Connected({ postId }: { postId: string }) {
  const api = useApi();
  const [all, setAll] = useState(false);
  const [phone] = useState(isPhone);
  const query = useQuery({
    queryKey: ['post-connected', postId, all],
    queryFn: () => api.getPostConnected(postId, all),
    staleTime: 60_000,
    retry: false,
    placeholderData: keepPreviousData,
  });
  const data = query.data;
  if (!data || !(data.earlier.length + data.later.length + data.outside.length)) return null;
  const more = (group: keyof PostConnected['more']) => (all ? 0 : data.more?.[group] ?? 0);
  return (
    <section id="connected" data-connected aria-label="Connected" className="mt-8 text-[0.8125rem] leading-5 text-fg-3">
      <p>Connected</p>
      <Group label="Earlier" rows={data.earlier} more={more('earlier')} open onMore={() => setAll(true)} />
      <Group label="Later" rows={data.later} more={more('later')} open={!phone} onMore={() => setAll(true)} />
      <Group label="Outside INSIGHT" rows={data.outside} more={more('outside')} open={!phone} onMore={() => setAll(true)} outside />
    </section>
  );
}

/** A phone (below Tailwind's `sm`), read once when the block mounts. */
function isPhone(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 639px)').matches;
}

function Group({ label, rows, more, open, onMore, outside = false }: {
  label: string; rows: ConnectedRow[]; more: number; open: boolean; onMore: () => void; outside?: boolean;
}) {
  if (!rows.length) return null;
  const now = new Date();
  return (
    <details open={open} aria-label={label} className="group mt-1">
      <summary className="flex cursor-pointer list-none items-baseline gap-1.5 [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="inline-block w-3 shrink-0 text-center group-open:rotate-90">›</span>
        {label}
        <span className="tabular-nums">· {rows.length + more}</span>
      </summary>
      <ul className="mt-1 flex flex-col gap-1.5 border-l border-line pl-3">
        {rows.map((row) => (outside ? <OutsideRow key={row.address ?? row.url} row={row} /> : <StoredRow key={row.post_id} row={row} now={now} />))}
      </ul>
      {more ? (
        <button type="button" onClick={onMore}
          className={`ml-3 mt-1 rounded-sm text-fg-2 underline-offset-4 hover:underline hover:decoration-fg-3 ${FOCUS_RING}`}>
          +{more} more
        </button>
      ) : null}
    </details>
  );
}

/** The reason line, in quotes: not when it only repeats the row's title. */
function Reason({ row }: { row: ConnectedRow }) {
  if (!row.reason || (row.reason_kind === 'title' && row.reason === row.title)) return null;
  return <q dir="auto" className="mt-0.5 block text-fg-3 [overflow-wrap:anywhere]">{row.reason}</q>;
}

function StoredRow({ row, now }: { row: ConnectedRow; now: Date }) {
  return (
    <li>
      <div className="flex min-w-0 items-baseline gap-x-1.5 max-sm:flex-wrap">
        <span className={LINE_NAME} title={sourceLabel(row.source ?? '')}>{middleTruncate(sourceLabel(row.source ?? ''), 32)}</span>
        <span aria-hidden="true" className="shrink-0 max-sm:hidden">·</span>
        <Link to={`/posts/${encodeURIComponent(row.post_id ?? '')}`} dir="auto"
          className={`${LINE_TITLE} rounded-sm text-fg-2 underline-offset-4 hover:underline hover:decoration-fg-3 ${FOCUS_RING}`}>
          {row.title?.trim() || 'Untitled post'}
        </Link>
        {row.same_source ? <span className="shrink-0">· same source</span> : null}
        {row.date ? (
          <time dateTime={row.date} title={feedFullTime(row.date)} className="ml-auto shrink-0 pl-2 tabular-nums">
            {feedDateLabel(row.date, now)}
          </time>
        ) : null}
      </div>
      <Reason row={row} />
    </li>
  );
}

function OutsideRow({ row }: { row: ConnectedRow }) {
  const save = new URLSearchParams({ url: row.url });
  if (row.title) save.set('title', row.title);
  return (
    <li>
      <div className="flex min-w-0 items-baseline gap-x-1.5 max-sm:flex-wrap">
        <span className={LINE_NAME} title={row.host}>{middleTruncate(row.host ?? '', 32)}</span>
        <span aria-hidden="true" className="shrink-0 max-sm:hidden">·</span>
        <ExternalLink href={row.url} dir="auto" title={row.address ?? row.url} className={`${LINE_TITLE} text-fg-2`}>
          {row.title?.trim() || row.address || row.url}
        </ExternalLink>
        <Link to={`${SAVE_PATH}?${save.toString()}`} title="Save it to INSIGHT (fetching its source first when you follow it)"
          className={`ml-auto shrink-0 rounded-sm pl-2 underline-offset-4 hover:underline hover:decoration-fg-3 ${FOCUS_RING}`}>
          Save
        </Link>
      </div>
      <Reason row={row} />
    </li>
  );
}
