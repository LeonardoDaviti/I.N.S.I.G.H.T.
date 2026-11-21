import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { Button, ExternalLink, Page, PageHeader, TextLink } from '../components/ui';
import { ErrorState, LoadingState } from '../components/states';
import { EntityPostLine, MentionContext, QueueItem, SurgeMark, entityHref, entityMeta } from '../components/markx/MarkXEntities';
import { ThingLinks, Timeline, VersionLine } from '../components/markx/MarkXTimeline';   // 0165 C: its timeline
import { EntityBrief } from '../components/markx/EntityBrief';   // 0261: what it is, how it works, its results
import { useApi } from '../services/ApiContext';
import { plural } from '../lib/format';
import type { MarkxEntityPage as EntityPageData, MarkxEntityPost, MarkxEntityStory, MarkxOlderPost, MarkxRabbitHole,
  MarkxEntityHandles, MarkxEntityLimits } from '../services/markx';
import { errorMessage } from '../lib/apiError';
import { request } from '../lib/request';
import { researchStartHref } from '../services/research';
import { bylineText } from '../lib/byline';

type PageCalls = {
  answerMarkxEntitySources: (entity: string, sourceIds: string[], answer: 'yes' | 'no') => Promise<unknown>;
};
/** 0144's calls, here (this page's chunk) and not in api.ts; a test's fake api may provide them. */
function pageCalls(api: object): PageCalls {
  const got = api as Partial<PageCalls>;
  return {
    answerMarkxEntitySources: got.answerMarkxEntitySources ?? ((entity, sourceIds, answer) =>
      request(`/api/markx/entities/${encodeURIComponent(entity)}/sources`, { method: 'POST', body: { source_ids: sourceIds, answer } })),
  };
}

const WHY: Record<string, string> = { by: 'its own post', origin: 'the page it began from', root: 'the first post' };

/** 0144 B2-B3: a Mark X story (or, marked so, the Mark IX story of a post in none) with all its posts, the original
 *  first: the entity's own earliest post, else the story's root (Mark IX's outside page when it began from one). */
export function StoryBlock({ s, onAll }: { s: MarkxEntityStory; onAll?: () => void }) {
  const o = s.original;
  const total = s.posts_total ?? s.posts.length;   // 0277: the first 6 listed by default
  const title = s.headline ?? (s.mark === 'ix' ? 'A Mark IX story' : 'A Mark X story');
  return (
    <section aria-label={title}>
      <h2 className={H2}>
        {s.mark === 'x' ? <TextLink to={`/markx/stories/${encodeURIComponent(s.story)}`} muted>{title}</TextLink> : title}
        {' · '}{plural(s.voices, 'source')} · {plural(total, 'post')}{s.mark === 'ix' ? ' · Mark IX' : ''}
      </h2>
      {o?.url ? (
        <p className="mt-2 text-[0.8125rem] text-fg-2">
          <span className="font-semibold text-fg">Original</span>{' '}
          {o.stored ? <TextLink to={`/posts/${encodeURIComponent(o.stored)}`}>{o.title || o.url}</TextLink>
            : <ExternalLink href={o.url}>{o.title || o.url}</ExternalLink>}
          <span className="text-fg-3"> · {WHY.origin}</span>
        </p>
      ) : null}
      <ul className="mt-2 space-y-1">
        {s.posts.map((p) => (o?.post === p.id ? (
          <li key={p.id} className="text-[0.8125rem]" data-original>
            <span className="font-semibold text-fg">Original</span>{' '}
            <TextLink to={`/posts/${encodeURIComponent(p.id)}`}>{p.title || '(no title)'}</TextLink>
            <span className="text-fg-3">{p.source ? ` · ${bylineText(p.byline, p.source)}` : ''} · {WHY[o.why] ?? o.why}</span>
            {p.context?.length ? <MentionContext parts={p.context} /> : null}
          </li>
        ) : <EntityPostLine key={p.id} post={p} />))}
      </ul>
      {total > s.posts.length && onAll ? (
        <button type="button" className={MORE} onClick={onAll}>All {plural(total, 'post')} of this story</button>
      ) : null}
    </section>
  );
}

