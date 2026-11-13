import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { markxRoundupApi, type MarkxRoundupIssue, type MarkxRoundupItem } from '../../services/api';   // 0181
import type { MarkxStoryView } from '../../services/markx';
import { Button, TextLink } from '../ui';
import { plural } from '../../lib/format';

const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';

/** A story's "also in round-ups" line (0181): the round-ups carrying one of its members. Display only. */
export function AlsoInRoundups({ roundups }: { roundups: MarkxStoryView['roundups'] }) {
  if (!roundups || !roundups.length) return null;
  return (
    <p className="text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]" data-also-in-roundups>
      Also in round-ups:{' '}
      {roundups.map((r, k) => (
        <span key={r.post}>
          {k ? ', ' : ''}
          <TextLink to={`/posts/${encodeURIComponent(r.post)}`} muted>{r.source || r.title || 'a round-up'}</TextLink>
          <span className="text-fg-3"> (item {r.n})</span>
        </span>
      ))}
    </p>
  );
}

function Row({ item }: { item: MarkxRoundupItem }) {
  const head = item.headline || item.units[0]?.item || '(no title)';
  const to = item.kind === 'mx_story' && item.ref ? `/markx/stories/${encodeURIComponent(item.ref)}`
    : item.posts[0] ? `/posts/${encodeURIComponent(item.posts[0])}` : null;
  const sources = Array.from(new Set(item.units.map((u) => u.source).filter(Boolean)));
  return (
    <li className="border-b border-line py-2" data-roundup-item={item.key}>
      <p className="text-[0.875rem] leading-[1.35] text-fg [overflow-wrap:anywhere]">
        {to ? <TextLink to={to}>{head}</TextLink> : head}
      </p>
      <p className="mt-0.5 text-[0.75rem] leading-5 text-fg-2">
        {plural(item.curators, 'curator')} · {sources.join(', ')}
        {item.only_roundups ? <span className="text-fg"> · only in round-ups</span> : null}
      </p>
    </li>
  );
}

/** "1 Jun" (a day) or "1–7 Jun" (a week), in the owner's offset the issue was built at. */
function when(issue: Pick<MarkxRoundupIssue, 'span' | 'from' | 'until'>, offsetMinutes: number): string {
  const local = (iso: string, back = 0) => new Date(Date.parse(iso) + offsetMinutes * 60_000 - back);
  const day = (d: Date) => `${d.getUTCDate()} ${d.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })}`;
  return issue.span === 'day' ? day(local(issue.from)) : `${day(local(issue.from))}–${day(local(issue.until, 1))}`;
}

function Issue({ issue, offset }: { issue: MarkxRoundupIssue; offset: number }) {
  const items = issue.items ?? [];
  const left = Object.values(issue.left_out ?? {}).reduce((a, b) => a + b, 0);
  return (
    <div data-roundup-issue={issue.id}>
      <p className="text-[0.75rem] text-fg-2">
        {issue.span === 'day' ? 'Daily' : 'Weekly'} · {when(issue, offset)} · {plural(issue.roundups, 'round-up')} ·{' '}
        {plural(issue.count, 'item')}{issue.version > 1 ? ` · version ${issue.version}` : ''}
        {left ? ` · ${left} left out (not news)` : ''}
      </p>
      {items.length ? <ul aria-label="Round-up items">{items.map((i) => <Row key={i.key} item={i} />)}</ul>
        : <p className="text-[0.8125rem] text-fg-2">No round-up items in this {issue.span}.</p>}
    </div>
  );
}

/**
 * INSIGHT's own round-ups (0181): a daily and a weekly issue, each built once after its day or week closes and kept.
 * The latest of each, and the past ones to open.
 */
export default function MarkXRoundup() {
  const [span, setSpan] = useState<'day' | 'week'>('day');
  const [picked, setPicked] = useState<number | null>(null);
  const list = useQuery({ queryKey: ['markx-roundup-issues'], queryFn: () => markxRoundupApi.issues(), staleTime: 60_000 });
  const one = useQuery({ queryKey: ['markx-roundup-issue', picked], queryFn: () => markxRoundupApi.issue(picked as number),
    enabled: picked !== null, staleTime: 300_000 });
  const d = list.data;
  const offset = d?.tz_offset_minutes ?? 0;
  const latest = d ? (span === 'day' ? d.daily : d.weekly) : null;
  const shown = picked !== null ? one.data ?? null : latest;
  return (
    <section aria-label="Own round-up" className="mt-6 space-y-2">
      <h2 className={H2}>Own round-up</h2>
      <p className="flex items-center gap-1 text-[0.75rem] text-fg-2" role="group" aria-label="Span">
        {(['day', 'week'] as const).map((s) => (
          <Button key={s} size="sm" variant={s === span && picked === null ? 'secondary' : 'ghost'} className="text-[0.75rem]"
            aria-pressed={s === span && picked === null} onClick={() => { setSpan(s); setPicked(null); }}>
            {s === 'day' ? 'daily' : 'weekly'}
          </Button>
        ))}
      </p>
      {list.isError ? <p role="alert" className="text-[0.8125rem] text-fg">× not loaded</p> : null}
      {d && !shown && picked === null ? <p className="text-[0.8125rem] text-fg-2">No {span === 'day' ? 'daily' : 'weekly'} round-up built yet.</p> : null}
      {shown ? <Issue issue={shown} offset={offset} /> : null}
      {d && d.past.length ? (
        <details>
          <summary className="cursor-pointer text-[0.75rem] text-fg-2">Past round-ups · {d.past.length}</summary>
          <ul aria-label="Past round-ups" className="mt-1 flex flex-wrap gap-1">
            {d.past.map((p) => (
              <li key={p.id}>
                <Button size="sm" variant={picked === p.id ? 'secondary' : 'ghost'} className="text-[0.75rem]"
                  aria-pressed={picked === p.id} onClick={() => setPicked(p.id)}>
                  {p.span === 'day' ? 'daily' : 'weekly'} {when(p, offset)}
                </Button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
