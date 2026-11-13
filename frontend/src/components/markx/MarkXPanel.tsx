import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import { markxGraphApi, type MarkxEdgeAnswer } from '../../services/api';   // 0131
import type { MarkxBefore, MarkxPostPanel } from '../../services/markx';
import { Button, TextLink } from '../ui';
import { judged, relationWords, whyWords } from '../../lib/markx';
import { request } from '../../lib/request';   // 0133 v4.2
import { plural } from '../../lib/format';
import { postBylineTime } from '../../lib/dates';
import { bylineText } from '../../lib/byline';
import MarkXTranslation from './MarkXTranslation';   // 0130 D
import { TimelineLine } from './MarkXTimeline';       // 0165 D

/**
 * The post page's "Mark X" panel (issue 0086 E), folded, loaded only when opened (its own chunk, and only while
 * Mark X is on): the post's reading, its entities and their roles, its Mark X stories with why it is in each, and
 * its connections, each with its reason; and (0131) the older posts it connects to, "Before".
 */
export default function MarkXPanel({ postId, url }: { postId: string; url?: string | null }) {
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
        {url ? (
          <p className="text-fg-3">
            <TextLink to={`/research?seed=${encodeURIComponent(url)}`} muted>Research this</TextLink>
            {' '}· its maker, channels, papers and who discusses it (issue 0162)
          </p>
        ) : null}
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
            <MarkXTranslation postId={postId} where="panel" />{/* 0130 D */}
            <section aria-label="Entities">
              <h3 className="text-[0.75rem] font-medium text-fg-3">
                Entities{data.entities_guide && data.entities_guide !== 'ent-v3' ? ` · ${data.entities_guide}` : ''}
              </h3>
              {data.entities.length ? (
                <Entities postId={postId} items={data.entities.filter((e) => !CITED.has(e.role ?? ''))} />
              ) : <p className="mt-1 text-fg-3">None read yet.</p>}
            </section>
            {/* 0133: the documents it names and its cited sources, under their roles */}
            {(data.documents?.length || data.sources?.length || data.recommended?.length) ? (
              <section aria-label="Documents and cited sources">
                <h3 className="text-[0.75rem] font-medium text-fg-3">Documents and cited sources</h3>
                {data.sources?.length ? <p className="mt-1 text-fg-3">cited as evidence</p> : null}
                {data.sources?.length ? <Entities postId={postId} items={data.sources} /> : null}
                {data.recommended?.length ? <p className="mt-1 text-fg-3">recommended</p> : null}
                {data.recommended?.length ? <Entities postId={postId} items={data.recommended} /> : null}
                {data.documents?.length ? <p className="mt-1 text-fg-3">documents it names</p> : null}
                {data.documents?.length ? <Entities postId={postId} items={data.documents} /> : null}
              </section>
            ) : null}
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
            {data.before?.length || data.before_timeline?.length ? (
              <BeforeList postId={postId} rows={data.before ?? []} more={data.before_more ?? 0} timeline={data.before_timeline ?? []} />
            ) : null}
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

const CITED = new Set(['source', 'recommended']);   // 0133: listed under "Documents and cited sources"

/** A post's entities, each opening its page; the citation rule's marked, a document's publisher after it (0133);
 *  the second question's marked, and right / wrong on each new entity (0133 v4.2). */
function Entities({ postId, items }: { postId: string; items: MarkxPostPanel['entities'] }) {
  return (
    <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
      {items.map((e, n) => (
        <li key={n} className="[overflow-wrap:anywhere]">
          {e.entity_id ? (
            <TextLink to={`/markx/entities/${encodeURIComponent(e.entity_id)}`}
                      className={e.role === 'subject' ? 'font-semibold text-fg' : 'text-fg'}>{e.name}</TextLink>
          ) : <span className={e.role === 'subject' ? 'font-semibold text-fg' : 'text-fg'}>{e.name}</span>}
          <span className="text-fg-3"> {e.type}{e.version ? ` ${e.version}` : ''} · {e.role}
            {e.by ? ` · by ${e.by}` : ''}{e.rule === 'citation' ? ' · citation rule' : ''}{e.q2 ? ' · second question' : ''}</span>
          {e.new && e.n != null && e.guide ? <> <MentionButtons postId={postId} entity={e} /></> : null}
        </li>
      ))}
    </ul>
  );
}

type MentionAnswer = 'right' | 'wrong';
type LabelMention = (postId: string, guide: string, n: number, answer: MentionAnswer) => Promise<{ label: MentionAnswer }>;
/** 0133 v4.2: the label's call, here (the panel's chunk) and not in api.ts; a test's fake api may provide it. */
function markxMentionApi(api: object): { labelMarkxMention: LabelMention } {
  const got = (api as { labelMarkxMention?: unknown }).labelMarkxMention;
  return { labelMarkxMention: typeof got === 'function' ? (got as LabelMention)
    : (postId, guide, n, answer) => request(`/api/markx/posts/${encodeURIComponent(postId)}/mentions/label`,
      { method: 'POST', body: { guide, n, answer } }) };
}

/** 0133 v4.2: the owner's right / wrong on one new entity (ent-v4.2 is measured on the server by these labels). */
function MentionButtons({ postId, entity }: { postId: string; entity: MarkxPostPanel['entities'][number] }) {
  const api = markxMentionApi(useApi());
  const client = useQueryClient();
  const [mine, setMine] = useState<MentionAnswer | null>(entity.label ?? null);
  const tap = useMutation({
    mutationFn: (answer: MentionAnswer) => api.labelMarkxMention(postId, entity.guide ?? '', entity.n ?? 0, answer),
    onSuccess: (got) => {
      setMine(got.label);
      void client.invalidateQueries({ queryKey: ['markx-post', postId] });
    },
  });
  return (
    <span className="inline-flex flex-wrap items-center gap-1" role="group" aria-label={`Is ${entity.name} right?`}>
      {mine ? <span className="text-fg-3">you said {mine}</span> : null}
      <Button size="sm" variant="ghost" className="text-[0.75rem]" aria-label="entity right" aria-pressed={mine === 'right'}
        disabled={tap.isPending} onClick={() => tap.mutate('right')}>✓</Button>
      <Button size="sm" variant="ghost" className="text-[0.75rem]" aria-label="entity wrong" aria-pressed={mine === 'wrong'}
        disabled={tap.isPending} onClick={() => tap.mutate('wrong')}>✗</Button>
      {tap.isError ? <span className="text-fg">× not saved</span> : null}
    </span>
  );
}

/** What made an edge (0131): an author's link, entity identity, or the judge alone. */
const RULE_WORDS: Record<string, string> = {
  author_link_other: 'the author links it',
  author_link_own: 'the source links its own post',
  entity_next_version: 'entities: the next version',
};

/**
 * The older posts this post connects to (issue 0131, Stalker's first edges), oldest first, with their relation and
 * the reason line. An edge the judge alone made is marked uncertain, with ✓ / ✗ (the owner's labels).
 */
function BeforeList({ postId, rows, more, timeline }: { postId: string; rows: MarkxBefore[]; more: number;
  timeline: NonNullable<MarkxPostPanel['before_timeline']> }) {
  return (
    <section aria-label="Before">
      <h3 className="text-[0.75rem] font-medium text-fg-3">Before</h3>
      {/* 0165 D: what came before in its subject's timeline (its birth, its last release, its first outside mention) */}
      {timeline.map((t) => (
        <div key={t.entity.id} className="mt-1" data-timeline={t.entity.id}>
          <p className="text-fg-3">
            In <TextLink to={`/markx/entities/${encodeURIComponent(t.entity.id)}`} muted>{t.entity.name ?? 'its subject'}</TextLink>’s timeline
          </p>
          <ol className="mt-0.5 space-y-0.5">{t.items.map((e) => <TimelineLine key={`${e.kind}-${e.post?.id ?? e.at}`} e={e} />)}</ol>
        </div>
      ))}
      {rows.length ? <ul className="mt-1 space-y-1.5">
        {rows.map((r) => (
          <li key={r.post_id} className="[overflow-wrap:anywhere]" data-uncertain={r.uncertain || undefined}>
            <span className="text-fg">{relationWords(r.relation)}</span>{' '}
            <TextLink to={`/posts/${encodeURIComponent(r.post_id)}`} muted>{r.title || 'a post'}</TextLink>
            <span className="text-fg-3">
              {r.source ? ` · ${bylineText(r.byline, r.source)}` : ''}{r.at ? ` · ${postBylineTime(r.at)}` : ''}
              {' · '}{r.rule ? RULE_WORDS[r.rule] ?? `rule ${r.rule}` : judged(r.relation, r.p)}
            </span>
            {r.uncertain ? <> <span className="rounded-sm border border-line px-1 text-[0.6875rem] text-fg-3">uncertain</span>{' '}
              <EdgeButtons newer={postId} row={r} /></> : null}
            {r.reason ? <span className="block text-fg-3">{r.reason}</span> : null}
          </li>
        ))}
      </ul> : null}
      {more > 0 ? <p className="mt-1 text-fg-3">+{more} more</p> : null}
    </section>
  );
}

function EdgeButtons({ newer, row }: { newer: string; row: MarkxBefore }) {
  const client = useQueryClient();
  const [mine, setMine] = useState<'right' | 'wrong' | null>(row.label);
  const tap = useMutation({
    mutationFn: (answer: MarkxEdgeAnswer) => markxGraphApi.labelEdge(newer, row.post_id, answer),
    onSuccess: (got) => {
      setMine(got.label);
      void client.invalidateQueries({ queryKey: ['markx-post', newer] });
    },
  });
  return (
    <span className="inline-flex flex-wrap items-center gap-1" role="group" aria-label="Is this edge right?">
      {mine ? (
        <>
          <span className="text-fg-2">you said {mine}</span>
          <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={tap.isPending} onClick={() => tap.mutate('undo')}>undo</Button>
        </>
      ) : (
        <>
          <Button size="sm" variant="ghost" className="text-[0.75rem]" aria-label="edge right" disabled={tap.isPending}
            onClick={() => tap.mutate('right')}>✓</Button>
          <Button size="sm" variant="ghost" className="text-[0.75rem]" aria-label="edge wrong" disabled={tap.isPending}
            onClick={() => tap.mutate('wrong')}>✗</Button>
        </>
      )}
      {tap.isError ? <span className="text-fg">× not saved</span> : null}
    </span>
  );
}
