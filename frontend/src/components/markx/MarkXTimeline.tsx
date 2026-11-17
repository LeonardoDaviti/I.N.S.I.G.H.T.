import { useState, type ReactNode } from 'react';

import { TextLink } from '../ui';
import { plural } from '../../lib/format';
import type { MarkxEntityRelation, MarkxStop, MarkxTimeline, MarkxTimelineEvent, MarkxTimelineKind,
  MarkxVersionLine } from '../../services/markx';
import { bylineText } from '../../lib/byline';

/** Why a line is on the timeline (0165 C), in words. */
const WHY: Record<MarkxTimelineKind, string> = {
  birth: 'first seen', earlier_name: 'last seen under its earlier name', renamed: 'first seen under its name now',
  release: 'release', first_outside: 'first outside mention', outside: 'outside mentions', story: 'story',
  later: 'later development', back: 'back in the news', analysis: 'analysis', in_story: 'named in a story',
};

/** What happened to the thing in a story (0165's stops), in words. */
const STOP: Record<MarkxStop, string> = {
  teaser: 'teaser', preview: 'preview', launch: 'launch', availability: 'availability', update: 'update',
  weights: 'weights', benchmark: 'benchmark', ranking: 'ranking', adoption: 'adoption', research: 'research',
  incident: 'incident', deal: 'deal', analysis: 'analysis', other: 'story',
};

export function timelineWhy(e: MarkxTimelineEvent): string {
  const parts: string[] = [];
  if (e.kind === 'birth') parts.push(e.name ? `first seen, as ${e.name}` : WHY.birth);
  else if (e.kind === 'earlier_name') parts.push(`last seen as ${e.name ?? 'its earlier name'}`);
  else if (e.kind === 'renamed') parts.push(`renamed${e.name ? ` ${e.name}` : ''}`);
  else if (e.kind === 'release') parts.push(e.name ? `release · ${e.name}` : WHY.release);
  else if (e.kind === 'first_outside') parts.push(e.linked ? 'first outside mention · links back' : WHY.first_outside);
  else if (e.kind === 'outside') parts.push(`outside · ${plural(e.n ?? 1, 'post')}${e.sources ? `, ${plural(e.sources, 'source')}` : ''} in ${e.month ?? 'the month'}`);
  else if (e.kind === 'story' || e.kind === 'in_story') {
    const what = e.kind === 'in_story' ? WHY.in_story : e.stop ? STOP[e.stop] : WHY.story;
    parts.push(`${what}${e.mark === 'ix' ? ' · Mark IX' : ''}${e.voices ? ` · ${plural(e.voices, 'source')}` : ''}`);
  } else parts.push(WHY[e.kind]);
  for (const also of e.also ?? []) parts.push(WHY[also]);
  return parts.join(' · ');
}

const isStory = (e: MarkxTimelineEvent) => e.kind === 'story' || e.kind === 'in_story' || e.kind === 'back';

/** One line: the date, what it is (the post, or the story), its source, and why it is on the line. */
export function TimelineLine({ e, children }: { e: MarkxTimelineEvent; children?: ReactNode }) {
  const title = e.post?.title || (isStory(e) ? e.headline : null) || '(no title)';
  const stop = e.kind === 'story';
  return (
    <li className="min-w-0 text-[0.8125rem] text-fg-2" data-kind={e.kind}>
      <div className="flex min-w-0 gap-3">
        <span className="w-[5.5rem] shrink-0 tabular-nums text-fg-3">{e.at.slice(0, 10)}</span>
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {e.post ? <TextLink to={`/posts/${encodeURIComponent(e.post.id)}`} muted>{title}</TextLink>
            : (e.kind === 'story' || e.kind === 'in_story') && e.mark === 'x' && e.story
              ? <TextLink to={`/markx/stories/${encodeURIComponent(e.story)}`} muted>
                  {stop ? <span className="font-semibold text-fg">{title}</span> : title}
                </TextLink>
              : <span className="text-fg">{title}</span>}
          <span className="text-fg-3">{e.post?.source ? ` · ${bylineText(e.post.byline, e.post.source)}` : ''} · {timelineWhy(e)}</span>
        </span>
      </div>
      {children}
    </li>
  );
}

/** The lines shown, as the line reads: each stop (a story about the thing) with the posts inside it (or an analysis
 *  after it) under it; the other lines on their own, oldest first. */
export function timelineRows(items: MarkxTimelineEvent[]): { e: MarkxTimelineEvent; under: MarkxTimelineEvent[] }[] {
  const stops = new Set(items.filter((e) => e.kind === 'story' && e.story).map((e) => e.story as string));
  const under = new Map<string, MarkxTimelineEvent[]>();
  const rows: { e: MarkxTimelineEvent; under: MarkxTimelineEvent[] }[] = [];
  for (const e of items) {
    if (!isStory(e) && e.on && stops.has(e.on)) {
      under.set(e.on, [...(under.get(e.on) ?? []), e]);
    } else rows.push({ e, under: [] });
  }
  for (const r of rows) if (r.e.kind === 'story' && r.e.story) r.under = under.get(r.e.story) ?? [];
  return rows;
}

