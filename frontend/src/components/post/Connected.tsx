import { useState } from 'react';
import { Link } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { ConnectedRow, PostConnected, PostConnectedSeries, PostSeries, SeriesPart } from '../../services/api';
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
 *
 * Above it (issue 0134), the Series line: "Part 3 of 4 in <name>" with the stored parts in order and prev / next, or
 * "Issue #136 of <name>" with the previous and next issues. The same-source links that are series navigation ("the
 * previous part") show there, not as Earlier or Later rows.
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
  const data = query.data as PostConnectedSeries | undefined;
  if (!data) return null;
  const series = data.series ?? null;
  const parts = new Set(series?.parts.map((p) => p.post_id) ?? []);
  const navigation = (data.navigation ?? []).filter((r) => !parts.has(r.post_id ?? ''));
  const rows = data.earlier.length + data.later.length + data.outside.length;
  if (!rows && !series && !navigation.length) return null;
  const more = (group: keyof PostConnected['more']) => (all ? 0 : data.more?.[group] ?? 0);
  return (
    <section id="connected" data-connected aria-label="Connected" className="mt-8 text-[0.8125rem] leading-5 text-fg-3">
      {series || navigation.length ? <SeriesLine series={series} navigation={navigation} phone={phone} /> : null}
      {rows ? <p>Connected</p> : null}
      <Group label="Earlier" rows={data.earlier} more={more('earlier')} open onMore={() => setAll(true)} />
      <Group label="Later" rows={data.later} more={more('later')} open={!phone} onMore={() => setAll(true)} />
      <Group label="Outside INSIGHT" rows={data.outside} more={more('outside')} open={!phone} onMore={() => setAll(true)} outside />
    </section>
  );
}

/** "Part 3 of 4 in <name>" / "Issue #136 of <name>": what the post is in its series. */
function seriesLabel(s: PostSeries): string {
  if (s.kind === 'column') return s.number ? `Issue #${s.number} of ${s.name}` : `An issue of ${s.name}`;
  return `Part ${s.number ?? s.position} of ${s.total} in ${s.name}`;
}

function SeriesLine({ series, navigation, phone }: {
  series: PostSeries | null; navigation: ConnectedRow[]; phone: boolean;
}) {
  const now = new Date();
  return (
    <div data-series aria-label="Series" className="mb-4">
      {series ? (
        <>
          <p dir="auto" className="text-fg-2">{seriesLabel(series)}</p>
          <nav aria-label="Series navigation" className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            {series.prev ? <PartLink part={series.prev} label={series.kind === 'column' ? '‹ Previous issue' : '‹ Previous part'} /> : null}
            {series.next ? <PartLink part={series.next} label={series.kind === 'column' ? 'Next issue ›' : 'Next part ›'} /> : null}
          </nav>
          {series.kind === 'series' && series.parts.length > 1 ? (
            <details open={!phone} aria-label="Parts" className="group mt-1">
              <summary className="flex cursor-pointer list-none items-baseline gap-1.5 [&::-webkit-details-marker]:hidden">
                <span aria-hidden="true" className="inline-block w-3 shrink-0 text-center group-open:rotate-90">›</span>
                Parts <span className="tabular-nums">· {series.count}</span>
              </summary>
              <ol className="mt-1 flex flex-col gap-1 border-l border-line pl-3">
                {series.parts.map((p) => (
                  <li key={p.post_id} className="flex min-w-0 items-baseline gap-x-1.5">
                    {p.number ? <span className="shrink-0 tabular-nums">{p.number}.</span> : null}
                    {p.current ? (
                      <span aria-current="true" dir="auto" className={`${LINE_TITLE} text-fg font-medium`}>{p.title?.trim() || 'This post'}</span>
                    ) : (
                      <Link to={`/posts/${encodeURIComponent(p.post_id)}`} dir="auto"
                        className={`${LINE_TITLE} rounded-sm text-fg-2 underline-offset-4 hover:underline hover:decoration-fg-3 ${FOCUS_RING}`}>
                        {p.title?.trim() || 'Untitled post'}
                      </Link>
                    )}
                    {p.date ? (
                      <time dateTime={p.date} title={feedFullTime(p.date)} className="ml-auto shrink-0 pl-2 tabular-nums">
                        {feedDateLabel(p.date, now)}
                      </time>
                    ) : null}
                  </li>
                ))}
              </ol>
            </details>
          ) : null}
        </>
      ) : null}
      {navigation.length ? (
        <div aria-label="Series links" className="mt-1">
          <p>{series ? 'Also linked as part of a series' : 'Series links'}</p>
          <ul className="mt-1 flex flex-col gap-1.5 border-l border-line pl-3">
            {navigation.map((row) => <StoredRow key={row.post_id} row={row} now={now} />)}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function PartLink({ part, label }: { part: SeriesPart; label: string }) {
  return (
    <Link to={`/posts/${encodeURIComponent(part.post_id)}`} title={part.title ?? undefined}
      className={`rounded-sm text-fg-2 underline-offset-4 hover:underline hover:decoration-fg-3 ${FOCUS_RING}`}>
      {label}
    </Link>
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
