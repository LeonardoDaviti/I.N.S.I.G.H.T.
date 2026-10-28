import { memo, useMemo, useState, type MouseEvent } from 'react';
import { Link } from 'react-router-dom';
import { Circle, CircleCheck, Clock, PlayCircle, Star } from 'lucide-react';

import type { FeedItem as FeedItemData } from '../../services/api';
import { feedDateLabel, feedFullTime, feedTimeLabel } from '../../lib/dates';
import { formatCount, middleTruncate } from '../../lib/format';
import { sourceLabel } from '../../lib/sourceLabel';
import { feedItemDomId } from '../../lib/feedItem';
import { formatClock } from '../../lib/duration';
import { resumeShare } from '../../hooks/useReadingPosition';
import { StatusIcon } from '../ui/StatusGlyph';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';
import { proxiedImage } from '../../lib/mediaProxy';
import { sourceReadPath } from '../../lib/feedContext';
import { TextLink } from '../ui/TextLink';

function lengthLabel(item: FeedItemData): string | null {
  if (item.duration_seconds) return formatClock(item.duration_seconds);
  if (item.reading_minutes) return `${formatCount(item.reading_minutes)} min read`;
  return null;
}

/** Quiet 32px icon buttons that grow to 44px on touch (spec §F.6). */
const ICON_BUTTON = `inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-fg-3 hover:bg-raised hover:text-fg coarse:h-11 coarse:w-11 ${PRESS_FEEDBACK} ${FOCUS_RING}`;

export interface FeedItemProps {
  item: FeedItemData;
  selected: boolean;
  /** The one item in the list with tabIndex 0 (roving tabindex). */
  tabbable: boolean;
  href: string;
  onSelect: (id: string) => void;
  onOpen: (item: FeedItemData) => void;
  onToggleRead: (item: FeedItemData) => void;
  onToggleStar: (item: FeedItemData) => void;
  onToggleLater: (item: FeedItemData) => void;
  /**
   * What the left column shows. `date` ("Sep 29", relative inside 24h) when the
   * row stands alone; `time` ("14:05") when it already sits under a day header,
   * so the column does not repeat the header on every row.
   */
  dateColumn?: 'date' | 'time';
  /** With `dateColumn="time"`: the day the visual header names ("Today"), read out with the time. */
  dayLabel?: string;
  /** Position in the feed (1-based) and its size, -1 while more pages can load (ARIA feed). */
  position?: number;
  setSize?: number;
  now?: Date;
  /** False on one source's own page, where the name would only link to the page you are on. */
  showSource?: boolean;
}

/**
 * One feed row (spec §F.6): an `<article>` whose links are the title and the
 * source name (which reads that source, issue 0019), with the read circle and one
 * save button as siblings (32px, 44px on touch): Read later (the clock) on an unread
 * row, Keep (the star) on a read one (issue 0022); a save already on keeps its button,
 * so it can be undone by hand. Laid out like
 * the news.smol.ai list: a hairline-bordered row, a muted date column ("Sep 29",
 * relative only inside 24h), a bold title when unread. Selection is a roving
 * tabIndex plus `aria-current`; no animation, since j/k runs hundreds of times a day.
 */