/**
 * The entity page's Timeline (0165 C): every dated event INSIGHT holds about it, oldest first (its birth, its earlier
 * names, its releases, the outside mentions, the stories about it as stops with the posts inside them and the
 * breakdowns written on it, back in the news); the most important by default, "all" opens the rest (the stories that
 * only name it among them).
 */
export function Timeline({ timeline }: { timeline: MarkxTimeline }) {
  const [all, setAll] = useState(false);
  const shown = all ? timeline.items : timeline.items.filter((e) => e.top);
  const left = timeline.total - shown.length;
  const key = (e: MarkxTimelineEvent, n: number) => `${e.kind}-${e.post?.id ?? e.story ?? n}-${e.at}`;
  return (
    <section aria-label="Timeline">
      <h2 className="border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2">
        Timeline · {plural(timeline.total, 'event')}
        {timeline.earlier.length ? <span className="font-normal text-fg-3"> · earlier {timeline.earlier.length > 1 ? 'names' : 'name'}{' '}
          {timeline.earlier.map((x) => x.name).filter(Boolean).join(', ')}</span> : null}
      </h2>
      <ol className="mt-2 space-y-1">
        {timelineRows(shown).map(({ e, under }, n) => (
          <TimelineLine key={key(e, n)} e={e}>
            {under.length ? (
              <ol aria-label="In this story" className="ml-[6.25rem] mt-1 space-y-1 border-l border-line pl-3">
                {under.map((u, k) => <TimelineLine key={key(u, k)} e={u} />)}
              </ol>
            ) : null}
          </TimelineLine>
        ))}
      </ol>
      {left > 0 ? (
        <button type="button" className="mt-2 text-[0.8125rem] text-fg underline-offset-2 hover:underline"
                onClick={() => setAll(true)}>All {plural(timeline.total, 'event')}</button>
      ) : null}
    </section>
  );
}


/**
 * 0220: the family's versions on one line ("Orbit 2 -> Orbit 2.5 -> Orbit 3"), each with the month of its first post
 * about it; the page's own version marked, the others linked. A family running two numbered lines shows each.
 */
export function VersionLine({ line }: { line: MarkxVersionLine }) {
  return (
    <section aria-label="Version line">
      <h2 className="border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2">
        Version line{line.family.name ? <span className="font-normal text-fg-3"> · {line.family.name}</span> : null}
      </h2>
      {line.lines.map((stops, n) => (
        <ol key={n} className="mt-2 flex flex-wrap items-baseline gap-x-1 gap-y-1 text-[0.8125rem]">
          {stops.map((s, k) => (
            <li key={s.id} className="flex items-baseline gap-x-1">
              {k ? <span aria-hidden="true" className="text-fg-3">→ </span> : null}
              {s.current ? <span aria-current="true" className="font-semibold text-fg">{s.name}</span>
                : <TextLink to={`/markx/entities/${encodeURIComponent(s.id)}`}>{s.name}</TextLink>}
              {s.first ? <span className="tabular-nums text-fg-3"> · {s.first.slice(0, 7)}</span> : null}
            </li>
          ))}
        </ol>
      ))}
    </section>
  );
}

const RELATION: Record<MarkxEntityRelation['relation'], [string, string]> = {
  based_on: ['Based on', 'Built on it'], released: ['Released', 'Released by'], acquired: ['Acquired', 'Acquired by'],
  part_of: ['Part of', 'Its parts'], partnered_with: ['Partnered with', 'Partnered with'],
};

/** 0220: how a relation reads from this thing's page (out: it -> the other thing; in: the other thing -> it). */
export const relationWords = (relation: MarkxEntityRelation['relation'], direction: MarkxEntityRelation['direction']) =>
  RELATION[relation][direction === 'out' ? 0 : 1];

/** 0220: the relations posts state between this thing and others (only the measured ones reach the page), grouped. */
export function ThingLinks({ relations }: { relations: MarkxEntityRelation[] }) {
  if (!relations.length) return null;
  const groups = new Map<string, MarkxEntityRelation[]>();
  for (const r of relations) {
    const k = relationWords(r.relation, r.direction);
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }
  return (
    <section aria-label="Links">
      <h2 className="border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2">Links</h2>
      <ul className="mt-2 space-y-1 text-[0.8125rem] text-fg-2">
        {[...groups].map(([words, rows]) => (
          <li key={words} className="[overflow-wrap:anywhere]">
            {words}:{' '}
            {rows.map((r, n) => (
              <span key={r.other.id}>{n ? ', ' : ''}
                <TextLink to={`/markx/entities/${encodeURIComponent(r.other.id)}`}>{r.other.name ?? 'a thing'}</TextLink>
                <span className="text-fg-3"> ({plural(r.posts, 'post')})</span>
              </span>
            ))}
          </li>
        ))}
      </ul>
    </section>
  );
}
