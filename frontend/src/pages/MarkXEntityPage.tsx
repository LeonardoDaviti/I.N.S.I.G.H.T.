import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { Button, ExternalLink, Page, PageHeader, TextLink } from '../components/ui';
import { ErrorState, LoadingState } from '../components/states';
import { Accuracy, EntityPostLine, QueueItem, SurgeMark, entityHref, entityMeta } from '../components/markx/MarkXEntities';
import { useApi } from '../services/ApiContext';
import { plural } from '../lib/format';
import type { MarkxEntityPage as EntityPageData, MarkxOlderPost, MarkxRabbitHole } from '../services/markx';
import { errorMessage } from '../lib/apiError';

const RULES: Record<string, string> = {
  identifier: 'by its identifier', title: 'by its title', maker: 'on its maker’s site', lookup: 'looked up by its title',
};
const KINDS: Record<string, string> = { paper: 'paper', release: 'release page', code: 'code', demo: 'demo' };

/** 0138: the entity's original first: the stored post when INSIGHT has it, else the page with how it was found. */
export function Original({ d }: { d: EntityPageData }) {
  const o = d.original;
  if (!o && !d.addresses?.length) return null;
  return (
    <section aria-label="Original">
      <h2 className={H2}>Original</h2>
      {o ? (
        <p className="mt-2 text-[0.8125rem] text-fg-2">
          {o.post
            ? <TextLink to={`/posts/${encodeURIComponent(o.post.id)}`}>{o.post.title || o.url}</TextLink>
            : <ExternalLink href={o.url}>{o.url}</ExternalLink>}
          <span className="text-fg-3">
            {` · ${KINDS[o.kind] ?? o.kind}, found ${RULES[o.rule] ?? o.rule}`}
            {o.post ? (o.post.collected ? ' · collected original' : ' · in INSIGHT') : o.asked ? ` · ${o.asked.outcome.replace('_', ' ')}` : ' · not collected yet'}
          </span>
        </p>
      ) : null}
      {d.addresses?.length ? (
        <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
          {d.addresses.map((a) => <li key={a.url}><ExternalLink href={a.url}>{KINDS[a.kind] ?? a.kind}</ExternalLink></li>)}
        </ul>
      ) : null}
    </section>
  );
}

const followHref = (url: string) => `/sources?follow=${encodeURIComponent(url)}`;
const SITE_STATE: Record<string, string> = { followed: 'Followed ✓', stored: 'Stored ✓' };

/**
 * 0138 E3, the rabbit hole: the entity's sites (Follow or Watch page through Add source: the feed finder, then page
 * watching), its works (Collect: the save path) and its people. "Go down the rabbit hole" collects every work not stored,
 * then opens Add source on the first site you don't follow; nothing is followed without your tap there.
 */
