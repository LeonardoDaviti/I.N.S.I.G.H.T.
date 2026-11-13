import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type {
  MarkxAnswer, MarkxFeaturePrecision, MarkxLabelItem, MarkxLabelQueue, MarkxStat, MarkxVerdict,
} from '../../services/markx';
import { Button, Select, Textarea } from '../ui';
import { EmptyState, ErrorState, LoadingState } from '../states';
import { plural } from '../../lib/format';
import { errorMessage } from '../../lib/apiError';
import { ANSWER_WORDS, percent, pWords, relationWords, withInterval } from '../../lib/markx';
import { cn } from '../../lib/utils';
import { PerspectiveAccuracy } from './MarkXPerspectives';

const QUEUE_KEY = ['markx-labels'] as const;
const BUILDING = 'Built after each decision run, in the background; it shows within a few minutes.';
const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';

function day(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : '';
}

/** What Haiku said and what Mark X did, shown once the item has your answer. */
function Verdict({ verdict, item }: { verdict: MarkxVerdict; item: MarkxLabelItem }) {
  if (item.feature === 'entities') {
    return <p className="text-[0.8125rem] text-fg-2">Your answer is stored. Entities have no bar: precision is the share named right.</p>;
  }
  return (
    <p className="text-[0.875rem] leading-6 text-fg [overflow-wrap:anywhere]" data-verdict>
      <span className="font-semibold">Haiku: {relationWords(verdict.relation) || 'answered'} {pWords(verdict.p)}</span>
      {verdict.reason ? <span className="text-fg-2"> — {verdict.reason}</span> : null}
      <span className="block text-[0.8125rem] text-fg-2">
        Bar {pWords(verdict.bar)}: {verdict.decision}
      </span>
    </p>
  );
}

