import { Fragment, Suspense, lazy, memo, useMemo, useState, type MouseEvent } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, Circle, CircleCheck, Clock, PlayCircle, Star } from 'lucide-react';

import type { FeedItem as FeedItemData, FeedStory, SnippetPart } from '../../services/api';
import { feedDateLabel, feedFullTime, feedTimeLabel } from '../../lib/dates';
import { countsLabel, formatCount, middleTruncate } from '../../lib/format';
import { sourceLabel } from '../../lib/sourceLabel';
import { feedItemDomId } from '../../lib/feedItem';
import { formatClock } from '../../lib/duration';
import { resumeShare } from '../../lib/readingPosition';
import { lateFind, updateChanges, updateLine } from '../../lib/pageUpdate';
import { StatusIcon } from '../ui/StatusGlyph';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';
import { proxiedImage } from '../../lib/mediaProxy';
import { postHref, sourceReadPath } from '../../lib/feedContext';
import { rememberSelection } from '../../lib/readerSelection';
import {
  coveredBy, LINE_NAME, LINE_TITLE, originHref, originLabel, repostedBy, storyTree, type StoryLine,
} from '../../lib/story';
import { bylineName, carried, carriedLine } from '../../lib/byline';
import { TextLink } from '../ui/TextLink';

// "Also on <channel>" (issue 0132 A): its own chunk, loaded the first time a row has one (the reader's JS budget).
const AlsoOn = lazy(() => import('./AlsoOn'));

function lengthLabel(item: FeedItemData): string | null {
  if (item.duration_seconds) return formatClock(item.duration_seconds);
  if (item.reading_minutes) return `${formatCount(item.reading_minutes)} min read`;
  return null;
}

/** A story line, and its indent in the tree (issue 0064): two levels at most, one on a phone (issue 0068),
 *  where the title takes a line of its own under source and date (issue 0070). */
const STORY_LINE = 'flex min-w-0 items-baseline gap-x-1.5 max-sm:flex-wrap text-[0.8125rem] leading-5 text-fg-3';
const INDENT = ['', 'pl-2 sm:pl-4', 'pl-2 sm:pl-8'];

const CHEVRON = 'h-3 w-3 shrink-0 max-sm:mt-1';

/** On a phone, a line at the deepest indent names its parent instead (issue 0068): "↳ Mat Duggan". */
const Under = ({ name }: { name?: string }) =>
  name ? <span className="max-w-[30%] shrink-0 truncate sm:hidden">↳ {sourceLabel(name)}</span> : null;

/**
 * A folded story's line under its lead (issue 0050): "covered by 3 · Anthropic, Simon Willison, +1"
 * opens the story's other posts, each a quiet link to the post (its source, title and date; a
 * share says so). Opening one comes back to the lead's row. The posts are the story's tree (issue
 * 0064): what came from the lead indented under it, and when the lead is not the origin, the
 * origin first (a page outside INSIGHT opens in Save any page) and the lead's place as "this post".
 */
function StoryPosts({ story, label, lead, now }: { story: FeedStory; label: string; lead: FeedItemData; now?: Date }) {
  const [open, setOpen] = useState(false);
  const listId = `${feedItemDomId(lead.id)}-story`;
  return (
    <div className="mt-0.5 max-sm:col-span-full max-sm:row-start-4">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((value) => !value)}
        // On a phone the line may take two lines, so its names show (issue 0073).
        className={`-ml-1 inline-flex max-w-full items-center gap-1 rounded-sm px-1 text-[0.8125rem] leading-5 text-fg-3 hover:text-fg-2 coarse:min-h-[44px] max-sm:items-start max-sm:py-3 max-sm:text-left ${FOCUS_RING}`}
      >
        {open ? <ChevronDown aria-hidden="true" className={CHEVRON} /> : <ChevronRight aria-hidden="true" className={CHEVRON} />}
        <span className="truncate max-sm:line-clamp-2 max-sm:whitespace-normal">{label}</span>
      </button>
      {open ? (
        <ul id={listId} data-story-posts className="mt-1 mb-1 flex flex-col gap-1 border-l border-line pl-3">
          {storyTree(story, lead.id, lead.sort_at ?? lead.published_at, lead.source_display_name).map((line, i) => (
            <StoryLineItem key={i} line={line} lead={lead} now={now} />
          ))}
        </ul>
      ) : null}
      {open && story.roundups?.length ? (
        // The roundups that mention the story and are not in it, each source once (issue 0068).
        <p className="mb-1 pl-3 text-[0.8125rem] leading-5 text-fg-3 [overflow-wrap:anywhere]">
          Also in roundups:{' '}
          {story.roundups.map((roundup, i) => (
            <Fragment key={roundup.id}>
              {i ? ', ' : null}
              <TextLink to={postHref(roundup.id, null)} title={roundup.title} onClick={() => rememberSelection(lead.id)} muted>
                {sourceLabel(roundup.source_display_name)}
              </TextLink>
            </Fragment>
          ))}
        </p>
      ) : null}
    </div>
  );
}