function FeedItem({
  item, selected, tabbable, href, onSelect, onOpen, onToggleRead, onToggleStar, onToggleLater, dateColumn = 'date', dayLabel, position, setSize, now, showSource = true,
}: FeedItemProps) {
  const [thumbFailed, setThumbFailed] = useState(false);
  const isRead = Boolean(item.read_at);
  const isStarred = Boolean(item.starred_at);
  const isLater = Boolean(item.later_at);
  // Unread: "I want this, not now" (Later); read: "this mattered" (Keep).
  const offerLater = !isRead || isLater;
  const offerKeep = isRead || isStarred;
  const titleId = `${feedItemDomId(item.id)}-title`;
  // The API's title already falls back to the body (display_title), as on the post page.
  const title = item.title?.trim() || 'Untitled post';
  const length = lengthLabel(item);
  const share = resumeShare(item.resume_block, item.resume_blocks);
  const progress = share === null ? null : Math.round(share * 100);
  // The feed's own order key (published, else fetched), so the column and the day headers agree.
  const time = item.sort_at ?? item.published_at;
  const showThumb = item.media_thumb && !thumbFailed;
  const excerpt = item.excerpt?.trim();
  const showExcerpt = excerpt && excerpt !== title && !title.startsWith(excerpt.slice(0, 40));

  const selectFromClick = (event: MouseEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest('a, button')) return;
    onSelect(item.id);
  };

  // Relative labels only move by the minute, so a re-render inside the same
  // minute reuses the label (and the formatters are cached in lib/dates).
  const minute = Math.floor((now ? now.getTime() : Date.now()) / 60_000);
  const timeLabel = useMemo(
    () => (dateColumn === 'time' ? feedTimeLabel(time) : feedDateLabel(time, now ?? new Date())),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `minute` stands in for `now`.
    [dateColumn, minute, time],
  );
  const fullTime = useMemo(() => feedFullTime(time), [time]);
  const source = sourceLabel(item.source_display_name);
  // On a real pointer the actions wait for hover or focus; on touch (phones
  // included), and on the selected row, they stay visible (lead review #1). The
  // reveal is instant: hovering rows happens hundreds of times a day.
  const actionsReveal = selected
    ? ''
    : '[@media(hover:hover)_and_(pointer:fine)]:opacity-0 group-hover:opacity-100 group-focus-within:opacity-100';

  return (
    <article
      id={feedItemDomId(item.id)}
      tabIndex={tabbable ? 0 : -1}
      aria-current={selected ? 'true' : undefined}
      aria-labelledby={titleId}
      aria-posinset={position}
      aria-setsize={position ? setSize : undefined}
      data-read={isRead ? 'true' : 'false'}
      onClick={selectFromClick}
      onFocus={(event) => { if (event.target === event.currentTarget) onSelect(item.id); }}
      className={`reader-row group relative flex scroll-mt-40 scroll-mb-24 items-start gap-3 rounded-md border pl-3 pr-1.5 sm:gap-4 sm:pl-4 py-2 outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg ${selected ? 'border-fg-3 bg-surface' : 'border-line hover:border-line-strong'}`}
    >
      <time
        dateTime={time}
        title={fullTime}
        className={`shrink-0 text-[0.75rem] leading-6 tabular-nums text-fg-3 sm:whitespace-nowrap sm:text-[0.8125rem] ${dateColumn === 'time' ? 'w-[2.25rem] sm:w-[2.75rem]' : 'w-[3.25rem] sm:w-[4.25rem]'}`}
      >
        {dayLabel && dateColumn === 'time' ? <span className="sr-only">{dayLabel}, </span> : null}
        {timeLabel}
      </time>
      <div className="min-w-0 flex-1">
        <h3
          dir="auto"
          className={`line-clamp-2 min-w-0 text-[0.9375rem] leading-6 tracking-[-0.011em] [overflow-wrap:anywhere] ${isRead ? 'font-normal text-fg-2' : 'font-semibold text-fg'}`}
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
        <p className="flex min-w-0 flex-nowrap items-center gap-x-1.5 text-[0.8125rem] leading-5 text-fg-3 tabular-nums">
          {!isRead ? <StatusIcon status="unread" className="text-fg" /> : null}
          {isLater ? <Clock aria-hidden="true" className="h-3 w-3 shrink-0 text-fg" /> : null}
          {isStarred ? <span aria-hidden="true" className="shrink-0 text-fg">★</span> : null}
          {showSource ? (
            <TextLink
              to={sourceReadPath(item.source_id)}
              title={item.source_display_name}
              className="min-w-0 truncate text-fg-3 decoration-transparent hover:decoration-fg-3"
            >
              {middleTruncate(source, 56)}
            </TextLink>
          ) : null}
          {length ? (
            <>
              {showSource ? <span aria-hidden="true" className="shrink-0">·</span> : null}
              <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap">
                {item.duration_seconds ? <PlayCircle aria-hidden="true" className="h-3 w-3" /> : null}
                {length}
              </span>
            </>
          ) : null}
          {progress !== null ? (
            <>
              <span aria-hidden="true" className="shrink-0">·</span>
              {/* Started, not finished (issue 0030): a hairline track, filled as far as read. */}
              <span aria-hidden="true" data-reading-progress className="h-px w-10 shrink-0 bg-line">
                <span className="block h-px bg-fg-3" style={{ width: `${progress}%` }} />
              </span>
              <span className="sr-only">{progress}% read</span>
            </>
          ) : null}
          {!isRead ? <span className="sr-only">Unread</span> : null}
          {isLater ? <span className="sr-only">In Later</span> : null}
          {isStarred ? <span className="sr-only">Kept</span> : null}
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
            src={proxiedImage(item.id, item.media_thumb)}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setThumbFailed(true)}
            className="h-full w-full object-cover grayscale"
          />
        </div>
      ) : null}
      <div className={`flex shrink-0 items-center gap-0.5 coarse:-my-2.5 ${actionsReveal}`}>
        <button
          type="button"
          aria-label={isRead ? 'Mark unread' : 'Mark read'}
          title={isRead ? 'Mark unread (m)' : 'Mark read (m)'}
          onClick={() => onToggleRead(item)}
          className={ICON_BUTTON}
        >
          {isRead ? <CircleCheck aria-hidden="true" className="h-4 w-4" /> : <Circle aria-hidden="true" className="h-4 w-4" />}
        </button>
        {offerLater ? (
          <button
            type="button"
            aria-label="Read later"
            aria-pressed={isLater}
            title={isLater ? 'In Later: take it out (l)' : 'Read later (l)'}
            onClick={() => onToggleLater(item)}
            className={`${ICON_BUTTON} ${isLater ? 'text-fg' : ''}`}
          >
            <Clock aria-hidden="true" className="h-4 w-4" strokeWidth={isLater ? 2.75 : 2} />
          </button>
        ) : null}
        {offerKeep ? (
          <button
            type="button"
            aria-label="Keep"
            aria-pressed={isStarred}
            title={isStarred ? 'Kept: unkeep (s)' : 'Keep (s)'}
            onClick={() => onToggleStar(item)}
            className={`${ICON_BUTTON} ${isStarred ? 'text-fg' : ''}`}
          >
            <Star aria-hidden="true" className="h-4 w-4" fill={isStarred ? 'currentColor' : 'none'} />
          </button>
        ) : null}
      </div>
    </article>
  );
}

export default memo(FeedItem);
