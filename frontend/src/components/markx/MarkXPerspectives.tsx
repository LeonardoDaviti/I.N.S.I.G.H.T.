import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type {
  MarkxFact, MarkxFactAnswer, MarkxPerspectiveAnswer, MarkxPerspectiveLabel, MarkxPerspectiveLine, MarkxRate,
  MarkxSheet, MarkxSheetFact, MarkxStoryPost,
} from '../../services/markx';
import { Button, ExternalLink, TextLink } from '../ui';
import { ErrorState, LoadingState } from '../states';
import { feedFullTime, postBylineTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import { errorMessage } from '../../lib/apiError';
import { bylineText } from '../../lib/byline';

export const LABEL_WORDS: Record<MarkxPerspectiveLabel, string> = {
  original: 'original', new_facts: 'new facts', opinion: 'opinion', same: 'same', not_this_story: 'not this story',
};
const LABELS = Object.keys(LABEL_WORDS) as MarkxPerspectiveLabel[];
const FACT_WRONG: { answer: MarkxFactAnswer; words: string }[] = [
  { answer: 'not_new', words: 'not new' }, { answer: 'not_true', words: 'not true to the post' },
  { answer: 'not_about', words: 'not about this story' },
];
const FACT_WORDS: Record<MarkxFactAnswer, string> = { right: 'right', not_new: 'not new', not_true: 'not true to the post',
  not_about: 'not about this story' };
const H3 = 'text-[0.75rem] font-semibold uppercase tracking-[0.04em] text-fg-3';
const SMALL = 'text-[0.75rem]';

function byWords(by: string | null): string {
  if (!by) return '';
  if (by === 'haiku') return 'Haiku';
  return `code: ${by.replace(/^code:/, '').replace(/-/g, ' ')}`;
}

function sources(f: MarkxSheetFact): string {
  return f.sources.filter(Boolean).join(', ');
}

/** The story sheet (0119 B4): what the story's members add, merged, above the members. */
export function StorySheet({ sheet, posts }: { sheet: MarkxSheet; posts: Record<string, MarkxStoryPost> }) {
  const o = sheet.original;
  const first = posts[o.post];
  // Who wrote each (Byline, issue 0185): the member's byline, else the name the sheet kept.
  const who = (post: string, source: string | null) => bylineText(posts[post]?.byline, source);
  return (
    <section aria-label="Story sheet" className="space-y-4 rounded-md border border-line p-4">
      <div>
        <p className={H3}>{o.is_original ? 'Original' : 'Earliest report'}</p>
        <p className="mt-1 text-[0.9375rem] font-semibold leading-snug text-fg [overflow-wrap:anywhere]">
          <TextLink to={`/posts/${encodeURIComponent(o.post)}`}>{o.title || '(no title)'}</TextLink>
        </p>
        <p className="text-[0.8125rem] text-fg-2">
          {who(o.post, o.source)}{first ? ` · ${postBylineTime(first.at, new Date())}` : ''}
          {o.also.length ? ` · also primary: ${o.also.map((a) => who(a.post, a.source)).join(', ')}` : ''}
        </p>
        {sheet.source_page ? (
          <p className="text-[0.8125rem] text-fg-2 [overflow-wrap:anywhere]">
            Source page (no member is it): <ExternalLink href={`https://${sheet.source_page}`}>{sheet.source_page}</ExternalLink>
          </p>
        ) : null}
        {o.text ? <p className="mt-1 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">{o.text}…</p> : null}
      </div>
      {sheet.before.facts.length || sheet.before.claims.length ? (
        <div>
          <p className={H3}>Before the release</p>
          <ul className="mt-1 space-y-0.5 text-[0.8125rem] leading-5 text-fg">
            {sheet.before.facts.map((f) => <li key={f.lines.join()}>{f.fact} <span className="text-fg-3">({sources(f)})</span></li>)}
            {sheet.before.claims.map((c, n) => <li key={`c${n}`}>{c.claim} <span className="text-fg-3">({who(c.post, c.source)})</span></li>)}
          </ul>
        </div>
      ) : null}
      <div>
        <p className={H3}>New facts</p>
        {sheet.new_facts.length ? (
          <ul className="mt-1 space-y-0.5 text-[0.8125rem] leading-5 text-fg" aria-label="New facts">
            {sheet.new_facts.map((f) => (
              <li key={f.lines.join()} data-correction={f.correction || undefined}>
                {f.correction ? <span className="font-semibold">Correction: </span> : null}
                {f.fact} <span className="text-fg-3">({sources(f)})</span>
              </li>
            ))}
          </ul>
        ) : <p className="mt-1 text-[0.8125rem] text-fg-3">None: the others say what the first said.</p>}
      </div>
      {sheet.claims.length ? (
        <div>
          <p className={H3}>Unconfirmed claims</p>
          <ul className="mt-1 space-y-0.5 text-[0.8125rem] leading-5 text-fg">
            {sheet.claims.map((c, n) => <li key={n}>{c.claim} <span className="text-fg-3">({who(c.post, c.source)})</span></li>)}
          </ul>
        </div>
      ) : null}
      {sheet.opinions.length ? (
        <div>
          <p className={H3}>Opinions</p>
          <ul className="mt-1 space-y-0.5 text-[0.8125rem] leading-5 text-fg">
            {sheet.opinions.map((o2, n) => (
              <li key={n}>{o2.point || <span className="text-fg-3">an opinion without a stated point</span>}{' '}
                <span className="text-fg-3">({who(o2.post, o2.source)})</span></li>
            ))}
          </ul>
        </div>
      ) : null}
      {sheet.related.length ? (
        <div>
          <p className={H3}>Related, not members</p>
          <ul className="mt-1 space-y-0.5 text-[0.8125rem] leading-5 text-fg-2">
            {sheet.related.map((r) => (
              <li key={r.post}><TextLink to={`/posts/${encodeURIComponent(r.post)}`} muted>{r.title || '(no title)'}</TextLink>
                <span className="text-fg-3"> · {who(r.post, r.source)}</span></li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-[0.8125rem] text-fg-2">
        {plural(sheet.same, 'more says', 'more say')} the same{sheet.copies ? `, plus ${plural(sheet.copies, 'copy', 'copies')}` : ''}.
        {sheet.lines > sheet.merged ? <span className="text-fg-3"> {sheet.lines} fact lines merged into {sheet.merged}.</span> : null}
      </p>
    </section>
  );
}

/** ✓ / ✗ on one new fact; ✗ asks why in one more tap (0119 B7). */
function FactButtons({ story, post, fact }: { story: string; post: string; fact: MarkxFact }) {
  const api = useApi();
  const [mine, setMine] = useState<MarkxFactAnswer | null>(fact.mine);
  const [asking, setAsking] = useState(false);
  const tap = useMutation({
    mutationFn: (answer: MarkxFactAnswer) => api.labelMarkxFact(story, post, fact.index, answer),
    onSuccess: (got) => { setMine(got.answer); setAsking(false); },
  });
  if (mine && !asking) {
    return (
      <span className={`${SMALL} text-fg-2`} data-mine={mine}>
        {' '}· you: {FACT_WORDS[mine]}{' '}
        <Button size="sm" variant="ghost" className={SMALL} onClick={() => setAsking(true)}>change</Button>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1" role="group" aria-label="Is this a new fact?">
      {asking ? FACT_WRONG.map((w) => (
        <Button key={w.answer} size="sm" variant="ghost" className={SMALL} disabled={tap.isPending}
          onClick={() => tap.mutate(w.answer)}>{w.words}</Button>
      )) : (
        <>
          <Button size="sm" variant="ghost" className={SMALL} aria-label="right" disabled={tap.isPending}
            onClick={() => tap.mutate('right')}>✓</Button>
          <Button size="sm" variant="ghost" className={SMALL} aria-label="wrong" disabled={tap.isPending}
            onClick={() => setAsking(true)}>✗</Button>
        </>
      )}
      {tap.isError ? <span role="alert" className={`${SMALL} text-fg`}>{errorMessage(tap.error)}</span> : null}
    </span>
  );
}

/** ✓ / ✗ on a member's label; ✗ offers the right label in one tap (0119 B7). */
function LabelButtons({ story, line }: { story: string; line: MarkxPerspectiveLine }) {
  const api = useApi();
  const client = useQueryClient();
  const [mine, setMine] = useState(line.mine?.answer ?? null);
  const [asking, setAsking] = useState(false);
  const tap = useMutation({
    mutationFn: (answer: MarkxPerspectiveAnswer) => api.labelMarkxPerspective(story, line.post, answer),
    onSuccess: (got) => {
      setMine(got.answer);
      setAsking(got.answer === 'wrong');
      void client.invalidateQueries({ queryKey: ['markx-perspective-accuracy'] });
    },
  });
  if (mine && !asking) {
    const words = mine === 'right' ? 'right' : mine === 'wrong' ? 'wrong' : `it is ${LABEL_WORDS[mine]}`;
    return (
      <span className={`${SMALL} text-fg-2`} data-mine={mine}>
        you: {words}{' '}
        <Button size="sm" variant="ghost" className={SMALL} onClick={() => setAsking(true)}>change</Button>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1" role="group" aria-label="Is this label right?">
      {asking ? (
        <>
          <span className={`${SMALL} text-fg-3`}>it is:</span>
          {LABELS.filter((l) => l !== line.label).map((l) => (
            <Button key={l} size="sm" variant="ghost" className={SMALL} disabled={tap.isPending}
              onClick={() => tap.mutate(l)}>{LABEL_WORDS[l]}</Button>
          ))}
        </>
      ) : (
        <>
          <Button size="sm" variant="ghost" className={SMALL} aria-label="label right" disabled={tap.isPending}
            onClick={() => tap.mutate('right')}>✓</Button>
          <Button size="sm" variant="ghost" className={SMALL} aria-label="label wrong" disabled={tap.isPending}
            onClick={() => tap.mutate('wrong')}>✗</Button>
        </>
      )}
      {tap.isError ? <span role="alert" className={`${SMALL} text-fg`}>{errorMessage(tap.error)}</span> : null}
    </span>
  );
}

/** One member's line (0119 B6): its sign and label, its new facts one line each, copies folded, the label buttons. */
export function MemberLine({ story, line, posts, now }: { story: string; line: MarkxPerspectiveLine;
  posts: Record<string, MarkxStoryPost>; now: Date }) {
  const p = posts[line.post];
  return (
    <li className="grid gap-x-3 gap-y-0.5 border-t border-line py-2.5 first:border-t-0 sm:grid-cols-[1.25rem_1fr]"
      data-label={line.label ?? 'unjudged'}>
      <span aria-hidden="true" className="text-[0.9375rem] font-semibold leading-5 text-fg">{line.sign ?? '·'}</span>
      <span className="min-w-0">
        <span className="block min-w-0 text-[0.875rem] leading-5 text-fg [overflow-wrap:anywhere]">
          <TextLink to={`/posts/${encodeURIComponent(line.post)}`}>{p?.title || '(no title)'}</TextLink>
          <span className="text-fg-3"> · {bylineText(p?.byline, p?.source)}</span>
          {p ? <span className="text-fg-3" title={feedFullTime(p.at)}> · {postBylineTime(p.at, now)}</span> : null}
        </span>
        <span className="block text-[0.8125rem] leading-5 text-fg-2">
          {line.label ? <span className="font-medium text-fg">{LABEL_WORDS[line.label]}</span> : 'not judged yet'}
          {line.by ? <span className="text-fg-3"> · {byWords(line.by)}</span> : null}
          {line.before ? <span className="text-fg-3"> · before the original</span> : null}
          {line.copies.length ? <span className="text-fg-3"> · {plural(line.copies.length, 'copy', 'copies')} folded</span> : null}
          {line.label ? <>{' '}<LabelButtons story={story} line={line} /></> : null}
        </span>
        {line.point ? <span className="block text-[0.8125rem] leading-5 text-fg-2">~ {line.point}</span> : null}
        {line.facts.length ? (
          <ul className="mt-0.5 space-y-0.5" aria-label="Its new facts">
            {line.facts.map((f) => (
              <li key={f.index} className="text-[0.8125rem] leading-5 text-fg [overflow-wrap:anywhere]">
                + {f.correction ? <span className="font-semibold">correction: </span> : null}{f.fact}
                {f.span ? <span className="text-fg-3" title={f.span}> “{f.span.length > 80 ? `${f.span.slice(0, 80)}…` : f.span}”</span> : null}
                {' '}<FactButtons story={story} post={line.post} fact={f} />
              </li>
            ))}
          </ul>
        ) : null}
        {line.claims.length ? (
          <span className="block text-[0.75rem] leading-5 text-fg-3">unconfirmed: {line.claims.map((c) => c.claim).join('; ')}</span>
        ) : null}
      </span>
    </li>
  );
}

function pc(r: MarkxRate): string {
  if (r.p === null) return '–';
  return `${Math.round(100 * r.p)}% (${Math.round(100 * r.lo)}–${Math.round(100 * r.hi)}), ${r.k}/${r.n}`;
}

/** The Labels tab's perspectives section (0119 B7): your labels counted, the running accuracy against the lab's. */
export function PerspectiveAccuracy() {
  const api = useApi();
  const query = useQuery({ queryKey: ['markx-perspective-accuracy'], queryFn: () => api.getMarkxPerspectiveAccuracy(),
    staleTime: 30_000 });
  if (query.isPending) return <LoadingState label="Loading perspective labels" rows={2} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} title="Perspective labels did not load" />;
  const a = query.data;
  const lab = (x: number) => `${Math.round(100 * x)}%`;
  return (
    <section aria-label="Perspectives" className="mt-10">
      <h2 className="border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2">Perspectives and new facts</h2>
      <p className="mt-2 text-[0.8125rem] leading-5 text-fg-2">
        {plural(a.labels, 'label')} on members, {plural(a.fact_labels, 'label')} on new facts. Only reported: nothing is
        tuned on them. The lab's numbers (unseen stories, {a.lab.date}) count until you have 50.
      </p>
      <table className="mt-3 w-full text-left text-[0.8125rem] tabular-nums">
        <thead className="text-fg-3"><tr><th className="py-1 font-medium">On your labels</th><th className="font-medium">yours</th>
          <th className="font-medium">lab</th></tr></thead>
        <tbody className="text-fg">
          <tr><td className="py-1">worth opening</td><td>{pc(a.worth)}</td><td>{lab(a.lab.worth)}</td></tr>
          <tr><td className="py-1">the four labels</td><td>{pc(a.four)}</td><td>{lab(a.lab.four)}</td></tr>
          <tr><td className="py-1">new facts (label)</td><td>{pc(a.new_facts)}</td><td>{lab(a.lab.new_facts)}</td></tr>
          <tr><td className="py-1">each new fact</td><td>{pc(a.facts)}</td><td>–</td></tr>
          {LABELS.filter((l) => a.per_label[l] && l !== 'new_facts').map((l) => (
            <tr key={l}><td className="py-1">{LABEL_WORDS[l]}</td><td>{pc(a.per_label[l]!)}</td><td>–</td></tr>
          ))}
        </tbody>
      </table>
      {Object.keys(a.errors).length ? (
        <p className="mt-2 text-[0.75rem] leading-5 text-fg-3">
          Errors: {Object.entries(a.errors).map(([k, n]) => `${k.replace('->', ' → ').replace(/_/g, ' ')} ${n}`).join(', ')}
        </p>
      ) : null}
    </section>
  );
}