function StoryLineItem({ line, lead, now }: { line: StoryLine; lead: FeedItemData; now?: Date }) {
  const indent = `${STORY_LINE} ${INDENT[line.depth] ?? ''}`;
  if (line.kind === 'page') {
    const { site, title, linkedBy } = originLabel(line.origin);
    return (
      <li data-depth={line.depth} className={indent}>
        <span className={LINE_NAME} title={site}>{middleTruncate(site, 32)}</span>
        <span aria-hidden="true" className="shrink-0 max-sm:hidden">·</span>
        <Link
          to={originHref(line.origin)}
          onClick={() => rememberSelection(lead.id)}
          dir="auto"
          title={line.origin.url}
          className={`${LINE_TITLE} rounded-sm text-fg-2 underline-offset-4 hover:underline hover:decoration-fg-3 ${FOCUS_RING}`}
        >
          {title}
        </Link>
        <span className="ml-auto shrink-0 pl-2">{linkedBy}</span>
      </li>
    );
  }
  if (line.kind === 'reposts') return <li data-depth={line.depth} className={indent}>{repostedBy(line.by)}</li>;
  if (line.kind === 'self') {
    return (
      <li data-depth={line.depth} aria-current="true" className={indent}>
        <Under name={line.under} />
        <span className={LINE_NAME}>{middleTruncate(sourceLabel(lead.source_display_name), 32)}</span>
        <span aria-hidden="true" className="shrink-0 max-sm:hidden">·</span>
        <span dir="auto" className={`${LINE_TITLE} text-fg-2`}>{lead.title?.trim() || 'Untitled post'}</span>
        <span className="shrink-0">· this post</span>
      </li>
    );
  }
  const { post } = line;
  return (
    <li data-depth={line.depth} className={indent}>
      <Under name={line.under} />
      {!post.read_at ? <StatusIcon status="unread" className="shrink-0 self-center text-fg" /> : null}
      <span className={LINE_NAME} title={sourceLabel(post.source_display_name)}>{middleTruncate(bylineName(post), 32)}</span>
      <span aria-hidden="true" className="shrink-0 max-sm:hidden">·</span>
      <Link
        to={postHref(post.id, null)}
        onClick={() => rememberSelection(lead.id)}
        dir="auto"
        className={`${LINE_TITLE} rounded-sm underline-offset-4 hover:underline hover:decoration-fg-3 ${post.read_at ? 'text-fg-2' : 'font-medium text-fg'} ${FOCUS_RING}`}
      >
        {post.title?.trim() || 'Untitled post'}
      </Link>
      {carried(post) ? <span className="max-w-[30%] shrink-0 truncate">· ↻ {sourceLabel(post.source_display_name)}</span>
        : post.role === 'share' ? <span className="shrink-0">· share</span> : null}
      <time dateTime={post.sort_at} title={feedFullTime(post.sort_at)} className="ml-auto shrink-0 pl-2 tabular-nums">
        {feedDateLabel(post.sort_at, now ?? new Date())}
      </time>
      {!post.read_at ? <span className="sr-only">Unread</span> : null}
    </li>
  );
}

/** A line of a row's meta: below `sm` a line of its own, from `sm` up part of one line (issue 0073). */
const META_LINE = 'contents max-sm:flex max-sm:min-w-0 max-sm:items-center max-sm:gap-x-1.5';

