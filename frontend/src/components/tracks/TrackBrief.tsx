import { Fragment, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  briefApi, type BriefPoint, type QuickLook, type Thing, type ThingFieldDef, type ThingPost, type ThingSection,
} from '../../services/tracks';
import { Button, Chip, ExternalLink, FilterChip, TextLink } from '../ui';
import { ErrorState, LoadingState } from '../states';
import {
  chipParams, citeMarks, dayWord, fieldWord, filterChips, hostOf, kindWord, nextSort, sinceLine, sortThings,
  thingFacts, thingLinks, thingName, toggleChip, weekDay, weekLine, type FilterChipDef, type SortState,
} from './briefWords';

/**
 * The track briefer's reading views (issue 0245, frontend v10.28): the quick look on top of a track, the weekly
 * issue with its date strip, and the tables with filter chips. Everything comes from the backend's typed rows; no
 * word here is about one track. P6: no metadata on top (no model, no counts beyond "N new"), citations are quiet
 * superscript links to the posts (0002).
 */

const postHref = (id: string) => `/posts/${encodeURIComponent(id)}`;
const QUICK_ROWS = 5;   // v10.29: the quick look shows a kind's newest rows; "see all" opens the rest

/** A practice in one line: what, then its result ("→ 1.8x faster"). */
const practiceLine = (p: Thing) => [p.fields.what?.shown, p.fields.result?.shown].filter(Boolean).join(' → ');

/**
 * The ↗ to a thing's newest post, in INSIGHT (v10.29): a post's own address can be a feed bridge's (a Nitter or
 * Telegram bridge on the server's network) that the reader's device cannot open; the post page links its original.
 */
function OpenThing({ thing, name }: { thing: Thing; name: string }) {
  const post = thing.posts[0];
  if (!post) return null;
  return (
    <TextLink to={postHref(post.id)} aria-label={`Open the post about ${name}`} title={post.title ?? undefined}
      className="shrink-0 text-fg-2 no-underline">↗</TextLink>
  );
}

/** "· 3 sources" when more than one of the reader's sources reported the thing (v10.29: the brief's rank). */
function Sources({ thing }: { thing: Thing }) {
  return thing.sources && thing.sources > 1
    ? <span className="text-fg-3 tabular-nums" data-thing-sources={thing.sources}> · {thing.sources} sources</span> : null;
}

/** A thing's own practices (v10.29: a practice from the post that gave the thing is shown inside it). */
function InsidePractices({ thing, max = 3 }: { thing: Thing; max?: number }) {
  const ps = thing.practices ?? [];
  if (!ps.length) return null;
  return (
    <ul className="mt-0.5 space-y-0.5 text-[0.8125rem] leading-5 text-fg-2" data-thing-practices={thing.id}>
      {ps.slice(0, max).map((p) => (
        <li key={p.id} className="[overflow-wrap:anywhere]">
          <span aria-hidden="true">– </span>{practiceLine(p)}
        </li>
      ))}
      {ps.length > max ? <li className="text-fg-3">+{ps.length - max} more</li> : null}
    </ul>
  );
}

function LinkFacts({ thing, fields }: { thing: Thing; fields: ThingFieldDef[] }) {
  const links = thingLinks(thing, fields);
  if (!links.length) return null;
  return (
    <>
      {links.map((l) => (
        <Fragment key={l.name}>
          {' · '}
          <ExternalLink href={l.url} className="text-fg-2" title={`${fieldWord(l.name)}: ${l.url}`}>{hostOf(l.url)}</ExternalLink>
        </Fragment>
      ))}
    </>
  );
}

