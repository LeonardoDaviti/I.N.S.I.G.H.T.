import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { tracksApi, type TrackItem, type TrackLabel, type TrackPage } from '../../services/tracks';
import { Button, TextLink } from '../ui';
import { EmptyState, ErrorState, LoadingState } from '../states';
import { postBylineTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import TrackSheet from './TrackSheet';
import TrackScout from './TrackScout';
import { foundByLine, joinLine, precisionLine, rankWords, suggestionLine, footerLine } from './trackWords';

export const trackKey = (id: string) => ['markx-track', id] as const;

function Labels({ folderId, item }: { folderId: string; item: TrackItem }) {
  const client = useQueryClient();
  const [mine, setMine] = useState<TrackLabel | null>(item.label);
  const tap = useMutation({
    mutationFn: (answer: TrackLabel | 'undo') => tracksApi.label(folderId, item.post_id, answer),
    onSuccess: (got) => {
      setMine(got.label);
      void client.invalidateQueries({ queryKey: trackKey(folderId) });
    },
  });
  return (
    <span className="flex shrink-0 items-center gap-1 text-[0.75rem]" role="group" aria-label="Does it belong here?">
      {mine ? (
        <>
          <span className="text-fg-2">{mine === 'in' ? '✓ yours' : '✗ not this'}</span>
          <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={tap.isPending} onClick={() => tap.mutate('undo')}>undo</Button>
        </>
      ) : (
        <>
          <Button size="sm" variant="ghost" className="text-[0.75rem]" aria-label="Belongs in this track" disabled={tap.isPending}
            onClick={() => tap.mutate('in')}>✓</Button>
          <Button size="sm" variant="ghost" className="text-[0.75rem]" aria-label="Does not belong" disabled={tap.isPending}
            onClick={() => tap.mutate('out')}>✗</Button>
        </>
      )}
      {tap.isError ? <span role="alert" className="text-fg">× not saved</span> : null}
    </span>
  );
}

function Row({ folderId, item, discover = false }: { folderId: string; item: TrackItem; discover?: boolean }) {
  return (
    <li className="flex items-start gap-3 border-b border-line py-2.5" data-track-item={item.post_id}>
      <div className="min-w-0 flex-1">
        <p className="text-[0.9375rem] font-semibold leading-[1.35] text-fg [overflow-wrap:anywhere]">
          <TextLink to={`/posts/${encodeURIComponent(item.post_id)}`}>{item.title || '(no title)'}</TextLink>
        </p>
        <p className="mt-0.5 text-[0.8125rem] tabular-nums leading-5 text-fg-3 [overflow-wrap:anywhere]"
          title={foundByLine(item) ?? undefined}>
          {[item.source, item.at ? postBylineTime(item.at) : null,
            item.place === 'joined' ? 'joined by INSIGHT' : null,
            discover ? rankWords(item) : null].filter(Boolean).join(' · ')}
        </p>
        {item.why ? <p className="mt-0.5 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">{item.why}</p> : null}
      </div>
      <Labels folderId={folderId} item={item} />
    </li>
  );
}

function Suggestions({ page }: { page: TrackPage }) {
  const client = useQueryClient();
  const make = useMutation({
    mutationFn: (sourceId: string) => tracksApi.activate(page.track.id, sourceId),
    onSuccess: () => void client.invalidateQueries({ queryKey: trackKey(page.track.id) }),
  });
  if (!page.suggestions.length) return null;
  return (
    <ul aria-label="Sources to make active" className="mb-4">
      {page.suggestions.map((s) => (
        <li key={s.source_id} className="flex flex-wrap items-baseline gap-2 text-[0.8125rem] leading-6 text-fg-2">
          <span>{suggestionLine(s)}</span>
          <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={make.isPending}
            onClick={() => make.mutate(s.source_id)}>make it active</Button>
        </li>
      ))}
    </ul>
  );
}

/**
 * A track as a topic (issue 0145, Mark X): its posts judged against the owner's description, as sections by
 * sub-topic (newest first within), then Discover (passive sources' matches, ranked by calibrated precision), each
 * with ✓ / ✗; the precision and the auto-join bar, the sources it found, and what it costs. A track without a
 * description is a folder: one line and the sheet to describe it.
 */
export default function TrackTopic({ folderId }: { folderId: string }) {
  const [editing, setEditing] = useState(false);
  const query = useQuery({ queryKey: trackKey(folderId), queryFn: () => tracksApi.page(folderId), staleTime: 30_000 });
  if (query.isPending) return <LoadingState label="Loading the topic" rows={6} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Could not load the topic" />;
  const page = query.data;
  const sheet = <TrackSheet key={page.track.version ?? 0} open={editing} onOpenChange={setEditing} page={page} />;
  if (!page.track.topic) {
    return (
      <>
        <EmptyState
          title="This track is a folder of sources"
          description="Describe it in your own words and INSIGHT reads every source for posts that belong here: its own sources' posts go in when they fit, others wait in Discover for your ✓."
          action={{ label: 'Describe this track', onClick: () => setEditing(true) }}
        />
        {sheet}
      </>
    );
  }
  const counts = page.counts;
  return (
    <section aria-label={`${page.track.name} as a topic`}>
      <div className="mb-4 border-b border-line pb-3">
        <p className="text-[0.875rem] leading-6 text-fg [overflow-wrap:anywhere]">{page.track.description}</p>
        {page.track.excludes ? <p className="text-[0.8125rem] leading-5 text-fg-2">Not: {page.track.excludes}</p> : null}
        <p className="mt-1 text-[0.75rem] leading-5 text-fg-3">
          {precisionLine(page.calibration)} · {joinLine(page.calibration)}
          {counts.waiting ? ` · ${plural(counts.waiting, 'post')} waiting for Haiku` : ''}
        </p>
        <Button size="sm" variant="ghost" className="mt-1 text-[0.75rem]" onClick={() => setEditing(true)}>edit the topic</Button>
      </div>
      <Suggestions page={page} />
      {page.sections.length ? page.sections.map((s) => (
        <section key={s.id ?? 'other'} aria-label={s.name} className="mb-6">
          <h2 className="border-b border-line pb-1 text-[0.8125rem] font-semibold text-fg-2">
            {s.name} <span className="font-normal text-fg-3">· {s.count}</span>
          </h2>
          {s.definition ? <p className="mt-1 text-[0.75rem] text-fg-3">{s.definition}</p> : null}
          <ul>{s.items.map((it) => <Row key={it.post_id} folderId={folderId} item={it} />)}</ul>
        </section>
      )) : (
        <p className="mb-6 text-[0.8125rem] text-fg-2">Nothing in this track yet. The worker judges its posts at its next run.</p>
      )}
      <section aria-label="Discover" className="mb-6">
        <h2 className="border-b border-line pb-1 text-[0.8125rem] font-semibold text-fg-2">
          Discover <span className="font-normal text-fg-3">· {counts.discover ?? 0}</span>
        </h2>
        <p className="mt-1 text-[0.75rem] text-fg-3">Posts from your other sources that look like this track. ✓ takes one in; ✗ teaches it what doesn’t belong.</p>
        {page.discover.length ? <ul>{page.discover.map((it) => <Row key={it.post_id} folderId={folderId} item={it} discover />)}</ul>
          : <p className="mt-2 text-[0.8125rem] text-fg-2">Nothing waiting.</p>}
      </section>
      <TrackScout folderId={folderId} />
      {page.footer ? <p className="text-[0.75rem] tabular-nums text-fg-3">{footerLine(page.footer, counts)}</p> : null}
      {sheet}
    </section>
  );
}
