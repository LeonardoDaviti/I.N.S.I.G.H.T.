import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Button, TextLink } from '../ui';
import { postBylineTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import { request } from '../../lib/request';

// 0163 (Stealth v10.13.11): later developments, Shadow. A story about a paper, a document, a model, software or a
// dataset keeps gathering the posts that follow it up, at any age; each asked of the back judge three times. Shown on
// the Mark X story page ("Later") and the subject's entity page ("Later developments"), never on News.
export type MarkxLaterLabel = 'development' | 'retold' | 'related' | 'unrelated';
export interface MarkxLaterRow {
  id: string; story: string; headline: string | null; post: string; title: string | null; url: string | null;
  source: string | null; at: string | null; days_after: number; trig: string[]; entity: string | null;
  entity_name: string | null; verdict: MarkxLaterLabel | 'unknown' | null; runs: (string | null)[];
  label: MarkxLaterLabel | null;
}
export interface MarkxLaterStory {
  story: string; headline: string | null; long_lived: boolean; following: boolean;
  subjects: { id: string; name: string | null }[];
}
export interface MarkxLaterPrecision { labelled: number; development: number; precision: number | null }
export interface MarkxStoryLater {
  stories: MarkxLaterStory[]; items: MarkxLaterRow[]; counts: Record<string, number>; precision: MarkxLaterPrecision;
  news: boolean;
}
export interface MarkxEntityLater { entity: string | null; items: MarkxLaterRow[]; counts: Record<string, number> }

export const markxLaterApi = {
  story: (story: string) => request<MarkxStoryLater>(`/api/markx/later?story=${encodeURIComponent(story)}`),
  entity: (entity: string) => request<MarkxEntityLater>(`/api/markx/entities/${encodeURIComponent(entity)}/later`),
  label: (row: string, answer: MarkxLaterLabel | 'undo') =>
    request<{ id: string; answer: string; label: MarkxLaterLabel | null; precision: MarkxLaterPrecision }>(
      '/api/markx/labels/later', { method: 'POST', body: { row, answer } }),
  follow: (story: string, following: boolean) =>
    request<{ story: string; following: boolean }>('/api/markx/later/follow', { method: 'POST', body: { story, following } }),
};

const LABELS: MarkxLaterLabel[] = ['development', 'retold', 'related', 'unrelated'];
const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';

function trigWords(row: MarkxLaterRow): string {
  const what = row.entity_name ?? 'its subject';
  return row.trig.map((t) => (t === 'E' ? `names ${what}` : t === 'L' ? `links ${row.entity_name ?? 'its page'}` : t)).join(', ');
}

function LabelButtons({ row, refresh }: { row: MarkxLaterRow; refresh: () => void }) {
  const [mine, setMine] = useState<MarkxLaterLabel | null>(row.label);
  const tap = useMutation({
    mutationFn: (answer: MarkxLaterLabel | 'undo') => markxLaterApi.label(row.id, answer),
    onSuccess: (got) => { setMine(got.label); refresh(); },
  });
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1 text-[0.75rem]" role="group" aria-label="What is this?">
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

function verdictWords(row: MarkxLaterRow): string {
  if (!row.verdict) return 'waiting for Haiku';
  const dev = row.runs.filter((r) => r === 'development').length;
  return `${row.verdict} (${dev} of ${row.runs.length} runs development)`;
}

function Row({ row, refresh, showStory }: { row: MarkxLaterRow; refresh: () => void; showStory?: boolean }) {
  return (
    <li className="border-b border-line py-2" data-later-row={row.id}>
      <p className="text-[0.875rem] leading-5 text-fg [overflow-wrap:anywhere]">
        <TextLink to={`/posts/${encodeURIComponent(row.post)}`}>{row.title || '(no title)'}</TextLink>
      </p>
      <p className="text-[0.8125rem] tabular-nums leading-5 text-fg-2 [overflow-wrap:anywhere]">
        {row.at ? postBylineTime(row.at) : ''} · {plural(row.days_after, 'day')} after
        {row.source ? ` · ${row.source}` : ''}{row.trig.length ? ` · ${trigWords(row)}` : ''} · {verdictWords(row)}
      </p>
      {showStory ? (
        <p className="text-[0.75rem] leading-5 text-fg-3 [overflow-wrap:anywhere]">
          after <TextLink to={`/posts/${encodeURIComponent(row.story)}`} muted>{row.headline || 'the story'}</TextLink>
        </p>
      ) : null}
      <LabelButtons row={row} refresh={refresh} />
    </li>
  );
}

/** The rows judged development first, the rest folded with their verdicts (all take the owner's label). */
function Rows({ items, refresh, showStory }: { items: MarkxLaterRow[]; refresh: () => void; showStory?: boolean }) {
  const dev = items.filter((r) => r.verdict === 'development');
  const rest = items.filter((r) => r.verdict !== 'development');
  return (
    <>
      {dev.length ? <ul aria-label="Developments">{dev.map((r) => <Row key={r.id} row={r} refresh={refresh} showStory={showStory} />)}</ul>
        : <p className="mt-2 text-[0.8125rem] text-fg-2">No development judged yet.</p>}
      {rest.length ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-[0.8125rem] text-fg-2">
            {plural(rest.length, 'other later post')} (retold, related, unrelated or waiting)
          </summary>
          <ul aria-label="Other later posts">{rest.map((r) => <Row key={r.id} row={r} refresh={refresh} showStory={showStory} />)}</ul>
        </details>
      ) : null}
    </>
  );
}

function FollowButton({ s, refresh }: { s: MarkxLaterStory; refresh: () => void }) {
  const tap = useMutation({ mutationFn: (following: boolean) => markxLaterApi.follow(s.story, following), onSuccess: refresh });
  return (
    <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={tap.isPending} onClick={() => tap.mutate(!s.following)}>
      {s.following ? 'Stop following this story' : 'Follow again'}
    </Button>
  );
}

/** A story page's "Later" (0163): shown for a long-lived story, or when it has Later rows. */
export function StoryLater({ storyId }: { storyId: string }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ['markx-later', storyId], queryFn: () => markxLaterApi.story(storyId), staleTime: 60_000 });
  if (!query.data) return null;   // loading or failed: the page stands alone
  const { stories, items, precision } = query.data;
  const lived = stories.filter((s) => s.long_lived);
  if (!lived.length && !items.length) return null;
  const refresh = () => void client.invalidateQueries({ queryKey: ['markx-later', storyId] });
  return (
    <section aria-label="Later">
      <h2 className={H2}>Later · {plural(items.length, 'post')}</h2>
      <div className="mt-2 space-y-1 text-[0.75rem] leading-5 text-fg-3">
        {lived.map((s) => (
          <p key={s.story} className="flex flex-wrap items-center gap-x-2">
            <span>
              {s.following ? 'Following' : 'Not following'}{' '}
              {s.subjects.length ? s.subjects.map((x) => x.name ?? 'its subject').join(', ') : 'its subject'}
              {stories.length > 1 && s.headline ? ` (${s.headline})` : ''}
            </span>
            <FollowButton s={s} refresh={refresh} />
          </p>
        ))}
        <p>
          Shadow only, not on News · {precision.precision === null ? 'none labelled yet'
            : `your labels: ${precision.development} of ${precision.labelled} development`}
        </p>
      </div>
      {items.length ? <Rows items={items} refresh={refresh} />
        : <p className="mt-2 text-[0.8125rem] text-fg-2">Nothing has followed it up yet.</p>}
    </section>
  );
}

/** An entity page's "Later developments" (0163): the Later rows found for it. */
export function EntityLater({ entityId }: { entityId: string }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ['markx-entity-later', entityId], queryFn: () => markxLaterApi.entity(entityId), staleTime: 60_000 });
  if (!query.data || !query.data.items.length) return null;
  const refresh = () => void client.invalidateQueries({ queryKey: ['markx-entity-later', entityId] });
  return (
    <section aria-label="Later developments">
      <h2 className={H2}>Later developments · {plural(query.data.items.length, 'post')}</h2>
      <Rows items={query.data.items} refresh={refresh} showStory />
    </section>
  );
}
