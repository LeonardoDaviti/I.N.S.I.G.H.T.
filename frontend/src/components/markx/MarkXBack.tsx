import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { markxBackApi, type MarkxBackLabel, type MarkxBackRow } from '../../services/api';   // 0136
import { Button, TextLink } from '../ui';
import { postBylineTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import { bylineText } from '../../lib/byline';

const LABELS: MarkxBackLabel[] = ['development', 'retold', 'related', 'unrelated'];
const TRIG_WORDS: Record<string, string> = { E: 'names its subject', L: 'links its page', V: 'reads like it' };

function pct(x: number) {
  return `${Math.round(x * 100)}%`;
}

function LabelButtons({ row }: { row: MarkxBackRow }) {
  const client = useQueryClient();
  const [mine, setMine] = useState<MarkxBackLabel | null>(row.label);
  const tap = useMutation({
    mutationFn: (answer: MarkxBackLabel | 'undo') => markxBackApi.label(row.id, answer),
    onSuccess: (got) => {
      setMine(got.label);
      void client.invalidateQueries({ queryKey: ['markx-back'] });
    },
  });
  return (
    <span className="mt-2 flex flex-wrap items-center gap-1 text-[0.75rem]" role="group" aria-label="What is this?">
      {mine ? (
        <>
          <span className="text-fg-2">you said {mine}</span>
          <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={tap.isPending} onClick={() => tap.mutate('undo')}>undo</Button>
        </>
      ) : LABELS.map((l) => (
        <Button key={l} size="sm" variant="ghost" className="text-[0.75rem]" disabled={tap.isPending} onClick={() => tap.mutate(l)}>
          {l}
        </Button>
      ))}
      {tap.isError ? <span role="alert" className="text-fg">× not saved</span> : null}
    </span>
  );
}

function Row({ row }: { row: MarkxBackRow }) {
  return (
    <li className="border-b border-line py-3" data-back-row={row.id}>
      <p className="text-[0.9375rem] font-semibold leading-[1.35] text-fg [overflow-wrap:anywhere]">
        <TextLink to={`/posts/${encodeURIComponent(row.story)}`}>{row.headline || '(no title)'}</TextLink>
      </p>
      <p className="mt-0.5 text-[0.8125rem] tabular-nums leading-5 text-fg-2">
        {postBylineTime(row.first_at)} · back {plural(row.days_later, 'day')} later
        {row.trig.length ? ` · ${row.trig.map((t) => TRIG_WORDS[t] ?? t).join(', ')}` : ''}
      </p>
      {row.old_thing || row.what_new.length ? (
        <p className="mt-1 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
          {row.old_thing ? <>Haiku: <span className="text-fg">{row.old_thing}</span></> : 'Haiku'}
          {row.what_new.length ? ` — ${row.what_new.join(' / ')}` : ''}
          <span className="text-fg-3"> ({row.runs.filter((r) => r === 'development').length} of {row.runs.length} runs)</span>
        </p>
      ) : null}
      <ul aria-label="The new posts" className="mt-1">
        {row.posts.map((p) => (
          <li key={p.id} className="text-[0.8125rem] leading-5 [overflow-wrap:anywhere]">
            <span className="text-fg-3">{p.n}. </span>
            <TextLink to={`/posts/${encodeURIComponent(p.id)}`} muted>{p.title || '(no title)'}</TextLink>
            <span className="text-fg-3">
              {p.source ? ` · ${bylineText(p.byline, p.source)}` : ''}{p.at ? ` · ${postBylineTime(p.at)}` : ''}
              {p.verdict ? ` · ${p.verdict}` : ''}
            </span>
          </li>
        ))}
      </ul>
      <LabelButtons row={row} />
    </li>
  );
}

/**
 * Back in the news (issue 0136, Shadow): old Mark IX stories with a fresh development, judged by Haiku three times.
 * Shown on /markx only, never in Mark IX's News; each row takes the owner's label, and the running precision is shown.
 */
export default function MarkXBack() {
  const query = useQuery({ queryKey: ['markx-back'], queryFn: () => markxBackApi.list(), staleTime: 60_000 });
  if (!query.data) return null;   // loading or failed: Mark X News below stands alone
  const { items, precision, measured, counts } = query.data;
  if (!items.length && !counts.candidates) return null;
  return (
    <section aria-label="Back in the news" className="mb-8">
      <h2 className="border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2">Back in the news</h2>
      <p className="mt-2 text-[0.75rem] leading-5 text-fg-3">
        {measured.words}
        {' · '}
        {precision.precision === null ? 'none labelled yet'
          : `your labels: ${precision.development} of ${precision.labelled} development (${pct(precision.precision)})`}
        {' · '}{plural(counts.candidates ?? 0, 'candidate')}{counts.waiting ? `, ${counts.waiting} waiting for Haiku` : ''}
      </p>
      {items.length ? <ul>{items.map((row) => <Row key={row.id} row={row} />)}</ul>
        : <p className="mt-2 text-[0.8125rem] text-fg-2">No old story is back with a development yet.</p>}
    </section>
  );
}
