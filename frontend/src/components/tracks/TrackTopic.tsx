import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  tracksApi, type ShadowMeasure, type TrackItem, type TrackLabel, type TrackPage, type TrackSection, type TrackSeen,
  type TrackTool,
} from '../../services/tracks';
import { Button, Input, TextLink } from '../ui';
import { EmptyState, ErrorState, LoadingState } from '../states';
import { postBylineTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import TrackSheet from './TrackSheet';
import TrackScout from './TrackScout';
import {
  baseline, foundByLine, isNew, joinLine, newSince, precisionLine, rankWords, shadowLine, stateWords, suggestionLine, footerLine,
  toolLine, trackNewLine, whyLine,
} from './trackWords';
import { bylineText } from '../../lib/byline';

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

function Row({ folderId, item, discover = false, fresh = false }: {
  folderId: string; item: TrackItem; discover?: boolean; fresh?: boolean;
}) {
  return (
    <li className="flex items-start gap-3 border-b border-line py-2.5" data-track-item={item.post_id} data-new={fresh || undefined}>
      <div className="min-w-0 flex-1">
        <p className="text-[0.9375rem] font-semibold leading-[1.35] text-fg [overflow-wrap:anywhere]">
          {fresh ? <span className="mr-1.5 text-[0.75rem] font-normal text-fg-2" aria-label="new since you looked">new ·</span> : null}
          <TextLink to={`/posts/${encodeURIComponent(item.post_id)}`}>{item.title || '(no title)'}</TextLink>
        </p>
        <p className="mt-0.5 text-[0.8125rem] tabular-nums leading-5 text-fg-3 [overflow-wrap:anywhere]"
          title={foundByLine(item) ?? undefined}>
          {[bylineText(item.byline, item.source), item.at ? postBylineTime(item.at) : null,
            item.place === 'joined' ? 'joined by INSIGHT' : null,
            discover ? rankWords(item) : null].filter(Boolean).join(' · ')}
        </p>
        {item.why ? <p className="mt-0.5 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">{item.why}</p> : null}
      </div>
      <Labels folderId={folderId} item={item} />
    </li>
  );
}

/** Issue 0185: why a post is, or isn't, in this track — Haiku's stored verdict for it, read on demand. */
function WhyNotHere({ folderId }: { folderId: string }) {
  const [post, setPost] = useState('');
  const ask = useMutation({ mutationFn: (ref: string) => tracksApi.why(folderId, ref) });
  return (
    <form className="mb-6" aria-label="Why is a post not here?"
      onSubmit={(e) => { e.preventDefault(); if (post.trim()) ask.mutate(post.trim()); }}>
      <div className="flex items-center gap-2">
        <Input value={post} onChange={(e) => setPost(e.target.value)} placeholder="A post’s link or address"
          aria-label="A post’s link or address" className="h-8 text-[0.8125rem]" />
        <Button size="sm" variant="ghost" type="submit" className="text-[0.75rem]" disabled={ask.isPending || !post.trim()}>
          Why not here?
        </Button>
      </div>
      {ask.data ? <p className="mt-1 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]" data-track-why={ask.data.state}>
        {whyLine(ask.data)}</p> : null}
      {ask.isError ? <p role="alert" className="mt-1 text-[0.8125rem] text-fg">No such post in INSIGHT.</p> : null}
    </form>
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

/** 0207: a sub-topic's digest: each point with the posts it cites, numbered in the order they are first cited. */
function Digest({ section, shadow }: { section: TrackSection; shadow?: ShadowMeasure }) {
  const d = section.digest;
  if (!d?.points.length) return null;
  const order: string[] = [];
  for (const p of d.points) for (const c of p.cites) if (!order.includes(c)) order.push(c);
  const titles = new Map(section.items.map((it) => [it.post_id, it.title ?? '']));
  return (
    <div className="mt-1.5 mb-1 border-l border-line pl-3" aria-label={`Digest of ${section.name}`} data-digest-stale={d.stale || undefined}>
      <ul className="space-y-0.5">
        {d.points.map((p, k) => (
          <li key={k} className="text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
            {p.text}{' '}
            {p.cites.map((c) => (
              <TextLink key={c} to={`/posts/${encodeURIComponent(c)}`} muted className="text-[0.75rem] tabular-nums"
                title={titles.get(c) || undefined}>[{order.indexOf(c) + 1}]</TextLink>
            ))}
          </li>
        ))}
      </ul>
      <p className="mt-0.5 text-[0.6875rem] text-fg-3">
        digest by Haiku{d.stale ? ' · new posts since, a fresh one is on its way' : ''}{shadowLine(shadow) ? ` · ${shadowLine(shadow)}` : ''}
      </p>
    </div>
  );
}

function Section({ folderId, section, since, onSeen, shadow }: {
  folderId: string; section: TrackSection; since: string | null; onSeen: (id: string) => void; shadow?: ShadowMeasure;
}) {
  const [open, setOpen] = useState(section.state !== 'quiet');
  const fresh = newSince(section.joined, since);
  const state = stateWords(section);
  return (
    <section aria-label={section.name} className="mb-6" data-subtopic-state={section.state}>
      <h2 className="flex flex-wrap items-baseline gap-x-2 border-b border-line pb-1 text-[0.8125rem] font-semibold text-fg-2">
        <button type="button" className="text-left" aria-expanded={open} onClick={() => setOpen(!open)}>
          {section.name} <span className="font-normal text-fg-3">· {section.count}</span>
        </button>
        {state ? <span className="font-normal text-fg-3">· {state}</span> : null}
        {fresh ? (
          <>
            <span className="font-normal text-fg">· {fresh} new since you looked</span>
            {section.id ? (
              <Button size="sm" variant="ghost" className="text-[0.75rem] font-normal" onClick={() => onSeen(section.id as string)}>
                mark seen
              </Button>
            ) : null}
          </>
        ) : null}
      </h2>
      {open ? (
        <>
          {section.definition ? <p className="mt-1 text-[0.75rem] text-fg-3">{section.definition}</p> : null}
          <Digest section={section} shadow={shadow} />
          <ul>{section.items.map((it) => <Row key={it.post_id} folderId={folderId} item={it} fresh={isNew(it, since)} />)}</ul>
        </>
      ) : null}
    </section>
  );
}

/** 0207: the tools and products the track's practitioners discuss, by voices, each linked to its entity page. */
function Tools({ tools, shadow }: { tools: TrackTool[]; shadow?: ShadowMeasure }) {
  if (!tools.length) return null;
  return (
    <section aria-label="Tools in use" className="mb-6">
      <h2 className="border-b border-line pb-1 text-[0.8125rem] font-semibold text-fg-2">
        Tools in use <span className="font-normal text-fg-3">· by how many voices here discuss them</span>
        {shadowLine(shadow) ? <span className="ml-1 font-normal text-fg-3" data-shadow="tools">· {shadowLine(shadow)}</span> : null}
      </h2>
      <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        {tools.map((t) => (
          <li key={t.id} className="text-[0.8125rem] leading-6" data-tool={t.id}>
            <TextLink to={`/markx/entities/${encodeURIComponent(t.id)}`} title={t.what ?? undefined}>{t.name}</TextLink>
            <span className="ml-1 tabular-nums text-fg-3">{toolLine(t)}</span>
          </li>
        ))}
      </ul>
    </section>
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
  // 0207: the looks before this visit are what "new since you looked" counts from; this open is recorded as a look
  const [seen, setSeen] = useState<TrackSeen | null>(null);
  const topic = query.data?.track.topic ?? false;
  useEffect(() => {
    if (!topic) return;
    let live = true;
    tracksApi.look(folderId).then((got) => { if (live) setSeen(got.before); }).catch(() => undefined);
    return () => { live = false; };
  }, [folderId, topic]);
  const markSeen = (sub: string) => {
    tracksApi.look(folderId, sub).then((got) => setSeen((was) => ({
      track: was?.track ?? got.before.track, subtopics: { ...(was?.subtopics ?? {}), [sub]: got.now.subtopics[sub] },
    }))).catch(() => undefined);
  };
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
          {trackNewLine(page, seen) ? ` · ${trackNewLine(page, seen)}` : ''}
        </p>
        <Button size="sm" variant="ghost" className="mt-1 text-[0.75rem]" onClick={() => setEditing(true)}>edit the topic</Button>
      </div>
      <Suggestions page={page} />
      <Tools tools={page.tools ?? []} shadow={page.shadow?.tools} />
      {page.sections.some((s) => s.id) && shadowLine(page.shadow?.subtopics) ? (
        <p className="mb-2 text-[0.75rem] text-fg-3" data-shadow="subtopics">
          Sub-topics found and placed by INSIGHT · {shadowLine(page.shadow?.subtopics)}
        </p>
      ) : null}
      {page.sections.length ? page.sections.map((s) => (
        <Section key={s.id ?? 'other'} folderId={folderId} section={s} since={baseline(seen, s.id)} onSeen={markSeen}
          shadow={page.shadow?.digests} />
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
      <WhyNotHere folderId={folderId} />
      <TrackScout folderId={folderId} />
      {page.footer ? <p className="text-[0.75rem] tabular-nums text-fg-3">{footerLine(page.footer, counts)}</p> : null}
      {sheet}
    </section>
  );
}
