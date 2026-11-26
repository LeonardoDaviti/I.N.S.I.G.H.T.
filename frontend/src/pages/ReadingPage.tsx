import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

import { Page, PageHeader, TextLink } from '../components/ui';
import { EmptyState, ErrorState, LoadingState } from '../components/states';
import SlashChoice from '../components/reader/SlashChoice';
import { readingApi, type ReadingDays, type ReadingPost, type ReadingSeen, type ReadingTotal } from '../services/reading';
import { feedTimeLabel } from '../lib/dates';
import { formatElapsed } from '../lib/duration';
import { formatCount, middleTruncate, plural } from '../lib/format';
import { sourceReadPath } from '../lib/feedContext';
import { sourceLabel } from '../lib/sourceLabel';

const WINDOWS: ReadonlyArray<{ value: string; label: string }> = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: 'all', label: 'All time' },
];

const TH = 'py-1.5 pr-3 text-left font-normal';
const TD = 'py-1.5 pr-3 align-top';
const NUM = 'py-1.5 pr-3 text-right align-top tabular-nums';

const postPath = (id: string) => `/posts/${encodeURIComponent(id)}`;
const trackPath = (id: string) => `/read/folder/${encodeURIComponent(id)}`;
const storyPath = (id: string) => `/markx/stories/${encodeURIComponent(id)}`;

/** "4m 10s"; a session recorded before active time was measured shows its open time, marked "open". */
function activeWords(post: Pick<ReadingPost, 'active_seconds' | 'open_seconds'>): string {
  if (post.active_seconds !== null) return formatElapsed(post.active_seconds) ?? '—';
  if (post.open_seconds !== null) return `${formatElapsed(post.open_seconds)} open`;
  return '—';
}

const depthWords = (depth: number | null) => (depth === null ? '—' : `${Math.round(depth * 100)}%`);

/** "Thursday 26 November" for a UTC day (YYYY-MM-DD). */
function dayWords(day: string): string {
  return new Date(`${day}T12:00:00Z`).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' });
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="mb-8">
      <h2 className="mb-2 text-[0.9375rem] font-semibold tracking-[-0.011em] text-fg">{title}</h2>
      {children}
    </section>
  );
}

function Table({ head, children, label }: { head: ReactNode; children: ReactNode; label: string }) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full border-collapse text-[0.8125rem]">
        <thead><tr className="border-b border-line text-fg-3">{head}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function ByDay({ posts }: { posts: ReadingPost[] }) {
  const days: Array<[string, ReadingPost[]]> = [];
  for (const post of posts) {
    const last = days[days.length - 1];
    if (last && last[0] === post.day) last[1].push(post);
    else days.push([post.day, [post]]);
  }
  return (
    <>
      {days.map(([day, rows]) => (
        <div key={day} className="mb-5" data-reading-day={day}>
          <h3 className="mb-1 text-[0.8125rem] font-semibold text-fg-2">{dayWords(day)} · {plural(rows.length, 'post')}</h3>
          <Table label={`Opened ${dayWords(day)}`} head={<>
            <th className={TH}>Time</th><th className={TH}>Title</th><th className={TH}>Source</th>
            <th className={`${TH} text-right`}>Active</th><th className={`${TH} text-right`}>Depth</th><th className={TH}>Original</th>
          </>}>
            {rows.map((post) => (
              <tr key={post.post_id} className="border-b border-line" data-reading-post={post.post_id}>
                <td className={`${TD} whitespace-nowrap tabular-nums text-fg-2`}>{feedTimeLabel(post.at)}</td>
                <td className={`${TD} text-fg [overflow-wrap:anywhere]`}><TextLink to={postPath(post.post_id)}>{post.title || '(no title)'}</TextLink></td>
                <td className={`${TD} text-fg-2 [overflow-wrap:anywhere]`}>
                  <TextLink to={sourceReadPath(post.source_id)} muted>{middleTruncate(sourceLabel(post.source), 32)}</TextLink>
                </td>
                <td className={`${NUM} whitespace-nowrap text-fg-2`}>{activeWords(post)}</td>
                <td className={`${NUM} text-fg-2`}>{depthWords(post.depth)}</td>
                <td className={`${TD} text-fg-2`}>{post.source_opened ? 'opened' : ''}</td>
              </tr>
            ))}
          </Table>
        </div>
      ))}
    </>
  );
}

