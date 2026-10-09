import { memo, useState, type MouseEvent } from 'react';
import { Link } from 'react-router-dom';
import { CheckCheck, Circle, CircleCheck, PlayCircle, Star } from 'lucide-react';

import type { FeedItem as FeedItemData } from '../../services/api';
import type { FeedDensity } from '../../hooks/useShortcutPreference';
import { feedDateLabel } from '../../lib/feedDates';
import { formatCount, middleTruncate } from '../../lib/format';
import { sourceLabel } from '../../lib/sourceLabel';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';

export function feedItemDomId(id: string) {
  return `feed-item-${id}`;
}

/** 4:02:07 / 12:34 / 0:45 for video durations. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function lengthLabel(item: FeedItemData): string | null {
  if (item.duration_seconds) return formatDuration(item.duration_seconds);
  if (item.reading_minutes) return `${formatCount(item.reading_minutes)} min read`;
  return null;
}

/** The backend already falls back to the excerpt; this guards a fixture or an old row. */
function displayTitle(item: FeedItemData): string {
  const title = item.title?.trim();
  if (title) return title;
  const excerpt = item.excerpt?.trim();
  if (excerpt) return excerpt.length > 80 ? `${excerpt.slice(0, 80)}…` : excerpt;
  return 'Untitled post';
}

/** Quiet 32px icon buttons that grow to 44px on touch (spec §F.6). */
const ICON_BUTTON = `inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-fg-3 hover:bg-raised hover:text-fg coarse:h-11 coarse:w-11 ${PRESS_FEEDBACK} ${FOCUS_RING}`;

export interface FeedItemProps {
  item: FeedItemData;
  density: FeedDensity;
  selected: boolean;
  /** The one item in the list with tabIndex 0 (roving tabindex). */
  tabbable: boolean;
  href: string;
  onSelect: (id: string) => void;
  onOpen: (item: FeedItemData) => void;
  onToggleRead: (item: FeedItemData) => void;
  onToggleStar: (item: FeedItemData) => void;
  /** Shown on the selected row only: mark read from the top down to here. */
  onMarkThrough?: (item: FeedItemData) => void;
  now?: Date;
}

/**
 * One feed row (spec §F.6): an `<article>` whose only link is the title, with the
 * read and star toggles as sibling buttons (32px, 44px on touch). Laid out like
 * the news.smol.ai list: a hairline-bordered row, a muted date column ("Sep 29",
 * relative only inside 24h), a bold title when unread. Selection is a roving
 * tabIndex plus `aria-current`; no animation, since j/k runs hundreds of times a day.
 */