export function RabbitHole({ hole, entityId }: { hole: MarkxRabbitHole; entityId: string }) {
  const api = useApi();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const collect = async (urls: string[]) => {
    let done = 0;
    for (const url of urls) {
      setBusy(`Collecting ${done + 1} of ${urls.length}…`);
      try {
        await api.savePage(url);
        done += 1;
      } catch (error: unknown) {
        toast.error(`Could not collect ${url}: ${errorMessage(error)}`);
      }
    }
    setBusy(null);
    if (done) toast(`Collected ${plural(done, 'work')}`);
    void client.invalidateQueries({ queryKey: ['markx-entity', entityId] });
  };
  const open = hole.sites.find((s) => s.state !== 'followed' && s.state !== 'stored');
  const missing = hole.works.filter((w) => w.url && !w.stored).map((w) => w.url as string);
  const dive = async () => {
    if (missing.length) await collect(missing);
    if (open) navigate(followHref(open.url));
  };
  return (
    <section aria-label="The rabbit hole">
      <h2 className={H2}>The rabbit hole</h2>
      {hole.sites.length ? (
        <ul className="mt-2 space-y-1 text-[0.8125rem] text-fg-2">
          {hole.sites.map((site) => (
            <li key={site.url} className="flex flex-wrap gap-x-3">
              <ExternalLink href={site.url}>{site.host}</ExternalLink>
              {SITE_STATE[site.state] ? <span className="text-fg-3">{SITE_STATE[site.state]}</span>
                : <TextLink to={followHref(site.url)}>{site.state === 'page' ? 'Watch page' : 'Follow'}</TextLink>}
            </li>
          ))}
        </ul>
      ) : null}
      {hole.works.length ? (
        <ul className="mt-2 space-y-1 text-[0.8125rem] text-fg-2">
          {hole.works.map((w) => (
            <li key={w.id} className="flex flex-wrap gap-x-3">
              <TextLink to={entityHref(w.id)}>{w.name}</TextLink>
              {w.stored && w.post_id ? <TextLink to={`/posts/${encodeURIComponent(w.post_id)}`} muted>Stored ✓</TextLink>
                : w.url ? <button type="button" className="text-fg underline-offset-2 hover:underline" disabled={busy !== null}
                  onClick={() => void collect([w.url as string])}>Collect</button>
                  : <span className="text-fg-3">no page known</span>}
            </li>
          ))}
        </ul>
      ) : null}
      {hole.people.length ? (
        <p className="mt-2 text-[0.8125rem] text-fg-2">People: {hole.people.map((p, n) => (
          <span key={p.id}>{n ? ', ' : ''}<TextLink to={entityHref(p.id)}>{p.name}</TextLink></span>))}</p>
      ) : null}
      {open || missing.length ? (
        <Button size="sm" variant="secondary" className="mt-3" disabled={busy !== null} onClick={() => void dive()}>
          {busy ?? 'Go down the rabbit hole'}
        </Button>
      ) : null}
    </section>
  );
}

