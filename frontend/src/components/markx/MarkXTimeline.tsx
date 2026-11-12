import { useState } from 'react';

import { TextLink } from '../ui';
import { plural } from '../../lib/format';
import type { MarkxTimeline, MarkxTimelineEvent, MarkxTimelineKind } from '../../services/markx';

/** Why a line is on the timeline (0165 C), in words. */
const WHY: Record<MarkxTimelineKind, string> = {
  birth: 'first seen', earlier_name: 'last seen under its earlier name', renamed: 'first seen under its name now',
  release: 'release', first_outside: 'first outside mention', outside: 'outside mentions', story: 'story',
  later: 'later development', back: 'back in the news',
};

export function timelineWhy(e: MarkxTimelineEvent): string {
  const parts: string[] = [];
  if (e.kind === 'birth') parts.push(e.name ? `first seen, as ${e.name}` : WHY.birth);
  else if (e.kind === 'earlier_name') parts.push(`last seen as ${e.name ?? 'its earlier name'}`);
  else if (e.kind === 'renamed') parts.push(`renamed${e.name ? ` ${e.name}` : ''}`);
  else if (e.kind === 'release') parts.push(e.name ? `release · ${e.name}` : WHY.release);
  else if (e.kind === 'first_outside') parts.push(e.linked ? 'first outside mention · links back' : WHY.first_outside);
  else if (e.kind === 'outside') parts.push(`outside · ${plural(e.n ?? 1, 'post')}${e.sources ? `, ${plural(e.sources, 'source')}` : ''} in ${e.month ?? 'the month'}`);
  else if (e.kind === 'story') parts.push(`${e.mark === 'ix' ? 'Mark IX story' : 'story'}${e.voices ? ` · ${plural(e.voices, 'source')}` : ''}`);
  else parts.push(WHY[e.kind]);
  for (const also of e.also ?? []) parts.push(WHY[also]);
  return parts.join(' · ');
}

/** One line: the date, what it is (the post, or the story), its source, and why it is on the line. */
export function TimelineLine({ e }: { e: MarkxTimelineEvent }) {
  const title = e.post?.title || (e.kind === 'story' || e.kind === 'back' ? e.headline : null) || '(no title)';
  return (
    <li className="flex min-w-0 gap-3 text-[0.8125rem] text-fg-2" data-kind={e.kind}>
      <span className="w-[5.5rem] shrink-0 tabular-nums text-fg-3">{e.at.slice(0, 10)}</span>
      <span className="min-w-0 [overflow-wrap:anywhere]">
        {e.post ? <TextLink to={`/posts/${encodeURIComponent(e.post.id)}`} muted>{title}</TextLink>
          : e.kind === 'story' && e.mark === 'x' && e.story
            ? <TextLink to={`/markx/stories/${encodeURIComponent(e.story)}`} muted>{title}</TextLink>
            : <span className="text-fg">{title}</span>}
        <span className="text-fg-3">{e.post?.source ? ` · ${e.post.source}` : ''} · {timelineWhy(e)}</span>
      </span>
    </li>
  );
}

/**
 * The entity page's Timeline (0165 C): every dated event INSIGHT holds about it, oldest first (its birth, its earlier
 * names, its releases, the outside mentions, its stories, later developments, back in the news); the most important
 * by default, "all" opens the rest.
 */
export function Timeline({ timeline }: { timeline: MarkxTimeline }) {
  const [all, setAll] = useState(false);
  const rows = all ? timeline.items : timeline.items.filter((e) => e.top);
  const left = timeline.total - rows.length;
  return (
    <section aria-label="Timeline">
      <h2 className="border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2">
        Timeline · {plural(timeline.total, 'event')}
        {timeline.earlier.length ? <span className="font-normal text-fg-3"> · earlier {timeline.earlier.length > 1 ? 'names' : 'name'}{' '}
          {timeline.earlier.map((x) => x.name).filter(Boolean).join(', ')}</span> : null}
      </h2>
      <ol className="mt-2 space-y-1">{rows.map((e, n) => <TimelineLine key={`${e.kind}-${e.post?.id ?? e.story ?? n}-${e.at}`} e={e} />)}</ol>
      {left > 0 ? (
        <button type="button" className="mt-2 text-[0.8125rem] text-fg underline-offset-2 hover:underline"
                onClick={() => setAll(true)}>All {plural(timeline.total, 'event')}</button>
      ) : null}
    </section>
  );
}