function Totals({ rows, label, href, name }: {
  rows: ReadingTotal[]; label: string; href: (id: string) => string; name: (row: ReadingTotal) => string;
}) {
  if (!rows.length) return <p className="text-[0.8125rem] text-fg-2">None in this window.</p>;
  return (
    <Table label={label} head={<>
      <th className={TH}>{label}</th><th className={`${TH} text-right`}>Posts</th>
      <th className={`${TH} text-right`}>Active</th><th className={`${TH} text-right`}>Originals</th>
    </>}>
      {rows.map((row) => (
        <tr key={row.id} className="border-b border-line">
          <td className={`${TD} text-fg [overflow-wrap:anywhere]`}><TextLink to={href(row.id)}>{name(row)}</TextLink></td>
          <td className={NUM}>{formatCount(row.posts)}</td>
          <td className={`${NUM} text-fg-2`}>{formatElapsed(row.active_seconds) ?? '—'}</td>
          <td className={`${NUM} text-fg-2`}>{formatCount(row.originals_opened)}</td>
        </tr>
      ))}
    </Table>
  );
}

function SeenTable({ rows, label, href, name }: {
  rows: ReadingSeen[]; label: string; href: (id: string) => string; name: (row: ReadingSeen) => string;
}) {
  if (!rows.length) return <p className="text-[0.8125rem] text-fg-2">Nothing seen in this window.</p>;
  return (
    <Table label={`Seen by ${label.toLowerCase()}`} head={<>
      <th className={TH}>{label}</th><th className={`${TH} text-right`}>Seen</th><th className={`${TH} text-right`}>Opened</th>
      <th className={`${TH} text-right`}>Seen, not opened</th>
    </>}>
      {rows.map((row) => (
        <tr key={row.id} className="border-b border-line">
          <td className={`${TD} text-fg [overflow-wrap:anywhere]`}><TextLink to={href(row.id)}>{name(row)}</TextLink></td>
          <td className={NUM}>{formatCount(row.seen)}</td>
          <td className={NUM}>{formatCount(row.opened)}</td>
          <td className={`${NUM} text-fg-2`}>{formatCount(row.seen - row.opened)}</td>
        </tr>
      ))}
    </Table>
  );
}

/**
 * `/reading`: Your reading, private to this INSIGHT. What you opened by day (time, title, source, active time,
 * depth, whether you opened the original), totals by source, track and story, and the rows you saw in News, a track
 * or a feed against those you opened. Over the last 7 or 30 days or all time; nothing leaves the server.
 */
export default function ReadingPage() {
  const [span, setSpan] = useState<string>('7');
  const days = (span === 'all' ? 'all' : Number(span)) as ReadingDays;
  const summary = useQuery({ queryKey: ['reading-summary', days], queryFn: () => readingApi.summary(days), staleTime: 30_000 });
  const data = summary.data;

  let body: ReactNode;
  if (summary.isPending) body = <LoadingState label="Loading your reading" rows={6} />;
  else if (summary.isError || !data) body = <ErrorState title="Could not load your reading" error={summary.error} onRetry={() => void summary.refetch()} />;
  else if (!data.posts.length && !data.seen_by_source.length) {
    body = <EmptyState title="Nothing read in this window" description="Posts you open, and rows you scroll past, show here." />;
  } else {
    const more = data.posts_total - data.posts.length;
    body = (
      <>
        <Section title="Opened, by day">
          {data.posts.length ? <ByDay posts={data.posts} /> : <p className="text-[0.8125rem] text-fg-2">Nothing opened in this window.</p>}
          {more > 0 ? <p className="text-[0.75rem] text-fg-3">{`and ${plural(more, 'earlier open')} not listed (the totals count them)`}</p> : null}
        </Section>
        <Section title="By source">
          <Totals rows={data.by_source} label="Source" href={sourceReadPath} name={(r) => sourceLabel(r.name ?? r.id)} />
        </Section>
        <Section title="By track">
          <Totals rows={data.by_track} label="Track" href={trackPath} name={(r) => r.name ?? 'Track'} />
        </Section>
        <Section title="By story">
          <Totals rows={data.by_story} label="Story" href={storyPath} name={(r) => r.name || 'Untitled story'} />
        </Section>
        <Section title="Seen but not opened, by source">
          <SeenTable rows={data.seen_by_source} label="Source" href={sourceReadPath} name={(r) => sourceLabel(r.name ?? r.id)} />
        </Section>
        <Section title="Seen but not opened, by track">
          <SeenTable rows={data.seen_by_track} label="Track" href={trackPath} name={(r) => r.name ?? 'Track'} />
        </Section>
      </>
    );
  }

  // each post has one source: the sources' counts add up to the posts opened
  const opened = data ? data.by_source.reduce((n, row) => n + row.posts, 0) : 0;
  const meta = data ? `${plural(opened, 'post')} opened · kept on this INSIGHT only` : 'Kept on this INSIGHT only';
  return (
    <Page width="ops">
      <PageHeader title="Your reading" meta={meta}>
        <SlashChoice label="Window" value={span} options={WINDOWS} onChange={setSpan} />
      </PageHeader>
      {body}
    </Page>
  );
}
