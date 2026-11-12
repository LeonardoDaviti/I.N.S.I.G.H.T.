import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { useApi } from '../../services/ApiContext';
import type { MainSourceResponse, MainSourceRow } from '../../services/api';
import { Button, ExternalLink, TextLink } from '../ui';
import { FOCUS_RING } from '../states';
import { errorMessage } from '../../lib/apiError';
import { plural } from '../../lib/format';
import { eventTypeLabel, followLabel, ownPageLine, rowReason, rowTitle, testLine } from '../../lib/mainSource';
import { untitledLine } from '../../lib/discover';
import { sourceLabel } from '../../lib/sourceLabel';

export const MAIN_SOURCE_KEY = ['main-source-missing'] as const;

/** One row: the channel, why, what its follow test found, its events behind a fold, and its actions. */
function Row({ row, onFollow, onHide, onTurnOn }: {
  row: MainSourceRow; onFollow: (url: string) => void; onHide: (row: MainSourceRow) => void; onTurnOn: (row: MainSourceRow) => void;
}) {
  const [open, setOpen] = useState(false);
  const listId = `main-source-${row.key.replace(/[^a-z0-9]+/gi, '-')}`;
  const follow = followLabel(row);
  return (
    <li className="border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-full sm:basis-0">
          <h3 className="text-[0.9375rem] font-semibold leading-6 text-fg [overflow-wrap:anywhere]">
            {rowTitle(row)}
            <span className="ml-2 text-[0.75rem] font-normal text-fg-3">
              <TextLink to={`/markx/entities/${row.actor.id}`}>{row.actor.name}</TextLink>
            </span>
          </h3>
          <p className="text-[0.8125rem] leading-5 text-fg-2">{rowReason(row)}</p>
          {row.kind !== 'disabled' ? <p className="text-[0.8125rem] leading-5 text-fg-3">{testLine(row.test)}</p> : null}
          <button
            type="button"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen((value) => !value)}
            className={`-ml-1 inline-flex max-w-full items-start gap-1 rounded-sm px-1 text-left text-[0.8125rem] leading-5 text-fg-2 hover:text-fg ${FOCUS_RING}`}
          >
            {open ? <ChevronDown aria-hidden="true" className="mt-1 h-3 w-3 shrink-0" /> : <ChevronRight aria-hidden="true" className="mt-1 h-3 w-3 shrink-0" />}
            <span>The {plural(row.events.length, 'event')}</span>
          </button>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {follow ? <Button size="sm" variant="secondary" onClick={() => onFollow(row.channel.url)}>{follow}</Button> : null}
          {row.kind === 'disabled' && row.source ? (
            <Button size="sm" variant="secondary" onClick={() => onTurnOn(row)}>Turn on</Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={() => onHide(row)}>Not interested</Button>
        </div>
      </div>
      {open ? (
        <ul id={listId} className="mt-2 flex flex-col gap-2 border-l border-line pl-3">
          {row.events.map((event) => (
            <li key={event.story} className="text-[0.8125rem] leading-5 text-fg-3">
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
                <TextLink to={`/markx/stories/${event.story}`} className="min-w-0 text-fg" dir="auto">{event.headline || 'A story'}</TextLink>
                <span className="shrink-0">· {eventTypeLabel(event.event_type)} · {plural(event.voices, 'source')}</span>
              </div>
              {event.own_page ? (
                <div className="flex min-w-0 items-baseline gap-1.5">
                  <span className="shrink-0">Own page:</span>
                  <ExternalLink href={event.own_page.url} className="min-w-0 truncate text-fg" title={event.own_page.url}>
                    {untitledLine(event.own_page.url)}
                  </ExternalLink>
                  <span className="shrink-0 truncate">· {ownPageLine(event.own_page)}</span>
                </div>
              ) : null}
              <ul className="flex flex-col">
                {event.posts.map((post) => (
                  <li key={post.id} className="flex min-w-0 items-baseline gap-1.5">
                    {post.url ? (
                      <ExternalLink href={post.url} dir="auto" className="min-w-0 truncate" title={post.url}>{post.title || untitledLine(post.url)}</ExternalLink>
                    ) : <span className="min-w-0 truncate" dir="auto">{post.title}</span>}
                    <span className="shrink-0 truncate">· {sourceLabel(post.source)}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/**
 * Discover → "The main source is missing" (issue 0170): events your sources covered whose actor's own channel you don't
 * hold (Mark X's stories of 2+ sources; never a lawsuit, a regulator's action, a filing or a scoop), the channel's
 * section to follow, a followed site's other section, or a turned-off source that was the event's own. Follow… opens
 * Add source on the channel (the feed finder, then page watching, as every add); Not interested hides the row for good.
 * Shows nothing when there is nothing, or when Mark X is off.
 */
export default function MainSourceMissing({ onFollow }: { onFollow: (url: string) => void }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: [...MAIN_SOURCE_KEY],
    queryFn: ({ signal }) => api.getMainSourceMissing(signal),
    staleTime: 60_000,
    retry: false,
  });
  const drop = (row: MainSourceRow) => queryClient.setQueryData<MainSourceResponse>([...MAIN_SOURCE_KEY], (current) => (
    current ? { ...current, rows: current.rows.filter((r) => r.key !== row.key), total: Math.max(0, current.total - 1) } : current
  ));
  const hide = (row: MainSourceRow) => {
    drop(row);
    void api.hideSuggestedSource(row.key).then(
      () => toast(`${rowTitle(row)} won’t be suggested again`),
      (error: unknown) => {
        toast.error(`Could not hide ${rowTitle(row)}: ${errorMessage(error)}`);
        void queryClient.invalidateQueries({ queryKey: [...MAIN_SOURCE_KEY] });
      },
    );
  };
  const turnOn = (row: MainSourceRow) => {
    if (!row.source) return;
    const source = row.source;
    // setSourceEnabled settles: a failure is the {success: false, error} envelope
    void api.setSourceEnabled(source.id, true).then((answer) => {
      if (answer.success === false) {
        toast.error(`Could not turn on ${source.name}: ${answer.error ?? 'the request failed'}`);
        return;
      }
      drop(row);
      toast(`${source.name} is on again`);
    });
  };
  const rows = query.data?.rows ?? [];
  if (!rows.length) return null;
  return (
    <section aria-label="The main source is missing" className="mb-2">
      <h2 className="pt-1 text-[0.75rem] font-medium text-fg-3">The main source is missing</h2>
      <p className="text-[0.75rem] text-fg-3">
        Events your sources covered whose maker&rsquo;s own post none of your sources holds, from the pages those posts link.
      </p>
      <ul>
        {rows.map((row) => <Row key={row.key} row={row} onFollow={onFollow} onHide={hide} onTurnOn={turnOn} />)}
      </ul>
    </section>
  );
}