function Item({ id, onNext, onSkip, onAnswered, nextLabel }: { id: string; onNext: (next: string | null) => void;
  onSkip: () => void; onAnswered: () => void; nextLabel: string }) {
  const api = useApi();
  const client = useQueryClient();
  const query = useQuery({ queryKey: ['markx-label-item', id], queryFn: () => api.getMarkxLabelItem(id) });
  const [note, setNote] = useState('');
  const [next, setNext] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    setNote(query.data?.label?.note ?? '');
    setNext(undefined);
  }, [id, query.data?.label?.note]);
  const answer = useMutation({
    mutationFn: (a: MarkxAnswer) => api.labelMarkxItem(id, a, note.trim() || undefined),
    onSuccess: (got) => {
      client.setQueryData<MarkxLabelItem>(['markx-label-item', id], (old) => old && {
        ...old, verdict: got.verdict,
        label: { answer: got.label.answer, note: got.label.note, split: got.label.split, created_at: new Date().toISOString() },
      });
      setNext(got.next);
      onAnswered();   // stay on this item (its verdict) while the queue refetches
      void client.invalidateQueries({ queryKey: [...QUEUE_KEY] });
      void client.invalidateQueries({ queryKey: ['markx-precision'] });
    },
  });
  const item = query.data;
  useEffect(() => {
    if (!item) return undefined;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT' || target.tagName === 'SELECT')) return;
      const n = Number(e.key);
      if (Number.isInteger(n) && n >= 1 && n <= item.answers.length && !answer.isPending) answer.mutate(item.answers[n - 1]);
      else if ((e.key === 'Enter' || e.key === 'n') && item.label) onNext(next ?? null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [item, next, answer, onNext]);

  if (query.isPending) return <LoadingState label="Loading the item" rows={4} />;
  if (query.isError || !item) return <ErrorState error={query.error} onRetry={() => query.refetch()} title="The item did not load" />;
  const chosen = item.label?.answer;
  return (
    <article aria-label="Item to label" className="mt-4">
      <p className="text-[0.75rem] tabular-nums leading-5 text-fg-3">
        {item.position ? `#${item.position} · ` : ''}{item.name} · {day(item.day)} · {item.split}
      </p>
      <h3 className="mt-1 text-[0.9375rem] font-semibold leading-[1.4] text-fg">{item.question}</h3>
      {item.extracted ? (
        <ul aria-label="What the extraction named" className="mt-3 space-y-1 text-[0.875rem] leading-5 text-fg">
          {item.extracted.length ? item.extracted.map((e, n) => (
            <li key={n} className="[overflow-wrap:anywhere]">
              <span className="font-medium">{e.name}</span>
              <span className="text-fg-3"> · {[e.type, e.role, e.version, e.maker].filter(Boolean).join(' · ')}</span>
            </li>
          )) : <li className="text-fg-3">nothing</li>}
        </ul>
      ) : null}
      <pre
        aria-label="The evidence, as the judge saw it"
        className="mt-3 whitespace-pre-wrap rounded-md border border-line bg-surface p-3 font-mono text-[0.78125rem] leading-[1.55] text-fg [overflow-wrap:anywhere] sm:max-h-[32rem] sm:overflow-auto"
      >
        {item.evidence}
      </pre>
      <div className="sticky bottom-0 z-10 -mx-1 mt-3 border-t border-line bg-bg px-1 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2 sm:static sm:border-t-0 sm:pb-0">
        <div role="group" aria-label="Your answer" className="grid grid-cols-3 gap-2 sm:flex sm:flex-wrap">
          {item.answers.map((a, n) => (
            <Button
              key={a}
              size="lg"
              variant={chosen === a ? 'primary' : 'secondary'}
              aria-pressed={chosen === a}
              disabled={answer.isPending}
              onClick={() => answer.mutate(a)}
              className="w-full sm:w-auto"
              title={`${ANSWER_WORDS[a] ?? a} (key ${n + 1})`}
            >
              {ANSWER_WORDS[a] ?? a}
            </Button>
          ))}
        </div>
        {item.verdict ? (
          <div className="mt-2 max-h-[30vh] overflow-auto border-t border-line pt-2 sm:max-h-none">
            <p className="mb-1 text-[0.75rem] text-fg-3">
              You: {ANSWER_WORDS[chosen ?? ''] ?? chosen}{item.label?.note ? ` — “${item.label.note}”` : ''}. Answer again to change it (kept as a new label).
            </p>
            <Verdict verdict={item.verdict} item={item} />
          </div>
        ) : null}
        <div className="mt-2 flex flex-wrap gap-2">
          {item.verdict ? (
            <Button variant="primary" onClick={() => onNext(next ?? null)}>{nextLabel}</Button>
          ) : (
            <Button variant="ghost" onClick={onSkip}>skip for now</Button>
          )}
        </div>
      </div>
      <label className="mt-2 block">
        <span className="sr-only">Note</span>
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="note (optional, saved with your answer)"
          className="min-h-[2.75rem]" rows={1} />
      </label>
      {answer.isError ? <p role="alert" className="mt-2 text-[0.8125rem] text-fg">{errorMessage(answer.error)}</p> : null}
    </article>
  );
}

function Progress({ queue }: { queue: MarkxLabelQueue }) {
  return (
    <div>
      <p className="text-[0.8125rem] tabular-nums leading-5 text-fg-2">
        {queue.done} of {plural(queue.total, 'item')} answered
        {queue.cut ? ` · dev before ${queue.cut}, test from it` : ''}
      </p>
      <ul aria-label="By feature" className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[0.75rem] tabular-nums leading-5 text-fg-3">
        {queue.features.map((f) => <li key={f.feature}>{f.name} {f.done}/{f.total}</li>)}
      </ul>
    </div>
  );
}

function Queue() {
  const api = useApi();
  const query = useQuery({ queryKey: [...QUEUE_KEY], queryFn: () => api.getMarkxLabels(), staleTime: 30_000,
    refetchInterval: (q) => (q.state.data?.building ? 30_000 : false) });
  const [current, setCurrent] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const queue = query.data;
  const pending = queue ? queue.next.filter((i) => !skipped.includes(i)) : [];
  const shown = current ?? pending[0] ?? null;

  if (query.isPending) return <LoadingState label="Loading the queue" rows={4} />;
  if (query.isError || !queue) return <ErrorState error={query.error} onRetry={() => query.refetch()} title="The queue did not load" />;
  if (!queue.run) {
    return <EmptyState title="Nothing to label yet" description="The queue is drawn from the decision job's runs, once the worker has answered." />;
  }
  if (queue.building && !queue.total) {
    return <EmptyState title="The queue is being built" description={BUILDING} />;
  }
  const last = queue.answered.at(-1);
  return (
    <section aria-label="Label">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Progress queue={queue} />
          {queue.building ? <p className="text-[0.75rem] leading-5 text-fg-3">The last decision run's queue is being built; this is the one before.</p> : null}
        </div>
        {last && last !== shown ? (
          <Button size="sm" variant="ghost" onClick={() => setCurrent(last)}>last answered</Button>
        ) : null}
      </div>
      {shown ? (
        <Item
          key={shown}
          id={shown}
          nextLabel={pending.filter((i) => i !== shown).length ? 'next' : 'done'}
          onAnswered={() => setCurrent(shown)}
          onNext={(next) => {
            setCurrent(next && next !== shown ? next : pending.find((i) => i !== shown) ?? null);
          }}
          onSkip={() => {
            setSkipped((s) => [...s, shown]);
            setCurrent(null);
          }}
        />
      ) : (
        <EmptyState className="mt-6" title={queue.total ? 'Every item is answered' : 'The queue is empty'}
          description={queue.total ? 'Precision shows what your labels say about each feature.' : undefined}
          action={skipped.length ? { label: `back to the ${plural(skipped.length, 'skipped item')}`, onClick: () => setSkipped([]) } : undefined} />
      )}
    </section>
  );
}

function Stat({ s }: { s: MarkxStat }) {
  if (!s.labelled) return <span className="text-fg-3">–</span>;
  return (
    <span title={`${s.right} of ${s.labelled} labelled right; ${s.n_eff} effective after the pools' weights`}>
      {withInterval(s.precision, s.lo, s.hi)}
      <span className="text-fg-3"> · {s.labelled}</span>
    </span>
  );
}

function FeatureCard({ f, target }: { f: MarkxFeaturePrecision; target: number }) {
  const flags = Object.entries(f.flags).filter(([, n]) => n);
  return (
    <section aria-label={f.name} className="border-b border-line py-4">
      <h3 className="text-[0.9375rem] font-semibold text-fg">
        {f.name}
        <span className="ml-2 text-[0.8125rem] font-normal tabular-nums text-fg-2">
          {f.bar !== null ? `bar ${pWords(f.bar)} · ` : ''}{plural(f.population, 'question')} · {f.labelled} labelled
        </span>
      </h3>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[19rem] text-left text-[0.8125rem] tabular-nums leading-6">
          <thead className="text-[0.75rem] text-fg-3">
            <tr>
              <th scope="col" className="w-12 font-medium" />
              <th scope="col" className="font-medium">{f.feature === 'entities' ? 'named right' : `${f.acted}: right`}</th>
              {f.feature !== 'entities' ? <th scope="col" className="font-medium">the rest: right</th> : null}
            </tr>
          </thead>
          <tbody>
            {(['dev', 'test', 'all'] as const).map((sp) => (
              <tr key={sp} className="border-t border-line">
                <th scope="row" className="font-medium text-fg-2">{sp}</th>
                <td><Stat s={f.splits[sp].acted} /></td>
                {f.feature !== 'entities' ? <td><Stat s={f.splits[sp].rejected} /></td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {f.repick ? (
        <p className="mt-2 text-[0.8125rem] leading-5 text-fg-2">
          On dev, {f.feature === 'check' ? 'the highest' : 'the lowest'} bar reaching {percent(target)} is {pWords(f.repick.bar)}:
          {' '}test {withInterval(f.repick.test.precision, f.repick.test.lo, f.repick.test.hi)}
          {f.repick.test.labelled ? ` on ${f.repick.test.labelled}` : ''}.
        </p>
      ) : f.sweep.length && f.labelled ? (
        <p className="mt-2 text-[0.8125rem] leading-5 text-fg-3">No bar reaches {percent(target)} on dev yet (on 10 or more labels).</p>
      ) : null}
      {flags.length ? (
        <p className="mt-1 text-[0.8125rem] leading-5 text-fg-2">
          One tap on Mark X News: {flags.map(([k, n]) => `${n} ${ANSWER_WORDS[k] ?? k}`).join(', ')}
        </p>
      ) : null}
      {f.sweep.length && f.labelled ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-[0.8125rem] text-fg-2">every bar</summary>
          <div className="overflow-x-auto">
            <table className="mt-1 w-full min-w-[19rem] text-left text-[0.8125rem] tabular-nums leading-6">
              <thead className="text-[0.75rem] text-fg-3">
                <tr><th scope="col" className="w-12 font-medium">bar</th><th scope="col" className="font-medium">dev</th>
                  <th scope="col" className="font-medium">test</th></tr>
              </thead>
              <tbody>
                {f.sweep.map((s) => (
                  <tr key={s.bar} className={cn('border-t border-line', s.bar === f.bar && 'font-semibold')}>
                    <th scope="row" className="font-medium text-fg-2">{pWords(s.bar)}</th>
                    <td><Stat s={s.dev} /></td>
                    <td><Stat s={s.test} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </section>
  );
}

function Precision() {
  const api = useApi();
  const [labeller, setLabeller] = useState('owner');
  const query = useQuery({ queryKey: ['markx-precision', labeller], queryFn: () => api.getMarkxPrecision(labeller),
    staleTime: 30_000 });
  if (query.isPending) return <LoadingState label="Counting" rows={4} />;
  if (query.isError || !query.data) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const data = query.data;
  const rules = data.flags.rule ? Object.entries(data.flags.rule).filter(([, n]) => n) : [];
  return (
    <section aria-label="Precision">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 text-[0.8125rem] leading-5 text-fg-2">
          Each feature's decisions against {data.labeller === 'owner' ? 'your labels' : `${data.labeller}'s labels`}: the share
          right, its 95% interval and how many are labelled. Pools are weighed back to their size.
          {data.cut ? ` Dev is before ${data.cut}, test from it.` : ''}
          {data.unsure ? ` ${data.unsure} unsure left out.` : ''}
        </p>
        {data.labellers.length > 1 ? (
          <label className="inline-flex items-center gap-2 text-[0.8125rem] text-fg-2">
            labels by
            <Select value={labeller} onChange={(e) => setLabeller(e.target.value)} aria-label="Labels by">
              {data.labellers.map((l) => <option key={l} value={l}>{l === 'owner' ? 'you' : l}</option>)}
            </Select>
          </label>
        ) : null}
      </div>
      {data.features.length ? data.features.map((f) => <FeatureCard key={f.feature} f={f} target={data.target} />) : (
        data.building
          ? <EmptyState className="mt-6" title="The queue is being built" description={BUILDING} />
          : <EmptyState className="mt-6" title="No decisions to count yet" />
      )}
      {rules.length ? (
        <p className="mt-3 text-[0.8125rem] leading-5 text-fg-2">
          One tap on members Mark IX's rules placed: {rules.map(([k, n]) => `${n} ${ANSWER_WORDS[k] ?? k}`).join(', ')}
        </p>
      ) : null}
    </section>
  );
}

/**
 * Mark X's labels (issue 0086 F): the queue (decisions near a bar, every merge, a weighted sample of the rest), one
 * item at a time with the evidence as the judge saw it and its verdict only after your answer; and each feature's
 * precision on your labels, dev and test by date, with its bar and interval.
 */
export default function MarkXLabels() {
  const [view, setView] = useState<'label' | 'precision'>('label');
  return (
    <div>
      <div role="group" aria-label="Labels view" className="mb-3 flex gap-2">
        {(['label', 'precision'] as const).map((v) => (
          <Button key={v} size="sm" variant={view === v ? 'primary' : 'ghost'} aria-pressed={view === v} onClick={() => setView(v)}>
            {v}
          </Button>
        ))}
      </div>
      <h2 className={H2}>{view === 'label' ? 'Your labels' : 'Precision per feature'}</h2>
      <div className="mt-3">{view === 'label' ? <Queue /> : <Precision />}</div>
      {view === 'precision' ? <PerspectiveAccuracy /> : null}   {/* 0119 B7 */}
    </div>
  );
}