/** A meta line's dot, shown from `sm` up (`wide`) and below it (`phone`), each where something comes before it. */
function Dot({ wide, phone, className = '' }: { wide: boolean; phone: boolean; className?: string }) {
  if (!wide && !phone) return null;
  return <span aria-hidden="true" className={`shrink-0 ${wide ? '' : 'sm:hidden'} ${phone ? '' : 'max-sm:hidden'} ${className}`}>·</span>;
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
  /** A search result's matching line (issue 0040), shown instead of the excerpt, its words in bold. */
  snippet?: SnippetPart[] | null;
  /** Issue 0139: `markx` when only Mark X's English layer matched: the line is its headline, labelled "Mark X". */
  snippetFrom?: 'markx' | null;
  /** A story's line in place of "covered by …": News says what its score is made of (issue 0051). */
  storyLine?: string;
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
  snippet, snippetFrom, storyLine,
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
  // The feed's own order key (when it reached you if later than its date, else published, else
  // fetched; issue 0039), so the column and the day headers agree.
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
  const carriedText = carriedLine(item);
  // The date column is when the post reached you; a changed or late-found page says why.
  const pageNote = item.update
    ? `updated ${updateChanges(item.update)}`.trim()
    : lateFind(item) ? `published ${feedDateLabel(item.published_at, now ?? new Date())}` : null;
  // Below `sm` the meta line is up to three lines beside the actions (issue 0073): the source, the
  // time and the length; a repost's line, a Hacker News item's counts and a reading bar (with its
  // length); a page's note. From `sm` up they are one line, in this order (`sm:order-*`).
  const barLine = progress !== null;
  const lengthPart = length ? (
    <>
      <Dot wide={showSource || Boolean(carriedText || item.counts)} phone={!barLine || Boolean(carriedText || item.counts)} className="sm:order-2" />
      {/* On a phone a long source name gives way first; beside a short one the length may, rather than
          run under the actions (issue 0073). */}
      <span className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap sm:order-2 ${showSource && source.length > 12 ? '' : 'max-sm:min-w-0 max-sm:shrink'}`}>
        {item.duration_seconds ? <PlayCircle aria-hidden="true" className="h-3 w-3 shrink-0" /> : null}
        <span className="truncate">{length}</span>
      </span>
    </>
  ) : null;
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
      className={`reader-row group relative flex scroll-mt-40 scroll-mb-24 items-start gap-3 max-sm:grid max-sm:grid-cols-[minmax(0,1fr)_auto] max-sm:gap-x-1 max-sm:gap-y-0 rounded-md border pl-3 pr-1.5 sm:gap-4 sm:pl-4 py-2 outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg ${selected ? 'border-fg-3 bg-surface' : 'border-line hover:border-line-strong'}`}
    >
      <time
        dateTime={time}
        title={fullTime}
        className={`shrink-0 whitespace-nowrap text-[0.8125rem] leading-6 tabular-nums text-fg-3 max-sm:hidden ${dateColumn === 'time' ? 'w-[2.75rem]' : 'w-[4.25rem]'}`}
      >
        {dayLabel && dateColumn === 'time' ? <span className="sr-only">{dayLabel}, </span> : null}
        {timeLabel}
      </time>
      <div className="min-w-0 flex-1 max-sm:contents">
        <h3
          dir="auto"
          className={`line-clamp-2 min-w-0 max-sm:col-span-full max-sm:pr-1.5 text-[0.9375rem] leading-6 tracking-[-0.011em] [overflow-wrap:anywhere] ${isRead ? 'font-normal text-fg-2' : 'font-semibold text-fg'}`}
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
        <p className="flex min-w-0 items-center gap-x-1.5 text-[0.8125rem] leading-5 text-fg-3 tabular-nums max-sm:col-start-1 max-sm:row-start-2 max-sm:block">
          <span className={META_LINE}>
            {!isRead ? <StatusIcon status="unread" className="text-fg" /> : null}
            {isLater ? <Clock aria-hidden="true" className="h-3 w-3 shrink-0 text-fg" /> : null}
            {isStarred ? <span aria-hidden="true" className="shrink-0 text-fg">★</span> : null}
            {showSource ? (
              <TextLink
                to={sourceReadPath(item.source_id)}
                title={item.source_display_name}
                // A name up to 12 characters stays whole. On a phone its line holds only the time and the
                // length, so a longer one is cut only as far as they need (issues 0070, 0073).
                className={`min-w-0 truncate text-fg-3 decoration-transparent hover:decoration-fg-3 ${source.length > 12 ? '' : 'shrink-0'}`}
              >
                {middleTruncate(source, 56)}
              </TextLink>
            ) : null}
            {/* A page you saved that is its source's post (issue 0122). */}
            {item.saved_by_you ? <span className="shrink-0">{showSource ? '· ' : ''}saved by you</span> : null}
            {/* On a phone the time column's time joins the meta line (issue 0073). */}
            <Dot wide={false} phone={showSource} />
            <time dateTime={time} title={fullTime} className="shrink-0 sm:hidden">
              {dayLabel && dateColumn === 'time' ? <span className="sr-only">{dayLabel}, </span> : null}
              {timeLabel}
            </time>
            {barLine ? null : lengthPart}
          </span>
          {carriedText || item.counts || barLine ? (
            <span className={META_LINE}>
              {/* A repost or forward (issue 0066): its author, beside the source that carried it (issue 0070); whom it quotes (Byline, 0185). */}
              {carriedText ? <span className="min-w-0 truncate sm:order-1">{carriedText}</span> : null}
              {/* A Hacker News item's counts (issue 0070), no longer its text. */}
              {item.counts ? (
                <>
                  <Dot wide={showSource || Boolean(carriedText)} phone={Boolean(carriedText)} className="sm:order-1" />
                  <span className="shrink-0 truncate max-sm:min-w-0 max-sm:shrink sm:order-1">{countsLabel(item.counts)}</span>
                </>
              ) : null}
              {barLine ? lengthPart : null}
              {barLine ? (
                <>
                  <Dot wide phone={Boolean(carriedText || item.counts || length)} className="sm:order-2" />
                  {/* Started, not finished (issue 0030): a hairline track, filled as far as read. */}
                  <span aria-hidden="true" data-reading-progress className="h-px w-10 shrink-0 bg-line sm:order-2">
                    <span className="block h-px bg-fg-3" style={{ width: `${progress}%` }} />
                  </span>
                  <span className="sr-only">{progress}% read</span>
                </>
              ) : null}
            </span>
          ) : null}
          {pageNote ? (
            <span className={META_LINE}>
              <Dot wide={showSource || Boolean(length || carriedText || item.counts)} phone={false} className="sm:order-3" />
              {/* A watched page that changed, or a page new to you long after its date (issue 0039). */}
              <span data-page-note className="min-w-0 truncate sm:order-3" title={item.update ? updateLine(item.update, now) : undefined}>{pageNote}</span>
            </span>
          ) : null}
          {!isRead ? <span className="sr-only">Unread</span> : null}
          {isLater ? <span className="sr-only">In Later</span> : null}
          {isStarred ? <span className="sr-only">Kept</span> : null}
        </p>
        {snippet?.length ? (
          // The words that matched carry weight and the full tone, never a fill (P2, P3).
          <p dir="auto" data-snippet className="mt-0.5 line-clamp-2 max-sm:col-start-1 max-sm:row-start-3 text-sm leading-5 text-fg-2 [overflow-wrap:anywhere]">
            {snippetFrom === 'markx' ? (
              // Why it matched (issue 0139): Mark X's English reading of the post, not its own words.
              <span data-snippet-from="markx" className="mr-1.5 text-[0.75rem] text-fg-3">Mark X ·</span>
            ) : null}
            {snippet.map((part, index) => (part.mark
              ? <mark key={index} className="bg-transparent font-semibold text-fg">{part.text}</mark>
              : <Fragment key={index}>{part.text}</Fragment>))}
          </p>
        ) : showExcerpt ? (
          <p dir="auto" className="mt-0.5 line-clamp-1 max-sm:col-start-1 max-sm:row-start-3 text-sm leading-5 text-fg-2 [overflow-wrap:anywhere]">
            {excerpt}
          </p>
        ) : null}
        {item.story && (storyLine ?? coveredBy(item.story, item.source_id)) ? (
          <StoryPosts story={item.story} label={storyLine ?? coveredBy(item.story, item.source_id) ?? ''} lead={item} now={now} />
        ) : null}
        {item.news?.analysis?.length ? (
          // Issue 0208: a News row's expert breakdowns, apart from its reports, each with its author.
          <ul aria-label="Analysis" className="mt-1 flex flex-col gap-0.5 max-sm:col-start-1 text-[0.8125rem] leading-5">
            {item.news.analysis.map((post) => (
              <li key={post.id} className="min-w-0 truncate text-fg-2">
                <span className="font-semibold text-fg-3">Analysis</span>
                {' · '}{post.author}{' · '}
                <Link to={`/posts/${post.id}`} className="underline-offset-2 hover:underline">{post.title}</Link>
              </li>
            ))}
          </ul>
        ) : null}
        {item.also_on?.length ? <Suspense fallback={null}><AlsoOn lines={item.also_on} now={now} /></Suspense> : null}
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
      <div className={`flex shrink-0 items-center gap-0.5 coarse:-my-2.5 max-sm:col-start-2 max-sm:row-span-2 max-sm:row-start-2 max-sm:self-center ${actionsReveal}`}>
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
