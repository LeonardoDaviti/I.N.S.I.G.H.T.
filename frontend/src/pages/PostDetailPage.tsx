import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  ArrowUpRight,
  Check,
  Loader2,
} from 'lucide-react';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import PostActions from '../components/post/PostActions';
import { PostFigure, PostImageList } from '../components/post/PostImages';
import { postMedia } from '../components/post/media';
import { Button, Skeleton } from '../components/ui';
import { EmptyState, Notice } from '../components/states';
import { useDevFixtureApi } from '../hooks/useDevFixtureApi';
import DevDataSwitch from '../components/ops/DevDataSwitch';
import ShortcutHelp from '../components/reader/ShortcutHelp';
import { usePost, usePrefetchPost } from '../hooks/usePost';
import { usePostNeighbors } from '../hooks/usePostNeighbors';
import { findFeedItems, patchFeeds, useReaderMutations } from '../hooks/useReaderMutations';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { useShortcutPreference } from '../hooks/useShortcutPreference';
import { decodeFeedContext, postHref, scopePath, sourceSettingsHref, type FeedContext } from '../lib/feedContext';
import TextLink from '../components/ui/TextLink';
import { rememberSelection } from '../lib/readerSelection';
import { displayPostTitle } from '../lib/postTitle';
import { postSourceName } from '../lib/sourceLabel';
import { errorMessage } from '../lib/apiError';
import { writeToClipboard } from '../lib/clipboard';
import { middleTruncate, plural } from '../lib/format';
import { feedFullTime, formatLocalDateTime } from '../lib/dates';
import { formatClock } from '../lib/duration';
import type {
  Api,
  FeedItem,
  Post,
  PostDetailResponse,
  ReaderState,
  RedditComment,
  YouTubeWatchProgress,
} from '../services/api';
import { proxiedImage } from '../lib/mediaProxy';

/**
 * The post reading view (/posts/:id): one centred column — source and date, the
 * title with three icon actions in its top-right corner (open original, star,
 * copy), the images, the text — and nothing beside it.
 */

/** The dev-only `?data=` fixtures, imported on demand: a production build drops them. */
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

/** Plain text of a post for the clipboard: the stored text, else the HTML's text. */
function postPlainText(post: Post): string {
  const text = typeof post.content === 'string' ? post.content.trim() : '';
  if (text) return text;
  const html = typeof post.content_html === 'string' ? post.content_html : '';
  if (!html || typeof document === 'undefined') return '';
  const container = document.createElement('div');
  container.innerHTML = html;
  return (container.textContent || '').trim();
}

/** A section heading in the reading column: small, semibold, a hairline above. */
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

/** A spinner inside a button while its request is in flight. */
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

/** The YouTube player, privacy-enhanced, in a reserved 16:9 frame. */
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

/** The page frame, shared by the loading skeleton and the loaded post. */
const PAGE_CLASS = 'mx-auto w-full max-w-6xl px-4 pb-24 pt-6 sm:px-6 sm:pt-8';
/** One column of ~70ch at the body size, centred, nothing beside it. */
const GRID_CLASS = 'grid grid-cols-[minmax(0,42rem)] justify-center';

/** The loading frame: the same container, grid and column as the loaded page, so
 *  React swaps only the children on arrival (no width or padding jump). */
function PostSkeleton() {
  return (
    <div className={PAGE_CLASS}>
      <div className={GRID_CLASS}>
        <div className="min-w-0" role="status" aria-busy="true" aria-live="polite">
          <span className="sr-only">Loading post</span>
          <div aria-hidden="true">
            <div className="mb-5 min-h-[2rem]" />
            <div className="mb-8">
              <div className="flex min-h-[2.25rem] items-start justify-between gap-4">
                <Skeleton className="mt-1 h-3 w-48" />
                <Skeleton className="h-6 w-24" />
              </div>
              <Skeleton className="mt-2 h-7 w-11/12" />
              <Skeleton className="mt-2 h-7 w-2/3" />
            </div>
            <div className="max-w-[68ch] space-y-3">
              {['w-full', 'w-11/12', 'w-full', 'w-4/5', 'w-full', 'w-3/5'].map((width, index) => (
                <Skeleton key={index} className={`h-3.5 ${width}`} />
              ))}
            </div>
          </div>
        </div>
      </div>
      <DevDataSwitch options={POST_FIXTURE_NAMES} />
    </div>
  );
}

/**
 * /posts/:id. The post loads through `usePost` (react-query, `['post', id]`), so
 * a post the feed prefetched opens from cache with no skeleton (spec §F.3). Each
 * post gets its own `PostView` (keyed by id): its state starts from that post and
 * nothing of the previous post (metadata, reading time) carries over on j/k.
 */
