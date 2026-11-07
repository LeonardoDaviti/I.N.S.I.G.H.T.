import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { MarkxFlag, MarkxLeftOut, MarkxLine, MarkxNews as News, MarkxRow, MarkxTag } from '../../services/markx';
import { Button, Chip, Switch, TextLink } from '../ui';
import { EmptyState, ErrorState, LoadingState } from '../states';
import { feedFullTime, postBylineTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import { newsPart } from '../../lib/news';
import { errorMessage } from '../../lib/apiError';
import { ANSWER_WORDS, ixWords, judged, TAG_WORDS, whyWords } from '../../lib/markx';
import { FoldedPosts, FoldHeader } from './MarkXFolds';   // 0127: duplicates folded

const TAG_ORDER: MarkxTag[] = ['NEW', 'MERGED', 'SPLIT', 'CHANGED', 'SAME'];

export function TagChip({ tag }: { tag: MarkxTag }) {
  return (
    <Chip variant={tag === 'NEW' ? 'solid' : tag === 'SAME' ? 'quiet' : 'outline'} title={TAG_WORDS[tag]} data-tag={tag}>
      {tag.toLowerCase()}
    </Chip>
  );
}

function part(row: MarkxRow, now: Date) {
  const recent = new Date(row.first_at).getTime() >= now.getTime() - 48 * 3600_000;
  return newsPart({ part: recent ? 'recent' : 'earlier', first_at: row.first_at }, now);
}

/** One tap on a member (0086 F): "wrong story" or "not about this", stored as a label; "undo" stores "ok". */
function OneTap({ line }: { line: MarkxLine & { story: string } }) {
  const api = useApi();
  const [flag, setFlag] = useState<MarkxFlag | null>(line.flag ?? null);
  const tap = useMutation({
    mutationFn: (answer: MarkxFlag) => api.flagMarkxMember(line.id, line.story, answer),
    onSuccess: (got) => setFlag(got.answer === 'ok' ? null : got.answer),
  });
  if (flag) {
    return (
      <span className="mt-1 flex flex-wrap items-center gap-2 text-[0.75rem] text-fg-2">
        <span data-flag={flag}>you: {ANSWER_WORDS[flag]}</span>
        <Button size="sm" variant="ghost" disabled={tap.isPending} onClick={() => tap.mutate('ok')}>undo</Button>
      </span>
    );
  }
  return (
    <span className="mt-1 flex flex-wrap items-center gap-2" role="group" aria-label="Is this post in the right story?">
      {(['wrong_story', 'not_about'] as const).map((a) => (
        <Button key={a} size="sm" variant="ghost" disabled={tap.isPending} onClick={() => tap.mutate(a)}
          className="text-[0.75rem]">{ANSWER_WORDS[a]}</Button>
      ))}
      {tap.isError ? <span role="alert" className="text-[0.75rem] text-fg">{errorMessage(tap.error)}</span> : null}
    </span>
  );
}

function PostLine({ line, now, extra }: { line: MarkxLine; now: Date; extra?: ReactNode }) {
  const words = line.why?.words;
  return (
    <li className="grid gap-x-3 gap-y-0.5 border-t border-line py-2.5 first:border-t-0 sm:grid-cols-[7.5rem_1fr]">
      <span className="text-[0.75rem] tabular-nums text-fg-3" title={feedFullTime(line.at)}>
        {postBylineTime(line.at, now)}
      </span>
      <span className="min-w-0">
        <span className="block min-w-0 text-[0.875rem] leading-5 text-fg [overflow-wrap:anywhere]">
          <TextLink to={`/posts/${encodeURIComponent(line.id)}`}>{line.title || '(no title)'}</TextLink>
          <span className="text-fg-3"> · {line.source}</span>
        </span>
        <span className="mt-0.5 block text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
          {line.why ? whyWords(line.why) : line.name
            ? `in no Mark X story: Mark IX's News joins it by the name “${line.name}”`
            : "in no Mark X story: Mark IX's News joins it"}
          {words ? <span className="text-fg-3"> — {words}</span> : null}
        </span>
        <span className="block text-[0.75rem] leading-5 text-fg-3 [overflow-wrap:anywhere]">{ixWords(line.ix)}</span>
        {line.story && line.why ? <OneTap line={{ ...line, story: line.story }} /> : null}
        {extra}
      </span>
    </li>
  );
}

function LeftOutLine({ post, now, rows }: { post: MarkxLeftOut; now: Date; rows: Map<string, MarkxRow> }) {
  const moved = post.now_in ? rows.get(post.now_in) : undefined;
  let what = 'not in Mark X’s News';
  if (post.mention) what = `kept as ${post.mention.role === 'digest_item' ? 'a digest item' : 'a mention'}`;
  else if (post.now_in) what = moved ? `moved to “${moved.headline.text}”` : 'in another Mark X row';
  else if (post.check) what = 'taken out';
  return (
    <li className="grid gap-x-3 gap-y-0.5 border-t border-line py-2.5 first:border-t-0 sm:grid-cols-[7.5rem_1fr]">
      <span className="text-[0.75rem] tabular-nums text-fg-3">
        <span aria-hidden="true" className="mr-1 font-semibold text-fg">−</span>
        {postBylineTime(post.at, now)}
      </span>
      <span className="min-w-0">
        <span className="block text-[0.875rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
          <TextLink to={`/posts/${encodeURIComponent(post.id)}`} muted>{post.title || '(no title)'}</TextLink>
          <span className="text-fg-3"> · {post.source}</span>
        </span>
        <span className="block text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
          {what}
          {post.check ? <span className="text-fg-3"> ({judged(post.check.relation, post.check.p)}{post.check.words ? ` — ${post.check.words}` : ''})</span> : null}
        </span>
      </span>
    </li>
  );
}

function Row({ row, now, rows }: { row: MarkxRow; now: Date; rows: Map<string, MarkxRow> }) {
  const ixTitle = row.ix.length === 1 ? row.ix[0].title : null;
  const added = row.posts.filter((line) => !line.ix?.same_row).length;
  return (
    <li id={`mx-${row.id}`} className="border-b border-line">
      <details className="group">
        <summary className="flex cursor-pointer list-none gap-3 py-3.5 [&::-webkit-details-marker]:hidden">
          <span aria-hidden="true" className="inline-block h-5 w-3 shrink-0 self-start text-center leading-5 text-fg-3 group-open:rotate-90">›</span>
          <span className="min-w-0 flex-1">
            <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
              <TagChip tag={row.tag} />
              <span className="min-w-0 text-[0.9375rem] font-semibold leading-[1.35] text-fg [overflow-wrap:anywhere]">
                {row.headline.text || '(no title)'}
              </span>
            </span>
            <span className="mt-1 block text-[0.8125rem] tabular-nums leading-5 text-fg-2">
              {plural(row.voices, 'source')}
              {row.shares ? ` (${plural(row.shares, 'share')})` : ''}
              {row.mentions ? ` · in ${plural(row.mentions, 'roundup')}` : ''}
              {` · ${postBylineTime(row.first_at, now)}`}
              {added && row.tag !== 'NEW' ? ` · +${added}` : ''}
              {row.removed.length ? ` · −${row.removed.length}` : ''}
              {row.folded ? ` · ${row.folded} retold` : ''}
              {row.headline.from === 'haiku' ? ' · headline by Haiku' : ''}
              {row.surging?.length ? (
                <span data-surging> · surging: {row.surging.map((s) => s.name).join(', ')}</span>
              ) : null}
            </span>
            {row.tag !== 'NEW' && (row.ix.length > 1 || (ixTitle && ixTitle !== row.headline.text)) ? (
              <span className="block text-[0.75rem] leading-5 text-fg-3 [overflow-wrap:anywhere]">
                Mark IX: {row.ix.map((ix) => `“${ix.title ?? 'a row'}”`).join(' + ')}
              </span>
            ) : null}
          </span>
        </summary>
        <div className="pb-4 pl-6">
          <ul aria-label="Posts in this Mark X row">
            <FoldedPosts lines={row.posts} render={(line, extra) => <PostLine key={line.id} line={line} now={now} extra={extra} />} />
          </ul>
          {row.removed.length ? (
            <>
              <p className="mt-3 text-[0.75rem] font-medium text-fg-3">In Mark IX’s row, not in this one</p>
              <ul aria-label="Left out">{row.removed.map((post) => <LeftOutLine key={post.id} post={post} now={now} rows={rows} />)}</ul>
            </>
          ) : null}
        </div>
      </details>
    </li>
  );
}

/**
 * Mark X's News beside Mark IX's (issue 0086 E): every row with its tag and headline; opened, each post with why it is
 * there (Mark IX's rule, or Haiku's relation, p and words) and what Mark IX did with it, and the Mark IX posts it left
 * out. "Only differences" is on by default; the rows Mark X no longer counts as News close the list.
 */
export default function MarkXNews() {
  const api = useApi();
  const [all, setAll] = useState(false);
  const query = useQuery({ queryKey: ['markx-news', all], queryFn: () => api.getMarkxNews(all), staleTime: 60_000 });
  const now = useMemo(() => new Date(), [query.dataUpdatedAt]); // eslint-disable-line react-hooks/exhaustive-deps

  if (query.isPending) return <LoadingState label="Loading Mark X News" rows={5} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} title="Mark X News did not load" />;
  const news: News = query.data;
  const rows = new Map(news.items.map((row) => [row.id, row]));
  const parts: { label: string; rows: MarkxRow[] }[] = [];
  for (const row of [...news.items].sort((a, b) => part(a, now).rank - part(b, now).rank)) {
    const label = part(row, now).label;
    if (parts.at(-1)?.label !== label) parts.push({ label, rows: [] });
    parts.at(-1)!.rows.push(row);
  }
  const counts = TAG_ORDER.filter((tag) => news.counts[tag]).map((tag) => `${news.counts[tag]} ${tag.toLowerCase()}`);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <p className="min-w-0 text-[0.8125rem] tabular-nums leading-5 text-fg-2">
          {news.run ? (
            <>
              Mark X {plural(news.counts.rows ?? 0, 'row')} · Mark IX {news.counts.ix_rows ?? 0}
              {counts.length ? ` · ${counts.join(', ')}` : ''}
              {news.gone.length ? ` · ${news.gone.length} no longer News` : ''}
            </>
          ) : 'No decision run yet'}
        </p>
        <label className="inline-flex items-center gap-2 text-[0.8125rem] text-fg-2">
          <Switch checked={!all} onCheckedChange={(only) => setAll(!only)} aria-label="Only differences" />
          only differences
        </label>
      </div>
      {news.folds ? <FoldHeader score={news.folds} /> : null}
      {!news.run ? (
        <EmptyState className="mt-6" title="No Mark X News yet"
          description="The decision job writes it after the worker's answers arrive, and every hour." />
      ) : news.items.length === 0 ? (
        <EmptyState className="mt-6" title={all ? 'No Mark X News in the last 30 days' : 'No differences from Mark IX'}
          description={all ? undefined : 'Every Mark X row has the same posts as Mark IX’s. Turn off “only differences” to read them.'} />
      ) : (
        parts.map((p) => (
          <section key={p.label} aria-label={p.label} className="mt-6">
            <h2 className="border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2">{p.label}</h2>
            <ul>{p.rows.map((row) => <Row key={row.id} row={row} now={now} rows={rows} />)}</ul>
          </section>
        ))
      )}
      {news.gone.length ? (
        <section aria-label="No longer News" className="mt-10">
          <h2 className="border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2">
            Mark IX rows Mark X no longer counts as News
          </h2>
          <ul>
            {news.gone.map((row) => (
              <li key={row.id} className="border-b border-line">
                <details className="group">
                  <summary className="flex cursor-pointer list-none gap-3 py-3 [&::-webkit-details-marker]:hidden">
                    <span aria-hidden="true" className="inline-block h-5 w-3 shrink-0 self-start text-center leading-5 text-fg-3 group-open:rotate-90">›</span>
                    <span className="min-w-0 text-[0.875rem] leading-5 text-fg [overflow-wrap:anywhere]">
                      {row.title || '(no title)'}
                      <span className="text-fg-3"> · {plural(row.voices ?? 0, 'source')} in Mark IX</span>
                    </span>
                  </summary>
                  <ul className="pb-3 pl-6">{row.posts.map((post) => <LeftOutLine key={post.id} post={post} now={now} rows={rows} />)}</ul>
                </details>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