/** "What changed": at most 4 short points, each with its superscript cites to the posts its rows came from. */
export function WhatChanged({ points, sections, asOf, now }: {
  points: BriefPoint[]; sections: ThingSection[]; asOf?: string | null; now?: Date;
}) {
  const marks = useMemo(() => citeMarks(points, sections), [points, sections]);
  if (!points.length) return null;
  return (
    <section aria-label="What changed" className="mb-4" data-brief-as-of={asOf ?? undefined}>
      <h3 className="text-[0.8125rem] font-semibold text-fg-2">
        What changed{asOf ? <span className="font-normal text-fg-3"> · as of {dayWord(asOf, now)}</span> : null}
      </h3>
      <ul className="mt-1 list-disc space-y-1 pl-5">
        {points.slice(0, 4).map((p, k) => (
          <li key={k} className="text-[0.9375rem] leading-6 text-fg [overflow-wrap:anywhere]">
            {p.text}
            {p.cites.map((c) => {
              const m = marks.get(c.thing);
              if (!m) return null;
              const post = m.thing.posts[0];
              return (
                <sup key={c.thing} className="ml-0.5 text-[0.6875rem] tabular-nums">
                  <TextLink to={postHref(post.id)} muted title={post.title ?? undefined} aria-label={`source ${m.n}`}>{m.n}</TextLink>
                </sup>
              );
            })}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A kind's things as compact rows (the quick look): the name, two or three facts, ↗. */
function CompactRows({ section, onSeeAll }: { section: ThingSection; onSeeAll?: (kind: string) => void }) {
  return (
    <section aria-label={section.header} className="mb-3" data-thing-kind={section.kind}>
      <h3 className="flex items-baseline justify-between gap-2 text-[0.8125rem] font-semibold text-fg-2">
        <span>{newHeader(section)}</span>
        {onSeeAll ? (
          <Button size="sm" variant="ghost" className="text-[0.75rem] font-normal" onClick={() => onSeeAll(section.kind)}>see all ›</Button>
        ) : null}
      </h3>
      <ul>
        {section.things.slice(0, QUICK_ROWS).map((t) => {
          const name = thingName(t, section.fields);
          const facts = thingFacts(t, section.fields);
          return (
            <li key={t.id} className="flex items-baseline gap-2 py-1 text-[0.875rem] leading-5" data-thing={t.id}>
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                <span className="text-fg">{name}</span><Sources thing={t} />
                {facts.length ? <span className="text-fg-2"> · {facts.join(' · ')}</span> : null}
                <LinkFacts thing={t} fields={section.fields} />
                <InsidePractices thing={t} max={2} />
              </span>
              <OpenThing thing={t} name={name} />
            </li>
          );
        })}
      </ul>
      {section.things.length > QUICK_ROWS && !onSeeAll ? (
        <p className="text-[0.75rem] text-fg-3">+{section.things.length - QUICK_ROWS} more</p>
      ) : null}
    </section>
  );
}

/** "New setups (2)": the backend's header is the kind and its count; the quick look says they are new. */
function newHeader(s: ThingSection): string {
  const word = s.header.replace(/\s*\(\d+\)$/, '') || kindWord(s.kind);
  return `New: ${word.toLowerCase()} (${s.count})`;
}

function PostList({ posts, label }: { posts: ThingPost[]; label: string }) {
  if (!posts.length) return null;
  return (
    <section aria-label={label} className="mb-4">
      <h3 className="text-[0.8125rem] font-semibold text-fg-2">{label}</h3>
      <ul className="mt-1">
        {posts.map((p) => (
          <li key={p.id} className="py-0.5 text-[0.875rem] leading-5 [overflow-wrap:anywhere]">
            <TextLink to={postHref(p.id)}>{p.title || '(no title)'}</TextLink>
            {p.why ? <span className="text-fg-2"> · {p.why}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The quick look (0245 moment A) at the top of a track: "since <day> · N new", what changed (when the points are
 * newer than every new row), the new things by kind, the posts that gave no row. "Nothing new since <day>" when
 * empty. When the points are older than the newest find (`stale`), they are not shown here: the page shows them
 * after its posts, "as of <day>" (0002: never a stale brief above fresh posts).
 */
export function QuickLookPanel({ look, stale = look.stale, onSeeAll, onOpenIssue, now }: {
  look: QuickLook; stale?: boolean; onSeeAll?: (kind: string) => void; onOpenIssue?: (week: string) => void; now?: Date;
}) {
  if (look.nothing_new) {
    return (
      <section aria-label="Since you looked" className="mb-6 border-b border-line pb-3" data-quick-look="empty">
        <p className="text-[0.8125rem] text-fg-2">
          Nothing new since {dayWord(look.since, now)}
          {look.last_issue && onOpenIssue ? (
            <>
              {' · '}
              <Button size="sm" variant="ghost" className="text-[0.8125rem]" onClick={() => onOpenIssue(look.last_issue as string)}>
                the issue of {weekDay(look.last_issue)} ›
              </Button>
            </>
          ) : null}
        </p>
      </section>
    );
  }
  return (
    <section aria-label="Since you looked" className="mb-6 border-b border-line pb-3" data-quick-look="new">
      <p className="mb-2 text-right text-[0.8125rem] tabular-nums text-fg-2">{sinceLine(look.since, look.counts.things + look.counts.also, now)}</p>
      {!stale ? <WhatChanged points={look.points} sections={look.sections} now={now} /> : null}
      {look.sections.map((s) => <CompactRows key={s.kind} section={s} onSeeAll={onSeeAll} />)}
      <PostList posts={look.also} label="Also in the track" />
    </section>
  );
}

// ---- things as a table (desktop) or cards (under 640px) --------------------------------------------------------------

function Cell({ thing, field }: { thing: Thing; field: ThingFieldDef }) {
  const v = thing.fields[field.name];
  if (!v) return <span className="text-fg-3">—</span>;
  if (field.type === 'link' && typeof v.value === 'string') {
    return <ExternalLink href={v.shown} className="text-fg-2" title={v.shown}>{hostOf(v.shown)}</ExternalLink>;
  }
  return <span title={v.quote ?? undefined}>{v.shown}</span>;
}

/** A kind's rows: a table at 640px and up (sortable headers when `sort` is given), a stack of cards below. */
export function ThingsView({ section, sort, onSort }: {
  section: Pick<ThingSection, 'kind' | 'fields' | 'things' | 'header'>; sort?: SortState; onSort?: (field: string) => void;
}) {
  const rows = sort !== undefined ? sortThings(section.things, sort) : section.things;
  const fields = section.fields;
  return (
    <>
      <div className="hidden overflow-x-auto sm:block" data-things-table={section.kind}>
        <table className="w-full border-collapse text-left text-[0.8125rem] leading-5">
          <thead>
            <tr className="border-b border-line text-fg-3">
              {fields.map((f) => {
                const dir = sort && sort.field === f.name ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined;
                return (
                  <th key={f.name} scope="col" aria-sort={onSort ? dir ?? 'none' : undefined} className="py-1 pr-3 font-normal">
                    {onSort ? (
                      <button type="button" className="text-left hover:text-fg" onClick={() => onSort(f.name)}>
                        {fieldWord(f.name)}{dir === 'ascending' ? ' ↑' : dir === 'descending' ? ' ↓' : ''}
                      </button>
                    ) : fieldWord(f.name)}
                  </th>
                );
              })}
              <th scope="col" className="w-6 py-1"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id} className="border-b border-line align-baseline" data-thing={t.id}>
                {fields.map((f, i) => (
                  <td key={f.name} className={`py-1.5 pr-3 [overflow-wrap:anywhere] ${i === 0 ? 'text-fg' : 'text-fg-2'}`}>
                    <Cell thing={t} field={f} />
                    {i === 0 ? <><Sources thing={t} /><InsidePractices thing={t} /></> : null}
                  </td>
                ))}
                <td className="py-1.5"><OpenThing thing={t} name={thingName(t, fields)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="sm:hidden" data-things-cards={section.kind}>
        {rows.map((t) => {
          const name = thingName(t, fields);
          return (
            <li key={t.id} className="mb-2 rounded-md border border-line px-3 py-2" data-thing-card={t.id}>
              <p className="flex items-baseline gap-2 text-[0.9375rem] font-semibold leading-5 text-fg">
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{name}<Sources thing={t} /></span>
                <OpenThing thing={t} name={name} />
              </p>
              {thingFacts(t, fields).length ? (
                <p className="mt-0.5 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
                  {thingFacts(t, fields).join(' · ')}<LinkFacts thing={t} fields={fields} />
                </p>
              ) : null}
              <InsidePractices thing={t} />
            </li>
          );
        })}
      </ul>
    </>
  );
}

// ---- the weekly issue ------------------------------------------------------------------------------------------------

/** The issue strip: ‹ the weeks around the chosen one › (newest on the right), the chosen one pressed. */
function DateStrip({ weeks, week, onWeek }: { weeks: string[]; week: string; onWeek: (w: string) => void }) {
  const asc = [...weeks].reverse();
  const i = Math.max(0, asc.indexOf(week));
  const shown = asc.slice(Math.max(0, Math.min(i - 1, asc.length - 3)), Math.max(0, Math.min(i - 1, asc.length - 3)) + 3);
  return (
    <nav aria-label="Issues" className="flex items-center gap-1 text-[0.8125rem]">
      <Button size="sm" variant="ghost" aria-label="Older issue" disabled={i <= 0} onClick={() => onWeek(asc[i - 1])}>‹</Button>
      {shown.map((w) => (
        <FilterChip key={w} selected={w === week} onClick={() => onWeek(w)} aria-label={`Week of ${weekDay(w)}`}>{weekDay(w)}</FilterChip>
      ))}
      <Button size="sm" variant="ghost" aria-label="Newer issue" disabled={i >= asc.length - 1} onClick={() => onWeek(asc[i + 1])}>›</Button>
    </nav>
  );
}

const issueKey = (id: string, week: string) => ['markx-track-issue', id, week] as const;

/** The weekly issue (0245 moment B): Monday-Sunday, what changed, things by kind, "Also in the track", "updated". */
export function WeekIssueView({ trackId, weeks, initial }: { trackId: string; weeks: string[]; initial: string | null }) {
  const [week, setWeek] = useState<string | null>(initial ?? weeks[0] ?? null);
  const query = useQuery({
    queryKey: issueKey(trackId, week ?? ''), queryFn: () => briefApi.issue(trackId, week as string), enabled: Boolean(week),
    staleTime: 60_000,
  });
  if (!week) return <p className="text-[0.8125rem] text-fg-2">No issue yet: the first is built when the track has things.</p>;
  const issue = query.data;
  return (
    <section aria-label="Weekly issue">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2">
        <h2 className="text-[0.9375rem] font-semibold text-fg">
          {issue ? weekLine(issue.week.start, issue.week.end) : `week of ${weekDay(week)}`}
          {issue && !issue.week.closed ? <span className="font-normal text-fg-3"> · so far</span> : null}
          {issue?.updated ? <Chip variant="quiet" className="ml-2 align-middle" title="Corrected after the week closed">updated</Chip> : null}
        </h2>
        <DateStrip weeks={weeks} week={week} onWeek={setWeek} />
      </div>
      {query.isPending ? <LoadingState label="Loading the issue" rows={4} /> : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Could not load the issue" />
      ) : issue && issue.on ? (
        <>
          <WhatChanged points={issue.points} sections={issue.sections} />
          {issue.sections.map((s) => (
            <section key={s.kind} aria-label={s.header} className="mb-5" data-thing-kind={s.kind}>
              <h3 className="mb-1 text-[0.8125rem] font-semibold text-fg-2">{s.header}</h3>
              <ThingsView section={s} />
            </section>
          ))}
          {!issue.sections.length && !issue.also.length ? <p className="text-[0.8125rem] text-fg-2">Nothing in this week.</p> : null}
          <PostList posts={issue.also} label="Also in the track" />
        </>
      ) : null}
    </section>
  );
}

// ---- the tables ----------------------------------------------------------------------------------------------------

const tableKey = (id: string, kind: string, params: Record<string, string>) =>
  ['markx-track-things', id, kind, params] as const;

/** The tables (0245 moment C): every row of a kind, newest first, filter chips from its typed fields, sortable. */
export function ThingTables({ trackId, kinds, kind: initial }: { trackId: string; kinds: Array<{ kind: string; header: string }>; kind?: string }) {
  const [kind, setKind] = useState(initial && kinds.some((k) => k.kind === initial) ? initial : kinds[0]?.kind ?? '');
  const [chosen, setChosen] = useState<FilterChipDef[]>([]);
  const [sort, setSort] = useState<SortState>(null);
  const params = chipParams(chosen);
  const all = useQuery({ queryKey: tableKey(trackId, kind, {}), queryFn: () => briefApi.things(trackId, kind), enabled: Boolean(kind), staleTime: 60_000 });
  const filtered = useQuery({
    queryKey: tableKey(trackId, kind, params), queryFn: () => briefApi.things(trackId, kind, params),
    enabled: Boolean(kind) && chosen.length > 0, staleTime: 60_000,
  });
  const chips = useMemo(() => (all.data ? filterChips(all.data.fields, all.data.things) : []), [all.data]);
  const shown = chosen.length ? filtered : all;
  const pick = (k: string) => { setKind(k); setChosen([]); setSort(null); };
  return (
    <section aria-label="Tables">
      <div className="mb-2 flex flex-wrap gap-1.5" role="group" aria-label="Kinds">
        {kinds.map((k) => <FilterChip key={k.kind} selected={k.kind === kind} onClick={() => pick(k.kind)}>{k.header}</FilterChip>)}
      </div>
      {chips.length ? (
        <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Filters">
          {chips.map((c) => (
            <FilterChip key={`${c.field}:${c.label}`} selected={chosen.some((x) => x.field === c.field && x.label === c.label)}
              onClick={() => setChosen(toggleChip(chosen, c))}>{c.label}</FilterChip>
          ))}
        </div>
      ) : null}
      {shown.isPending ? <LoadingState label="Loading the table" rows={4} /> : shown.isError ? (
        <ErrorState error={shown.error} onRetry={() => void shown.refetch()} title="Could not load the table" />
      ) : shown.data.on ? (
        <>
          <p className="mb-1 text-[0.75rem] tabular-nums text-fg-3">{shown.data.count} {shown.data.count === 1 ? 'row' : 'rows'}{sort ? '' : ' · newest first'}</p>
          {shown.data.things.length ? (
            <ThingsView section={{ kind, fields: shown.data.fields, things: shown.data.things, header: kind }} sort={sort}
              onSort={(f) => setSort(nextSort(sort, f))} />
          ) : <p className="text-[0.8125rem] text-fg-2">No row matches.</p>}
        </>
      ) : null}
    </section>
  );
}
