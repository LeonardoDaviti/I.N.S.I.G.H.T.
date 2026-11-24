import { useQuery } from '@tanstack/react-query';

import { formatRelativeTime } from '../../lib/dates';
import type { AttentionItem } from '../../services/api';
import { useApi } from '../../services/ApiContext';
import { StatusGlyph } from '../ui';

export const ATTENTION_KEY = ['operations', 'attention'] as const;

/** The kept check (computed by the jobs process after a scheduled run, at most every 30 minutes). */
export function useAttention() {
  const api = useApi();
  return useQuery({ queryKey: [...ATTENTION_KEY], queryFn: () => api.getAttention(), refetchInterval: 5 * 60_000 });
}

function Item({ item, onOpenSource }: { item: AttentionItem; onOpenSource?: (id: string) => void }) {
  const title = item.source_id && onOpenSource ? (
    <button type="button" className="text-left font-medium text-fg underline-offset-2 hover:underline"
            onClick={() => onOpenSource(item.source_id as string)}>
      {item.title}
    </button>
  ) : <span className="font-medium text-fg">{item.title}</span>;
  return (
    <li data-attention={item.key} className="space-y-0.5 py-2 [overflow-wrap:anywhere]">
      {title}
      <p className="text-[0.8125rem] tabular-nums text-fg-3">{item.detail}</p>
    </li>
  );
}

/** Needs attention, first on Sources → ingestion → overview (0280 I): what is failing or changed and is the reader's to
 *  fix (a source failing, a platform quiet at once, a page watch landing elsewhere, a host blocking, new failed Mark X
 *  tasks, a queue behind), counted; what to watch and the database's week below, listed only. Read only. */
export default function NeedsAttention({ titleClass, onOpenSource }: {
  titleClass: string;
  onOpenSource?: (id: string) => void;
}) {
  const attention = useAttention();
  const data = attention.data;
  const act = data?.items.filter((i) => i.level === 'act') ?? [];
  const watch = data?.items.filter((i) => i.level === 'watch') ?? [];
  const info = data?.items.filter((i) => i.level === 'info') ?? [];

  return (
    <section aria-labelledby="ingestion-attention" className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 id="ingestion-attention" className={titleClass}>Needs attention</h2>
        {data?.computed_at ? (
          <StatusGlyph status={data.count ? 'failing' : 'ok'} label={data.count ? String(data.count) : 'nothing'}
                       className="text-[0.875rem] tabular-nums" />
        ) : null}
      </div>
      {!data ? (
        <p className="text-[0.875rem] text-fg-2">
          {attention.isError ? 'Could not read what needs attention.' : 'Reading what needs attention…'}
        </p>
      ) : !data.computed_at ? (
        <p className="text-[0.875rem] text-fg-2">Not checked yet: the check runs after the next scheduled fetch run.</p>
      ) : (
        <>
          {act.length ? (
            <ul aria-label="Needs attention now" className="divide-y divide-line border-y border-line text-[0.875rem]">
              {act.map((item) => <Item key={item.key} item={item} onOpenSource={onOpenSource} />)}
            </ul>
          ) : <p className="text-[0.875rem] text-fg-2">Nothing needs attention.</p>}
          {watch.length ? (
            <details className="text-[0.875rem]">
              <summary className="cursor-pointer text-fg-2">{watch.length} to watch</summary>
              <ul aria-label="To watch" className="divide-y divide-line text-[0.875rem]">
                {watch.map((item) => <Item key={item.key} item={item} onOpenSource={onOpenSource} />)}
              </ul>
            </details>
          ) : null}
          {info.length ? (
            <ul aria-label="Database this week" className="space-y-1 text-[0.8125rem] text-fg-3">
              {info.map((item) => (
                <li key={item.key} data-attention={item.key} className="[overflow-wrap:anywhere]">
                  <span className="text-fg-2">{item.title}</span> · {item.detail}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="text-[0.75rem] text-fg-3">Checked {formatRelativeTime(data.computed_at)}</p>
        </>
      )}
    </section>
  );
}

/** The briefing's line (0280 I): "Needs attention (7): Hacker News: hnrss.org answers 502; …", linking to the list;
 *  nothing when nothing does or it can't be read. */
export function AttentionLine() {
  const attention = useAttention();
  const line = attention.data?.line;
  if (!line) return null;
  return (
    <p data-attention="line" className="mb-3 text-[0.8125rem] text-fg-2 [overflow-wrap:anywhere]">
      <a href="/settings/sources?tab=ingestion" className="underline decoration-fg-3/60 underline-offset-2 hover:text-fg">
        {line}
      </a>
    </p>
  );
}
