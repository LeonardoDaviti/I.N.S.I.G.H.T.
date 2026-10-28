import { Link } from 'react-router-dom';

import type { FeedGroup as FeedGroupData, FeedItem as FeedItemData } from '../../services/api';
import { scopePath } from '../../lib/feedContext';
import { sourceLabel } from '../../lib/sourceLabel';
import { formatCount, middleTruncate, plural } from '../../lib/format';
import FeedItem from './FeedItem';

export interface FeedGroupProps {
  group: FeedGroupData;
  selectedId: string | null;
  /** The id that carries tabIndex 0 (the selection, or the first item of the list). */
  tabbableId?: string | null;
  itemHref: (item: FeedItemData) => string;
  onSelect: (id: string) => void;
  onOpen: (item: FeedItemData) => void;
  onToggleRead: (item: FeedItemData) => void;
  onToggleStar: (item: FeedItemData) => void;
  now?: Date;
}

/** One source in the by-source view: up to 3 posts, then "N more from <source>". */
export default function FeedGroup({ group, selectedId, tabbableId, itemHref, now, ...handlers }: FeedGroupProps) {
  const name = sourceLabel(group.source_display_name);
  const more = Math.max(0, group.count - group.items.length);
  const sourceHref = scopePath(`source:${group.source_id}`);
  const headingId = `feed-group-${group.source_id}`;
  return (
    <section aria-labelledby={headingId}>
      <header className="flex items-baseline justify-between gap-3 px-1 pb-2">
        <h2 id={headingId} className="min-w-0 truncate text-[0.9375rem] font-semibold tracking-[-0.011em] text-fg" title={group.source_display_name}>
          <Link to={sourceHref} className="rounded-sm underline decoration-fg-3/60 decoration-1 underline-offset-[0.22em] hover:decoration-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg">{middleTruncate(name, 56)}</Link>
        </h2>
        <span className="shrink-0 whitespace-nowrap text-[0.8125rem] text-fg-3 tabular-nums">{plural(Math.max(group.count, group.items.length), 'post')}</span>
      </header>
      <div className={"flex flex-col gap-2"}>
        {group.items.map((item) => (
          <FeedItem
            key={item.id}
            item={item}
            selected={item.id === selectedId}
            tabbable={item.id === tabbableId}
            href={itemHref(item)}
            now={now}
            {...handlers}
          />
        ))}
      </div>
      {more > 0 ? (
        <Link
          to={sourceHref}
          className="mt-1 inline-flex min-h-[2.5rem] items-center rounded-sm px-1 text-[0.8125rem] text-fg-2 underline decoration-fg-3/60 underline-offset-[0.22em] hover:text-fg hover:decoration-fg coarse:min-h-[44px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg"
        >
          {`${formatCount(more)} more from ${middleTruncate(name, 40)}`}
          <span aria-hidden="true" className="ml-1 no-underline">→</span>
        </Link>
      ) : null}
    </section>
  );
}