const RULES: Record<string, string> = {
  identifier: 'by its identifier', title: 'by its title', maker: 'on its maker’s site', lookup: 'looked up by its title',
};
const KINDS: Record<string, string> = { paper: 'paper', release: 'release page', code: 'code', demo: 'demo', package: 'package' };

/**
 * 0138: the entity's original first: the stored post when INSIGHT has it, else the page with how it was found.
 * 0229: then, apart, the papers and pages its posts cite (never its original).
 */
export function Original({ d }: { d: EntityPageData }) {
  const o = d.original;
  if (!o && !d.addresses?.length && !d.cited?.length) return null;
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
      {!o ? <p className="mt-2 text-[0.8125rem] text-fg-3">No original page found yet.</p> : null}
      {d.cited?.length ? (
        <div aria-label="Cited">
          <h3 className="mt-3 text-[0.8125rem] font-medium text-fg-2">Cited · what its posts cite, not its own page</h3>
          <ul className="mt-1 space-y-1 text-[0.8125rem] text-fg-2">
            {d.cited.map((c) => (
              <li key={c.url}>
                <ExternalLink href={c.url}>{c.url}</ExternalLink>
                <span className="text-fg-3">{` · ${KINDS[c.kind] ?? c.kind}, found ${RULES[c.rule] ?? c.rule}`}</span>
              </li>
            ))}
          </ul>
        </div>
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
  const missingAll = hole.missing ?? missing.length;   // 0277: the answer lists its first 30 works, counts them all
  const dive = async () => {
    let urls = missing;
    if (missingAll > missing.length) {   // every work not stored, from the whole page (?all=true)
      const whole = await api.getMarkxEntity(entityId, undefined, undefined, undefined, true);
      urls = (whole.rabbit_hole?.works ?? []).filter((w) => w.url && !w.stored).map((w) => w.url as string);
    }
    if (urls.length) await collect(urls);
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
      {open || missingAll ? (
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
            <span className="text-fg-3">{p.source ? ` · ${bylineText(p.byline, p.source)}` : ''} · “{p.span}”</span>
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
const MORE = 'mt-2 text-[0.8125rem] text-fg underline-offset-2 hover:underline';   // 0277: an "All N" link

const ROLE_GROUP: Record<string, number> = { subject: 0, actor: 0, by: 1, venue: 2, source: 2, recommended: 2, mention: 3 };
/** 0144 B4: subject or actor (0), by (1), venue / source / recommended (2), mentions (3): the server's order. */
export const looseGroup = (p: MarkxEntityPost) => Math.min(3, ...(p.roles ?? []).map((r) => ROLE_GROUP[r] ?? 3));

/**
 * An entity's page, `/markx/entities/<id>` (0119 A3, 0115 Decided 3): every post naming it in every role, grouped by
 * its Mark X stories (most voices first), the posts in no story last; every source with its counts; its family and
 * versions as links. Read posts stay, dimmed. A merged entity's id opens its group's page. 0133: a document shows who
 * published it and the posts citing it as evidence or recommending it; an org or person, what it published. 0138: its
 * Original first (and its code, demo, other pages); one no current reading names lists the posts an earlier guide named
 * it in, with what each names now.
 */
const PLATFORM: Record<string, string> = { x: 'X', github: 'GitHub', telegram: 'Telegram', bluesky: 'Bluesky', hf: 'Hugging Face' };

/** 0168: its handles (the owner's yes, its own sources' accounts; an old one with the months its pairs span) and how
 *  many posts cite them by the handle rule (their posts are in the stories and the lists above, as by / source /
 *  mention); the replies to them are hidden until asked. */
function Handles({ h, name, onReplies }: { h: MarkxEntityHandles; name: string; onReplies: () => void }) {
  return (
    <section aria-label={`${name}'s handles`}>
      <h2 className={H2}>Handles · {plural(h.posts, 'post')} cite them</h2>
      <p className="mt-2 text-[0.8125rem] text-fg-2 [overflow-wrap:anywhere]">
        {h.known.map((k, n) => (
          <span key={`${k.platform}:${k.handle}`} data-handle={`${k.platform}:${k.handle}`}>
            {n ? ', ' : ''}@{k.handle} <span className="text-fg-3">({PLATFORM[k.platform] ?? k.platform}
              {k.first_seen && k.last_seen ? `, ${k.first_seen.slice(0, 7)} to ${k.last_seen.slice(0, 7)}` : ''}
              {k.via === 'source' ? ', its own source' : ''})</span>
          </span>
        ))}
        {h.replies && !h.replies_shown ? (
          <> · <button type="button" className="text-fg underline-offset-2 hover:underline" onClick={onReplies}>
            show {plural(h.replies, 'reply', 'replies')} to them</button></>
        ) : null}
      </p>
    </section>
  );
}

/** How many more stories and posts in no story one Show more asks for (issue 0195: the API's pages). */
const ENTITY_MORE = { stories: 20, loose: 30 } as const;

export default function MarkXEntityPage() {
  const { entityId = '' } = useParams();
  const api = useApi();
  const calls = pageCalls(api);
  const client = useQueryClient();
  const [byLimit, setByLimit] = useState<number | undefined>(undefined);
  const [mentionsOpen, setMentionsOpen] = useState(false);
  const [replies, setReplies] = useState(false);   // 0168: the replies to its handles, hidden by default
  // Issue 0195: the API lists the first 20 stories and 30 posts in no story (0277; were 50 and 100); Show more asks for more.
  const [limits, setLimits] = useState<MarkxEntityLimits | undefined>(undefined);
  // 0277: the API lists each story's first posts, the first citing posts and works and the timeline's top events;
  // an "All" link asks for every one (?all=true)
  const [whole, setWhole] = useState(false);
  const all = () => setWhole(true);
  const query = useQuery({ queryKey: ['markx-entity', entityId, byLimit ?? null, replies, limits ?? null, whole],
    queryFn: () => (whole ? api.getMarkxEntity(entityId, byLimit, replies || undefined, limits, true)
      : limits ? api.getMarkxEntity(entityId, byLimit, replies || undefined, limits)
      : replies ? api.getMarkxEntity(entityId, byLimit, true)
      : byLimit === undefined ? api.getMarkxEntity(entityId) : api.getMarkxEntity(entityId, byLimit)), staleTime: 30_000,
    placeholderData: (previous, last) => (last?.queryKey[1] === entityId ? previous : undefined) });
  const refresh = () => void client.invalidateQueries({ queryKey: ['markx-entity', entityId] });
  const act = async (call: () => Promise<unknown>) => {
    try { await call(); refresh(); } catch (error: unknown) { toast.error(errorMessage(error)); }
  };
  if (query.isPending) return <Page><LoadingState label="Loading" rows={6} /></Page>;
  if (query.isError) return <Page><ErrorState error={query.error} onRetry={() => query.refetch()} /></Page>;
  const d = query.data;
  const e = d.entity;
  const group = (n: number) => d.loose.filter((p) => looseGroup(p) === n);
  const counts = d.loose_counts;
  const byShown = group(1);
  return (
    <Page>
      <PageHeader title={e.name} meta={`${entityMeta(e)} · ${plural(d.voices, 'source')} · ${plural(d.posts, 'post')}`}>
        <div className="space-y-8">
          <p className="text-[0.8125rem] text-fg-2">
            {d.maker ? <>by <TextLink to={entityHref(d.maker.id)}>{d.maker.name}</TextLink> · </> : null}
            {d.family ? <>family <TextLink to={entityHref(d.family.id)}>{d.family.name}</TextLink> · </> : null}
            {d.published_by?.length ? <>published by {d.published_by.map((p, n) => (
              <span key={p.id}>{n ? ', ' : ''}<TextLink to={entityHref(p.id)}>{p.name}</TextLink></span>))} · </> : null}
            {d.aliases.length > 1 ? `also written ${d.aliases.filter((a) => a !== e.name).join(', ')} · ` : ''}
            {d.surges.length ? <><SurgeMark surges={d.surges} />{' · '}</> : null}
            <TextLink to={researchStartHref(e.id, e.name)}>Research this</TextLink>
          </p>
          <EntityBrief brief={d.brief} />{/* 0261 */}
          <Original d={d} />
          {d.current === false && d.older?.length ? <Older older={d.older} /> : null}
          {d.rabbit_hole ? <RabbitHole hole={d.rabbit_hole} entityId={entityId} /> : null}
          {d.version_line ? <VersionLine line={d.version_line} /> : null}{/* 0220 */}
          {d.relations?.length ? <ThingLinks relations={d.relations} /> : null}{/* 0220 */}
          {d.relations && (d.relations_total ?? 0) > d.relations.length ? (
            <button type="button" className={MORE} onClick={all}>All {plural(d.relations_total ?? 0, 'link')}</button>
          ) : null}
          {d.versions.length ? (
            <section aria-label="Versions">
              <h2 className={H2}>{d.family ? 'Other versions of the family' : 'Versions'}</h2>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
                {d.versions.map((v) => (
                  <li key={v.id}>{v.id === e.id ? <span className="font-semibold text-fg">{v.name}</span>
                    : <TextLink to={entityHref(v.id)}>{v.name}</TextLink>}
                    {v.settings?.length ? (/* 0259: a version's settings, under it */
                      <span className="text-fg-3"> ({v.settings.map((s, i) => (
                        <span key={s.id}>{i ? ', ' : ''}{s.id === e.id ? <span className="font-semibold text-fg">{s.variant ?? s.name}</span>
                          : <TextLink to={entityHref(s.id)}>{s.variant ?? s.name}</TextLink>}</span>))})</span>
                    ) : null}</li>
                ))}
              </ul>
            </section>
          ) : null}
          {d.components?.length ? (
            <section aria-label="Components">
              <h2 className={H2}>Components</h2>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
                {d.components.map((c) => (
                  <li key={c.id}><TextLink to={entityHref(c.id)}>{c.name ?? 'a component'}</TextLink>
                    <span className="text-fg-3"> · {plural(c.posts, 'post')}</span></li>
                ))}
              </ul>
            </section>
          ) : null}
          {d.timeline ? <Timeline timeline={d.timeline} onAll={all} /> : null}{/* 0165 C; 0277: All asks for every event */}
          {d.published?.length ? (
            <section aria-label="Published">
              <h2 className={H2}>Published</h2>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
                {d.published.map((w) => <li key={w.id}><TextLink to={entityHref(w.id)}>{w.name}</TextLink></li>)}
              </ul>
              {(d.published_total ?? 0) > d.published.length ? (
                <button type="button" className={MORE} onClick={all}>All {plural(d.published_total ?? 0, 'work')}</button>
              ) : null}
            </section>
          ) : null}
          {d.citing?.length ? (
            <section aria-label="Cited as evidence">
              <h2 className={H2}>Cited as evidence · {plural(d.citing_total ?? d.citing.length, 'post')}</h2>
              <ul className="mt-2 space-y-1">{d.citing.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
              {(d.citing_total ?? 0) > d.citing.length ? (
                <button type="button" className={MORE} onClick={all}>All {plural(d.citing_total ?? 0, 'post')}</button>
              ) : null}
            </section>
          ) : null}
          {d.recommending?.length ? (
            <section aria-label="Recommended">
              <h2 className={H2}>Recommended · {plural(d.recommending_total ?? d.recommending.length, 'post')}</h2>
              <ul className="mt-2 space-y-1">{d.recommending.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
              {(d.recommending_total ?? 0) > d.recommending.length ? (
                <button type="button" className={MORE} onClick={all}>All {plural(d.recommending_total ?? 0, 'post')}</button>
              ) : null}
            </section>
          ) : null}
          {d.queue.some((item) => item.flag) ? (
            <section aria-label="Flagged for you">
              <h2 className={H2}>Flagged for you</h2>
              <ul>{d.queue.filter((item) => item.flag).map((item) => <QueueItem key={item.id} item={item} />)}</ul>
            </section>
          ) : null}
          {d.queue.some((item) => !item.flag) ? (
            // 0222: the rest is decided by its measured band or asked again: the operator's view, collapsed
            <details aria-label="Open questions (operator view)">
              <summary className="cursor-pointer text-[0.8125rem] text-fg-2">
                Operator view: {plural(d.queue.filter((item) => !item.flag).length, 'open question')} about it
              </summary>
              <ul>{d.queue.filter((item) => !item.flag).map((item) => <QueueItem key={item.id} item={item} />)}</ul>
            </details>
          ) : null}
          {d.stories.map((s) => <StoryBlock key={s.story} s={s} onAll={all} />)}
          {d.stories_total !== undefined && d.stories_total > d.stories.length ? (
            <button type="button" className="text-[0.8125rem] text-fg underline-offset-2 hover:underline"
                    onClick={() => setLimits({ ...limits, stories: d.stories.length + ENTITY_MORE.stories })}>
              Show more stories · {d.stories_total - d.stories.length} more</button>
          ) : null}
          {d.by && (d.by.sources.length || d.by.proposed.length) ? (
            <section aria-label={`By ${e.name}`}>
              <h2 className={H2}>By {e.name} · {plural(d.by.posts, 'post')}</h2>
              {d.by.sources.length ? (
                <p className="mt-2 text-[0.8125rem] text-fg-2">
                  {d.by.sources.map((s, n) => <span key={s.id}>{n ? ', ' : ''}{s.name ?? 'a source'}</span>)}
                  <span className="text-fg-3"> · {d.by.sources.every((s) => s.via === 'voice') ? 'its voice' : 'you said so'}</span>
                </p>
              ) : null}
              {d.by.proposed.length ? (
                <p className="mt-2 flex flex-wrap items-center gap-x-3 text-[0.8125rem] text-fg-2">
                  <span>These sources are {e.name}: {d.by.proposed.map((s) => s.name ?? 'a source').join(', ')}?</span>
                  <Button size="sm" variant="secondary" onClick={() => void act(() => calls.answerMarkxEntitySources(e.id, d.by!.proposed.map((s) => s.id), 'yes'))}>Yes</Button>
                  <Button size="sm" variant="secondary" onClick={() => void act(() => calls.answerMarkxEntitySources(e.id, d.by!.proposed.map((s) => s.id), 'no'))}>No</Button>
                </p>
              ) : null}
              {byShown.length ? <ul className="mt-2 space-y-1">{byShown.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul> : null}
              {counts && counts.by > byShown.length ? (
                <button type="button" className="mt-2 text-[0.8125rem] text-fg underline-offset-2 hover:underline"
                        onClick={() => setByLimit(counts.by)}>Show all {plural(counts.by, 'post')} in no story</button>
              ) : null}
            </section>
          ) : null}
          {d.loose_total !== undefined && d.loose_total > d.loose.length ? (
            <button type="button" className="text-[0.8125rem] text-fg underline-offset-2 hover:underline"
                    onClick={() => setLimits({ ...limits, loose: d.loose.length + ENTITY_MORE.loose })}>
              Show more posts in no story · {d.loose_total - d.loose.length} more</button>
          ) : null}
          {d.handles?.known.length ? <Handles h={d.handles} name={e.name} onReplies={() => setReplies(true)} /> : null}
          {group(0).length || group(2).length || group(3).length ? (
            <section aria-label={`About ${e.name}`}>
              <h2 className={H2}>About {e.name} · in no story · {plural(group(0).length + group(2).length + group(3).length, 'post')}</h2>
              <ul className="mt-2 space-y-1">{[...group(0), ...group(2)].map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
              {group(3).length ? (mentionsOpen
                ? <ul className="mt-1 space-y-1">{group(3).map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
                : <button type="button" className="mt-2 text-[0.8125rem] text-fg underline-offset-2 hover:underline"
                          onClick={() => setMentionsOpen(true)}>{plural(group(3).length, 'mention')}</button>) : null}
            </section>
          ) : null}
          <section aria-label="Sources">
            <h2 className={H2}>Sources</h2>
            <ul className="mt-2 text-[0.8125rem] text-fg-2">
              {d.sources.map((s) => (
                <li key={s.id} className="flex gap-3 border-t border-line py-1.5">
                  <span className="min-w-0 flex-1 truncate text-fg">{s.name ?? 'a source'}</span>
                  <span className="tabular-nums">{plural(s.posts, 'post')}{s.reports ? ` · ${s.reports} about it` : ''}{s.by ? ' · by it' : ''}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </PageHeader>
    </Page>
  );
}
