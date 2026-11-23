import { Fragment, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueries, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { ArrowUpRight, Check, Loader2 } from 'lucide-react';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import PostActions from '../components/post/PostActions';
import PostNav from '../components/post/PostNav';
import ReadingSettingsButton from '../components/post/ReadingSettingsButton';
import { PostFigure, PostImageList } from '../components/post/PostImages';
import { postMedia } from '../components/post/media';
import { Button, Skeleton } from '../components/ui';
import { EmptyState, FOCUS_RING, Notice } from '../components/states';
import { useDevFixtureApi } from '../hooks/useDevFixtureApi';
import DevDataSwitch from '../components/ops/DevDataSwitch';
import ShortcutHelp from '../components/reader/ShortcutHelp';
import { StatusIcon } from '../components/ui/StatusGlyph';
import { postQueryOptions, usePost, usePrefetchPost } from '../hooks/usePost';
import { usePostNeighbors } from '../hooks/usePostNeighbors';
import { findFeedItems, patchFeeds, useReaderMutations } from '../hooks/useReaderMutations';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { LONG_POST_CHARS, useReadingPosition } from '../hooks/useReadingPosition';
import { useFlowPreference, useShortcutPreference } from '../hooks/useShortcutPreference';
import { useReadingSettings } from '../hooks/useReadingSettings';
import { READING_TEXT_CLASS, readingStyle } from '../lib/readingSettings';
import {
  decodeFeedContext, postHref, scopePath, sourceReadPath, type ContextEntry, type FeedContext,
} from '../lib/feedContext';
import TextLink, { ExternalLink } from '../components/ui/TextLink';
import { rememberSelection } from '../lib/readerSelection';
import { classicTitle } from '../lib/classics';
import {
  coveredBy, LINE_NAME, LINE_TITLE, originHref, originLabel, repostedBy, storyTree,
} from '../lib/story';
import { postSourceName, sourceLabel } from '../lib/sourceLabel';
import { bylineName, carried, carriedLine, pageSite } from '../lib/byline';
import { errorMessage } from '../lib/apiError';
import { writeToClipboard } from '../lib/clipboard';
import { countsLabel, middleTruncate, plural } from '../lib/format';
import { feedDateLabel, feedFullTime, formatLocalDateTime, postBylineTime } from '../lib/dates';
import { pageState, updateLine } from '../lib/pageUpdate';
import { formatClock } from '../lib/duration';
import { publicationOf } from '../lib/addresses';
import type {
  Api,
  FeedItem,
  FeedStory,
  Post,
  PostDetailResponse,
  ReaderState,
  RedditComment,
  StoryPost,
  YouTubeWatchProgress,
} from '../services/api';
import { proxiedImage } from '../lib/mediaProxy';
import { htmlText } from '../lib/inertHtml';
import { useMarkxOn } from '../hooks/useMarkxOn';

const MarkXPanel = lazy(() => import('../components/markx/MarkXPanel'));
const MarkXRelated = lazy(() => import('../components/markx/MarkXRelated'));
const MarkXDiscussion = lazy(() => import('../components/markx/MarkXDiscussion'));   // 0280
const PostTeach = lazy(() => import('../components/post/PostTeach'));   // v10.42: More / Less like this
const Connected = lazy(() => import('../components/post/Connected'));
const MarkXTranslation = lazy(() => import('../components/markx/MarkXTranslation'));

/**
 * The post reading view (/posts/:id): one centred column (source and date, title, images, text), the post's
 * actions in the sticky band. Read continuously, the feed's next posts follow below.
 */

const POST_FIXTURE_NAMES = ['worst', 'empty', 'missing', 'slow'] as const;
const loadPostFixtures = import.meta.env.DEV ? () => import('./PostDetailPage.fixtures') : null;

/** The fixture API for `?data=<name>`: the post comes from the fixtures, writes are no-ops. */
function postFixtureApi(name: string): Partial<Api> | null {
  if (!loadPostFixtures || !(POST_FIXTURE_NAMES as readonly string[]).includes(name)) return null;
  const load = loadPostFixtures;
  const ok = async () => ({ success: true });
  return {
    getPostDetail: async () => {
      if (name === 'slow') await new Promise((resolve) => setTimeout(resolve, 2500));
      return (await load()).postFixtureDetail(name) ?? { success: false, error: 'Post not found' };
    },
    recordPostOpen: ok,
    recordPostReadingSession: ok,
    togglePostFavorite: ok,
  };
}

/** A story line on the post page and its tree indent: two levels at most, one on a phone (a deepest line names
 *  its parent instead, "↳ Mat Duggan"). Kept here so the reader's initial JS does not grow. */
const STORY_LINE = 'flex min-w-0 items-baseline gap-x-1.5 max-sm:flex-wrap';  // a phone: the title on its own line
const INDENT = ['', 'pl-2 sm:pl-4', 'pl-2 sm:pl-8'];
const Under = ({ name }: { name?: string }) =>
  name ? <span className="max-w-[30%] shrink-0 truncate sm:hidden">↳ {sourceLabel(name)}</span> : null;

/**
 * "Covered by 4" at the end of a post: its story's tree as the feed's folded row lists it (the origin first,
 * children indented, this post in its place as "this post"). A thread lists only what wasn't read above it.
 * Its own block, so the reader's initial JS does not grow.
 */
function CoveredBy({ story, post, postId }: { story: FeedStory; post: Post; postId: string }) {
  const now = new Date();
  const readAbove = new Set(story.thread ? threadAfter(story, postId).map((reply) => reply.id) : []);
  const lines = storyTree({ ...story, posts: story.posts.filter((p) => !readAbove.has(p.id)) }, postId,
    post.published_at ?? post.fetched_at, postSourceName(post));
  if (!lines.length && !story.roundups?.length) return null;
  return (
    <section data-covered-by aria-label="Covered by" className="mt-8 text-[0.8125rem] leading-5 text-fg-3">
      <p>
        {story.thread || story.voices < 2 ? coveredBy(story, post.source_id) : `Covered by ${story.voices}`}
        {story.first === postId ? ' · this post was first' : null}
      </p>
      <ul className="mt-1 flex flex-col gap-1 border-l border-line pl-3">
        {lines.map((line, i) => {
          const indent = `${STORY_LINE} ${INDENT[line.depth] ?? ''}`;
          if (line.kind === 'reposts') return <li key={i} data-depth={line.depth} className={indent}>{repostedBy(line.by)}</li>;
          if (line.kind === 'page') {
            const { site, title, linkedBy } = originLabel(line.origin);
            return (
              <li key="origin" data-depth={line.depth} className={indent}>
                <span className={LINE_NAME} title={site}>{middleTruncate(site, 32)}</span>
                <span aria-hidden="true" className="shrink-0 max-sm:hidden">·</span>
                <Link
                  to={originHref(line.origin)}
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
          if (line.kind === 'self') {
            return (
              <li key="self" data-depth={line.depth} aria-current="true" className={indent}>
                <Under name={line.under} />
                <span className={LINE_NAME}>{middleTruncate(postSourceName(post), 32)}</span>
                <span aria-hidden="true" className="shrink-0 max-sm:hidden">·</span>
                <span dir="auto" className={`${LINE_TITLE} text-fg-2`}>{post.title?.trim() || 'Untitled post'}</span>
                <span className="shrink-0">· this post</span>
              </li>
            );
          }
          const other = line.post;
          return (
            <li key={other.id} data-depth={line.depth} className={indent}>
              <Under name={line.under} />
              {!other.read_at ? <StatusIcon status="unread" className="shrink-0 self-center text-fg" /> : null}
              <span className={LINE_NAME} title={sourceLabel(other.source_display_name)}>
                {middleTruncate(bylineName(other), 32)}
              </span>
              <span aria-hidden="true" className="shrink-0 max-sm:hidden">·</span>
              <Link
                to={postHref(other.id, null)}
                dir="auto"
                className={`${LINE_TITLE} rounded-sm underline-offset-4 hover:underline hover:decoration-fg-3 ${other.read_at ? 'text-fg-2' : 'font-medium text-fg'} ${FOCUS_RING}`}
              >
                {other.title?.trim() || 'Untitled post'}
              </Link>
              {carried(other) ? <span className="max-w-[30%] shrink-0 truncate">· ↻ {sourceLabel(other.source_display_name)}</span> : other.role === 'share' ? <span className="shrink-0">· share</span> : null}
              {other.id === story.first ? <span className="shrink-0">· first</span> : null}
              <time dateTime={other.sort_at} title={feedFullTime(other.sort_at)} className="ml-auto shrink-0 pl-2 tabular-nums">
                {feedDateLabel(other.sort_at, now)}
              </time>
              {!other.read_at ? <span className="sr-only">Unread</span> : null}
            </li>
          );
        })}
      </ul>
      {story.roundups?.length ? (
        // The roundups that mention the story and are not in it, each source once.
        <p className="mt-1 [overflow-wrap:anywhere]">
          Also in roundups:{' '}
          {story.roundups.map((roundup, i) => (
            <Fragment key={roundup.id}>
              {i ? ', ' : null}
              <TextLink to={postHref(roundup.id, null)} title={roundup.title} muted>
                {sourceLabel(roundup.source_display_name)}
              </TextLink>
            </Fragment>
          ))}
        </p>
      ) : null}
    </section>
  );
}

function threadAfter(story: FeedStory, postId: string): StoryPost[] {
  const next: StoryPost[] = [];
  for (let at = postId, reply; (reply = story.posts.find((p) => p.parent_id === at && p.parent_reason === 'thread')); at = reply.id) {
    next.push(reply);
  }
  return next;
}

/**
 * A thread read in order: the replies after this post, each read as the post's body is (links, image cache);
 * a reply quoting a tweet its story holds is no card ("↩ quotes the post above").
 */
function ThreadPosts({ story, postId }: { story: FeedStory; postId: string }) {
  return (
    <section data-thread aria-label="Thread" className="mt-6">
      {threadAfter(story, postId).map((reply) => (
        <div key={reply.id} className="border-t border-line py-4">
          {reply.html ? (
            <MarkdownRenderer content={reply.html} imageSrc={(src) => proxiedImage(reply.id, src)} internalLinks={reply.internal_links} />
          ) : reply.quotes_above ? null : (
            <p dir="auto" className="whitespace-pre-line [overflow-wrap:anywhere]">{reply.text}</p>
          )}
          {reply.quotes_above ? <span className="text-[0.8125rem] text-fg-3">↩ quotes the post above · </span> : null}
          <Link to={postHref(reply.id, null)} className={`text-[0.8125rem] text-fg-3 ${FOCUS_RING}`}>
            {feedDateLabel(reply.sort_at)}
          </Link>
        </div>
      ))}
    </section>
  );
}

/** A post read here reads as read in every cached post page's "covered by". */
function patchStoryRead(queryClient: QueryClient, postId: string, readAt: string | null) {
  queryClient.setQueriesData<PostDetailResponse>({ queryKey: ['post'] }, (data) => {
    const story = data?.post?.story;
    if (!data?.post || !story?.posts.some((p) => p.id === postId && Boolean(p.read_at) !== Boolean(readAt))) return data;
    const posts = story.posts.map((p) => (p.id === postId ? { ...p, read_at: readAt } : p));
    return { ...data, post: { ...data.post, story: { ...story, posts } } };
  });
}

function postPlainText(post: Post): string {
  const text = typeof post.content === 'string' ? post.content.trim() : '';
  if (text) return text;
  const html = typeof post.content_html === 'string' ? post.content_html : '';
  return htmlText(html).trim();  // inert: the feed's HTML never runs here
}

function SectionHeading({ title, meta, actions }: { title: string; meta?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-x-4 gap-y-2 border-t border-line pt-6">
      <div className="min-w-0">
        <h2 className="text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">{title}</h2>
        {meta ? <p className="mt-0.5 text-[0.8125rem] tabular-nums text-fg-3">{meta}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}

function Busy({ when, children }: { when: boolean; children: ReactNode }) {
  return when ? <Loader2 aria-hidden="true" className="motion-safe:animate-spin" /> : <>{children}</>;
}

type YouTubeMetadata = {
  kind?: string;
  description?: string;
  channel_id?: string | null;
  channel_title?: string | null;
  duration_seconds?: number | null;
  view_count?: number | null;
  like_count?: number | null;
  chapters?: Array<{
    title?: string;
    start_seconds?: number;
    end_seconds?: number;
  }>;
  thumbnails?: string[];
  transcript_source?: string | null;
  tags?: string[];
};

type YouTubeTranscriptBlock = {
  id: string;
  title: string;
  startSeconds: number;
  text: string;
};

/**
 * A transcript's text. `preserveLines` keeps the source's line breaks (posts);
 * caption transcripts break every few words, so they reflow.
 */
function TranscriptText({ content, preserveLines = true }: { content: string; preserveLines?: boolean }) {
  return <div className={preserveLines ? 'whitespace-pre-wrap' : 'whitespace-normal'}>{content}</div>;
}

function extractYouTubeVideoId(post?: Post | null): string | null {
  const candidate = String(post?.external_id || '').trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(candidate)) {
    return candidate;
  }

  const url = String(post?.url || '').trim();
  if (!url) {
    return null;
  }

  try {
    const parsed = new URL(url);
    if (parsed.hostname === 'youtu.be') {
      return parsed.pathname.replace(/^\/+/, '') || null;
    }
    if (parsed.hostname.includes('youtube.com')) {
      if (parsed.pathname === '/watch') {
        return parsed.searchParams.get('v');
      }
      if (parsed.pathname.startsWith('/shorts/')) {
        return parsed.pathname.split('/')[2] || null;
      }
      if (parsed.pathname.startsWith('/embed/')) {
        return parsed.pathname.split('/')[2] || null;
      }
    }
  } catch {
    return null;
  }

  return null;
}

function formatCompactCount(value?: number | null) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null;
  }
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(numeric);
}

function buildYouTubeTimestampUrl(url: string | undefined, seconds: number) {
  if (!url) {
    return '#';
  }

  try {
    const parsed = new URL(url);
    parsed.searchParams.set('t', `${Math.max(0, Math.floor(seconds))}s`);
    return parsed.toString();
  } catch {
    return url;
  }
}

function buildYouTubeTranscriptBlocks(
  transcript: string,
  durationSeconds?: number | null,
  chapters?: Array<{ title?: string; start_seconds?: number; end_seconds?: number }>,
): YouTubeTranscriptBlock[] {
  const cleaned = String(transcript || '').trim();
  if (!cleaned) {
    return [];
  }

  let chunks = cleaned
    .split(/\n\s*\n+/)
    .map((entry) => entry.trim())
    .filter(Boolean);

  if (chunks.length <= 1) {
    const sentences = cleaned
      .split(/(?<=[.!?])\s+/)
      .map((entry) => entry.trim())
      .filter(Boolean);
    chunks = [];
    let current = '';
    sentences.forEach((sentence) => {
      if (!current) {
        current = sentence;
        return;
      }
      if ((current + ' ' + sentence).length > 750) {
        chunks.push(current);
        current = sentence;
      } else {
        current += ` ${sentence}`;
      }
    });
    if (current) {
      chunks.push(current);
    }
  }

  const totalChars = Math.max(1, chunks.reduce((sum, chunk) => sum + chunk.length, 0));
  const duration = Math.max(0, Math.round(Number(durationSeconds || 0)));
  let consumedChars = 0;

  return chunks.map((chunk, index) => {
    const currentOffset = consumedChars;
    const ratio = duration > 0 ? currentOffset / totalChars : 0;
    const startSeconds = duration > 0 ? Math.round(ratio * duration) : 0;
    consumedChars += chunk.length;

    const chapter = (chapters || []).find((entry, chapterIndex, source) => {
      const start = Number(entry.start_seconds || 0);
      const nextStart = Number(source[chapterIndex + 1]?.start_seconds ?? Number.POSITIVE_INFINITY);
      const end = Number(entry.end_seconds || nextStart);
      return startSeconds >= start && startSeconds < end;
    });

    return {
      id: `yt-block-${index}`,
      title: chapter?.title || `Transcript ${index + 1}`,
      startSeconds,
      text: chunk,
    };
  });
}

function VideoPlayer({ videoId, title, className = '' }: { videoId: string; title: string; className?: string }) {
  return (
    <div className={`aspect-video w-full overflow-hidden rounded-md border border-line bg-black ${className}`}>
      <iframe
        src={`https://www.youtube-nocookie.com/embed/${videoId}`}
        title={title}
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        allowFullScreen
        loading="lazy"
        className="h-full w-full"
      />
    </div>
  );
}

const PAGE_CLASS = 'mx-auto w-full max-w-6xl px-4 pb-24 pt-6 sm:px-6 sm:pt-8';
/** One column of ~70ch at the body size, centred; the reading width may change it. */
const GRID_CLASS = 'grid grid-cols-[minmax(0,var(--reading-column,42rem))] justify-center';

function ReadingFrame({ children }: { children: ReactNode }) {
  const [settings] = useReadingSettings();
  return <div data-reading-frame className="contents" style={readingStyle(settings)}>{children}</div>;
}

function NavBand({ children }: { children?: ReactNode }) {
  return (
    <div data-nav-band className="reader-material reader-edge sticky top-topbar z-30 px-4 py-1 sm:px-6">
      <div className={GRID_CLASS}>
        <div className="min-h-[2rem] min-w-0">{children}</div>
      </div>
    </div>
  );
}

/** The loading frame: the same container, grid and column as the loaded page, so no width or padding jump. */
function PostSkeleton() {
  return (
    <>
      <NavBand />
      <div className={PAGE_CLASS}>
        <div className={GRID_CLASS}>
          <div className="min-w-0" role="status" aria-busy="true" aria-live="polite">
            <span className="sr-only">Loading post</span>
            <div aria-hidden="true">
              <div className="mb-8">
                <div className="flex min-h-[2.25rem] items-start">
                  <Skeleton className="mt-1 h-3 w-48" />
                </div>
                <Skeleton className="mt-2 h-7 w-11/12" />
                <Skeleton className="mt-2 h-7 w-2/3" />
              </div>
              <div className="max-w-[var(--reading-measure,68ch)] space-y-3">
                {['w-full', 'w-11/12', 'w-full', 'w-4/5', 'w-full', 'w-3/5'].map((width, index) => (
                  <Skeleton key={index} className={`h-3.5 ${width}`} />
                ))}
              </div>
            </div>
          </div>
        </div>
        <DevDataSwitch options={POST_FIXTURE_NAMES} />
      </div>
    </>
  );
}

/**
 * /posts/:id. Loads through `usePost` (`['post', id]`), so a prefetched post opens from cache. Each post gets
 * its own `PostArticle` (keyed by id), so nothing of another post carries over.
 */
export default function PostDetailPage() {
  const navigate = useNavigate();
  const { postId } = useParams();
  const { api, fixture } = useDevFixtureApi(postFixtureApi);
  const query = usePost(postId, { api, fixture });

  if (postId && query.data?.post) return <ReadingFrame><PostReader key={fixture ?? ''} postId={postId} api={api} fixture={fixture} /></ReadingFrame>;
  if (postId && query.isPending) return <ReadingFrame><PostSkeleton /></ReadingFrame>;
  return (
    <>
      <NavBand />
      <div className={PAGE_CLASS}>
        <div className={GRID_CLASS}>
          <div className="min-w-0">
            <EmptyState
              title="Post not found"
              description={postId ? errorMessage(query.error) : 'Missing post id'}
              action={{ label: 'Back to the feed', onClick: () => navigate('/') }}
            />
          </div>
        </div>
        <DevDataSwitch options={POST_FIXTURE_NAMES} />
      </div>
    </>
  );
}

const FAR = '100000px';

function postSortAt(queryClient: QueryClient, postId: string, post: Post): string | null {
  return findFeedItems(queryClient, [postId]).get(postId)?.sort_at ?? post.published_at ?? post.fetched_at ?? null;
}

interface Stream {
  entries: ContextEntry[];
  current: number;
  heights: Record<string, number>;
}

const streamAt = (id: string, ctx: FeedContext | null): Stream => ({ entries: [{ id, pageCursor: ctx?.cursor ?? null }], current: 0, heights: {} });

/**
 * The page around the posts: sticky navigation, keys, help and Back. Continuous (with a feed context), the
 * feed's next post follows below the current one's end. The post crossing the midline is current; the URL
 * follows it (replaced, so Back still leaves for the list). At most three posts are mounted (previous,
 * current, next); one further away keeps its height so the scroll does not jump.
 */
function PostReader({ postId, api, fixture }: { postId: string; api: Api; fixture: string | null }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [flow] = useFlowPreference();
  const [shortcutsOn] = useShortcutPreference();
  const [helpOpen, setHelpOpen] = useState(false);
  const prefetch = usePrefetchPost();
  const slots = useRef(new Map<string, HTMLElement>());
  const endRef = useRef<HTMLDivElement>(null);

  const ctx: FeedContext | null = useMemo(() => decodeFeedContext(searchParams.get('ctx')), [searchParams]);
  const continuous = flow === 'continuous' && ctx !== null && typeof IntersectionObserver !== 'undefined';

  const [stream, setStream] = useState(() => streamAt(postId, ctx));
  // A post reached from outside the stream starts a new stream; the URL catching up with the stream does not.
  if (!stream.entries.some((entry) => entry.id === postId)) setStream(streamAt(postId, ctx));
  const { entries, current } = stream;
  const currentEntry = entries[current];
  const shown = continuous ? entries : [currentEntry];
  const mounted = continuous ? entries.slice(Math.max(0, current - 1), current + 2) : shown;
  const details = useQueries({ queries: mounted.map((entry) => postQueryOptions(api, entry.id, fixture)) });
  const currentPost = details[mounted.indexOf(currentEntry)]?.data?.post ?? null;
  const neighbors = usePostNeighbors(api, ctx, {
    id: currentEntry.id,
    sortAt: currentPost ? postSortAt(queryClient, currentEntry.id, currentPost) : null,
  });

  const head = entries[0].id;
  const firstHead = useRef(head);
  useEffect(() => {
    if (head === firstHead.current) return;
    firstHead.current = head;
    window.scrollTo({ top: 0 });
  }, [head]);

  useEffect(() => {
    if (fixture) return;
    if (neighbors.next) prefetch(neighbors.next.id);
    if (neighbors.prev) prefetch(neighbors.prev.id);
  }, [fixture, neighbors.next, neighbors.prev, prefetch]);

  const openNeighbor = (entry: ContextEntry | null) => {
    if (!entry || !ctx) return;
    navigate(postHref(entry.id, { ...ctx, cursor: entry.pageCursor }), { replace: true, state: location.state });
  };

  const makeCurrent = (index: number) => {
    const entry = entries[index];
    if (!entry || index === current) return;
    const heights = { ...stream.heights };
    for (const [id, node] of slots.current) heights[id] = node.offsetHeight;
    setStream((state) => ({ ...state, current: index, heights }));
    openNeighbor(entry);
  };
  const makeCurrentRef = useRef(makeCurrent);
  makeCurrentRef.current = makeCurrent;

  useEffect(() => {
    if (!continuous) return undefined;
    const observer = new IntersectionObserver((seen) => {
      const crossing = seen.find((entry) => entry.isIntersecting)?.target as HTMLElement | undefined;
      const index = entries.findIndex((entry) => entry.id === crossing?.dataset.postSlot);
      if (index >= 0) makeCurrentRef.current(index);
    }, { rootMargin: '-50% 0px -50% 0px' });
    for (const node of slots.current.values()) observer.observe(node);
    return () => observer.disconnect();
  }, [continuous, entries]);

  const atEnd = current === entries.length - 1;
  const nextId = continuous && atEnd ? neighbors.next?.id ?? null : null;
  const nextCursor = neighbors.next?.pageCursor ?? null;
  useEffect(() => {
    const node = endRef.current;
    if (!nextId || !node) return undefined;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry?.isIntersecting) return;
      observer.disconnect();
      setStream((state) => (state.entries.some((item) => item.id === nextId)
        ? state
        : { ...state, entries: [...state.entries, { id: nextId, pageCursor: nextCursor }] }));
    }, { rootMargin: `${FAR} 0px 50% 0px` });
    observer.observe(node);
    return () => observer.disconnect();
  }, [nextId, nextCursor]);
  const caughtUp = continuous && atEnd && currentPost !== null && !neighbors.next && !neighbors.loading;

  const feedPath = ctx
    ? `${scopePath(ctx.scope)}${ctx.filter === 'unread' ? '' : `?filter=${ctx.filter}`}`
    : '/';
  const returnTo = (location.state as { returnTo?: string } | null)?.returnTo;
  // `default` is the key of the first entry: opened directly or reloaded, there is no in-app Back.
  const hasHistory = location.key !== 'default';
  const goBack = () => {
    if (returnTo) navigate(returnTo);
    else if (hasHistory) navigate(-1);
    else navigate(feedPath);
  };

  const jump = (index: number) => {
    slots.current.get(entries[index].id)?.scrollIntoView?.({ block: 'start' });
    makeCurrent(index);
  };
  const hasPrevious = continuous && current > 0;
  const hasNext = continuous && current < entries.length - 1;
  const goPrevious = hasPrevious ? () => jump(current - 1) : neighbors.prev ? () => openNeighbor(neighbors.prev) : null;
  const goNext = hasNext ? () => jump(current + 1) : neighbors.next ? () => openNeighbor(neighbors.next) : null;

  useKeyboardShortcuts({
    j: ctx ? () => goNext?.() : undefined,
    k: ctx ? () => goPrevious?.() : undefined,
    u: goBack,
    Escape: goBack,
    '?': () => setHelpOpen(true),
  }, { enabled: !helpOpen, singleKeys: shortcutsOn });

  const backLabel = hasHistory || returnTo ? 'Back' : 'Back to feed';
  const step = ctx ? { onPrevious: goPrevious, onNext: goNext } : undefined;
  const endNav = <PostNav label="After the post" size="lg" backLabel={backLabel} onBack={goBack} step={step} />;
  // The current post renders its own actions into this slot of the sticky band (a portal).
  const [actionsSlot, setActionsSlot] = useState<HTMLDivElement | null>(null);

  return (
    <>
      <NavBand>
        <div className="flex min-w-0 items-center justify-between gap-2">
          <PostNav label="Post navigation" size="sm" backLabel={backLabel} onBack={goBack} step={step} />
          <div className="flex shrink-0 items-center">
            <div ref={setActionsSlot} data-bar-actions className="flex items-center" />
            <ReadingSettingsButton />
          </div>
        </div>
      </NavBand>
      <div className={PAGE_CLASS}>
        <div className={GRID_CLASS}>
          <div className="min-w-0">
            {shown.map((entry, index) => {
              const slot = mounted.indexOf(entry);
              const query = slot >= 0 ? details[slot] : null;
              return (
                <div
                  key={entry.id}
                  ref={(node) => {
                    if (node) slots.current.set(entry.id, node);
                    else slots.current.delete(entry.id);
                  }}
                  data-post-slot={entry.id}
                  className="scroll-mt-[calc(var(--topbar-h)+3rem)]"
                  style={query ? undefined : { height: stream.heights[entry.id] ?? 0 }}
                >
                  {!query ? null : query.data?.post ? (
                    <PostArticle
                      postId={entry.id}
                      detail={query.data}
                      api={api}
                      fixture={fixture}
                      current={entry === currentEntry}
                      readOn={continuous ? 'end' : 'mount'}
                      divider={index > 0}
                      offerResume={index === 0}
                      keysEnabled={entry === currentEntry && !helpOpen}
                      actionsSlot={actionsSlot}
                    />
                  ) : query.isError ? (
                    <p className="mt-16 text-[0.875rem] text-fg-3">{errorMessage(query.error)}</p>
                  ) : (
                    <Skeleton className="mt-16 h-64 w-full" />
                  )}
                </div>
              );
            })}
            {continuous ? (
              // Room below the last post, so it can always reach the midline and become current.
              <div ref={endRef} data-stream-end className="min-h-[50vh]">
                {caughtUp ? (
                  <div className="mt-14 border-t border-line pt-6">
                    <p className="mb-3 text-[0.9375rem] font-medium text-fg">{ctx?.filter === 'unread' ? 'You’re all caught up' : 'You’ve reached the end'}</p>
                    {endNav}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="mt-14 border-t border-line pt-4">{endNav}</div>
            )}
          </div>
        </div>
        <ShortcutHelp open={helpOpen} onOpenChange={setHelpOpen} feedContext={Boolean(ctx)} />
        <DevDataSwitch options={POST_FIXTURE_NAMES} />
      </div>
    </>
  );
}

function initialComments(post: Post) {
  const metadata = post.metadata && typeof post.metadata === 'object' && !Array.isArray(post.metadata)
    ? post.metadata as Record<string, unknown>
    : null;
  const discussion = metadata?.reddit_discussion && typeof metadata.reddit_discussion === 'object' && !Array.isArray(metadata.reddit_discussion)
    ? metadata.reddit_discussion as Record<string, unknown>
    : null;
  return {
    comments: Array.isArray(discussion?.comments) ? discussion.comments as RedditComment[] : [],
    fetchedAt: typeof discussion?.fetched_at === 'string' ? discussion.fetched_at : null,
  };
}

interface PostArticleProps {
  postId: string;
  detail: PostDetailResponse;
  api: Api;
  fixture: string | null;
  current: boolean;
  /** When the open is recorded (and the post marked read): on mount, or once its end passes the top half of the screen. */
  readOn: 'mount' | 'end';
  divider: boolean;
  offerResume: boolean;
  keysEnabled: boolean;
  actionsSlot: HTMLElement | null;
}

/** "Read on example.com", or "Read “<title>” on example.com" when the page's title says more; "Open the picture"
 *  and "Watch on <site>" for a link post's picture and video. */
function readOnLabel(link: { url: string; title: string | null; kind?: string }, shown: string): string {
  const site = publicationOf(link.url) || link.url;
  if (link.kind === 'picture') return 'Open the picture';
  if (link.kind === 'video') return `Watch on ${site}`;
  return link.title && link.title !== shown ? `Read “${link.title}” on ${site}` : `Read on ${site}`;
}

/** One post and its own state; keyed by the post id, so nothing of another post carries over. */
function PostArticle({ postId, detail, api, fixture, current, readOn, divider, offerResume, keysEnabled, actionsSlot }: PostArticleProps) {
  const queryClient = useQueryClient();
  const initial = useMemo(() => initialComments(detail.post as Post), [detail.post]);
  const post = detail.post as Post;
  const markxOn = useMarkxOn();
  const [readerState, setReaderState] = useState<ReaderState | null>(detail.reader_state || null);
  const [youtubeProgress, setYouTubeProgress] = useState<YouTubeWatchProgress | null>(null);
  const [youtubeProgressDraft, setYouTubeProgressDraft] = useState(0);
  const { comments, fetchedAt: commentsFetchedAt } = initial;
  const [loadingYouTubeProgress, setLoadingYouTubeProgress] = useState(false);
  const [savingYouTubeProgress, setSavingYouTubeProgress] = useState(false);
  const [togglingFavorite, setTogglingFavorite] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied'>('idle');
  const [announcement, setAnnouncement] = useState('');
  const openRecordedRef = useRef(false);
  const endRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLElement>(null);
  /** Reaching the end: a post in Later leaves it (set each render, below). */
  const finishRef = useRef(() => {});
  const mutations = useReaderMutations({ dryRun: Boolean(fixture) });
  const [shortcutsOn] = useShortcutPreference();

  const loadYouTubeWatchProgress = async (videoId: string) => {
    setLoadingYouTubeProgress(true);
    const response = await api.getYouTubeWatchProgress(videoId);
    if (response.success && response.progress) {
      setYouTubeProgress(response.progress);
      setYouTubeProgressDraft(Number(response.progress.progress_seconds || 0));
    } else {
      setYouTubeProgress(null);
      setYouTubeProgressDraft(0);
    }
    setLoadingYouTubeProgress(false);
  };

  const saveCurrentYouTubeProgress = async (progressSeconds: number, completed = false) => {
    if (!post || post.platform !== 'youtube') return;
    const videoId = extractYouTubeVideoId(post);
    if (!videoId) return;
    setSavingYouTubeProgress(true);
    setError(null);
    const response = await api.saveYouTubeWatchProgress(videoId, {
      videoUrl: post.url || `https://www.youtube.com/watch?v=${videoId}`,
      title: post.title || videoId,
      durationSeconds: Number((post.metadata as Record<string, unknown> | null)?.duration_seconds || 0) || null,
      progressSeconds,
      sourceId: post.source_id || null,
      completed,
    });
    if (!response.success) {
      setError(response.error || 'Failed to save YouTube watch progress');
      setSavingYouTubeProgress(false);
      return;
    }
    setYouTubeProgress(response.progress || null);
    setYouTubeProgressDraft(Number(response.progress?.progress_seconds || progressSeconds || 0));
    setSavingYouTubeProgress(false);
  };

  useEffect(() => {
    const videoId = extractYouTubeVideoId(detail.post);
    if (detail.post?.platform !== 'youtube' || !videoId) return;
    void loadYouTubeWatchProgress(videoId);
    // Once per post: PostArticle is keyed by the post id.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const meta = useMemo(
    () => ({ title: detail.post?.title, source: detail.post?.source, platform: detail.post?.platform }),
    [detail.post],
  );

  const recordOpen = useCallback(() => {
    if (openRecordedRef.current) return;
    openRecordedRef.current = true;
    void api.recordPostOpen(postId, meta).then((response) => {
      if (!response.success) return;
      // The server marks an opened post read: so do the cached feed and counts.
      mutations.noteOpened(postId);
      const recordedAt = response.event?.created_at || new Date().toISOString();
      patchStoryRead(queryClient, postId, recordedAt);
      setReaderState((state) => ({
        ...state,
        post_id: postId,
        is_favorited: state?.is_favorited ?? false,
        open_count: (state?.open_count || 0) + 1,
        first_opened_at: state?.first_opened_at || recordedAt,
        last_opened_at: recordedAt,
        total_read_seconds: state?.total_read_seconds ?? 0,
        read_at: state?.read_at || recordedAt,
      }));
    });
  }, [api, meta, mutations, postId, queryClient]);

  useEffect(() => {
    if (readOn === 'mount') recordOpen();
  }, [readOn, recordOpen]);

  // Finished once its end passes the top half of the screen: then it is read (in the stream) and leaves Later. The
  // root reaches far above the viewport, so a fast scroll or a jump past the end still counts.
  useEffect(() => {
    const node = endRef.current;
    if (!node || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry?.isIntersecting) return;
      observer.disconnect();
      if (readOn === 'end') recordOpen();
      finishRef.current();
    }, { rootMargin: `${FAR} 0px -50% 0px` });
    observer.observe(node);
    return () => observer.disconnect();
  }, [readOn, recordOpen]);

  // Reading time runs while the post is current and the tab visible. Under a second (StrictMode's mount check,
  // a j held down) is not reading and is not recorded.
  useEffect(() => {
    if (!current) return undefined;
    rememberSelection(postId);
    let total = 0;
    let since: number | null = document.hidden ? null : Date.now();
    const onVisibility = () => {
      if (document.hidden && since !== null) {
        total += Date.now() - since;
        since = null;
      } else if (!document.hidden && since === null) {
        since = Date.now();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      const seconds = Math.round((total + (since === null ? 0 : Date.now() - since)) / 1000);
      if (seconds < 1) return;
      void api.recordPostReadingSession(postId, seconds, meta);
    };
  }, [api, current, meta, postId]);

  const isRedditPost = post?.platform === 'reddit';

  const handleToggleFavorite = async () => {
    if (!postId) return;
    setTogglingFavorite(true);
    const nextFavorited = !(readerState?.is_favorited ?? false);
    const response = await api.togglePostFavorite(postId, nextFavorited);
    if (!response.success) {
      setError(response.error || 'Failed to update favorite state');
      setTogglingFavorite(false);
      return;
    }
    if (response.reader_state) {
      setReaderState(response.reader_state);
    } else {
      setReaderState((current) => ({ ...current, post_id: postId, is_favorited: response.favorited }));
    }
    const starred = response.reader_state?.is_favorited ?? response.favorited ?? nextFavorited;
    patchFeeds(queryClient, new Set([postId]), { starred_at: starred ? new Date().toISOString() : null });
    setAnnouncement(starred ? 'Kept' : 'No longer kept');
    setTogglingFavorite(false);
  };

  const bodyHtml = typeof post?.content_html === 'string' && post.content_html.trim() ? post.content_html : null;
  const renderContent = bodyHtml ?? (typeof post?.content === 'string' ? post.content : '');
  // Images the body already shows stay inline; the first other one under the title, the rest after the text.
  const media = useMemo(() => postMedia(post, `${renderContent}\n${post.content || ''}`), [post, renderContent]);
  const bodyImageSrc = useCallback((src: string) => proxiedImage(postId, src), [postId]);
  // The same element while the body is the same, so a block keeps its focus across state changes.
  const internalLinks = post?.internal_links;
  const markdownBody = useMemo(
    () => <MarkdownRenderer content={renderContent} imageSrc={bodyImageSrc} html={bodyHtml !== null} internalLinks={internalLinks} />,
    [renderContent, bodyImageSrc, bodyHtml, internalLinks],
  );
  const isYouTubePost = post?.platform === 'youtube';
  const embeddedVideoId = !isYouTubePost ? media.video?.id ?? null : null;
  const heroImage = isYouTubePost || embeddedVideoId ? null : media.images[0] ?? null;
  const moreImages = heroImage ? media.images.slice(1) : media.images;
  const youtubeMetadata = useMemo(() => {
    const metadata = post?.metadata;
    if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
      return null;
    }
    return metadata as YouTubeMetadata;
  }, [post?.metadata]);
  const youtubeVideoId = useMemo(() => media.video?.id ?? extractYouTubeVideoId(post), [media.video, post]);
  const youtubeVideoUrl = post?.url || (youtubeVideoId ? `https://www.youtube.com/watch?v=${youtubeVideoId}` : undefined);
  const youtubeDurationSeconds = Number(youtubeMetadata?.duration_seconds || 0) || null;
  const youtubeChapters = useMemo(() => youtubeMetadata?.chapters || [], [youtubeMetadata?.chapters]);
  const youtubeTranscriptBlocks = useMemo(
    () => buildYouTubeTranscriptBlocks(post?.content || '', youtubeDurationSeconds, youtubeChapters),
    [post?.content, youtubeDurationSeconds, youtubeChapters],
  );
  const youtubeProgressPercent = Number(
    youtubeProgress?.progress_percent
      ?? (youtubeDurationSeconds ? ((youtubeProgressDraft || 0) / youtubeDurationSeconds) * 100 : 0),
  ) || 0;
  const youtubeViewCount = formatCompactCount(youtubeMetadata?.view_count);
  const youtubeLikeCount = formatCompactCount(youtubeMetadata?.like_count);
  const isFavorited = Boolean(readerState?.is_favorited);
  const safeCommentPreview = (comment: RedditComment) => {
    const body = typeof comment.body === 'string' ? comment.body : '';
    return body.slice(0, 24);
  };
  const sourceName = postSourceName(post);
  const site = pageSite(post);
  // The API's title is already the short one; a post whose whole text is that title shows it once.
  const displayTitle = post.title || 'Untitled post';
  const bodyIsTitle = useMemo(() => postPlainText(post).replace(/\s+/g, ' ') === displayTitle, [post, displayTitle]);
  const longPost = useMemo(() => postPlainText(post).length >= LONG_POST_CHARS, [post]);
  const position = useReadingPosition({
    postId, api, body: bodyRef, end: endRef, saved: detail.reader_state ?? null,
    enabled: longPost && !fixture && !isYouTubePost, offer: offerResume,
  });
  const publishedLabel = postBylineTime(post?.published_at || post?.fetched_at || null);
  const publishedFull = feedFullTime(post?.published_at || post?.fetched_at || null);
  const publishedIso = post?.published_at || post?.fetched_at || undefined;
  const page = useMemo(() => pageState(post.metadata, post.published_at), [post.metadata, post.published_at]);
  const pageLine = [page.update ? updateLine(page.update) : null, ...page.notes].filter(Boolean).join(' · ');

  useEffect(() => {
    if (current) document.title = `${displayTitle} · INSIGHT`;
  }, [current, displayTitle]);

  const handleCopy = async () => {
    if (!post) return;
    try {
      await writeToClipboard(postPlainText(post));
      setCopyState('copied');
      setAnnouncement('Post text copied to the clipboard');
      window.setTimeout(() => setCopyState('idle'), 2000);
    } catch {
      setError('Could not copy the post text in this browser.');
    }
  };

  const cachedItem = findFeedItems(queryClient, [postId]).get(postId);
  const isRead = Boolean(readerState?.read_at);
  const isLater = Boolean(readerState?.later_at);
  const asFeedItem = (): FeedItem => cachedItem ?? {
    id: postId, title: post.title ?? '', excerpt: '', url: post.url ?? '',
    source_id: post.source_id ?? '', source_display_name: post.source_display_name ?? '', platform: post.platform ?? '',
    sort_at: postSortAt(queryClient, postId, post) ?? '', published_at: post.published_at ?? null, read_at: readerState?.read_at ?? null, starred_at: null,
    reading_minutes: null, duration_seconds: null, media_thumb: null,
  };
  const toggleRead = async () => {
    const read = !isRead;
    const previous = { read_at: readerState?.read_at ?? null, later_at: readerState?.later_at ?? null };
    const item = asFeedItem();
    setReaderState((current) => ({ ...current, post_id: postId, read_at: read ? new Date().toISOString() : null, ...(read ? { later_at: null } : {}) }));
    try {
      await mutations.setRead(item, read);
      patchStoryRead(queryClient, postId, read ? new Date().toISOString() : null);
      setAnnouncement(read ? 'Marked as read' : 'Marked as unread');
    } catch (failure) {
      setReaderState((current) => ({ ...current, post_id: postId, ...previous }));
      setError(errorMessage(failure));
    }
  };
  const setLater = async (later: boolean) => {
    const previous = readerState?.later_at ?? null;
    setReaderState((current) => ({ ...current, post_id: postId, later_at: later ? new Date().toISOString() : null }));
    try {
      await mutations.setLater({ ...asFeedItem(), later_at: previous }, later);
      setAnnouncement(later ? 'Saved for later' : 'Removed from Later');
    } catch (failure) {
      setReaderState((current) => ({ ...current, post_id: postId, later_at: previous }));
      setError(errorMessage(failure));
    }
  };
  finishRef.current = () => {
    if (isLater) void setLater(false);
  };

  useKeyboardShortcuts({
    m: () => void toggleRead(),
    s: () => void handleToggleFavorite(),
    l: () => void setLater(!isLater),
  }, { enabled: keysEnabled, singleKeys: shortcutsOn });

  return (
    <>
      {current && actionsSlot ? createPortal(
        <PostActions
          url={post.url}
          discussionUrl={typeof post.metadata?.comments_url === 'string' ? post.metadata.comments_url : null}
          starred={isFavorited}
          starring={togglingFavorite}
          onStar={() => void handleToggleFavorite()}
          later={isLater}
          onLater={() => void setLater(!isLater)}
          copied={copyState === 'copied'}
          onCopy={() => void handleCopy()}
        />,
        actionsSlot,
      ) : null}
      {divider ? <hr className="mb-10 mt-16 border-0 border-t border-line-strong" /> : null}

      <header className="mb-8">
        <div className="flex min-h-[2.25rem] items-start">
          <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1 pt-1.5 text-[0.8125rem] text-fg-2">
            {/* An aggregator's page names its site first, the feed as "via" (0280). */}
            {site ? <span data-page-site className="min-w-0 font-medium text-fg [overflow-wrap:anywhere]">{middleTruncate(site, 40)}</span> : null}
            {site ? <span>via</span> : null}
            {/* The source name reads the source; a source is managed in Sources, not here. */}
            {post.source_id ? (
              <>
                <TextLink
                  to={sourceReadPath(post.source_id)}
                  className="min-w-0 font-medium decoration-transparent [overflow-wrap:anywhere] hover:decoration-fg-3"
                  title={post.source_display_name || post.source}
                >
                  {middleTruncate(sourceName, 40)}
                </TextLink>
              </>
            ) : (
              <span className="min-w-0 font-medium text-fg [overflow-wrap:anywhere]" title={post.source_display_name || post.source}>
                {middleTruncate(sourceName, 40)}
              </span>
            )}
            {!site && carriedLine(post) ? <span>{carriedLine(post)}</span> : null}
            {post.discussion ? <DiscussionLink discussion={post.discussion} /> : null}
            {post.metadata?.saved_by_owner && post.platform !== 'saved' ? <span className="whitespace-nowrap">· saved by you</span> : null}
            {post.metadata?.collected_original ? (
              <span className="whitespace-nowrap">
                {post.metadata?.collected_as === 'classic' ? '· classic, collected'
                  : post.metadata?.collected_as === 'work' ? '· work, collected' : '· collected original'}
              </span>
            ) : null}
            {/* Each "/ part" wraps as one, so a line never starts with a bare slash. */}
            {publishedLabel ? (
              <span className="whitespace-nowrap">
                <span aria-hidden="true" className="mr-2 text-fg-3">/</span>
                <time dateTime={publishedIso} title={publishedFull} className="tabular-nums">{publishedLabel}</time>
              </span>
            ) : null}
            {post.counts ? (
              <span className="whitespace-nowrap">
                <span aria-hidden="true" className="mr-2 text-fg-3">/</span>
                <span className="tabular-nums">{countsLabel(post.counts)}</span>
              </span>
            ) : null}
            {page.modified ? (
              <span className="whitespace-nowrap">
                <span aria-hidden="true" className="mr-2 text-fg-3">/</span>
                <time dateTime={page.modified} title={feedFullTime(page.modified)} className="tabular-nums">updated {feedDateLabel(page.modified)}</time>
              </span>
            ) : null}
          </p>
        </div>
        <h1 dir="auto" className="mt-2 break-words text-pretty [font-family:var(--reading-font)] text-[1.75rem] font-[650] leading-[1.15] tracking-[-0.025em] text-fg sm:text-[2rem]">
          {displayTitle}
        </h1>
        {pageLine ? <p data-page-state className="mt-2 text-[0.8125rem] text-fg-3 [overflow-wrap:anywhere]">{pageLine}</p> : null}
        <span aria-live="polite" className="sr-only">{announcement}</span>
      </header>

      {position.offerPercent !== null ? (
        <p className="-mt-4 mb-8">
          <button type="button" onClick={position.resume} className={`text-link rounded-sm text-[0.8125rem] text-fg-2 ${FOCUS_RING}`}>
            Continue from where you stopped ({position.offerPercent}%)
          </button>
        </p>
      ) : null}

      {heroImage ? <PostFigure image={heroImage} postId={postId} className="mb-10" /> : null}
      {embeddedVideoId ? <VideoPlayer videoId={embeddedVideoId} title={displayTitle} className="mb-10" /> : null}

      {error && (
        <Notice
          tone="error"
          title="That did not work"
          message={error}
          action={{ label: 'Dismiss', onClick: () => setError(null) }}
          className="mb-8"
        />
      )}

      {isYouTubePost && youtubeVideoId && (
        <section aria-label="Video" className="mb-10 space-y-5">
          <VideoPlayer videoId={youtubeVideoId} title={post.title || youtubeVideoId} />

          <p className="flex flex-wrap gap-x-3 gap-y-1 text-[0.8125rem] tabular-nums text-fg-3">
            {youtubeDurationSeconds ? <span>{formatClock(youtubeDurationSeconds)}</span> : null}
            {youtubeViewCount ? <span>{youtubeViewCount} views</span> : null}
            {youtubeLikeCount ? <span>{youtubeLikeCount} likes</span> : null}
            {youtubeMetadata?.transcript_source ? <span>transcript: {youtubeMetadata.transcript_source}</span> : null}
          </p>

          <div className="rounded-md border border-line p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <h2 className="text-[0.875rem] font-semibold text-fg">Watch progress</h2>
              <span className="text-[0.8125rem] tabular-nums text-fg-2">
                {loadingYouTubeProgress
                  ? 'Loading saved progress…'
                  : `${formatClock(youtubeProgressDraft)} / ${formatClock(youtubeDurationSeconds)}`}
              </span>
            </div>
            <div
              role="progressbar"
              aria-label="Watched"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(Math.min(100, youtubeProgressPercent))}
              className="mt-3 h-1 overflow-hidden rounded-full bg-raised"
            >
              <div className="h-full bg-fg" style={{ width: `${Math.min(100, youtubeProgressPercent)}%` }} />
            </div>
            {youtubeDurationSeconds ? (
              <input
                type="range"
                aria-label="Set watch position"
                min={0}
                max={youtubeDurationSeconds}
                value={Math.min(youtubeDurationSeconds, Math.max(0, youtubeProgressDraft))}
                onChange={(e) => setYouTubeProgressDraft(Number(e.target.value) || 0)}
                className="mt-3 w-full accent-[rgb(var(--text))]"
              />
            ) : null}
            {(youtubeProgress?.watch_sessions || youtubeProgress?.last_watched_at) ? (
              <p className="mt-1 text-[0.75rem] tabular-nums text-fg-3">
                {youtubeProgress?.watch_sessions ? plural(youtubeProgress.watch_sessions, 'watch session') : null}
                {youtubeProgress?.watch_sessions && youtubeProgress?.last_watched_at ? ' · ' : null}
                {youtubeProgress?.last_watched_at ? `last ${formatLocalDateTime(youtubeProgress.last_watched_at) ?? ''}` : null}
              </p>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void saveCurrentYouTubeProgress(youtubeProgressDraft, false)}
                disabled={savingYouTubeProgress}
              >
                <Busy when={savingYouTubeProgress}>{null}</Busy>
                Save progress
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  const completedAt = youtubeDurationSeconds || youtubeProgressDraft;
                  void saveCurrentYouTubeProgress(completedAt, true);
                }}
                disabled={savingYouTubeProgress}
              >
                <Check aria-hidden="true" />
                Mark complete
              </Button>
            </div>
          </div>

          {youtubeChapters.length ? (
            <div>
              <h2 className="mb-2 text-[0.875rem] font-semibold text-fg">Chapters</h2>
              <ol className="divide-y divide-line rounded-md border border-line">
                {youtubeChapters.map((chapter, index) => (
                  <li key={`${chapter.title || 'chapter'}-${index}`}>
                    <a
                      href={buildYouTubeTimestampUrl(youtubeVideoUrl, Number(chapter.start_seconds || 0))}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={() => setYouTubeProgressDraft(Number(chapter.start_seconds || 0))}
                      className="flex items-baseline gap-4 px-4 py-2.5 text-[0.875rem] hover:bg-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-fg"
                    >
                      <span className="w-12 shrink-0 tabular-nums text-fg-3">{formatClock(Number(chapter.start_seconds || 0))}</span>
                      <span className="min-w-0 font-medium text-fg [overflow-wrap:anywhere]">{chapter.title || `Chapter ${index + 1}`}</span>
                    </a>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
        </section>
      )}

      <article ref={bodyRef} aria-label={isYouTubePost ? 'Transcript' : 'Post content'} className="min-w-0">
        {isYouTubePost && youtubeTranscriptBlocks.length ? (
          <p className="mb-5 flex flex-wrap gap-x-3 gap-y-1 text-[0.8125rem] tabular-nums text-fg-3">
            <span>{plural(youtubeTranscriptBlocks.length, 'transcript section')}</span>
          </p>
        ) : null}

        <div className={READING_TEXT_CLASS}>
          {isYouTubePost ? (
            <div className="space-y-8">
              {youtubeMetadata?.description ? (
                <details className="group rounded-md border border-line text-[0.875rem] leading-[1.6]">
                  <summary className="flex cursor-pointer list-none items-baseline gap-3 px-4 py-2.5 font-medium text-fg-2 [&::-webkit-details-marker]:hidden">
                    <span aria-hidden="true" className="w-3 text-fg-3 group-open:rotate-90">›</span>
                    Video description
                  </summary>
                  <div className="whitespace-pre-wrap border-t border-line px-4 py-3 text-fg-2 [overflow-wrap:anywhere]">
                    {youtubeMetadata.description}
                  </div>
                </details>
              ) : null}

              {youtubeTranscriptBlocks.length ? (
                youtubeTranscriptBlocks.map((block, index) => (
                  <section key={block.id} aria-labelledby={`${postId}-${block.id}-title`}>
                    <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span className="text-[0.8125rem] tabular-nums text-fg-3">{formatClock(block.startSeconds)}</span>
                      <h3 id={`${postId}-${block.id}-title`} className="min-w-0 flex-1 text-[1rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">
                        {block.title || `Transcript ${index + 1}`}
                      </h3>
                      <span className="flex gap-1 text-[0.8125rem] leading-none">
                        <Button size="sm" variant="ghost" onClick={() => setYouTubeProgressDraft(block.startSeconds)}>
                          Set progress here
                        </Button>
                        {youtubeVideoUrl ? (
                          <Button asChild size="sm" variant="ghost">
                            <a href={buildYouTubeTimestampUrl(youtubeVideoUrl, block.startSeconds)} target="_blank" rel="noopener noreferrer">
                              Open at {formatClock(block.startSeconds)}
                              <ArrowUpRight aria-hidden="true" />
                            </a>
                          </Button>
                        ) : null}
                      </span>
                    </div>
                    <TranscriptText content={block.text} preserveLines={false} />
                  </section>
                ))
              ) : post.content ? (
                <TranscriptText content={post.content} />
              ) : (
                <p className="text-[0.9375rem] text-fg-3">No transcript was stored for this video yet.</p>
              )}
            </div>
          ) : bodyIsTitle ? null : renderContent.trim() ? (
            <>
              {markdownBody}
              {post.teaser_reason ? (
                <p data-teaser className="mt-4 text-[0.8125rem] leading-5 text-fg-3 [overflow-wrap:anywhere]">
                  {`Summary only · ${post.teaser_reason}`}
                  {post.url ? (
                    <>
                      {' · '}
                      <a href={post.url} target="_blank" rel="noopener noreferrer" className="text-link">Open the page ↗</a>
                    </>
                  ) : null}
                </p>
              ) : null}
            </>
          ) : post.link?.post_id ? (
            <p data-read-on><Link to={`/posts/${post.link.post_id}`} className="text-link">{readOnLabel(post.link, displayTitle)}</Link></p>
          ) : post.link || post.url ? (
            // No body stored: the next step is the page itself (a link post's: the page it shares).
            <p data-read-on>
              <a href={post.link?.url ?? post.url} target="_blank" rel="noopener noreferrer" className="text-link">{readOnLabel(post.link ?? { url: post.url ?? "", title: null }, displayTitle)} ↗</a>
            </p>
          ) : null}
        </div>
      </article>
      {markxOn && !fixture ? <Suspense fallback={null}><MarkXTranslation postId={postId} /></Suspense> : null}

      <PostImageList images={moreImages} postId={postId} />

      {post.news ? (
        <p data-news className="mt-8 min-w-0 text-[0.8125rem] leading-5 text-fg-3 [overflow-wrap:anywhere]">
          In News:{' '}
          <TextLink to={`${scopePath(post.news.scope)}?view=news`} className="text-fg-2">{post.news.title}</TextLink>
          {` · ${plural(post.news.voices, 'source')}`}
        </p>
      ) : null}

      {post.background?.length ? (
        <div data-background className="mt-8 flex flex-col gap-1 text-[0.8125rem] leading-5 text-fg-3">
          {post.background.map((classic) => (
            <p key={classic.url} className="min-w-0 [overflow-wrap:anywhere]">
              Builds on:{' '}
              {classic.post_id ? (
                <TextLink to={`/posts/${encodeURIComponent(classic.post_id)}`} className="text-fg-2">{classicTitle(classic)}</TextLink>
              ) : (
                <ExternalLink href={classic.url} className="text-fg-2">{classicTitle(classic)}</ExternalLink>
              )}
              {` · cited by ${classic.voices} of your sources`}
            </p>
          ))}
        </div>
      ) : null}

      {markxOn && !fixture ? <Suspense fallback={null}><MarkXPanel postId={postId} url={post.url} /></Suspense> : null}
      {markxOn && !fixture ? <Suspense fallback={null}><MarkXRelated postId={postId} /></Suspense> : null}
      {markxOn && !fixture && post.discussion ? <Suspense fallback={null}><MarkXDiscussion postId={postId} /></Suspense> : null}
      {/* v10.42: teach INSIGHT More / Less of this post's things, its kind of news, its source */}
      {markxOn && !fixture ? <Suspense fallback={null}><PostTeach postId={postId} /></Suspense> : null}

      {post.story?.thread ? <ThreadPosts story={post.story} postId={postId} /> : null}

      {!fixture ? <Suspense fallback={null}><Connected postId={postId} /></Suspense> : null}

      {post.story ? <CoveredBy story={post.story} post={post} postId={postId} /> : null}

      {isRedditPost && comments.length > 0 && (
        <section className="mt-14" aria-labelledby={`post-discussion-${postId}`}>
          <SectionHeading
            title="Discussion"
            meta={[
              plural(comments.length, 'comment'),
              commentsFetchedAt ? `fetched ${formatLocalDateTime(commentsFetchedAt) ?? ''}` : null,
            ].filter(Boolean).join(' · ')}
          />
          <span id={`post-discussion-${postId}`} className="sr-only">Discussion</span>
          <ol className="max-h-[36rem] space-y-4 overflow-y-auto pr-1">
            {comments.map((comment) => (
              <li
                key={comment.id || `${comment.author || 'unknown'}-${comment.created_at || 'unknown'}-${safeCommentPreview(comment)}`}
                className="border-l border-line-strong pl-3"
                style={{ marginLeft: `${Math.min(Number(comment.depth) || 0, 4) * 0.75}rem` }}
              >
                <div className="flex flex-wrap gap-x-3 text-[0.75rem] tabular-nums text-fg-3">
                  <span className="font-semibold text-fg-2 [overflow-wrap:anywhere]">{comment.author || 'unknown'}</span>
                  <span>{plural(Number(comment.score ?? 0), 'point')}</span>
                </div>
                <div className="mt-1 whitespace-pre-wrap text-[0.9375rem] leading-[1.6] text-fg [overflow-wrap:anywhere]">
                  {typeof comment.body === 'string' ? comment.body : ''}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
      <div ref={endRef} data-post-end={postId} aria-hidden="true" />
    </>
  );
}

/** The header's link to the post's thread on a discussion site (0280), shown before any fetch. */
export function DiscussionLink({ discussion }: { discussion: { name: string; url: string; total: number | null } }) {
  return (
    <span data-discussion-link className="whitespace-nowrap">
      <span aria-hidden="true" className="mr-2 text-fg-3">/</span>
      <a href={discussion.url} target="_blank" rel="noopener noreferrer" className="text-link">
        Discussion on {discussion.name}{discussion.total != null ? ` · ${plural(discussion.total, 'comment')}` : ''}
      </a>
    </span>
  );
}
