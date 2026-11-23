import { useEffect, useRef, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { SinceLooked as Since, SinceRow } from '../../services/api';
import { formatRelativeTime } from '../../lib/dates';
import { folderReadPath } from '../../lib/feedContext';
import { formatCount, plural } from '../../lib/format';
import TextLink from '../ui/TextLink';
import { LoadingState } from '../states';

const postPath = (id: string) => `/posts/${encodeURIComponent(id)}`;

/**
 * "Since you looked" (News's Show): what came since the reader's last look, in three lists: News rows begun since,
 * rows a voice joined since, and each track's new things. Opening it moves the look to now, once the list is shown.
 */
export default function SinceLooked() {
  const api = useApi();
  const query = useQuery({ queryKey: ['news-since'], queryFn: ({ signal }) => api.getSince(signal), staleTime: Infinity });
  const looked = useRef(false);
  useEffect(() => {
    if (query.data && !looked.current) {
      looked.current = true;
      void api.lookSince().catch(() => { looked.current = false; });
    }
  }, [api, query.data]);
  if (query.isPending) return <LoadingState label="Loading what is new" rows={6} />;
  if (query.isError || !query.data) return <p className="px-1 text-[0.8125rem] text-fg-3">Could not load what is new.</p>;
  return <SinceLists data={query.data} />;
}

export function SinceLists({ data }: { data: Since }) {
  const { news, tracks } = data;
  const when = data.first ? 'in the last day' : `since you looked ${formatRelativeTime(data.look)}`;
  const nothing = !news.counts.new && !news.counts.changed && !tracks.length;
  return (
    <div data-testid="since-looked" className="text-[0.875rem]">
      <p className="mb-3 px-1 text-[0.8125rem] text-fg-3">{nothing ? `Nothing new ${when}.` : `New ${when}.`}</p>
      {news.counts.new ? (
        <Section title={`New in News (${formatCount(news.counts.new)})`}>
          {news.new.map((row) => <li key={row.id}><RowLink row={row} /></li>)}
        </Section>
      ) : null}
      {news.counts.changed ? (
        <Section title={`Changed (${formatCount(news.counts.changed)})`}>
          {news.changed.map((row) => (
            <li key={row.id}>
              <RowLink row={row} />
              <span className="block text-[0.8125rem] text-fg-3">
                {`+ ${row.since?.voices.join(', ')}`}
                {row.since?.lines[0]?.title ? <>{': '}<TextLink to={postPath(row.since.lines[0].id)} muted>{row.since.lines[0].title}</TextLink></> : null}
              </span>
            </li>
          ))}
        </Section>
      ) : null}
      {tracks.map((t) => (
        <Section key={t.id} title={<><TextLink to={`${folderReadPath(t.id)}?view=topic`}>{t.name}</TextLink>{` (${formatCount(t.new + t.also)} new)`}</>}>
          {t.lines.map((line, i) => (
            <li key={`${t.id}:${i}`}>{line.post ? <TextLink to={postPath(line.post)} muted>{line.text}</TextLink> : line.text}</li>
          ))}
        </Section>
      ))}
    </div>
  );
}

function RowLink({ row }: { row: SinceRow }) {
  const voices = row.story?.voices ?? 0;
  return (
    <>
      <TextLink to={postPath(row.id)}>{row.title || '(no title)'}</TextLink>
      <span className="text-[0.8125rem] tabular-nums text-fg-3">{` · ${plural(voices, 'source')}`}</span>
    </>
  );
}

function Section({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <section className="mb-4 border-b border-line pb-3">
      <h2 className="px-1 text-[0.8125rem] font-semibold text-fg-2">{title}</h2>
      <ul className="mt-1 space-y-1 px-1 leading-6">{children}</ul>
    </section>
  );
}
