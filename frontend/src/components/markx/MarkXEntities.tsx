import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type {
  MarkxEntityAccuracy, MarkxEntityAnswer, MarkxEntityPost, MarkxEntityQueue, MarkxEntityRef, MarkxEntityRow,
  MarkxQueueItem, MarkxQueueSide, MarkxSurge,
} from '../../services/markx';
import { Button, Chip, TextLink } from '../ui';
import { EmptyState, ErrorState, LoadingState } from '../states';
import { postBylineTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import { errorMessage } from '../../lib/apiError';

export const ENTITIES_KEY = ['markx-entities'] as const;
export const QUEUE_KEY = ['markx-entity-queue'] as const;
const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';

export const entityHref = (id: string) => `/markx/entities/${encodeURIComponent(id)}`;

/** What an entity is: type, maker, its exact version (0119 A3). */
export function entityMeta(e: MarkxEntityRef): string {
  const version = [e.version, e.variant, e.size, e.build].filter(Boolean).join(' ');
  return [e.type, e.maker ? `by ${e.maker}` : null, version ? `version ${version}` : null,
    e.status === 'provisional' ? 'provisional' : null].filter(Boolean).join(' · ');
}

export function SurgeMark({ surges }: { surges: MarkxSurge[] }) {
  const s = surges[0];
  if (!s) return null;
  const via = s.via[0]?.name;
  return (
    <Chip variant="solid" title={`${plural(s.voices, 'voice')} on ${s.day}${via ? `, via ${via}` : ''}`} data-surging>
      surging{via ? ` · via ${via}` : ''}
    </Chip>
  );
}

/** A post line: read posts stay, only dimmed (0115: reading never removes anything). */
export function EntityPostLine({ post, now }: { post: MarkxEntityPost; now?: Date }) {
  return (
    <li className={`min-w-0 truncate text-[0.8125rem] ${post.read ? 'text-fg-3' : 'text-fg-2'}`} data-read={post.read || undefined}>
      <TextLink to={`/posts/${encodeURIComponent(post.id)}`} muted>{post.title || '(no title)'}</TextLink>
      <span className="text-fg-3">
        {post.source ? ` · ${post.source}` : ''}{post.at ? ` · ${postBylineTime(post.at, now)}` : ''}
        {post.roles?.length ? ` · ${post.roles.join(', ')}` : ''}{post.read ? ' · read' : ''}
      </span>
    </li>
  );
}

export function Accuracy({ accuracy }: { accuracy: MarkxEntityAccuracy }) {
  return (
    <p className="text-[0.75rem] leading-5 text-fg-3">
      Experimental: {accuracy.merges}; {accuracy.surges}; {accuracy.collisions}. Your answers below are the next test.
    </p>
  );
}

function Row({ e }: { e: MarkxEntityRow }) {
  return (
    <li className="border-b border-line py-2.5">
      <span className="flex flex-wrap items-baseline gap-x-2">
        <TextLink to={entityHref(e.id)} className="text-[0.9375rem] font-semibold text-fg [overflow-wrap:anywhere]">{e.name}</TextLink>
        <span className="text-[0.75rem] text-fg-3">{entityMeta(e)}</span>
        <SurgeMark surges={e.surges} />
        <span className="ml-auto text-[0.8125rem] tabular-nums text-fg-2">
          {plural(e.voices, 'source')} · {plural(e.posts, 'post')}{e.last_seen ? ` · last seen ${e.last_seen}` : ''}
        </span>
      </span>
      {e.stories.length ? (
        <p className="mt-0.5 text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">
          In {e.stories.map((s) => `“${s.headline ?? 'a Mark X story'}”`).join(', ')}
        </p>
      ) : null}
      <ul className="mt-1 space-y-0.5">{e.newest.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
    </li>
  );
}

const ANSWERS: { answer: MarkxEntityAnswer; label: string }[] = [
  { answer: 'same', label: 'same' }, { answer: 'other_version', label: 'other version' },
  { answer: 'different', label: 'different' }, { answer: 'not_entity', label: 'not an entity' },
];

const REASONS: Record<string, string> = {
  below_bar: 'Haiku says the same, below its 0.9 bar', version: 'one name states a version the other lacks',
  version_year: 'a year or edition on one side only', version_one_side: 'one name states a version the other lacks, its family has one',
  type: 'their types differ', chain: 'it would join two groups of names', handle_extra_word: 'a handle with an extra word',
  paren: '“X (Y)” written in one post', fields_parser: 'Haiku’s version fields agree, the parser’s don’t',
  maker_unstated: 'the maker in front is only guessed', collision: 'one name, maybe several things',
};

/** 0130 A1-A2: what the queue item carries beyond 0119's: its band, every reason, the second opinion. */
type Opinion = { relation?: string; confidence?: number; evidence?: string } | null;
type Item = MarkxQueueItem & {
  band?: string | null;
  evidence: MarkxQueueItem['evidence'] & { reasons?: string[] | null; second?: Opinion; disagree?: boolean | null; second_asked?: boolean | null };
};

/** The bands the queue is measured in (0130 A1); the owner's answers per band are the next labels. */
export const BANDS = ['>=0.90', '0.85-0.90', '0.80-0.85', '<0.80'] as const;
const bandLabel = (b: string) => b.replace('>=', '≥ ').replace('<', '< ').replace('-', '–');

/** The second opinion (0130 A2): asked again with other posts; a disagreement is marked. */
export function SecondOpinion({ item }: { item: Item }) {
  const second = item.evidence.second;
  if (second?.relation) {
    const pct = second.confidence != null ? ` ${Math.round(second.confidence * 100)}%` : '';
    return (
      <p className="mt-1 text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]" data-disagree={item.evidence.disagree || undefined}>
        {item.evidence.disagree ? <Chip variant="solid">second opinion disagrees</Chip> : <Chip>second opinion</Chip>}
        {' '}{second.relation.replace('_', ' ')}{pct}{second.evidence ? `: ${second.evidence}` : ''}
      </p>
    );
  }
  return item.evidence.second_asked ? <p className="mt-1 text-[0.75rem] text-fg-3">Second opinion asked; the next worker run answers it.</p> : null;
}

function Side({ side }: { side: MarkxQueueSide }) {
  return (
    <div className="min-w-0">
      <TextLink to={entityHref(side.root)} className="font-semibold text-fg [overflow-wrap:anywhere]">{side.name}</TextLink>
      <span className="block text-[0.75rem] text-fg-3">{entityMeta(side)}</span>
      <ul className="mt-1 space-y-0.5">
        {side.posts.map((p) => (
          <li key={p.id} className="min-w-0 truncate text-[0.8125rem] text-fg-2">
            <TextLink to={`/posts/${encodeURIComponent(p.id)}`} muted>{p.title || '(no title)'}</TextLink>
            <span className="text-fg-3"> · {p.source} · “{p.span}”</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function QueueItem({ item: base }: { item: MarkxQueueItem }) {
  const item = base as Item;
  const api = useApi();
  const queryClient = useQueryClient();
  const answer = useMutation({
    mutationFn: (a: MarkxEntityAnswer) => api.answerMarkxEntity(item.id, a),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [...QUEUE_KEY] });
      void queryClient.invalidateQueries({ queryKey: [...ENTITIES_KEY] });
      void queryClient.invalidateQueries({ queryKey: ['markx-entity'] });
    },
  });
  const chosen = answer.isPending ? answer.variables : item.answer;
  const judge = item.evidence.judge;
  return (
    <li className="border-b border-line py-3" data-queue-item={item.id}>
      <p className="text-[0.75rem] text-fg-3">
        {item.kind === 'collision'
          ? `Split proposed (${item.evidence.split_runs ?? 2} of ${item.evidence.runs ?? 3} runs)`
          : `Proposed: ${item.proposal.replace('_', ' ')}`}
        {' · '}{REASONS[item.reason] ?? item.reason}
        {(item.evidence.reasons ?? []).filter((r) => r !== item.reason).map((r) => ` · ${REASONS[r] ?? r}`).join('')}
        {item.confidence != null ? ` · ${Math.round(item.confidence * 100)}%` : ''}
        {item.band ? ` · band ${bandLabel(item.band)}` : ''}
      </p>
      {item.kind === 'collision' ? (
        <div className="mt-1">
          <Side side={item.a} />
          {item.evidence.senses?.length ? (
            <ul className="mt-1 text-[0.8125rem] text-fg-2">
              {item.evidence.senses.map((s, n) => (
                <li key={n}>Sense {n + 1}: {s.what || '—'} ({s.m.map((m) => {
                  const row = item.evidence.mentions?.find((x) => x.n === m);
                  return row ? `“${row.span}” ${row.type}` : `#${m}`;
                }).join(', ')})</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <div className="mt-1 grid gap-3 sm:grid-cols-2">
          <Side side={item.a} />
          {item.b ? <Side side={item.b} /> : null}
        </div>
      )}
      {judge?.evidence ? <p className="mt-1 text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">Haiku: {judge.evidence}</p> : null}
      <SecondOpinion item={item} />
      <div className="mt-2 flex flex-wrap items-center gap-2" role="group" aria-label="Your answer">
        {ANSWERS.map((a) => (
          <Button key={a.answer} size="sm" variant={chosen === a.answer ? 'primary' : 'secondary'}
                  aria-pressed={chosen === a.answer} disabled={answer.isPending} onClick={() => answer.mutate(a.answer)}>
            {a.label}
          </Button>
        ))}
        {answer.isError ? <span className="text-[0.8125rem] text-fg">× {errorMessage(answer.error)}</span> : null}
      </div>
    </li>
  );
}

function Merges({ queue }: { queue: MarkxEntityQueue }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const undo = useMutation({
    mutationFn: (id: string) => api.undoMarkxMerge(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [...QUEUE_KEY] });
      void queryClient.invalidateQueries({ queryKey: [...ENTITIES_KEY] });
    },
  });
  if (!queue.merges.length) return null;
  return (
    <details className="mt-4">
      <summary className="cursor-pointer text-[0.8125rem] text-fg-2">
        History: {plural(queue.counts.automatic_merges, 'automatic merge')}
        {queue.counts.automatic_undone ? ` · ${queue.counts.automatic_undone} undone` : ''}
      </summary>
      <ul className="mt-2 text-[0.8125rem] text-fg-2">
        {queue.merges.map((m) => (
          <li key={m.id} className="flex flex-wrap items-baseline gap-2 border-t border-line py-1.5">
            <span className={m.undone_at ? 'text-fg-3 line-through' : 'text-fg'}>{m.from.name} → {m.to.name}</span>
            <span className="text-fg-3">{m.automatic ? m.by : 'by you'}</span>
            {!m.undone_at ? (
              <Button size="sm" variant="secondary" disabled={undo.isPending} onClick={() => undo.mutate(m.id)}>undo</Button>
            ) : <span className="text-fg-3">undone</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The review queue (0119 A3): every pair the rules leave to you, and the merges' history. */
export function EntityQueue() {
  const api = useApi();
  const [band, setBand] = useState<string | null>(null);
  const query = useQuery({ queryKey: [...QUEUE_KEY], queryFn: () => api.getMarkxEntityQueue(), staleTime: 30_000 });
  if (query.isPending) return <LoadingState label="Loading" rows={2} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const q = query.data;
  const answered = Object.values(q.counts.answered).reduce((n, x) => n + (x ?? 0), 0);
  const items = q.open as Item[];
  const inBand = (b: string) => items.filter((i) => i.band === b).length;
  const shown = band ? items.filter((i) => i.band === band) : items;
  return (
    <section aria-label="Review queue">
      <h2 className={H2}>To review: {q.counts.open}{answered ? ` · ${answered} answered` : ''}</h2>
      {items.some((i) => i.band) ? (
        <div className="mt-2 flex flex-wrap items-center gap-2" role="group" aria-label="Band">
          <span className="text-[0.75rem] text-fg-3">Haiku’s confidence:</span>
          <Button size="sm" variant={band === null ? 'primary' : 'secondary'} aria-pressed={band === null} onClick={() => setBand(null)}>all</Button>
          {BANDS.filter((b) => inBand(b)).map((b) => (
            <Button key={b} size="sm" variant={band === b ? 'primary' : 'secondary'} aria-pressed={band === b} onClick={() => setBand(b)}>
              {bandLabel(b)} ({inBand(b)})
            </Button>
          ))}
        </div>
      ) : null}
      {shown.length === 0 ? <p className="mt-3 text-[0.8125rem] text-fg-3">Nothing to review.</p> : (
        <ul>{shown.slice(0, 20).map((item) => <QueueItem key={item.id} item={item} />)}</ul>
      )}
      {shown.length > 20 ? <p className="mt-2 text-[0.75rem] text-fg-3">{shown.length - 20} more after these.</p> : null}
      <Merges queue={q} />
    </section>
  );
}

/** The Entities tab (0119 A3, 0115): one list ranked like News, the review queue beside it. */
export default function MarkXEntities() {
  const api = useApi();
  const query = useQuery({ queryKey: [...ENTITIES_KEY], queryFn: () => api.getMarkxEntities(), staleTime: 30_000 });
  if (query.isPending) return <LoadingState label="Loading" rows={4} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const data = query.data;
  return (
    <div className="space-y-8">
      <Accuracy accuracy={data.accuracy} />
      <EntityQueue />
      <section aria-label="Entities">
        <h2 className={H2}>
          {plural(data.total, 'entity')} in the last {data.window_days} days · by sources, then reports, then the newest
        </h2>
        {data.items.length === 0 ? (
          <EmptyState title="No entity yet" description="Entities appear once the worker has read the posts' entities and a decision run linked them." />
        ) : <ul>{data.items.map((e) => <Row key={e.id} e={e} />)}</ul>}
      </section>
    </div>
  );
}