export default function PostDetailPage() {
  const navigate = useNavigate();
  const { postId } = useParams();
  const { api, fixture } = useDevFixtureApi(postFixtureApi);
  const query = usePost(postId, { api, fixture });

  if (postId && query.data?.post) {
    return <PostView key={`${postId}:${fixture ?? ''}`} postId={postId} detail={query.data} api={api} fixture={fixture} />;
  }
  if (postId && query.isPending) return <PostSkeleton />;
  return (
    <div className={PAGE_CLASS}>
      <div className={GRID_CLASS}>
        <div className="min-w-0">
          <div className="mb-5 min-h-[2rem]" aria-hidden="true" />
          <EmptyState
            title="Post not found"
            description={postId ? errorMessage(query.error) : 'Missing post id'}
            action={{ label: 'Back to the feed', onClick: () => navigate('/') }}
          />
        </div>
      </div>
      <DevDataSwitch options={POST_FIXTURE_NAMES} />
    </div>
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

function PostView({ postId, detail, api, fixture }: { postId: string; detail: PostDetailResponse; api: Api; fixture: string | null }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const initial = useMemo(() => initialComments(detail.post as Post), [detail.post]);
  const post = detail.post as Post;
  const [readerState, setReaderState] = useState<ReaderState | null>(detail.reader_state || null);
  const [youtubeProgress, setYouTubeProgress] = useState<YouTubeWatchProgress | null>(null);
  const [youtubeProgressDraft, setYouTubeProgressDraft] = useState(0);
  const [comments, setComments] = useState<RedditComment[]>(initial.comments);
  const [commentsFetchedAt, setCommentsFetchedAt] = useState<string | null>(initial.fetchedAt);
  const [loadingYouTubeProgress, setLoadingYouTubeProgress] = useState(false);
  const [loadingComments, setLoadingComments] = useState(false);
  const [savingYouTubeProgress, setSavingYouTubeProgress] = useState(false);
  const [togglingFavorite, setTogglingFavorite] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied'>('idle');
  const [announcement, setAnnouncement] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  const openRecordedRef = useRef(false);
  const mutations = useReaderMutations({ dryRun: Boolean(fixture) });
  const [shortcutsOn] = useShortcutPreference();
  const prefetch = usePrefetchPost();

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

  // YouTube posts only: the saved watch position.
  useEffect(() => {
    const videoId = extractYouTubeVideoId(detail.post);
    if (detail.post?.platform !== 'youtube' || !videoId) return;
    void loadYouTubeWatchProgress(videoId);
    // Once per post: PostView is keyed by the post id.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Record the open and, on leaving, the reading time, both with this post's own
  // metadata. A visit under a second (StrictMode's mount check, a j held down) is
  // not reading and is not recorded.
  useEffect(() => {
    const startedAt = Date.now();
    const meta = { title: detail.post?.title, source: detail.post?.source, platform: detail.post?.platform };
    rememberSelection(postId);
    if (!openRecordedRef.current) {
      openRecordedRef.current = true;
      void api.recordPostOpen(postId, meta).then((response) => {
        if (!response.success) return;
        // The server marks an opened post read: so do the cached feed and counts.
        mutations.noteOpened(postId);
        const recordedAt = response.event?.created_at || new Date().toISOString();
        setReaderState((current) => ({
          ...current,
          post_id: postId,
          is_favorited: current?.is_favorited ?? false,
          open_count: (current?.open_count || 0) + 1,
          first_opened_at: current?.first_opened_at || recordedAt,
          last_opened_at: recordedAt,
          total_read_seconds: current?.total_read_seconds ?? 0,
          read_at: current?.read_at || recordedAt,
        }));
      });
    }
    return () => {
      const seconds = Math.round((Date.now() - startedAt) / 1000);
      if (seconds < 1) return;
      void api.recordPostReadingSession(postId, seconds, meta);
    };
    // Once per post: PostView is keyed by the post id.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchComments = async (refresh = false) => {
    if (!postId) return;
    setLoadingComments(true);
    setError(null);
    const response = await api.fetchRedditComments(postId, { limit: 80, refresh });
    if (!response.success) {
      setError(response.error || 'Failed to fetch Reddit comments');
      setLoadingComments(false);
      return;
    }
    setComments(response.comments || []);
    setCommentsFetchedAt(response.fetched_at || null);
    setLoadingComments(false);
  };

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
    // The feed shows the same star: keep its cached rows in step.
    const starred = response.reader_state?.is_favorited ?? response.favorited ?? nextFavorited;
    patchFeeds(queryClient, new Set([postId]), { starred_at: starred ? new Date().toISOString() : null });
    setAnnouncement(starred ? 'Starred' : 'Removed star');
    setTogglingFavorite(false);
  };

  const platformLabel = typeof post?.platform === 'string' ? post.platform.toLowerCase() : '';
  const renderContent = typeof post?.content_html === 'string'
    ? post.content_html
    : typeof post?.content === 'string'
      ? post.content
      : '';
  // Images the body already shows stay inline; the rest: the first under the
  // title, the others after the text. A video post shows its player instead.
  const media = useMemo(() => postMedia(post, `${renderContent}\n${post.content || ''}`), [post, renderContent]);
  const bodyImageSrc = useCallback((src: string) => proxiedImage(postId, src), [postId]);
  const isYouTubePost = post?.platform === 'youtube';
  // A blog post that carries a YouTube video: the player stands in for the hero.
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
  const displayTitle = useMemo(() => displayPostTitle(post.title, postPlainText(post)), [post]);
  const publishedLabel = feedFullTime(post?.published_at || post?.fetched_at || null);
  const publishedIso = post?.published_at || post?.fetched_at || undefined;

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


  // ---- the feed context: prev/next, back, and the post page's keys (spec §F.5) ----
  const ctx: FeedContext | null = useMemo(() => decodeFeedContext(searchParams.get('ctx')), [searchParams]);
  const cachedItem = findFeedItems(queryClient, [postId]).get(postId);
  const sortAt = cachedItem?.sort_at ?? post.published_at ?? post.fetched_at ?? null;
  const neighbors = usePostNeighbors(api, ctx, { id: postId, sortAt });

  useEffect(() => {
    if (fixture) return;
    if (neighbors.next) prefetch(neighbors.next.id);
    if (neighbors.prev) prefetch(neighbors.prev.id);
  }, [fixture, neighbors.next, neighbors.prev, prefetch]);

  const openNeighbor = (entry: { id: string; pageCursor: string | null } | null) => {
    if (!entry || !ctx) return;
    // Replace, so Back still leads to the feed rather than through every post read.
    navigate(postHref(entry.id, { ...ctx, cursor: entry.pageCursor }), { replace: true, state: location.state });
  };

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

  const isRead = Boolean(readerState?.read_at);
  const toggleRead = async () => {
    const read = !isRead;
    const previous = readerState?.read_at ?? null;
    const item: FeedItem = cachedItem ?? {
      id: postId, title: post.title ?? '', excerpt: '', url: post.url ?? '',
      source_id: post.source_id ?? '', source_display_name: post.source_display_name ?? '', platform: post.platform ?? '',
      sort_at: sortAt ?? '', published_at: post.published_at ?? null, read_at: previous, starred_at: null,
      reading_minutes: null, duration_seconds: null, media_thumb: null,
    };
    setReaderState((current) => ({ ...current, post_id: postId, read_at: read ? new Date().toISOString() : null }));
    try {
      await mutations.setRead(item, read);
      setAnnouncement(read ? 'Marked as read' : 'Marked as unread');
    } catch (failure) {
      setReaderState((current) => ({ ...current, post_id: postId, read_at: previous }));
      setError(errorMessage(failure));
    }
  };

  useKeyboardShortcuts({
    j: ctx ? () => openNeighbor(neighbors.next) : undefined,
    k: ctx ? () => openNeighbor(neighbors.prev) : undefined,
    u: goBack,
    Escape: goBack,
    m: () => void toggleRead(),
    s: () => void handleToggleFavorite(),
    '?': () => setHelpOpen(true),
  }, { enabled: !helpOpen, singleKeys: shortcutsOn });

  return (
    <div className={PAGE_CLASS}>
      <div className={GRID_CLASS}>
        <div className="min-w-0">
          <nav aria-label="Post navigation" className="-ml-2.5 mb-5 flex min-h-[2rem] flex-wrap items-center gap-1">
            <Button variant="ghost" size="sm" onClick={goBack} title="Back (u)">
              <ArrowLeft aria-hidden="true" />
              {hasHistory || returnTo ? 'Back' : 'Back to feed'}
            </Button>
            {ctx ? (
              <>
                <Button variant="ghost" size="sm" onClick={() => openNeighbor(neighbors.prev)} disabled={!neighbors.prev} title="Previous post (k)">
                  <ArrowUp aria-hidden="true" />
                  Previous
                </Button>
                <Button variant="ghost" size="sm" onClick={() => openNeighbor(neighbors.next)} disabled={!neighbors.next} title="Next post (j)">
                  <ArrowDown aria-hidden="true" />
                  Next
                </Button>
              </>
            ) : null}
          </nav>

          {/* ---- Header: source / platform / date and the actions on one line, then the title ---- */}
          <header className="mb-8">
            <div className="flex min-h-[2.25rem] items-start justify-between gap-4">
              <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1 pt-1.5 text-[0.8125rem] text-fg-2">
                {/* The source name links quietly to where it is managed (issue 0003). */}
                {post.source_id ? (
                  <TextLink
                    to={sourceSettingsHref(post.source_id)}
                    className="min-w-0 font-medium decoration-transparent [overflow-wrap:anywhere] hover:decoration-fg-3"
                    title={post.source_display_name || post.source}
                  >
                    {middleTruncate(sourceName, 40)}
                  </TextLink>
                ) : (
                  <span className="min-w-0 font-medium text-fg [overflow-wrap:anywhere]" title={post.source_display_name || post.source}>
                    {middleTruncate(sourceName, 40)}
                  </span>
                )}
                {/* Each "/ part" wraps as one, so a line never starts with a bare slash. */}
                {platformLabel ? (
                  <span className="whitespace-nowrap">
                    <span aria-hidden="true" className="mr-2 text-fg-3">/</span>
                    {platformLabel}
                  </span>
                ) : null}
                {publishedLabel ? (
                  <span className="whitespace-nowrap">
                    <span aria-hidden="true" className="mr-2 text-fg-3">/</span>
                    <time dateTime={publishedIso} className="tabular-nums">{publishedLabel}</time>
                  </span>
                ) : null}
              </p>
              <PostActions
                url={post.url}
                starred={isFavorited}
                starring={togglingFavorite}
                onStar={() => void handleToggleFavorite()}
                copied={copyState === 'copied'}
                onCopy={() => void handleCopy()}
              />
            </div>
            <h1 dir="auto" className="mt-2 break-words text-pretty text-[1.75rem] font-[650] leading-[1.15] tracking-[-0.025em] text-fg sm:text-[2rem]">
              {displayTitle}
            </h1>
            <span aria-live="polite" className="sr-only">{announcement}</span>
          </header>

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

          {/* ---- YouTube watch mode ---- */}
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

          {/* ---- The article ---- */}
          <article aria-label={isYouTubePost ? 'Transcript' : 'Post content'} className="min-w-0">
            {isYouTubePost && youtubeTranscriptBlocks.length ? (
              <p className="mb-5 flex flex-wrap gap-x-3 gap-y-1 text-[0.8125rem] tabular-nums text-fg-3">
                <span>{plural(youtubeTranscriptBlocks.length, 'transcript section')}</span>
              </p>
            ) : null}

            <div className="max-w-[68ch] text-[1.0625rem] leading-[1.7] text-fg sm:text-[1.125rem]">
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
                      <section key={block.id} aria-labelledby={`${block.id}-title`}>
                        <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                          <span className="text-[0.8125rem] tabular-nums text-fg-3">{formatClock(block.startSeconds)}</span>
                          <h3 id={`${block.id}-title`} className="min-w-0 flex-1 text-[1rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">
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
              ) : (
                <MarkdownRenderer content={renderContent} imageSrc={bodyImageSrc} />
              )}
            </div>
          </article>

          <PostImageList images={moreImages} postId={postId} />

          {/* ---- Reddit discussion ---- */}
          {isRedditPost && (
            <section className="mt-14" aria-labelledby="post-discussion">
              <SectionHeading
                title="Discussion"
                meta={[
                  comments.length ? plural(comments.length, 'comment') : 'no comments loaded',
                  commentsFetchedAt ? `fetched ${formatLocalDateTime(commentsFetchedAt) ?? ''}` : null,
                ].filter(Boolean).join(' · ')}
                actions={(
                  <Button size="sm" variant="secondary" onClick={() => void fetchComments(true)} disabled={loadingComments}>
                    <Busy when={loadingComments}>{null}</Busy>
                    {comments.length ? 'Refresh comments' : 'Fetch comments'}
                  </Button>
                )}
              />
              <span id="post-discussion" className="sr-only">Discussion</span>
              {comments.length ? (
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
              ) : (
                <p className="text-[0.875rem] text-fg-3">Fetch the thread when you need the discussion around this post.</p>
              )}
            </section>
          )}
        </div>
      </div>
      <ShortcutHelp open={helpOpen} onOpenChange={setHelpOpen} />
      <DevDataSwitch options={POST_FIXTURE_NAMES} />
    </div>
  );
}