/** 0138: an entity no post's current reading names: the posts an earlier guide named it in, and what each names now. */
export function Older({ older }: { older: MarkxOlderPost[] }) {
  const guides = [...new Set(older.map((p) => p.guide))].join(', ');
  return (
    <section aria-label="Named by an earlier guide">
      <p className="text-[0.8125rem] text-fg-2">
        Not named in any post&rsquo;s current reading. An earlier guide ({guides}) named it in {plural(older.length, 'post')}:
      </p>
      <ul className="mt-2 space-y-1">
        {older.map((p) => (
          <li key={p.id} className="text-[0.8125rem] text-fg-2">
            <TextLink to={`/posts/${encodeURIComponent(p.id)}`} muted>{p.title || '(no title)'}</TextLink>
            <span className="text-fg-3">{p.source ? ` · ${p.source}` : ''} · “{p.span}”</span>
            <span className="text-fg-3">
              {' · now about '}
              {p.now.length ? p.now.map((x, n) => (
                <span key={`${x.id ?? x.name}-${n}`}>{n ? ', ' : ''}{x.id ? <TextLink to={entityHref(x.id)}>{x.name}</TextLink> : x.name}</span>
              )) : 'nothing it names as a subject'}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';

/**
 * An entity's page, `/markx/entities/<id>` (0119 A3, 0115 Decided 3): every post naming it in every role, grouped by
 * its Mark X stories (most voices first), the posts in no story last; every source with its counts; its family and
 * versions as links. Read posts stay, dimmed. A merged entity's id opens its group's page. 0133: a document shows who
 * published it and the posts citing it as evidence or recommending it; an org or person, what it published. 0138: its
 * Original first (and its code, demo, other pages); one no current reading names lists the posts an earlier guide named
 * it in, with what each names now.
 */
export default function MarkXEntityPage() {
  const { entityId = '' } = useParams();
  const api = useApi();
  const query = useQuery({ queryKey: ['markx-entity', entityId], queryFn: () => api.getMarkxEntity(entityId), staleTime: 30_000 });
  if (query.isPending) return <Page><LoadingState label="Loading" rows={6} /></Page>;
  if (query.isError) return <Page><ErrorState error={query.error} onRetry={() => query.refetch()} /></Page>;
  const d = query.data;
  const e = d.entity;
  return (
    <Page>
      <PageHeader title={e.name} meta={`${entityMeta(e)} · ${plural(d.voices, 'source')} · ${plural(d.posts, 'post')}`}>
        <div className="space-y-8">
          <p className="text-[0.8125rem] text-fg-2">
            <TextLink to="/markx?tab=entities" muted>Mark X entities</TextLink>
            {d.maker ? <> · by <TextLink to={entityHref(d.maker.id)}>{d.maker.name}</TextLink></> : null}
            {d.family ? <> · family <TextLink to={entityHref(d.family.id)}>{d.family.name}</TextLink></> : null}
            {d.published_by?.length ? <> · published by {d.published_by.map((p, n) => (
              <span key={p.id}>{n ? ', ' : ''}<TextLink to={entityHref(p.id)}>{p.name}</TextLink></span>))}</> : null}
            {d.aliases.length > 1 ? ` · also written ${d.aliases.filter((a) => a !== e.name).join(', ')}` : ''}
            {' '}<SurgeMark surges={d.surges} />
          </p>
          <Original d={d} />
          {d.current === false && d.older?.length ? <Older older={d.older} /> : null}
          {d.rabbit_hole ? <RabbitHole hole={d.rabbit_hole} entityId={entityId} /> : null}
          <Accuracy accuracy={d.accuracy} />
          {d.versions.length ? (
            <section aria-label="Versions">
              <h2 className={H2}>{d.family ? 'Other versions of the family' : 'Versions'}</h2>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
                {d.versions.map((v) => (
                  <li key={v.id}>{v.id === e.id ? <span className="font-semibold text-fg">{v.name}</span>
                    : <TextLink to={entityHref(v.id)}>{v.name}</TextLink>}</li>
                ))}
              </ul>
            </section>
          ) : null}
          {d.published?.length ? (
            <section aria-label="Published">
              <h2 className={H2}>Published</h2>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
                {d.published.map((w) => <li key={w.id}><TextLink to={entityHref(w.id)}>{w.name}</TextLink></li>)}
              </ul>
            </section>
          ) : null}
          {d.citing?.length ? (
            <section aria-label="Cited as evidence">
              <h2 className={H2}>Cited as evidence · {plural(d.citing.length, 'post')}</h2>
              <ul className="mt-2 space-y-1">{d.citing.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
            </section>
          ) : null}
          {d.recommending?.length ? (
            <section aria-label="Recommended">
              <h2 className={H2}>Recommended · {plural(d.recommending.length, 'post')}</h2>
              <ul className="mt-2 space-y-1">{d.recommending.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
            </section>
          ) : null}
          {d.queue.length ? (
            <section aria-label="To review">
              <h2 className={H2}>To review</h2>
              <ul>{d.queue.map((item) => <QueueItem key={item.id} item={item} />)}</ul>
            </section>
          ) : null}
          {d.stories.map((s) => (
            <section key={s.story} aria-label={s.headline ?? 'A Mark X story'}>
              <h2 className={H2}>{s.headline ?? 'A Mark X story'} · {plural(s.voices, 'source')}</h2>
              <ul className="mt-2 space-y-1">{s.posts.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
            </section>
          ))}
          {d.loose.length ? (
            <section aria-label="In no story">
              <h2 className={H2}>In no Mark X story · {plural(d.loose.length, 'post')}</h2>
              <ul className="mt-2 space-y-1">{d.loose.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
            </section>
          ) : null}
          <section aria-label="Sources">
            <h2 className={H2}>Sources</h2>
            <ul className="mt-2 text-[0.8125rem] text-fg-2">
              {d.sources.map((s) => (
                <li key={s.id} className="flex gap-3 border-t border-line py-1.5">
                  <span className="min-w-0 flex-1 truncate text-fg">{s.name ?? 'a source'}</span>
                  <span className="tabular-nums">{plural(s.posts, 'post')}{s.reports ? ` · ${s.reports} about it` : ''}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </PageHeader>
    </Page>
  );
}