function FeedItem({
  item, density, selected, tabbable, href, onSelect, onOpen, onToggleRead, onToggleStar, onMarkThrough, now,
}: FeedItemProps) {
  const [thumbFailed, setThumbFailed] = useState(false);
  const isRead = Boolean(item.read_at);
  const isStarred = Boolean(item.starred_at);
  const compact = density === 'compact';
  const titleId = `${feedItemDomId(item.id)}-title`;
  const title = displayTitle(item);
  const length = lengthLabel(item);
  // The feed's own order key (published, else fetched), so the column and the day headers agree.
  const time = item.sort_at ?? item.published_at;
  const showThumb = !compact && item.media_thumb && !thumbFailed;
  const excerpt = item.excerpt?.trim();
  const showExcerpt = !compact && excerpt && excerpt !== title && !title.startsWith(excerpt.slice(0, 40));

  const selectFromClick = (event: MouseEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest('a, button')) return;
    onSelect(item.id);
  };

  const timeLabel = feedDateLabel(time, now);
  const fullTime = new Date(time).toLocaleString();
  const source = sourceLabel(item.source_display_name);
  // On a real pointer the actions wait for hover or focus; on touch, and on the
  // selected row, they stay visible (lead review #1).
  // Below sm the title needs the width, so only the selected row (a tap selects)
  // carries them.
  const actionsReveal = selected
    ? 'flex'
    : 'hidden sm:flex [@media(hover:hover)_and_(pointer:fine)]:opacity-0 group-hover:opacity-100 group-focus-within:opacity-100';

  return (
    <article
      id={feedItemDomId(item.id)}
      tabIndex={tabbable ? 0 : -1}
      aria-current={selected ? 'true' : undefined}
      aria-labelledby={titleId}
      data-read={isRead ? 'true' : 'false'}
      onClick={selectFromClick}
      onFocus={(event) => { if (event.target === event.currentTarget) onSelect(item.id); }}
      className={`reader-row group relative flex scroll-mt-40 scroll-mb-24 items-start gap-3 rounded-md border pl-3 pr-1.5 sm:gap-4 sm:pl-4 ${compact ? 'py-1.5' : 'py-2'} outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg ${selected ? 'border-fg-3 bg-surface' : 'border-line hover:border-line-strong'}`}
    >
      <time
        dateTime={time}
        title={fullTime}
        className="w-[3.25rem] shrink-0 text-[0.75rem] leading-6 tabular-nums text-fg-3 sm:w-[4.25rem] sm:whitespace-nowrap sm:text-[0.8125rem]"
      >
        {timeLabel}
      </time>
      <div className={`min-w-0 flex-1 ${compact ? 'sm:flex sm:items-baseline sm:gap-3' : ''}`}>
        <h3
          className={`line-clamp-2 min-w-0 text-[0.9375rem] leading-6 tracking-[-0.011em] [overflow-wrap:anywhere] ${compact ? 'sm:flex-1' : ''} ${isRead ? 'font-normal text-fg-2' : 'font-semibold text-fg'}`}
        >
          <Link
            id={titleId}
            to={href}
            onClick={() => onOpen(item)}
            className="rounded-sm outline-none underline-offset-4 hover:underline hover:decoration-fg-3 focus-visible:underline focus-visible:decoration-2"
          >
            {title}
          </Link>
        </h3>
        <p className={`flex min-w-0 flex-nowrap items-center gap-x-1.5 text-[0.8125rem] leading-5 text-fg-3 tabular-nums ${compact ? 'sm:max-w-[14rem] sm:shrink-0' : ''}`}>
          {isStarred ? <span aria-hidden="true" className="shrink-0 text-fg">★</span> : null}
          <span className="min-w-0 truncate" title={item.source_display_name}>
            {middleTruncate(source, compact ? 32 : 56)}
          </span>
          {length ? (
            <>
              <span aria-hidden="true" className="shrink-0">·</span>
              <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap">
                {item.duration_seconds ? <PlayCircle aria-hidden="true" className="h-3 w-3" /> : null}
                {length}
              </span>
            </>
          ) : null}
          {!isRead ? <span className="sr-only">Unread</span> : null}
          {isStarred ? <span className="sr-only">Starred</span> : null}
        </p>
        {showExcerpt ? (
          <p dir="auto" className="mt-0.5 line-clamp-1 text-sm leading-5 text-fg-2 [overflow-wrap:anywhere]">
            {excerpt}
          </p>
        ) : null}
      </div>
      {showThumb ? (
        <div className="mt-0.5 hidden aspect-video w-20 shrink-0 overflow-hidden rounded-[0.25rem] border border-line bg-surface sm:block">
          <img
            src={item.media_thumb ?? undefined}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setThumbFailed(true)}
            className="h-full w-full object-cover grayscale"
          />
        </div>
      ) : null}
      <div className={`shrink-0 items-center gap-0.5 transition-opacity duration-100 ease-out coarse:-my-2.5 ${actionsReveal}`}>
        {selected && onMarkThrough ? (
          <button
            type="button"
            aria-label="Mark read up to here"
            title="Mark read up to here (Shift+A)"
            onClick={() => onMarkThrough(item)}
            className={ICON_BUTTON}
          >
            <CheckCheck aria-hidden="true" className="h-4 w-4" />
          </button>
        ) : null}
        <button
          type="button"
          aria-label={isRead ? 'Mark unread' : 'Mark read'}
          title={isRead ? 'Mark unread (m)' : 'Mark read (m)'}
          onClick={() => onToggleRead(item)}
          className={ICON_BUTTON}
        >
          {isRead ? <CircleCheck aria-hidden="true" className="h-4 w-4" /> : <Circle aria-hidden="true" className="h-4 w-4" />}
        </button>
        <button
          type="button"
          aria-label="Star"
          aria-pressed={isStarred}
          title={isStarred ? 'Unstar (s)' : 'Star (s)'}
          onClick={() => onToggleStar(item)}
          className={`${ICON_BUTTON} ${isStarred ? 'text-fg' : ''}`}
        >
          <Star aria-hidden="true" className="h-4 w-4" fill={isStarred ? 'currentColor' : 'none'} />
        </button>
      </div>
    </article>
  );
}

export default memo(FeedItem);
