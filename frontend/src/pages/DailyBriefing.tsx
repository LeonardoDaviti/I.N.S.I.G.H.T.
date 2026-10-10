import { Children, Fragment, useState, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { Check, ChevronRight, ExternalLink, Pencil, X } from 'lucide-react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { apiService } from '../services/api';
import type { BriefingReference, BriefingResponse, Post, BriefingTopicsResponse, Topic, SourcesWithCountsResponse, SourceWithSettings, SystemStatusResponse } from '../services/api';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import SourceSettingsEditor from '../components/SourceSettingsEditor';
import IngestionStatusNotice from '../components/ops/IngestionStatusNotice';
import { Button, Chip, Input, Page, Row, StatusGlyph, StatusIcon, Tabs, TabsContent, TabsList, TabsTrigger, iconButtonClass, tabTriggerClass } from '../components/ui';
import { EmptyState, LoadingState, Notice, FOCUS_RING } from '../components/states';
import { getPlatformLabel, getSourceDisplayName, getSourceHandleLabel } from '../lib/sourcePresentation';
import { writeToClipboard } from '../lib/clipboard';
import { formatRelativeTime, localDateISO } from '../lib/dates';
import { formatCount, plural } from '../lib/format';
import { isStale, readableSourceName, tabForMode, type BriefingTab } from '../lib/briefingPage';
import { formatIssueLong, formatIssueRange, formatIssueShort } from '../lib/issueDate';
import { cn } from '../lib/utils';

/**
 * The briefings page (/briefing, /briefing/topics).
 *
 * Mark IX restyle: read like a newsletter (news.smol.ai), not a dashboard. One
 * centred reading column: a dated header with the system line (loud only when
 * ingestion is stale), one tab per briefing kind (daily / topics / weekly, plus
 * the vertical page), a date and ONE primary action per tab, then the issue:
 * kicker, title, text in the reading measure, a plain numbered topic list and
 * the cited posts. It opens on the latest day that has posts, not on an empty
 * today. Monochrome only: no platform colours, no tinted stat cards, no emoji;
 * status is a glyph plus a word. Generation logic is unchanged.
 */


function getRenderablePostContent(post: Post): string {
  const raw = (post.content_html || post.content || '').trim();
  if (!raw) return '';

  const looksLikeEscapedHtml = /&lt;(?:!--|\/?(?:p|div|span|a|img|ul|ol|li|blockquote|code|pre|h[1-6]|table|thead|tbody|tr|td|th))/i.test(raw);
  if (!looksLikeEscapedHtml || typeof document === 'undefined') {
    return raw;
  }

  const textarea = document.createElement('textarea');
  textarea.innerHTML = raw;
  return textarea.value.replace(/<!--\s*SC_(?:OFF|ON)\s*-->/g, '').trim();
}

async function copyPostText(post: Post): Promise<void> {
  const container = document.createElement('div');
  container.innerHTML = getRenderablePostContent(post);
  const text = (container.textContent || container.innerText || post.content || '').trim();
  // Not navigator.clipboard directly: that object only exists in a secure context, and
  // INSIGHT is served over plain HTTP on a Tailscale address. See lib/clipboard.ts.
  await writeToClipboard(text);
}

const IMAGE_URL_PATTERN = /\.(?:jpe?g|png|gif|webp|avif|bmp)(?:[?#].*)?$/i;

function getPostThumbnails(post: Post, limit = 3): string[] {
  const urls = Array.isArray(post.media_urls) ? post.media_urls : [];
  const images = urls.filter((url) => typeof url === 'string' && IMAGE_URL_PATTERN.test(url));

  if (images.length === 0 && (post.platform || '').toLowerCase() === 'youtube') {
    const videoId = urls
      .concat(post.url ? [post.url] : [])
      .map((url) => /(?:v=|youtu\.be\/|\/shorts\/)([A-Za-z0-9_-]{11})/.exec(url || '')?.[1])
      .find(Boolean);
    if (videoId) {
      return [`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`];
    }
  }

  return images.slice(0, limit);
}

const MetaSep = () => (
  <span aria-hidden="true" className="text-fg-3">
    ·
  </span>
);

/** Long-form text (a briefing, a topic summary, a post) in the reading measure. */
function Reading({ content, size = 'body', className }: { content: string; size?: 'body' | 'small'; className?: string }) {
  return (
    <div
      className={cn(
        'min-w-0 max-w-reading break-words text-fg [overflow-wrap:anywhere]',
        size === 'body' ? 'text-[1.0625rem] leading-[1.7]' : 'text-[0.9375rem] leading-[1.6]',
        className,
      )}
    >
      <MarkdownRenderer content={content} />
    </div>
  );
}

/** A text action in a row's action line ("preview · read · original · copy"). */
function RowAction({
  children,
  onClick,
  href,
  pressed,
  label,
}: {
  children: ReactNode;
  onClick?: () => void;
  href?: string;
  pressed?: boolean;
  label?: string;
}) {
  const className = cn(
    'inline-flex items-center gap-1 whitespace-nowrap rounded-sm text-fg-2 hover:text-fg coarse:min-h-[2.75rem]',
    'underline decoration-[rgb(var(--text)/0.3)] underline-offset-[0.2em] hover:decoration-[rgb(var(--text))]',
    FOCUS_RING,
  );
  if (href) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={className} aria-label={label}>
        {children}
      </a>
    );
  }
  return (
    <button type="button" onClick={onClick} className={className} aria-pressed={pressed} aria-label={label}>
      {children}
    </button>
  );
}

function RowActions({ children }: { children: ReactNode }) {
  // Separators are real elements, not ::before content, so they never pick up an
  // action's underline and screen readers skip them.
  const items = Children.toArray(children).filter(Boolean);
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[0.8125rem]">
      {items.map((item, index) => (
        <Fragment key={index}>
          {index > 0 ? <MetaSep /> : null}
          {item}
        </Fragment>
      ))}
    </div>
  );
}

function postDateLabels(post: Post): { short: string; full: string } {
  const value = post.date || post.published_at || null;
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) return { short: '—', full: 'Unknown date' };
  return { short: formatIssueShort(value), full: parsed.toLocaleString() };
}

/**
 * One post in a briefing list or a feed: an optional muted date column, the bold
 * title (it toggles the inline preview), a meta line and a line of text actions.
 * Monochrome: the platform is a word, not a coloured stripe.
 */
function PostEntry({
  post,
  expanded,
  onToggle,
  onOpen,
  copied,
  onCopy,
  onOutlier,
  number,
  showDate = false,
  showThumbnails = false,
}: {
  post: Post;
  expanded: boolean;
  onToggle: () => void;
  onOpen?: () => void;
  copied?: boolean;
  onCopy?: () => void;
  onOutlier?: () => void;
  number?: number;
  /** true = a date column (meta line below sm); 'none' = no date at all (a list of one day). */
  showDate?: boolean | 'none';
  showThumbnails?: boolean;
}) {
  const title = post.title || `${getPlatformLabel(post.platform)} post`;
  const source = readableSourceName(post.source_display_name, post.source);
  const date = postDateLabels(post);
  const thumbnails = showThumbnails ? getPostThumbnails(post) : [];
  const body = expanded ? getRenderablePostContent(post) : '';

  return (
    <li className="border-t border-line first:border-t-0" data-testid="post-entry">
      <div className="flex items-start gap-3 py-3.5">
        {showDate === true ? (
          <span className="hidden w-[4.75rem] shrink-0 whitespace-nowrap pt-0.5 text-[0.8125rem] tabular-nums text-fg-3 sm:block" title={date.full}>
            {date.short}
          </span>
        ) : null}
        {number !== undefined ? (
          <span aria-hidden="true" className="w-6 shrink-0 pt-0.5 text-[0.8125rem] tabular-nums text-fg-3">
            {number}
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <button
            type="button"
            aria-expanded={expanded}
            onClick={onToggle}
            className={cn('block w-full rounded-sm text-left', FOCUS_RING)}
          >
            <span className="line-clamp-3 break-words font-semibold leading-[1.4] text-fg [overflow-wrap:anywhere]">{title}</span>
          </button>
          {/* Source name only (the platform word was noise); one line that never
              wraps: the source truncates, the date keeps its width (break-ui #9). */}
          <div className="mt-0.5 flex min-w-0 flex-nowrap items-center gap-x-1.5 text-[0.8125rem] text-fg-3">
            {source ? (
              <span className="min-w-0 truncate" title={source}>
                {source}
              </span>
            ) : null}
            {showDate !== 'none' && (post.date || post.published_at) ? (
              <span className={cn('contents', showDate === true && 'sm:hidden')}>
                {source ? <MetaSep /> : null}
                <span className="shrink-0 whitespace-nowrap tabular-nums" title={date.full}>
                  {date.short}
                </span>
              </span>
            ) : null}
          </div>
          {thumbnails.length > 0 ? (
            <div className="mt-2.5 flex flex-wrap gap-2">
              {thumbnails.map((mediaUrl) => (
                <img
                  key={mediaUrl}
                  src={mediaUrl}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  referrerPolicy="no-referrer"
                  className="aspect-video w-28 shrink-0 rounded-sm border border-line bg-raised object-cover"
                  onError={(e) => {
                    (e.currentTarget as HTMLImageElement).style.display = 'none';
                  }}
                />
              ))}
            </div>
          ) : null}
          <RowActions>
            <RowAction onClick={onToggle} pressed={expanded}>
              {expanded ? 'hide text' : 'preview'}
            </RowAction>
            {post.id && onOpen ? <RowAction onClick={onOpen}>read</RowAction> : null}
            {post.url ? (
              <RowAction href={post.url} label={`Open the original of ${title} in a new tab`}>
                original
                <ExternalLink aria-hidden="true" className="h-3 w-3" />
              </RowAction>
            ) : null}
            {onCopy ? (
              <RowAction onClick={onCopy} label={copied ? 'Copied to clipboard' : 'Copy post text'}>
                {copied ? (
                  <>
                    <Check aria-hidden="true" className="h-3 w-3" />
                    copied
                  </>
                ) : (
                  'copy'
                )}
              </RowAction>
            ) : null}
            {onOutlier ? <RowAction onClick={onOutlier}>move to outlier</RowAction> : null}
          </RowActions>
        </div>
      </div>
      {expanded ? (
        <div className={cn('pb-5', showDate === true ? 'sm:pl-[5.5rem]' : number !== undefined ? 'pl-9' : '')}>
          {body ? <Reading content={body} size="small" className="text-fg-2" /> : <p className="text-[0.875rem] text-fg-3">This post has no text.</p>}
        </div>
      ) : null}
    </li>
  );
}

/** A quiet text action that only underlines on hover (the row's actions are secondary to its title). */
const QUIET_ACTION = cn(
  'relative z-[1] inline-flex items-center gap-1 whitespace-nowrap rounded-sm text-fg-3 hover:text-fg coarse:min-h-[2.75rem]',
  'underline-offset-[0.2em] hover:underline',
  FOCUS_RING,
);

/**
 * One post in a plain post list (posts of the day, one source): the shared
 * smol-style Row. A muted date (or time) column, the bold title linking to the
 * post (the link covers the whole row), the source name as the only meta, and
 * preview / original / copy revealed on hover or focus (always on touch).
 */
function PostRow({
  post,
  to,
  linkState,
  timeOnly = false,
  expanded,
  onToggle,
  copied,
  onCopy,
}: {
  post: Post;
  to?: string;
  linkState?: unknown;
  /** A list of one day: the column shows the time, not the same date on every row. */
  timeOnly?: boolean;
  expanded: boolean;
  onToggle: () => void;
  copied?: boolean;
  onCopy?: () => void;
}) {
  const title = post.title || `${getPlatformLabel(post.platform)} post`;
  const source = readableSourceName(post.source_display_name, post.source);
  const date = postDateLabels(post);
  const raw = post.date || post.published_at || null;
  const parsed = raw ? new Date(raw) : null;
  const time =
    parsed && !Number.isNaN(parsed.getTime())
      ? parsed.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
      : '—';
  const column = timeOnly ? time : date.short;
  const body = expanded ? getRenderablePostContent(post) : '';

  return (
    <li data-testid="post-entry" data-expanded={expanded || undefined} className="group/post">
      <Row
        className={cn(
          'relative transition-[border-color,background-color] duration-[120ms] ease-out motion-reduce:transition-none',
          'hover:border-line-strong focus-within:border-line-strong',
          expanded && 'rounded-b-none border-line-strong',
          // Below sm the date column folds into the meta line, so the title keeps its width.
          'max-sm:[&>div:first-child]:hidden',
        )}
        meta={<span title={date.full}>{column}</span>}
        title={
          to ? (
            <Link
              to={to}
              state={linkState}
              className={cn(
                'rounded-sm after:absolute after:inset-0 after:rounded-md after:content-[""]',
                'focus-visible:outline-none focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:outline-offset-2 focus-visible:after:outline-fg',
              )}
            >
              {title}
            </Link>
          ) : (
            title
          )
        }
        description={
          <span className="flex min-w-0 flex-wrap items-center gap-x-3 text-fg-3">
            <span className="flex min-w-[min(100%,9rem)] flex-1 flex-nowrap items-center gap-x-1.5">
              {source ? (
                <span className="min-w-0 truncate" title={source}>
                  {source}
                </span>
              ) : null}
              {raw ? (
                <span className="contents sm:hidden">
                  {source ? <MetaSep /> : null}
                  <span className="shrink-0 whitespace-nowrap tabular-nums" title={date.full}>
                    {column}
                  </span>
                </span>
              ) : null}
            </span>
            <span
              className={cn(
                'flex shrink-0 items-center gap-x-3 transition-opacity duration-[120ms] ease-out motion-reduce:transition-none',
                'opacity-0 group-hover/post:opacity-100 group-focus-within/post:opacity-100 group-data-[expanded]/post:opacity-100 coarse:opacity-100',
                // Narrow and fine-pointed: hidden actions take no room from the source name.
                'max-sm:hidden max-sm:group-hover/post:flex max-sm:group-focus-within/post:flex max-sm:group-data-[expanded]/post:flex coarse:!flex',
              )}
            >
              <button type="button" onClick={onToggle} aria-expanded={expanded} className={QUIET_ACTION}>
                {expanded ? 'hide' : 'preview'}
              </button>
              {post.url ? (
                <a
                  href={post.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={QUIET_ACTION}
                  aria-label={`Open the original of ${title} in a new tab`}
                >
                  original
                  <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
              ) : null}
              {onCopy ? (
                <button type="button" onClick={onCopy} className={QUIET_ACTION} aria-label={copied ? 'Copied to clipboard' : 'Copy post text'}>
                  {copied ? (
                    <>
                      <Check aria-hidden="true" className="h-3 w-3" />
                      copied
                    </>
                  ) : (
                    'copy'
                  )}
                </button>
              ) : null}
            </span>
          </span>
        }
      />
      {expanded ? (
        <div className="rounded-b-md border border-t-0 border-line-strong px-4 pb-5 pt-3 sm:pl-[7.5rem]">
          {body ? <Reading content={body} size="small" className="text-fg-2" /> : <p className="text-[0.875rem] text-fg-3">This post has no text.</p>}
        </div>
      ) : null}
    </li>
  );
}

/** A numbered topic in a briefing: the title toggles its body (summary, timeline, posts). */
function TopicItem({
  number,
  title,
  count,
  open,
  onToggle,
  outlier = false,
  headerExtra,
  editor,
  children,
}: {
  number: number;
  title: string;
  count?: number;
  open: boolean;
  onToggle: () => void;
  outlier?: boolean;
  headerExtra?: ReactNode;
  /** Replaces the title button while the title is being edited. */
  editor?: ReactNode;
  children: ReactNode;
}) {
  return (
    <li className="border-t border-line first:border-t-0" data-testid="topic-item">
      <div className="flex items-start gap-2 py-4">
        <span aria-hidden="true" className="w-7 shrink-0 pt-[0.15rem] text-[0.8125rem] tabular-nums text-fg-3">
          {String(number).padStart(2, '0')}
        </span>
        {editor ?? (
          <button
            type="button"
            aria-expanded={open}
            onClick={onToggle}
            className={cn('group flex min-w-0 flex-1 items-start gap-2 rounded-sm text-left', FOCUS_RING)}
          >
            <span className="min-w-0 flex-1">
              <span className="break-words text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg [overflow-wrap:anywhere]">
                {title || 'Untitled topic'}
              </span>
              {outlier ? (
                <Chip variant="dashed" className="ml-2 align-[0.1em]">
                  outlier
                </Chip>
              ) : null}
              {count !== undefined ? (
                <span className="ml-2 whitespace-nowrap text-[0.8125rem] font-normal tabular-nums text-fg-3">{plural(count, 'post')}</span>
              ) : null}
            </span>
            <ChevronRight aria-hidden="true" className={cn('mt-1 h-4 w-4 shrink-0 text-fg-3 group-hover:text-fg', open && 'rotate-90')} />
          </button>
        )}
        {headerExtra}
      </div>
      {open ? <div className="space-y-5 pb-6 pl-9">{children}</div> : null}
    </li>
  );
}

/** The posts a briefing cites, as a plain list under the text. */
function ReferenceList({
  references,
  onOpenPost,
}: {
  references?: BriefingReference[] | null;
  onOpenPost: (postId: string) => void;
}) {
  if (!references?.length) {
    return null;
  }
  const visible = references.slice(0, 10);

  return (
    <section className="mt-8 max-w-reading" aria-label="Referenced posts">
      <h3 className="text-[0.8125rem] font-medium text-fg-3">
        Referenced posts <span className="tabular-nums">· {formatCount(references.length)}</span>
      </h3>
      <ol className="mt-2 border-t border-line">
        {visible.map((reference, index) => {
          const post = reference.post;
          const label = reference.display_label || post?.title || post?.source_display_name || post?.source || `Post ${index + 1}`;
          const rawHighlight = reference.highlight?.highlight_text || reference.highlight?.commentary || '';
          const highlight = rawHighlight.length > 220 ? `${rawHighlight.slice(0, 220)}…` : rawHighlight;
          const source = readableSourceName(post?.source_display_name, post?.source) || reference.reference_role || 'reference';
          return (
            <li key={reference.id || `${reference.post_id}-${index}`} className="flex items-start gap-3 border-b border-line py-2.5">
              <span aria-hidden="true" className="w-6 shrink-0 pt-0.5 text-[0.8125rem] tabular-nums text-fg-3">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                {reference.post_id ? (
                  <button
                    type="button"
                    onClick={() => onOpenPost(reference.post_id!)}
                    className={cn('block w-full rounded-sm text-left', FOCUS_RING)}
                  >
                    <span className="line-clamp-2 break-words font-medium text-fg [overflow-wrap:anywhere] hover:underline">{label}</span>
                  </button>
                ) : (
                  <span className="line-clamp-2 break-words font-medium text-fg [overflow-wrap:anywhere]">{label}</span>
                )}
                <span className="block truncate text-[0.8125rem] text-fg-3" title={source}>
                  {source}
                </span>
                {highlight ? (
                  <p className="mt-1 line-clamp-3 break-words text-[0.875rem] leading-[1.55] text-fg-2 [overflow-wrap:anywhere]">“{highlight}”</p>
                ) : null}
              </div>
              {post?.url ? (
                <a
                  href={post.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={iconButtonClass}
                  aria-label={`Open the original of ${label} in a new tab`}
                >
                  <ExternalLink aria-hidden="true" />
                </a>
              ) : null}
            </li>
          );
        })}
      </ol>
      {references.length > visible.length && (
        <p className="mt-2 text-[0.8125rem] tabular-nums text-fg-3">+{formatCount(references.length - visible.length)} more referenced posts</p>
      )}
    </section>
  );
}

/** One briefing on the page, read like a newsletter issue: kicker (date/kind), title, body. */
function IssueSection({ id, kicker, title, children }: { id: string; kicker?: ReactNode; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="border-t border-line pt-8 first:border-t-0 first:pt-0">
      {kicker ? <p className="text-[0.8125rem] tabular-nums text-fg-3">{kicker}</p> : null}
      <h2 id={id} className="mt-1 break-words text-[1.375rem] font-semibold leading-[1.25] tracking-[-0.02em] text-fg">
        {title}
      </h2>
      <div className="mt-5">{children}</div>
    </section>
  );
}

export default function DailyBriefing() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initializedFromUrlRef = useRef(false);
  const SOURCE_POSTS_PAGE_SIZE = 20;
  // One tab per briefing kind (daily / topics / weekly); vertical is its own page.
  const [tab, setTab] = useState<BriefingTab>(() => tabForMode(searchParams.get('mode')));
  // Resolves with the first /api/status answer, so the default date can follow it.
  const statusRequestRef = useRef<Promise<SystemStatusResponse | null> | null>(null);
  
  // Date selection (for briefing generation only)
  // The local calendar day: toISOString() is the UTC day, which is wrong for part of every day.
  const [selectedDate, setSelectedDate] = useState(() => localDateISO());
  
  // Briefing generation state
  const [isGenerating, setIsGenerating] = useState(false);
  const [briefingData, setBriefingData] = useState<string | null>(null);
  const [briefingTakeaway, setBriefingTakeaway] = useState<string | null>(null);
  const [briefingReferences, setBriefingReferences] = useState<BriefingReference[]>([]);
  const [isGeneratingWeekly, setIsGeneratingWeekly] = useState(false);
  const [isGeneratingWeeklyTopics, setIsGeneratingWeeklyTopics] = useState(false);
  const [weeklyBriefing, setWeeklyBriefing] = useState<string | null>(null);
  const [weeklyMeta, setWeeklyMeta] = useState<{
    weekStart?: string | null;
    weekEnd?: string | null;
    dailyBriefingsUsed?: number;
    cached?: boolean;
    variant?: string | null;
    oneSentenceTakeaway?: string | null;
  } | null>(null);
  const [weeklyTopics, setWeeklyTopics] = useState<Topic[]>([]);
  const [weeklyPostsMap, setWeeklyPostsMap] = useState<Record<string, Post>>({});
  const [weeklyReferences, setWeeklyReferences] = useState<BriefingReference[]>([]);
  const [briefingStats, setBriefingStats] = useState<{
    postsProcessed: number;
    totalFetched: number;
    date: string;
  } | null>(null);
  
  // Topics-based briefing state
  const [isGeneratingTopics, setIsGeneratingTopics] = useState(false);
  const [isRefreshingTopics, setIsRefreshingTopics] = useState(false);
  const [topicsBriefing, setTopicsBriefing] = useState<string | null>(null);
  const [topicsTakeaway, setTopicsTakeaway] = useState<string | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [postsMap, setPostsMap] = useState<Record<string, Post>>({});
  const [topicsReferences, setTopicsReferences] = useState<BriefingReference[]>([]);
  const [openTopics, setOpenTopics] = useState<Record<string, boolean>>({});
  const [expandedPosts, setExpandedPosts] = useState<Record<string, boolean>>({});
  
  // Error handling
  const [error, setError] = useState<string | null>(null);

  // System freshness/health strip (GET /api/status)
  const [systemStatus, setSystemStatus] = useState<SystemStatusResponse | null>(null);
  const [isLoadingStatus, setIsLoadingStatus] = useState(false);
  
  // Sources sidebar state
  const [sourcesData, setSourcesData] = useState<SourcesWithCountsResponse | null>(null);
  const [editingSource, setEditingSource] = useState<SourceWithSettings | null>(null);
  const [loadingSourceEditorId, setLoadingSourceEditorId] = useState<string | null>(null);
  
  // Selected source/view
  const [activeView, setActiveView] = useState<'briefing' | 'all-posts' | 'source' | 'configure'>('briefing');
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  
  // Posts display state
  const [displayedPosts, setDisplayedPosts] = useState<Post[]>([]);
  const [isLoadingPosts, setIsLoadingPosts] = useState(false);
  const [isLoadingMoreSourcePosts, setIsLoadingMoreSourcePosts] = useState(false);
  const [postsExpanded, setPostsExpanded] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<Record<string, boolean>>({});
  const [sourcePostsMeta, setSourcePostsMeta] = useState<{
    total: number;
    hasMore: boolean;
  }>({
    total: 0,
    hasMore: false,
  });
  
  // Posts fetched by date state
  const [, setDatabasePosts] = useState<Post[]>([]);
  const [databasePostsStats, setDatabasePostsStats] = useState<{
    total: number;
    date: string;
    source: string;
  } | null>(null);

  // Topics fetched by date state
  const [databaseTopics, setDatabaseTopics] = useState<Topic[]>([]);
  const [isLoadingTopics, setIsLoadingTopics] = useState(false);
  const [topicsStats, setTopicsStats] = useState<{
    total: number;
    date: string;
  } | null>(null);

  // Topic editing state
  const [editingTopicId, setEditingTopicId] = useState<string | null>(null);
  const [editingTopicTitle, setEditingTopicTitle] = useState<string>('');
  const [isSavingTitle, setIsSavingTitle] = useState(false);

  // 🚀 CACHE: Store fetched posts to avoid re-fetching
  // Think of this as your "photocopy collection"
  const [postsCache, setPostsCache] = useState<{
    bySource: Record<string, Post[]>;  // sourceId → posts
    byDate: Record<string, Post[]>;     // date → posts
    allPosts: Post[] | null;            // all posts cache
  }>({
    bySource: {},
    byDate: {},
    allPosts: null
  });
  const [sourcePostsCache, setSourcePostsCache] = useState<
    Record<string, { posts: Post[]; total: number; hasMore: boolean }>
  >({});

  const sourceGroups = useMemo(
    () => (
      sourcesData
        ? Object.entries(sourcesData.platforms)
          .filter(([, platformData]) => platformData.total_count > 0)
          .map(([platform, platformData]) => ({
            platform,
            totalCount: platformData.total_count,
            sources: platformData.sources
              .filter((source) => source.post_count > 0)
              .map((source) => ({ ...source, platform })),
          }))
        : []
    ),
    [sourcesData],
  );

  const selectedSource = useMemo(
    () => sourceGroups.flatMap((group) => group.sources).find((source) => source.id === selectedSourceId) || null,
    [selectedSourceId, sourceGroups],
  );

  const selectedSourceName = selectedSource
    ? readableSourceName(getSourceDisplayName(selectedSource), selectedSource.handle_or_url) || 'Source'
    : 'Source';
  const selectedSourceHandle = selectedSource ? getSourceHandleLabel(selectedSource) : '';

  // Load sources with counts on mount
  useEffect(() => {
    loadSourcesWithCounts();
    statusRequestRef.current = loadSystemStatus();
  }, []);

  const toggleTopic = (topicId: string) => {
    setOpenTopics((prev) => {
      const next = {
        ...prev,
        [topicId]: !prev[topicId],
      };
      const mode = searchParams.get('mode');
      if (mode && ['topics', 'db-topics', 'weekly-topics'].includes(mode)) {
        const openIds = Object.keys(next).filter((key) => next[key]);
        updateRouteState({
          topic: openIds.join(',') || null,
        });
      }
      return next;
    });
  };

  const updateRouteState = (params: Record<string, string | null | undefined>) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(params).forEach(([key, value]) => {
      if (value === null || value === undefined || value === '') {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    });
    setSearchParams(next, { replace: true });
  };

  const currentReturnUrl = () => {
    const query = searchParams.toString();
    return query ? `/briefing?${query}` : '/briefing';
  };

  const handleCopyPost = async (post: Post, key: string) => {
    try {
      await copyPostText(post);
      setCopied((prev) => ({ ...prev, [key]: true }));
      window.setTimeout(() => {
        setCopied((prev) => ({ ...prev, [key]: false }));
      }, 1800);
    } catch {
      setError('Failed to copy post text to clipboard');
    }
  };

  const loadSourcesWithCounts = async () => {
    try {
      console.log('📋 Loading sources with post counts...');
      const response = await apiService.getSourcesWithCounts();
      
      if (response.success) {
        console.log(`✅ Loaded sources: ${response.total_posts} total posts`);
        setSourcesData(response);

      } else {
        console.error('❌ Failed to load sources:', response.error);
        setError(response.error || 'Failed to load sources');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error');
    }
  };

  const loadSystemStatus = async (): Promise<SystemStatusResponse | null> => {
    setIsLoadingStatus(true);
    try {
      const response = await apiService.getStatus();
      setSystemStatus(response);
      return response ?? null;
    } catch {
      return null;
    } finally {
      setIsLoadingStatus(false);
    }
  };

  const openSourceSettings = async (sourceId: string) => {
    setLoadingSourceEditorId(sourceId);
    setError(null);

    try {
      const response = await apiService.getSourceSettings(sourceId);
      if (!response.success) {
        setError(response.error || 'Failed to load source settings');
        return;
      }

      const baseSource = sourceGroups
        .flatMap((group) => group.sources)
        .find((source) => source.id === sourceId);

      const source = response.source || (baseSource ? {
        id: baseSource.id,
        platform: baseSource.platform,
        handle_or_url: baseSource.handle_or_url,
        enabled: baseSource.enabled,
        post_count: baseSource.post_count,
        settings: {
          ...response.settings,
          display_name: response.settings.display_name ?? baseSource.display_name,
          priority: response.settings.priority ?? baseSource.priority,
        },
      } as SourceWithSettings : null);

      if (!source) {
        setError('Source settings could not be matched to a source');
        return;
      }

      setEditingSource(source);
    } catch (settingsError) {
      setError(settingsError instanceof Error ? settingsError.message : 'Failed to load source settings');
    } finally {
      setLoadingSourceEditorId(null);
    }
  };

  const handleLoadDatabasePosts = async (options?: { dateOverride?: string }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setActiveView('all-posts');
    setSelectedSourceId(null);
    updateRouteState({
      date: targetDate,
      view: 'all-posts',
      mode: 'db-posts',
      source: null,
      topic: null,
    });
    
    // 🔍 STEP 1: Check cache first (like checking your photocopies at home)
    if (postsCache.byDate[targetDate]) {
      console.log(`⚡ Using cached posts for date: ${targetDate}`);
      const cachedPosts = postsCache.byDate[targetDate];
      setDatabasePosts(cachedPosts);
      setDisplayedPosts(cachedPosts);
      setDatabasePostsStats({
        total: cachedPosts.length,
        date: targetDate,
        source: 'cache'  // Indicate it came from cache
      });
      return; // ✨ Done! No API call needed!
    }
    
    // 📞 STEP 2: If not in cache, fetch from API (go to the library)
    setIsLoadingPosts(true);
    setError(null);
    setDatabasePosts([]);
    setDatabasePostsStats(null);
    
    try {
      console.log(`📖 Loading posts from database for date: ${targetDate}`);
      const response = await apiService.getDailyPosts(targetDate);
      
      if (response.success) {
        console.log(`✅ Loaded ${response.total} posts from database`);
        
        // 💾 STEP 3: Save to cache for next time (make a photocopy)
        setPostsCache(prev => ({
          ...prev,
          byDate: {
            ...prev.byDate,
            [targetDate]: response.posts
          }
        }));
        
        setDatabasePosts(response.posts);
        setDisplayedPosts(response.posts);
        setDatabasePostsStats({
          total: response.total,
          date: response.date,
          source: response.source
        });
      } else {
        console.error('❌ Failed to load posts:', response.error);
        setError(response.error || 'Failed to load posts from database');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsLoadingPosts(false);
    }
  };

  const handleLoadTopics = async (options?: { dateOverride?: string; topicIds?: string[] }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setActiveView('briefing');  // Switch to briefing view to show topics
    setSelectedSourceId(null);
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'db-topics',
      source: null,
      topic: (options?.topicIds || []).join(',') || null,
    });
    
    setIsLoadingTopics(true);
    setError(null);
    setDatabaseTopics([]);
    setTopicsStats(null);
    
    try {
      console.log(`📚 Loading topics from database for date: ${targetDate}`);
      const response = await apiService.getTopicsByDate(targetDate);
      
      if (response.success) {
        console.log(`✅ Loaded ${response.total} topics from database`);
        
        setDatabaseTopics(response.topics);
        setTopicsStats({
          total: response.total,
          date: response.date
        });
        if (options?.topicIds?.length) {
          const nextOpenTopics: Record<string, boolean> = {};
          options.topicIds.forEach((topicId) => { nextOpenTopics[topicId] = true; });
          setOpenTopics(nextOpenTopics);
        }
        
        // If no topics found, show helpful message
        if (response.total === 0) {
          setError(response.message || `No topics found for ${targetDate}. Generate topics first using the backend script.`);
        }
      } else {
        console.error('❌ Failed to load topics:', response.error);
        setError(response.error || 'Failed to load topics from database');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsLoadingTopics(false);
    }
  };

  const handleEditTopicTitle = (topicId: string, currentTitle: string) => {
    setEditingTopicId(topicId);
    setEditingTopicTitle(currentTitle);
  };

  const handleCancelEditTitle = () => {
    setEditingTopicId(null);
    setEditingTopicTitle('');
    setIsSavingTitle(false);
  };

  const handleSaveTopicTitle = async (topicId: string) => {
    const newTitle = editingTopicTitle.trim();
    
    // Validate
    if (!newTitle) {
      setError('Topic title cannot be empty');
      return;
    }
    
    // Find the topic to check if title actually changed
    const topic = databaseTopics.find(t => t.id === topicId);
    if (topic && topic.title === newTitle) {
      // No change, just exit edit mode
      handleCancelEditTitle();
      return;
    }
    
    setIsSavingTitle(true);
    setError(null);
    
    try {
      console.log(`✏️  Updating topic title: ${topicId}`);
      const response = await apiService.updateTopicTitle(topicId, newTitle);
      
      if (response.success) {
        console.log(`✅ Topic title updated successfully`);
        
        // Update local state
        setDatabaseTopics(prevTopics =>
          prevTopics.map(t =>
            t.id === topicId ? { ...t, title: newTitle } : t
          )
        );
        
        // Exit edit mode
        handleCancelEditTitle();
      } else {
        console.error('❌ Failed to update topic title:', response.error);
        setError(response.error || 'Failed to update topic title');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsSavingTitle(false);
    }
  };

  const handleMovePostToOutlier = async (topicId: string, postId: string) => {
    setError(null);
    
    try {
      console.log(`✂️  Moving post ${postId} to outlier from topic ${topicId}`);
      const response = await apiService.movePostToOutlier(topicId, postId, selectedDate);
      
      if (response.success) {
        console.log(`✅ Post moved to outlier successfully`);
        
        // Update local state: Remove post from current topic
        setDatabaseTopics(prevTopics =>
          prevTopics.map(topic => {
            if (topic.id === topicId) {
              // Remove post from this topic
              return {
                ...topic,
                posts: topic.posts?.filter(p => p.id !== postId) || []
              };
            } else if (topic.id === response.outlier_topic_id) {
              // Add post to outlier topic (if it's already loaded)
              // Find the post from the original topic
              const postToMove = prevTopics
                .find(t => t.id === topicId)
                ?.posts?.find(p => p.id === postId);
              
              if (postToMove) {
                return {
                  ...topic,
                  posts: [...(topic.posts || []), postToMove]
                };
              }
            }
            return topic;
          })
        );
        
        // A success is a toast, not the error slot (it used to borrow setError and
        // clear itself after 3s, so a success read as a failure).
        toast.success(response.message || 'Post moved to the outlier topic');
      } else {
        console.error('❌ Failed to move post to outlier:', response.error);
        setError(response.error || 'Failed to move post to outlier');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    }
  };

  // "All posts" (every source, one request per source) is the reader now: the
  // feed at / reads every source in one keyset-paged query (spec §F.3).
  const openReader = () => navigate('/');

  const handleLoadSourcePosts = async (
    sourceId: string,
    options?: { append?: boolean; force?: boolean },
  ) => {
    const append = Boolean(options?.append);
    const force = Boolean(options?.force);
    setActiveView('source');
    setSelectedSourceId(sourceId);
    if (!append) {
      updateRouteState({
        date: selectedDate,
        view: 'source',
        mode: 'source-posts',
        source: sourceId,
        topic: null,
      });
    }

    const cachedSourcePosts = sourcePostsCache[sourceId];

    if (!append && cachedSourcePosts && !force) {
      console.log(`⚡ Using cached paged posts for source: ${sourceId}`);
      setDisplayedPosts(cachedSourcePosts.posts);
      setSourcePostsMeta({
        total: cachedSourcePosts.total,
        hasMore: cachedSourcePosts.hasMore,
      });
      setDatabasePosts([]);
      setDatabasePostsStats(null);
      setError(null);
      return;
    }

    if (append) {
      setIsLoadingMoreSourcePosts(true);
    } else {
      setIsLoadingPosts(true);
      setDisplayedPosts([]);
      setSourcePostsMeta({ total: 0, hasMore: false });
    }

    setError(null);
    setDatabasePosts([]);
    setDatabasePostsStats(null);
    
    try {
      const currentPosts = append
        ? (cachedSourcePosts?.posts || (selectedSourceId === sourceId ? displayedPosts : []))
        : [];
      const offset = append ? currentPosts.length : 0;

      console.log(`📖 Loading posts for source: ${sourceId} offset=${offset} limit=${SOURCE_POSTS_PAGE_SIZE}`);
      const response = await apiService.getPostsBySource(sourceId, {
        limit: SOURCE_POSTS_PAGE_SIZE,
        offset,
      });
      
      if (response.success) {
        // Dedupe on merge: pagination is offset-based, so a post ingested between
        // two "load more" clicks shifts the window and can re-return a row already
        // on screen. Since post.id is now the React key, a duplicate would collide.
        const mergedPosts = append
          ? Array.from(
              new Map(
                [...currentPosts, ...response.posts].map((p, i) => [p.id ?? p.url ?? `idx:${i}`, p])
              ).values()
            )
          : response.posts;
        const hasMore = Boolean(response.has_more ?? (mergedPosts.length < response.total));

        console.log(`✅ Loaded ${response.returned ?? response.posts.length} posts (${mergedPosts.length}/${response.total})`);

        setSourcePostsCache(prev => ({
          ...prev,
          [sourceId]: {
            posts: mergedPosts,
            total: response.total,
            hasMore,
          },
        }));

        setDisplayedPosts(mergedPosts);
        setSourcePostsMeta({
          total: response.total,
          hasMore,
        });
      } else {
        console.error('❌ Failed to load posts:', response.error);
        setError(response.error || 'Failed to load posts');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error');
    } finally {
      if (append) {
        setIsLoadingMoreSourcePosts(false);
      } else {
        setIsLoadingPosts(false);
      }
    }
  };

  const handleGenerateBriefing = async (options?: { dateOverride?: string }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setIsGenerating(true);
    setError(null);
    setBriefingData(null);
    setBriefingTakeaway(null);
    setBriefingReferences([]);
    setWeeklyBriefing(null);
    setWeeklyMeta(null);
    setWeeklyTopics([]);
    setWeeklyPostsMap({});
    setWeeklyReferences([]);
    setBriefingStats(null);
    setTopicsBriefing(null);
    setTopicsTakeaway(null);
    setTopics([]);
    setPostsMap({});
    setTopicsReferences([]);
    setOpenTopics({});
    setActiveView('briefing');
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'daily',
      source: null,
      topic: null,
    });

    try {
      console.log(`🚀 Generating briefing for date: ${targetDate}`);
      const response: BriefingResponse = await apiService.generateBriefing(targetDate);
      
      if (response.success && response.briefing) {
        console.log('✅ Briefing generated successfully');
        setBriefingData(response.briefing);
        setBriefingTakeaway(response.one_sentence_takeaway || null);
        setBriefingReferences(response.references || []);
        setBriefingStats({
          postsProcessed: response.posts_processed || 0,
          totalFetched: response.total_posts_fetched || 0,
          date: response.date || targetDate
        });
      } else {
        console.error('❌ Briefing generation failed:', response.error);
        setError(response.error || 'Failed to generate briefing');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleGenerateWeeklyBriefing = async (refresh = false, options?: { dateOverride?: string }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setIsGeneratingWeekly(true);
    setError(null);
    setBriefingData(null);
    setBriefingTakeaway(null);
    setBriefingReferences([]);
    setBriefingStats(null);
    setTopicsBriefing(null);
    setTopicsTakeaway(null);
    setTopics([]);
    setPostsMap({});
    setTopicsReferences([]);
    setWeeklyTopics([]);
    setWeeklyPostsMap({});
    setWeeklyReferences([]);
    setOpenTopics({});
    setActiveView('briefing');
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'weekly',
      source: null,
      topic: null,
    });

    try {
      const response = await apiService.generateWeeklyBriefing(targetDate, refresh, false);
      if (response.success) {
        setWeeklyBriefing(response.briefing || null);
        setWeeklyMeta({
          weekStart: response.week_start,
          weekEnd: response.week_end,
          dailyBriefingsUsed: response.daily_briefings_used,
          cached: response.cached,
          variant: response.variant || 'default',
          oneSentenceTakeaway: response.one_sentence_takeaway || null,
        });
        setWeeklyReferences(response.references || []);
      } else {
        setError(response.error || 'Failed to generate weekly briefing');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error occurred');
    } finally {
      setIsGeneratingWeekly(false);
    }
  };

  const handleGenerateWeeklyTopicBriefing = async (refresh = false, options?: { dateOverride?: string; topicIds?: string[] }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setIsGeneratingWeeklyTopics(true);
    setError(null);
    setBriefingData(null);
    setBriefingTakeaway(null);
    setBriefingReferences([]);
    setBriefingStats(null);
    setTopicsBriefing(null);
    setTopicsTakeaway(null);
    setTopics([]);
    setPostsMap({});
    setTopicsReferences([]);
    setWeeklyTopics([]);
    setWeeklyPostsMap({});
    setWeeklyReferences([]);
    setOpenTopics({});
    setActiveView('briefing');
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'weekly-topics',
      source: null,
      topic: (options?.topicIds || []).join(',') || null,
    });

    try {
      const response = await apiService.generateWeeklyBriefing(targetDate, refresh, true);
      if (response.success) {
        setWeeklyBriefing(response.briefing || null);
        setWeeklyMeta({
          weekStart: response.week_start,
          weekEnd: response.week_end,
          dailyBriefingsUsed: response.daily_briefings_used,
          cached: response.cached,
          variant: response.variant || 'topics',
          oneSentenceTakeaway: response.one_sentence_takeaway || null,
        });
        setWeeklyTopics(response.topics || []);
        setWeeklyPostsMap(response.posts || {});
        setWeeklyReferences(response.references || []);
        const requestedTopicIds = options?.topicIds || [];
        const nextOpenTopics: Record<string, boolean> = {};
        if (requestedTopicIds.length) {
          requestedTopicIds.forEach((topicId) => { nextOpenTopics[topicId] = true; });
        } else if (response.topics?.[0]?.id) {
          nextOpenTopics[response.topics[0].id] = true;
        }
        setOpenTopics(nextOpenTopics);
      } else {
        setError(response.error || 'Failed to generate weekly topic briefing');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error occurred');
    } finally {
      setIsGeneratingWeeklyTopics(false);
    }
  };

  const handleGenerateTopicBriefing = async (
    refresh = false,
    options?: { dateOverride?: string; topicIds?: string[] | null }
  ) => {
    const targetDate = options?.dateOverride || selectedDate;
    const requestedTopicIds = options?.topicIds || [];
    if (refresh) {
      setIsRefreshingTopics(true);
    } else {
      setIsGeneratingTopics(true);
    }
    setError(null);
    setTopicsBriefing(null);
    setTopicsTakeaway(null);
    setWeeklyBriefing(null);
    setWeeklyMeta(null);
    setWeeklyTopics([]);
    setWeeklyPostsMap({});
    setWeeklyReferences([]);
    setTopics([]);
    setPostsMap({});
    setTopicsReferences([]);
    setOpenTopics({});
    setBriefingData(null);
    setBriefingTakeaway(null);
    setBriefingReferences([]);
    setBriefingStats(null);
    setActiveView('briefing');
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'topics',
      source: null,
      topic: requestedTopicIds.join(',') || null,
    });
    
    try {
      const response: BriefingTopicsResponse = await apiService.generateBriefingWithTopics(targetDate, {
        includeUnreferenced: true,
        refresh,
      });
      if (response.success) {
        setTopicsBriefing(response.briefing || null);
        setTopicsTakeaway(response.one_sentence_takeaway || null);
        setTopics(response.topics || []);
        setPostsMap(response.posts || {});
        setTopicsReferences(response.references || []);
        const first = (response.topics || [])[0];
        const nextOpenTopics: Record<string, boolean> = {};
        if (requestedTopicIds.length) {
          requestedTopicIds.forEach((topicId) => { nextOpenTopics[topicId] = true; });
        } else if (first?.id) {
          nextOpenTopics[first.id] = true;
        }
        setOpenTopics(nextOpenTopics);
        const defaults: Record<string, boolean> = {};
        (response.topics || []).forEach((t) => (t.post_ids || []).forEach((pid) => { defaults[`${t.id}:${pid}`] = true; }));
        setExpandedPosts(defaults);
      } else {
        setError(response.error || 'Failed to generate topic-based briefing');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error occurred');
    } finally {
      setIsGeneratingTopics(false);
      setIsRefreshingTopics(false);
    }
  };

  useEffect(() => {
    if (initializedFromUrlRef.current) {
      return;
    }
    initializedFromUrlRef.current = true;

    const mode = searchParams.get('mode');
    const requestedDate = searchParams.get('date');
    const requestedView = searchParams.get('view');
    const requestedSourceId = searchParams.get('source');
    const requestedTopicIds = (searchParams.get('topic') || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);

    if (requestedDate) {
      setSelectedDate(requestedDate);
    }

    if (requestedView === 'source' && requestedSourceId) {
      handleLoadSourcePosts(requestedSourceId);
      return;
    }
    if (requestedView === 'all-posts' && mode === 'all-posts') {
      navigate('/', { replace: true });
      return;
    }
    if (mode === 'db-posts' && requestedDate) {
      handleLoadDatabasePosts({ dateOverride: requestedDate });
      return;
    }
    if (mode === 'db-topics' && requestedDate) {
      handleLoadTopics({ dateOverride: requestedDate, topicIds: requestedTopicIds });
      return;
    }
    if (mode === 'daily' && requestedDate) {
      handleGenerateBriefing({ dateOverride: requestedDate });
      return;
    }
    if (mode === 'topics' && requestedDate) {
      handleGenerateTopicBriefing(false, {
        dateOverride: requestedDate,
        topicIds: requestedTopicIds,
      });
      return;
    }
    if (mode === 'weekly' && requestedDate) {
      handleGenerateWeeklyBriefing(false, { dateOverride: requestedDate });
      return;
    }
    if (mode === 'weekly-topics' && requestedDate) {
      handleGenerateWeeklyTopicBriefing(false, {
        dateOverride: requestedDate,
        topicIds: requestedTopicIds,
      });
      return;
    }

    // No usable deep link: open today's feed instead of an empty briefing shell.
    // Guard on requestedDate, not mode - every mode branch above needs a date, so
    // e.g. "?mode=daily" with no date would otherwise fall through to nothing.
    // Open on the latest day that has posts, not on today: with ingestion paused
    // "today" is an empty page (lead review #9). /api/status knows the newest post.
    if (!requestedDate) {
      void (async () => {
        const status = await (statusRequestRef.current ?? Promise.resolve(null));
        const latest = status?.corpus?.latest_post_at ? new Date(status.corpus.latest_post_at) : null;
        const date = latest && !Number.isNaN(latest.getTime()) ? localDateISO(latest) : selectedDate;
        setSelectedDate(date);
        handleLoadDatabasePosts({ dateOverride: date });
      })();
    }
  }, [searchParams]);

  const activeTakeaway =
    tab === 'weekly' ? weeklyMeta?.oneSentenceTakeaway : tab === 'topics' ? topicsTakeaway : briefingTakeaway;
  const isDatePosts = activeView === 'all-posts' && searchParams.get('mode') === 'db-posts';
  const isBrowsing = activeView === 'source' || (activeView === 'all-posts' && !isDatePosts);
  const openPostDetail = (postId: string) => {
    navigate(`/posts/${postId}`, { state: { returnTo: currentReturnUrl() } });
  };
  const generating = {
    daily: isGenerating,
    topics: isGeneratingTopics || isRefreshingTopics,
    weekly: isGeneratingWeekly || isGeneratingWeeklyTopics,
  }[tab];

  const selectTab = (next: string) => {
    setTab(next as BriefingTab);
    // Browsing one source is not a briefing; a tab click returns to the briefings.
    if (activeView === 'source' || activeView === 'configure' || (activeView === 'all-posts' && !isDatePosts)) {
      setActiveView('briefing');
    }
  };

  // The page header names the view and, for briefings, the day (or week) it covers.
  const header = (() => {
    if (activeView === 'source') {
      return {
        kicker: selectedSource ? getPlatformLabel(selectedSource.platform) : 'Source',
        title: selectedSourceName,
        meta: sourcePostsMeta.total ? plural(sourcePostsMeta.total, 'post') : selectedSourceHandle,
      };
    }
    if (isBrowsing) {
      return { kicker: 'Every source', title: 'All posts', meta: plural(sourcesData?.total_posts ?? displayedPosts.length, 'post') };
    }
    if (tab === 'weekly' && (weeklyMeta?.weekStart || weeklyMeta?.weekEnd)) {
      return {
        kicker: `Week of ${formatIssueRange(weeklyMeta.weekStart, weeklyMeta.weekEnd)}`,
        title: 'Briefing',
        meta: plural(weeklyMeta.dailyBriefingsUsed || 0, 'daily briefing'),
      };
    }
    const meta =
      tab === 'daily'
        ? briefingStats
          ? plural(briefingStats.postsProcessed, 'post')
          : databasePostsStats && isDatePosts
            ? plural(databasePostsStats.total, 'post')
            : null
        : tab === 'topics'
          ? topicsStats
            ? plural(topicsStats.total, 'stored topic')
            : topics.length
              ? plural(topics.length, 'topic')
              : null
          : null;
    return { kicker: formatIssueLong(selectedDate), title: 'Briefing', meta };
  })();

  const lastFetch = systemStatus?.corpus?.latest_fetch_at;
  const stale = Boolean(systemStatus?.success) && isStale(lastFetch);

  const statusLine = systemStatus ? (
    <div className="mt-4 space-y-2">
      {/* A stopped ingestion is the one thing on this page that must be loud
          (lead review #11): the shared ingestion notice, a solid box and a sentence. */}
      {stale && (
        <IngestionStatusNotice
          state="stopped"
          testId="stale-warning"
          linkToIngestion
          message={
            <>
              Nothing fetched for {formatRelativeTime(lastFetch).replace(/ ago$/, '')}. Briefings stop at posts from{' '}
              {formatIssueShort(systemStatus.corpus?.latest_post_at)}.
            </>
          }
        />
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] tabular-nums text-fg-3" aria-label="System status">
        {systemStatus.success ? (
          <>
            {!stale && <StatusGlyph status="ok" label="system" className="text-fg-2" />}
            {!stale && <MetaSep />}
            <span>newest post {systemStatus.corpus?.latest_post_at ? formatRelativeTime(systemStatus.corpus.latest_post_at) : 'unknown'}</span>
            <MetaSep />
            <span>last fetch {lastFetch ? formatRelativeTime(lastFetch) : 'unknown'}</span>
            <MetaSep />
            <span>{formatCount(systemStatus.corpus?.posts_last_24h ?? 0)} posts / 24h</span>
            <MetaSep />
            <span>
              {formatCount(systemStatus.corpus?.enabled_sources ?? 0)}/{formatCount(systemStatus.corpus?.total_sources ?? 0)} sources on
            </span>
            {Boolean(systemStatus.source_health_summary?.errors) && (
              <Link
                to="/settings/sources?tab=health&status=error"
                className={cn('rounded-sm', FOCUS_RING)}
                title="Open the failing sources in Settings → Sources → Health"
              >
                <StatusGlyph status="failing" label={plural(systemStatus.source_health_summary?.errors ?? 0, 'source error')} />
              </Link>
            )}
            {systemStatus.gemini_configured === false && <StatusGlyph status="unavailable" label="Gemini key missing" />}
          </>
        ) : (
          <StatusGlyph status="failing" label="status unavailable" />
        )}
        <button
          type="button"
          onClick={() => void loadSystemStatus()}
          disabled={isLoadingStatus}
          className={cn('text-link rounded-sm text-fg-2 disabled:opacity-50 coarse:min-h-[2.75rem]', FOCUS_RING)}
        >
          {isLoadingStatus ? 'refreshing…' : 'refresh'}
        </button>
      </div>
    </div>
  ) : null;

  // One primary action per tab (the generator), the stored reads beside it as secondaries.
  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor="briefing-date" className="sr-only">
        Briefing date
      </label>
      <Input
        id="briefing-date"
        type="date"
        value={selectedDate}
        onChange={(e) => setSelectedDate(e.target.value)}
        disabled={isGenerating || isGeneratingTopics}
        className="w-auto tabular-nums"
      />
      {tab === 'daily' && (
        <>
          <Button variant="primary" onClick={() => void handleGenerateBriefing()} disabled={isGenerating} aria-busy={isGenerating || undefined}>
            {isGenerating ? 'Generating…' : 'Generate briefing'}
          </Button>
          <Button variant="secondary" onClick={() => void handleLoadDatabasePosts()} disabled={isLoadingPosts}>
            {isLoadingPosts ? 'Loading…' : 'Posts of the day'}
          </Button>
        </>
      )}
      {tab === 'topics' && (
        <>
          <Button
            variant="primary"
            onClick={() => handleGenerateTopicBriefing(false)}
            disabled={isGeneratingTopics || isRefreshingTopics}
            aria-busy={isGeneratingTopics || undefined}
          >
            {isGeneratingTopics ? 'Generating…' : 'Generate topic briefing'}
          </Button>
          <Button variant="secondary" onClick={() => void handleLoadTopics()} disabled={isLoadingTopics}>
            {isLoadingTopics ? 'Loading…' : 'Stored topics'}
          </Button>
          <Button variant="ghost" onClick={() => handleGenerateTopicBriefing(true)} disabled={isGeneratingTopics || isRefreshingTopics}>
            {isRefreshingTopics ? 'Refreshing…' : 'Refresh'}
          </Button>
        </>
      )}
      {tab === 'weekly' && (
        <>
          <Button
            variant="primary"
            onClick={() => handleGenerateWeeklyBriefing(false)}
            disabled={isGeneratingWeekly}
            aria-busy={isGeneratingWeekly || undefined}
          >
            {isGeneratingWeekly ? 'Generating…' : 'Generate weekly briefing'}
          </Button>
          <Button variant="secondary" onClick={() => handleGenerateWeeklyTopicBriefing(false)} disabled={isGeneratingWeeklyTopics}>
            {isGeneratingWeeklyTopics ? 'Generating…' : 'Weekly topics'}
          </Button>
        </>
      )}
    </div>
  );

  const renderTopicPosts = (topic: Topic, postsLookup: Record<string, Post>, defaultExpanded: boolean) => {
    const ids = topic.post_ids || [];
    const posts = ids.map((pid) => postsLookup[pid]).filter(Boolean) as Post[];
    if (!posts.length) return null;
    return (
      <ol className="border-t border-line">
        {posts.map((post, rIndex) => {
          const key = `${topic.id}:${post.id || ids[rIndex]}`;
          const isExpanded = expandedPosts[key] ?? defaultExpanded;
          return (
            <PostEntry
              key={`${key}_${rIndex}`}
              post={post}
              number={rIndex + 1}
              expanded={isExpanded}
              onToggle={() => setExpandedPosts((prev) => ({ ...prev, [key]: !isExpanded }))}
              onOpen={post.id ? () => openPostDetail(post.id as string) : undefined}
            />
          );
        })}
      </ol>
    );
  };

  const postsList = (
    <div>
      {activeView === 'source' && selectedSourceId && (
        <div className="mb-6 flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => navigate(`/briefing/vertical/source/${selectedSourceId}`)}>
            Source briefing
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void openSourceSettings(selectedSourceId)}
            disabled={loadingSourceEditorId === selectedSourceId}
          >
            {loadingSourceEditorId === selectedSourceId ? 'Opening…' : 'Settings'}
          </Button>
          {selectedSourceHandle ? (
            <span className="min-w-0 max-w-full truncate text-[0.8125rem] text-fg-3" title={selectedSourceHandle}>
              {selectedSourceHandle}
            </span>
          ) : null}
        </div>
      )}

      {isLoadingPosts && displayedPosts.length === 0 ? (
        <LoadingState label="Loading posts" rows={5} />
      ) : displayedPosts.length > 0 ? (
        <>
          <ol className="space-y-2">
            {displayedPosts.map((post, index) => {
              const key = post.id || `post:${index}`;
              const isExpanded = postsExpanded[key] ?? false;
              return (
                <PostRow
                  key={key}
                  post={post}
                  to={post.id ? `/posts/${encodeURIComponent(post.id)}` : undefined}
                  linkState={{ returnTo: currentReturnUrl() }}
                  timeOnly={isDatePosts}
                  expanded={isExpanded}
                  onToggle={() => setPostsExpanded((prev) => ({ ...prev, [key]: !isExpanded }))}
                  copied={Boolean(copied[key])}
                  onCopy={() => void handleCopyPost(post, key)}
                />
              );
            })}
          </ol>
          {activeView === 'source' && sourcePostsMeta.hasMore && (
            <div className="flex justify-center pt-6">
              <Button
                variant="secondary"
                onClick={() => selectedSourceId && handleLoadSourcePosts(selectedSourceId, { append: true })}
                disabled={isLoadingMoreSourcePosts}
                aria-busy={isLoadingMoreSourcePosts || undefined}
              >
                {isLoadingMoreSourcePosts ? 'Loading more…' : `Load ${SOURCE_POSTS_PAGE_SIZE} more`}
              </Button>
            </div>
          )}
        </>
      ) : (
        <EmptyState
          title={isDatePosts ? `No posts on ${formatIssueLong(databasePostsStats?.date || selectedDate)}` : 'No posts found'}
          description={
            isDatePosts
              ? 'Nothing was collected for this day. Pick another date, or read every source in the reader.'
              : 'Nothing stored for this view yet. It fills in after the next ingestion cycle.'
          }
          action={isDatePosts ? { label: 'Open in reader', onClick: openReader } : undefined}
        />
      )}
    </div>
  );

  const takeaway = activeTakeaway ? (
    <p className="max-w-reading text-[1.1875rem] font-medium leading-[1.5] tracking-[-0.01em] text-fg">
      <span className="mb-1 block text-[0.8125rem] font-normal tracking-normal text-fg-3">In one sentence</span>
      {activeTakeaway}
    </p>
  ) : null;

  const generatingNotice = generating ? (
    <Notice
      tone="status"
      title="Writing the briefing…"
      message={`The model is reading the posts for ${formatIssueLong(selectedDate)}. This can take a minute.`}
    />
  ) : null;

  const dailyTab = (
    <div className="space-y-12">
      {takeaway}
      {generatingNotice}
      {briefingData && (
        <IssueSection
          id="issue-daily"
          kicker={`daily · ${briefingStats ? plural(briefingStats.postsProcessed, 'post') : formatIssueShort(selectedDate)}`}
          title="Daily briefing"
        >
          <Reading content={briefingData} />
          <ReferenceList references={briefingReferences} onOpenPost={openPostDetail} />
        </IssueSection>
      )}
      {isDatePosts ? (
        <section aria-labelledby="posts-of-the-day" className={briefingData ? 'border-t border-line pt-8' : undefined}>
          <h2 id="posts-of-the-day" className="mb-4 text-[1.0625rem] font-semibold tracking-[-0.01em] text-fg">
            Posts of the day{' '}
            <span className="font-normal tabular-nums text-fg-3">{formatCount(databasePostsStats?.total ?? displayedPosts.length)}</span>
          </h2>
          {postsList}
        </section>
      ) : (
        !briefingData &&
        !generating && (
          <EmptyState
            title={`No daily briefing for ${formatIssueLong(selectedDate)} yet`}
            description="Generate it for this date, or read the posts of the day first."
          />
        )
      )}
    </div>
  );

  const topicsTab = (
    <div className="space-y-12">
      {takeaway}
      {generatingNotice}
      {topicsBriefing && (
        <IssueSection id="issue-topics" kicker={`topics · ${plural(topics.length, 'topic')}`} title="Topic briefing">
          <Reading content={topicsBriefing} />
          <ReferenceList references={topicsReferences} onOpenPost={openPostDetail} />
          {topics.length > 0 && (
            <ol className="mt-10 border-t border-line">
              {topics.map((topic, tIndex) => (
                <TopicItem
                  key={topic.id || `topic_${tIndex}`}
                  number={tIndex + 1}
                  title={topic.title}
                  count={topic.post_ids?.length}
                  open={Boolean(openTopics[topic.id])}
                  onToggle={() => toggleTopic(topic.id)}
                >
                  {topic.summary ? <Reading content={topic.summary} size="small" /> : null}
                  {renderTopicPosts(topic, postsMap, true)}
                </TopicItem>
              ))}
            </ol>
          )}
        </IssueSection>
      )}

      {databaseTopics.length > 0 && (
        <IssueSection id="issue-stored-topics" kicker={`stored · ${plural(databaseTopics.length, 'topic')}`} title="Stored topics">
          <ol className="border-t border-line">
            {databaseTopics.map((topic, tIndex) => {
              const isOpen = Boolean(openTopics[topic.id]);
              const topicPosts = topic.posts || [];
              const isEditing = editingTopicId === topic.id;
              return (
                <TopicItem
                  key={topic.id || `db_topic_${tIndex}`}
                  number={tIndex + 1}
                  title={topic.title}
                  count={topicPosts.length}
                  outlier={Boolean(topic.is_outlier)}
                  open={isOpen}
                  onToggle={() => toggleTopic(topic.id)}
                  editor={
                    isEditing ? (
                      <div className="flex min-w-0 flex-1 items-center gap-1">
                        <label htmlFor={`topic-title-${topic.id}`} className="sr-only">
                          Topic title
                        </label>
                        <Input
                          id={`topic-title-${topic.id}`}
                          value={editingTopicTitle}
                          onChange={(e) => setEditingTopicTitle(e.target.value)}
                          onBlur={() => !isSavingTitle && handleSaveTopicTitle(topic.id)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              handleSaveTopicTitle(topic.id);
                            } else if (e.key === 'Escape') {
                              handleCancelEditTitle();
                            }
                          }}
                          autoFocus
                          disabled={isSavingTitle}
                          className="flex-1"
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleSaveTopicTitle(topic.id)}
                          disabled={isSavingTitle}
                          aria-label="Save title"
                          title="Save"
                        >
                          {isSavingTitle ? <StatusIcon status="running" /> : <Check aria-hidden="true" />}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={handleCancelEditTitle}
                          disabled={isSavingTitle}
                          aria-label="Cancel editing"
                          title="Cancel"
                        >
                          <X aria-hidden="true" />
                        </Button>
                      </div>
                    ) : undefined
                  }
                  headerExtra={
                    isEditing ? null : (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleEditTopicTitle(topic.id, topic.title || '')}
                        aria-label={`Rename topic ${topic.title || tIndex + 1}`}
                        title="Rename topic"
                        className="-mt-1.5 text-fg-3"
                      >
                        <Pencil aria-hidden="true" />
                      </Button>
                    )
                  }
                >
                  {topic.summary ? <Reading content={topic.summary} size="small" className="text-fg-2" /> : null}
                  {topicPosts.length > 0 ? (
                    <ol className="border-t border-line">
                      {topicPosts.map((post, rIndex) => {
                        const key = `${topic.id}:${post.id || rIndex}`;
                        return (
                          <PostEntry
                            key={key}
                            post={post}
                            number={rIndex + 1}
                            expanded={expandedPosts[key] ?? false}
                            onToggle={() => setExpandedPosts((prev) => ({ ...prev, [key]: !(prev[key] ?? false) }))}
                            onOpen={post.id ? () => openPostDetail(post.id as string) : undefined}
                            copied={Boolean(copied[key])}
                            onCopy={() => void handleCopyPost(post, key)}
                            onOutlier={
                              topic.id && post.id && !topic.is_outlier
                                ? () => void handleMovePostToOutlier(topic.id, post.id as string)
                                : undefined
                            }
                          />
                        );
                      })}
                    </ol>
                  ) : (
                    <p className="text-[0.875rem] text-fg-3">No posts left in this topic.</p>
                  )}
                </TopicItem>
              );
            })}
          </ol>
        </IssueSection>
      )}

      {!topicsBriefing && databaseTopics.length === 0 && !generating && (
        <EmptyState
          title={`No topics for ${formatIssueLong(selectedDate)} yet`}
          description="Generate the topic briefing for this date, or open the topics already stored for it."
        />
      )}
    </div>
  );

  const weeklyTab = (
    <div className="space-y-12">
      {takeaway}
      {generatingNotice}
      {weeklyBriefing ? (
        <IssueSection
          id="issue-weekly"
          kicker={`weekly · ${formatIssueRange(weeklyMeta?.weekStart, weeklyMeta?.weekEnd)}${weeklyMeta?.cached ? ' · cached' : ''}`}
          title={weeklyMeta?.variant === 'topics' ? 'Weekly topic briefing' : 'Weekly briefing'}
        >
          <Reading content={weeklyBriefing} />
          <ReferenceList references={weeklyReferences} onOpenPost={openPostDetail} />
          {weeklyMeta?.variant === 'topics' && weeklyTopics.length > 0 && (
            <div className="mt-10">
              <h3 className="mb-2 text-[1.0625rem] font-semibold tracking-[-0.01em] text-fg">Topic evolution by week</h3>
              <ol className="border-t border-line">
                {weeklyTopics.map((topic, tIndex) => (
                  <TopicItem
                    key={topic.id || `weekly_topic_${tIndex}`}
                    number={tIndex + 1}
                    title={topic.title}
                    count={topic.post_ids?.length}
                    open={Boolean(openTopics[topic.id])}
                    onToggle={() => toggleTopic(topic.id)}
                  >
                    {topic.summary ? <Reading content={topic.summary} size="small" /> : null}
                    {(topic.timeline || []).length > 0 && (
                      <ol className="max-w-reading space-y-3">
                        {(topic.timeline || []).map((entry, entryIndex) => (
                          <li key={`${topic.id}-timeline-${entryIndex}`} className="grid grid-cols-[4.75rem_minmax(0,1fr)] gap-x-3">
                            <span className="whitespace-nowrap pt-0.5 text-[0.8125rem] tabular-nums text-fg-3">{formatIssueShort(entry.date)}</span>
                            <div className="min-w-0">
                              {(entry.source_topics || []).length > 0 && (
                                <p className="break-words text-[0.8125rem] text-fg-3">{(entry.source_topics || []).join(' · ')}</p>
                              )}
                              {entry.summary ? <Reading content={entry.summary} size="small" /> : null}
                            </div>
                          </li>
                        ))}
                      </ol>
                    )}
                    {renderTopicPosts(topic, weeklyPostsMap, false)}
                  </TopicItem>
                ))}
              </ol>
            </div>
          )}
        </IssueSection>
      ) : (
        !generating && (
          <EmptyState
            title="No weekly briefing loaded"
            description={`Generate the briefing for the week that contains ${formatIssueLong(selectedDate)}. It is built from that week's daily briefings.`}
          />
        )
      )}
    </div>
  );

  return (
    <Page width="list">
      <header className="mb-8">
        <p className="text-[0.8125rem] tabular-nums text-fg-3">{header.kicker}</p>
        <h1 className="mt-1 break-words text-[1.75rem] font-[650] leading-[1.15] tracking-[-0.025em] text-fg [overflow-wrap:anywhere]">
          {header.title}
        </h1>
        {header.meta ? <p className="mt-1.5 text-[0.875rem] tabular-nums text-fg-2">{header.meta}</p> : null}
        {statusLine}
      </header>

      <Tabs value={isBrowsing ? '' : tab} onValueChange={selectTab}>
        <div className="flex items-end gap-5 overflow-x-auto border-b border-line">
          <TabsList aria-label="Briefing kinds" className="overflow-visible border-b-0">
            <TabsTrigger value="daily">daily</TabsTrigger>
            <TabsTrigger value="topics">topics</TabsTrigger>
            <TabsTrigger value="weekly">weekly</TabsTrigger>
          </TabsList>
          <Link to="/briefing/vertical" className={tabTriggerClass}>
            vertical
          </Link>
          {/* Stories and the analyst inbox live under "briefings" in the top bar,
              so the section's own tab row names them too. */}
          <Link to="/stories" className={tabTriggerClass}>
            stories
          </Link>
          <Link to="/inbox" className={tabTriggerClass}>
            inbox
          </Link>
        </div>

        {!isBrowsing && <div className="mt-5">{toolbar}</div>}

        {error && (
          <Notice
            tone="error"
            title="That did not work"
            message={error}
            action={{ label: 'Dismiss', onClick: () => setError(null) }}
            className="mt-6"
          />
        )}

        {isBrowsing ? (
          <div className="pt-8">{postsList}</div>
        ) : (
          <>
            <TabsContent value="daily" className="pt-10">
              {dailyTab}
            </TabsContent>
            <TabsContent value="topics" className="pt-10">
              {topicsTab}
            </TabsContent>
            <TabsContent value="weekly" className="pt-10">
              {weeklyTab}
            </TabsContent>
          </>
        )}
      </Tabs>

      {editingSource && (
        <SourceSettingsEditor
          source={editingSource}
          onClose={() => setEditingSource(null)}
          onSave={() => {
            void loadSourcesWithCounts();
          }}
        />
      )}
    </Page>
  );
}
