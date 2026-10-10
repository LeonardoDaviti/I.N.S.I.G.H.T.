import { useEffect, useMemo, useRef, useState, Component } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  ArrowUpRight,
  Check,
  Download,
  Loader2,
  PanelRight,
} from 'lucide-react';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import PostIntelligenceInspector from '../components/PostIntelligenceInspector';
import PostActions from '../components/post/PostActions';
import { PostFigure, PostImageList } from '../components/post/PostImages';
import { postMedia } from '../components/post/media';
import { useAnalysisEnabled } from '../hooks/useAnalysis';
import {
  Button,
  Chip,
  Sheet,
  SheetContent,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from '../components/ui';
import { EmptyState, LoadingState, Notice } from '../components/states';
import { useDevFixtureApi } from '../components/analysis/useDevFixtureApi';
import DevDataSwitch from '../components/ops/DevDataSwitch';
import { POST_FIXTURE_NAMES, postFixtureApi } from './PostDetailPage.fixtures';
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
import { formatCount, middleTruncate, plural } from '../lib/format';
import type {
  Api,
  BriefingReference,
  FeedItem,
  Post,
  PostDetailResponse,
  PostHighlight,
  PostTimelineResponse,
  ReaderState,
  RedditComment,
  StoryCandidateLink,
  StoryCard,
  StoryDetail,
  StoryUpdateEntry,
  YouTubeVideoEvaluationResponse,
  YouTubeWatchProgress,
} from '../services/api';

/**
 * The post reading view (/posts/:id). Mark IX is reading-only (spec §9): one
 * centred column — source and date, the title with three icon actions in its
 * top-right corner (open original, star, copy), the images, the text — and
 * nothing beside it. With `VITE_INSIGHT_ANALYSIS=on` the machine views come
 * back: the folded summary, highlights, notes and chat in a side column, the
 * story and related posts, and the intelligence inspector in a sheet.
 */

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
};

/** The chat context summary the backend returns with each chat answer. */
type PostChatContext = {
  content_chars?: number;
  reddit_comments_loaded?: number;
  topics_loaded?: number;
  [key: string]: unknown;
};

type PostDetailPageErrorBoundaryState = {
  hasError: boolean;
};

class PostDetailPageErrorBoundary extends Component<
  { children: ReactNode },
  PostDetailPageErrorBoundaryState
> {
  state: PostDetailPageErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <Notice
          tone="error"
          title="Post intelligence unavailable"
          message="One of the inspector views failed to render. The rest of the post remains available."
        />
      );
    }

    return this.props.children;
  }
}

function defaultNotesTemplate(post?: Post | null) {
  return `# Notes for ${post?.title || 'This Post'}

## Key Points
-

## Questions
-

## Insights
-

## Connections
-

---

**Tip:** Select text from the post and bring it into your notes deliberately.`;
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

function formatPublished(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** "4m 12s" / "1h 3m" for accumulated reading time. */
function formatReadTime(seconds?: number | null) {
  const total = Math.max(0, Math.round(Number(seconds || 0)));
  if (total < 60) return `${total}s`;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m ${total % 60}s`;
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

type ResolvedHighlightRange = {
  start: number;
  end: number;
  usedInSummary: boolean;
};

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
  charOffset: number;
};

function buildResolvedHighlightRanges(
  content: string,
  highlights: PostHighlight[],
  summaryReferenceHighlightIds: Set<string>,
): ResolvedHighlightRange[] {
  if (!content || !highlights.length) {
    return [];
  }

  const resolved: ResolvedHighlightRange[] = [];
  const lowerContent = content.toLowerCase();

  highlights.forEach((highlight) => {
    const startChar = Number(highlight.start_char);
    const endChar = Number(highlight.end_char);
    const hasRange = Number.isFinite(startChar) && Number.isFinite(endChar) && endChar > startChar;

    if (hasRange) {
      const start = Math.max(0, Math.min(content.length, startChar));
      const end = Math.max(start, Math.min(content.length, endChar));
      if (end > start) {
        resolved.push({
          start,
          end,
          usedInSummary: Boolean(highlight.id && summaryReferenceHighlightIds.has(highlight.id)),
        });
        return;
      }
    }

    const needle = String(highlight.highlight_text || '').trim();
    if (!needle) {
      return;
    }

    let start = content.indexOf(needle);
    if (start < 0) {
      start = lowerContent.indexOf(needle.toLowerCase());
    }
    if (start < 0) {
      return;
    }

    resolved.push({
      start,
      end: start + needle.length,
      usedInSummary: Boolean(highlight.id && summaryReferenceHighlightIds.has(highlight.id)),
    });
  });

  if (!resolved.length) {
    return [];
  }

  resolved.sort((left, right) => {
    if (left.start !== right.start) return left.start - right.start;
    return right.end - left.end;
  });

  const merged: ResolvedHighlightRange[] = [];
  resolved.forEach((range) => {
    const previous = merged[merged.length - 1];
    if (!previous || range.start > previous.end) {
      merged.push({ ...range });
      return;
    }
    previous.end = Math.max(previous.end, range.end);
    previous.usedInSummary = previous.usedInSummary || range.usedInSummary;
  });

  return merged;
}

/**
 * The text with its highlights marked. `preserveLines` keeps the source's line
 * breaks (posts); caption transcripts break every few words, so they reflow.
 */
function renderHighlightedContent(content: string, ranges: ResolvedHighlightRange[], offset = 0, preserveLines = true) {
  const flow = preserveLines ? 'whitespace-pre-wrap' : 'whitespace-normal';
  const visibleRanges = ranges
    .filter((range) => range.end > offset && range.start < offset + content.length)
    .map((range) => ({
      start: Math.max(0, range.start - offset),
      end: Math.min(content.length, range.end - offset),
      usedInSummary: range.usedInSummary,
    }))
    .filter((range) => range.end > range.start);

  if (!visibleRanges.length) {
    return <div className={flow}>{content}</div>;
  }

  const nodes: ReactNode[] = [];
  let cursor = 0;

  visibleRanges.forEach((range, index) => {
    if (range.start > cursor) {
      nodes.push(
        <span key={`plain-${index}-${cursor}`}>
          {content.slice(cursor, range.start)}
        </span>,
      );
    }

    // Monochrome highlight (design doc §12): a neutral tint, and passages the
    // summary relied on are also underlined, so the difference is not hue.
    nodes.push(
      <mark
        key={`mark-${index}-${range.start}`}
        data-used-in-summary={range.usedInSummary ? 'true' : undefined}
        title={range.usedInSummary ? 'Highlight used in the summary' : 'Highlight'}
        className={`rounded-[2px] bg-[var(--text-highlight-bg-active)] px-[0.1em] text-fg ${
          range.usedInSummary ? 'underline decoration-fg decoration-[0.09em] underline-offset-[0.22em]' : ''
        }`}
      >
        {content.slice(range.start, range.end)}
      </mark>,
    );
    cursor = range.end;
  });

  if (cursor < content.length) {
    nodes.push(<span key={`plain-tail-${cursor}`}>{content.slice(cursor)}</span>);
  }

  return <div className={flow}>{nodes}</div>;
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

function formatDurationLabel(seconds?: number | null) {
  const total = Math.max(0, Math.round(Number(seconds || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remaining = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}`;
  }
  return `${minutes}:${String(remaining).padStart(2, '0')}`;
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
      charOffset: currentOffset,
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
const gridClass = (analysisEnabled: boolean) => (analysisEnabled
  ? 'grid gap-x-12 gap-y-12 xl:grid-cols-[minmax(0,46rem)_18rem] xl:justify-center'
  // Reading-only: one column of ~70ch at the body size, centred, nothing beside it.
  : 'grid grid-cols-[minmax(0,42rem)] justify-center');

/** The loading frame: the same container, grid and column as the loaded page, so
 *  React swaps only the children on arrival (no width or padding jump). */
function PostSkeleton() {
  const analysisEnabled = useAnalysisEnabled();
  return (
    <div className={PAGE_CLASS}>
      <div className={gridClass(analysisEnabled)}>
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
            {analysisEnabled ? <Skeleton className="mb-10 h-12 w-full" /> : null}
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
  const analysisEnabled = useAnalysisEnabled();

  if (postId && query.data?.post) {
    return <PostView key={`${postId}:${fixture ?? ''}`} postId={postId} detail={query.data} api={api} fixture={fixture} />;
  }
  if (postId && query.isPending) return <PostSkeleton />;
  return (
    <div className={PAGE_CLASS}>
      <div className={gridClass(analysisEnabled)}>
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
  const briefing = discussion?.briefing && typeof discussion.briefing === 'object' && !Array.isArray(discussion.briefing)
    ? discussion.briefing as Record<string, unknown>
    : null;
  return {
    comments: Array.isArray(discussion?.comments) ? discussion.comments as RedditComment[] : [],
    fetchedAt: typeof discussion?.fetched_at === 'string' ? discussion.fetched_at : null,
    briefing: typeof briefing?.summary_markdown === 'string' ? briefing.summary_markdown : null,
    briefingModel: typeof briefing?.model === 'string' ? briefing.model : null,
    briefingTokens: typeof briefing?.estimated_tokens === 'number' ? briefing.estimated_tokens : null,
  };
}

function PostView({ postId, detail, api, fixture }: { postId: string; detail: PostDetailResponse; api: Api; fixture: string | null }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const analysisEnabled = useAnalysisEnabled();
  const initial = useMemo(() => initialComments(detail.post as Post), [detail.post]);
  const [post, setPost] = useState<Post>(detail.post as Post);
  const [notes, setNotes] = useState(() => detail.notes?.notes_markdown || defaultNotesTemplate(detail.post));
  const [summary, setSummary] = useState<string | null>(detail.summary?.summary_markdown || null);
  const [summaryModel, setSummaryModel] = useState<string | null>(detail.summary?.model || null);
  const [summaryEstimatedTokens, setSummaryEstimatedTokens] = useState<number | null>(detail.summary?.estimated_tokens ?? null);
  const [summaryTakeaway, setSummaryTakeaway] = useState<string | null>(detail.summary?.one_sentence_takeaway || null);
  const [highlights, setHighlights] = useState<PostHighlight[]>(Array.isArray(detail.highlights) ? detail.highlights : []);
  const [summaryReferences, setSummaryReferences] = useState<BriefingReference[]>(Array.isArray(detail.summary_references) ? detail.summary_references : []);
  const [readerState, setReaderState] = useState<ReaderState | null>(detail.reader_state || null);
  const [storyPrimary, setStoryPrimary] = useState<StoryCard | null>(null);
  const [storyDetail, setStoryDetail] = useState<StoryDetail | null>(null);
  const [storyTimeline, setStoryTimeline] = useState<PostTimelineResponse['timeline'] | null>(null);
  const [storyCandidates, setStoryCandidates] = useState<StoryCandidateLink[]>([]);
  const [timelineLoaded, setTimelineLoaded] = useState(false);
  const [youtubeEvaluation, setYouTubeEvaluation] = useState<YouTubeVideoEvaluationResponse | null>(null);
  const [youtubeProgress, setYouTubeProgress] = useState<YouTubeWatchProgress | null>(null);
  const [youtubeProgressDraft, setYouTubeProgressDraft] = useState(0);
  const [comments, setComments] = useState<RedditComment[]>(initial.comments);
  const [commentsFetchedAt, setCommentsFetchedAt] = useState<string | null>(initial.fetchedAt);
  const [commentsBriefing, setCommentsBriefing] = useState<string | null>(initial.briefing);
  const [commentsBriefingModel, setCommentsBriefingModel] = useState<string | null>(initial.briefingModel);
  const [commentsBriefingEstimatedTokens, setCommentsBriefingEstimatedTokens] = useState<number | null>(initial.briefingTokens);
  const [activeTab, setActiveTab] = useState<'notes' | 'chat'>('notes');
  const [chatQuestion, setChatQuestion] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [loadingHighlights, setLoadingHighlights] = useState(false);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [loadingYouTubeEvaluation, setLoadingYouTubeEvaluation] = useState(false);
  const [loadingYouTubeProgress, setLoadingYouTubeProgress] = useState(false);
  const [loadingComments, setLoadingComments] = useState(false);
  const [loadingCommentsBriefing, setLoadingCommentsBriefing] = useState(false);
  const [savingNotes, setSavingNotes] = useState(false);
  const [savingYouTubeProgress, setSavingYouTubeProgress] = useState(false);
  const [togglingFavorite, setTogglingFavorite] = useState(false);
  const [actingCandidateId, setActingCandidateId] = useState<string | null>(null);
  const [chatting, setChatting] = useState(false);
  const [chatContext, setChatContext] = useState<PostChatContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied'>('idle');
  const [announcement, setAnnouncement] = useState('');
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const openRecordedRef = useRef(false);
  const mutations = useReaderMutations({ dryRun: Boolean(fixture) });
  const [shortcutsOn] = useShortcutPreference();
  const prefetch = usePrefetchPost();

  const loadSummary = async (refresh = false) => {
    if (!postId) return;
    setLoadingSummary(true);
    setError(null);
    const response = await api.getPostSummary(postId, refresh);
    if (!response.success) {
      setError(response.error || 'Failed to generate post summary');
      setLoadingSummary(false);
      return;
    }
    setSummary(response.summary_markdown || null);
    setSummaryModel(response.model || null);
    setSummaryEstimatedTokens(response.estimated_tokens ?? null);
    setSummaryTakeaway(response.one_sentence_takeaway || null);
    setSummaryReferences(Array.isArray(response.references) ? response.references : []);
    setHighlights(response.highlights || []);
    if (response.categories?.length) {
      setPost((current) => current ? { ...current, categories: response.categories } : current);
    }
    setLoadingSummary(false);
  };

  const loadHighlights = async (refresh = false) => {
    if (!postId) return;
    setLoadingHighlights(true);
    setError(null);
    const response = await api.getPostHighlights(postId, refresh);
    if (!response.success) {
      setError(response.error || 'Failed to generate highlights');
      setLoadingHighlights(false);
      return;
    }
    setHighlights(response.highlights || []);
    setSummaryTakeaway(response.one_sentence_takeaway || null);
    setLoadingHighlights(false);
  };

  const loadTimeline = async (refresh = false) => {
    if (!postId) return;
    setLoadingTimeline(true);
    setError(null);
    const response = await api.getPostTimeline(postId, refresh);
    if (!response.success) {
      setError(response.error || 'Failed to load story timeline');
      setLoadingTimeline(false);
      return;
    }
    setStoryPrimary(response.primary_story || null);
    setStoryDetail(response.story || null);
    setStoryTimeline(response.timeline || null);
    setStoryCandidates(Array.isArray(response.related_candidates) ? response.related_candidates : []);
    setTimelineLoaded(true);
    setLoadingTimeline(false);
  };

  const loadYouTubeEvaluation = async () => {
    if (!post || post.platform !== 'youtube') return;
    const videoRef = post.external_id || post.url;
    if (!videoRef) return;
    setLoadingYouTubeEvaluation(true);
    setError(null);
    const response = await api.evaluateYouTubeVideo(post.source, videoRef);
    if (!response.success) {
      setError(response.error || 'Failed to generate YouTube watch guide');
      setLoadingYouTubeEvaluation(false);
      return;
    }
    setYouTubeEvaluation(response);
    setLoadingYouTubeEvaluation(false);
  };

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
      notesMarkdown: notes || null,
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
    setChatContext((current) => current ? { ...current, reddit_comments_loaded: response.comment_count || 0 } : current);
    setLoadingComments(false);
  };

  const generateCommentsBriefing = async (refresh = false) => {
    if (!postId) return;
    setLoadingCommentsBriefing(true);
    setError(null);
    const response = await api.generateRedditCommentsBriefing(postId, { limit: 80, refresh });
    if (!response.success) {
      setError(response.error || 'Failed to generate Reddit discussion briefing');
      setLoadingCommentsBriefing(false);
      return;
    }
    setCommentsBriefing(response.summary_markdown || null);
    setCommentsBriefingModel(response.model || null);
    setCommentsBriefingEstimatedTokens(response.estimated_tokens ?? null);
    setLoadingCommentsBriefing(false);
  };

  const isRedditPost = post?.platform === 'reddit';

  const handleSaveNotes = async () => {
    if (!postId) return;
    setSavingNotes(true);
    const response = await api.savePostNotes(postId, notes);
    if (!response.success) {
      setError(response.error || 'Failed to save notes');
    }
    setSavingNotes(false);
  };

  const handleExportNotes = () => {
    const blob = new Blob([notes], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(post?.title || 'post-notes').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleSendChat = async () => {
    if (!postId || !chatQuestion.trim()) return;
    const question = chatQuestion.trim();
    setChatMessages((prev) => [...prev, { role: 'user', content: question }]);
    setChatQuestion('');
    setChatting(true);
    const response = await api.chatAboutPost(postId, question);
    setChatMessages((prev) => [
      ...prev,
      {
        role: 'assistant',
        content: response.answer || response.error || 'No response returned.',
      },
    ]);
    setChatContext(response.context && typeof response.context === 'object' && !Array.isArray(response.context) ? response.context as PostChatContext : null);
    setChatting(false);
  };

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

  const handleCandidateDecision = async (candidateId: string, decision: 'accept' | 'reject') => {
    setActingCandidateId(candidateId);
    setError(null);
    const response = decision === 'accept'
      ? await api.acceptStoryCandidate(candidateId)
      : await api.rejectStoryCandidate(candidateId);
    if (!response.success) {
      setError(response.error || `Failed to ${decision} story candidate`);
      setActingCandidateId(null);
      return;
    }
    if (response.timeline?.success) {
      setStoryPrimary(response.timeline.primary_story || null);
      setStoryDetail(response.timeline.story || null);
      setStoryTimeline(response.timeline.timeline || null);
      setStoryCandidates(Array.isArray(response.timeline.related_candidates) ? response.timeline.related_candidates : []);
    } else {
      await loadTimeline(false);
    }
    setActingCandidateId(null);
  };

  const openRelatedPost = (targetPostId?: string | null) => {
    if (!targetPostId || targetPostId === postId) return;
    navigate(`/posts/${encodeURIComponent(targetPostId)}`, {
      state: { returnTo: `${location.pathname}${location.search}` },
    });
  };

  const formatTimelineDate = (value?: string | null) => {
    if (!value) return 'Unknown date';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleDateString();
  };

  const categories = Array.isArray(post?.categories) ? post.categories : [];
  const topics = Array.isArray(post?.topics) ? post.topics : [];
  const platformLabel = typeof post?.platform === 'string' ? post.platform.toLowerCase() : '';
  const renderContent = typeof post?.content_html === 'string'
    ? post.content_html
    : typeof post?.content === 'string'
      ? post.content
      : '';
  // Images the body already shows stay inline; the rest: the first under the
  // title, the others after the text. A video post shows its player instead.
  const media = useMemo(() => postMedia(post, `${renderContent}\n${post.content || ''}`), [post, renderContent]);
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
  const youtubeChapters = useMemo(
    () => (youtubeEvaluation?.chapters?.length ? youtubeEvaluation.chapters : (youtubeMetadata?.chapters || [])),
    [youtubeEvaluation?.chapters, youtubeMetadata?.chapters],
  );
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
  const summaryReferenceHighlightIds = useMemo(
    () => new Set(
      summaryReferences
        .map((reference) => reference.highlight_id)
        .filter((highlightId): highlightId is string => Boolean(highlightId)),
    ),
    [summaryReferences],
  );
  const contentHighlightRanges = useMemo(
    () => (analysisEnabled ? buildResolvedHighlightRanges(post?.content || '', highlights, summaryReferenceHighlightIds) : []),
    [analysisEnabled, highlights, post?.content, summaryReferenceHighlightIds],
  );
  const highlightedContentBlock = useMemo(
    () => renderHighlightedContent(post?.content || '', contentHighlightRanges),
    [contentHighlightRanges, post?.content],
  );
  const mappedHighlightCount = contentHighlightRanges.length;
  const isFavorited = Boolean(readerState?.is_favorited);
  const safeCommentPreview = (comment: RedditComment) => {
    const body = typeof comment.body === 'string' ? comment.body : '';
    return body.slice(0, 24);
  };
  const sourceName = postSourceName(post);
  const displayTitle = useMemo(() => displayPostTitle(post.title, postPlainText(post)), [post]);
  const publishedLabel = formatPublished(post?.published_at || post?.fetched_at || null);
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


  const renderTimelineUpdate = (update: StoryUpdateEntry, relationLabel: string) => (
    <li key={update.id} className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.75rem] tabular-nums text-fg-3">
        <span className="font-medium text-fg-2">{relationLabel}</span>
        <span>{formatTimelineDate(update.update_date)}</span>
        {typeof update.importance_score === 'number' ? <span>importance {update.importance_score.toFixed(2)}</span> : null}
        {update.post_count ? <span>{plural(update.post_count, 'post')}</span> : null}
      </div>
      <div className="mt-1 font-semibold text-fg [overflow-wrap:anywhere]">{update.title}</div>
      {update.summary ? <p className="mt-1 text-[0.875rem] text-fg-2">{update.summary}</p> : null}
      {update.posts?.length ? (
        <ul className="mt-2 space-y-1 text-[0.8125rem]">
          {update.posts.map((entry) => (
            <li key={`${update.id}-${entry.post_id}`}>
              {entry.post_id === postId ? (
                <span aria-current="page" className="font-semibold text-fg">
                  ● {entry.post?.title || entry.post_id} <span className="font-normal text-fg-3">(this post)</span>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => openRelatedPost(entry.post_id)}
                  className="text-left text-link [overflow-wrap:anywhere]"
                >
                  {entry.post?.title || entry.post_id}
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );

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
  }, { enabled: !helpOpen && !inspectorOpen, singleKeys: shortcutsOn });

  const hasReadingStats = readerState && (readerState.open_count || readerState.total_read_seconds || readerState.first_opened_at);

  return (
    <div className={PAGE_CLASS}>
      <div className={gridClass(analysisEnabled)}>
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
            {analysisEnabled ? (
              <div className="mt-4">
                <Button size="sm" variant="ghost" className="-ml-2.5" onClick={() => setInspectorOpen(true)} aria-haspopup="dialog">
                  <PanelRight aria-hidden="true" />
                  Inspect
                </Button>
              </div>
            ) : null}
            <span aria-live="polite" className="sr-only">{announcement}</span>
          </header>

          {heroImage ? <PostFigure image={heroImage} className="mb-10" /> : null}
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
                {youtubeDurationSeconds ? <span>{formatDurationLabel(youtubeDurationSeconds)}</span> : null}
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
                      : `${formatDurationLabel(youtubeProgressDraft)} / ${formatDurationLabel(youtubeDurationSeconds)}`}
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
                    {youtubeProgress?.last_watched_at ? `last ${new Date(youtubeProgress.last_watched_at).toLocaleString()}` : null}
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
                  {analysisEnabled ? (
                    <Button size="sm" variant="secondary" onClick={() => void loadYouTubeEvaluation()} disabled={loadingYouTubeEvaluation}>
                      <Busy when={loadingYouTubeEvaluation}>{null}</Busy>
                      {youtubeEvaluation?.summary_markdown ? 'Refresh watch guide' : 'Generate watch guide'}
                    </Button>
                  ) : null}
                  {/* Reading-only: the header's ↗ already opens the video. */}
                  {analysisEnabled && youtubeVideoUrl && (
                    <Button asChild size="sm" variant="ghost">
                      <a href={youtubeVideoUrl} target="_blank" rel="noopener noreferrer">
                        Open on YouTube
                        <ArrowUpRight aria-hidden="true" />
                      </a>
                    </Button>
                  )}
                </div>
              </div>

              {youtubeEvaluation?.summary_markdown ? (
                <div className="rounded-md border border-line p-4">
                  <h2 className="mb-2 text-[0.875rem] font-semibold text-fg">Watch guide</h2>
                  <div className="text-[0.9375rem] leading-[1.6]">
                    <MarkdownRenderer content={youtubeEvaluation.summary_markdown} />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {youtubeEvaluation.depth ? <Chip>depth {youtubeEvaluation.depth}</Chip> : null}
                    {youtubeEvaluation.novelty ? <Chip>novelty {youtubeEvaluation.novelty}</Chip> : null}
                    {youtubeEvaluation.worth_watching ? <Chip variant="solid">{youtubeEvaluation.worth_watching}</Chip> : null}
                  </div>
                  {youtubeEvaluation.reasoning ? (
                    <p className="mt-3 text-[0.875rem] text-fg-2">{youtubeEvaluation.reasoning}</p>
                  ) : null}
                </div>
              ) : null}

              {analysisEnabled || youtubeChapters.length ? (
              <div>
                <h2 className="mb-2 text-[0.875rem] font-semibold text-fg">Chapters</h2>
                {youtubeChapters.length ? (
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
                          <span className="w-12 shrink-0 tabular-nums text-fg-3">{formatDurationLabel(Number(chapter.start_seconds || 0))}</span>
                          <span className="min-w-0 font-medium text-fg [overflow-wrap:anywhere]">{chapter.title || `Chapter ${index + 1}`}</span>
                        </a>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-[0.875rem] text-fg-3">No chapters were extracted for this video yet.</p>
                )}
              </div>
              ) : null}
            </section>
          )}

          {/* ---- Summary: folded, secondary to the text (analysis only) ---- */}
          {analysisEnabled ? (
          <details
            className="group mb-10 rounded-md border border-line"
            open={Boolean(summary) || loadingSummary || undefined}
          >
            <summary className="flex cursor-pointer list-none items-baseline gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
              <span aria-hidden="true" className="w-3 shrink-0 text-fg-3 group-open:rotate-90">›</span>
              <span className="text-[0.9375rem] font-semibold text-fg">Summary</span>
              <span className="min-w-0 truncate text-[0.8125rem] tabular-nums text-fg-3">
                {summary
                  ? [summaryModel, summaryReferences.length ? plural(summaryReferences.length, 'reference') : null].filter(Boolean).join(' · ')
                  : 'not generated yet'}
              </span>
            </summary>
            <div className="border-t border-line px-4 pb-4 pt-3">
              {summaryTakeaway ? (
                <p className="mb-3 text-[1rem] font-medium leading-[1.55] text-fg">{summaryTakeaway}</p>
              ) : null}
              {loadingSummary && !summary ? (
                <LoadingState label="Generating summary" rows={2} />
              ) : summary ? (
                <div className="text-[0.9375rem] leading-[1.65] text-fg">
                  <MarkdownRenderer content={summary} />
                </div>
              ) : (
                <p className="text-[0.875rem] text-fg-2">Generate a summary of this post when you want the short version.</p>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button size="sm" variant="secondary" onClick={() => void loadSummary(true)} disabled={loadingSummary}>
                  <Busy when={loadingSummary}>{null}</Busy>
                  {summary ? 'Refresh summary' : 'Generate summary'}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => void loadHighlights(true)} disabled={loadingHighlights}>
                  <Busy when={loadingHighlights}>{null}</Busy>
                  {highlights.length ? 'Refresh highlights' : 'Generate highlights'}
                </Button>
                {summaryEstimatedTokens ? (
                  <span className="text-[0.75rem] tabular-nums text-fg-3">~{formatCount(summaryEstimatedTokens)} tokens</span>
                ) : null}
              </div>
            </div>
          </details>
          ) : null}

          {/* ---- The article ---- */}
          <article aria-label={isYouTubePost ? 'Transcript' : 'Post content'} className="min-w-0">
            {(analysisEnabled && highlights.length) || (isYouTubePost && youtubeTranscriptBlocks.length) ? (
              <p className="mb-5 flex flex-wrap gap-x-3 gap-y-1 text-[0.8125rem] tabular-nums text-fg-3">
                {isYouTubePost && youtubeTranscriptBlocks.length ? <span>{plural(youtubeTranscriptBlocks.length, 'transcript section')}</span> : null}
                {analysisEnabled && highlights.length ? <span>{plural(highlights.length, 'highlight')} · {formatCount(mappedHighlightCount)} shown in the text</span> : null}
                {summaryReferenceHighlightIds.size > 0 ? (
                  <span>
                    <span className="text-fg underline decoration-fg underline-offset-[0.22em]">underlined</span> = used in the summary
                  </span>
                ) : null}
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
                          <span className="text-[0.8125rem] tabular-nums text-fg-3">{formatDurationLabel(block.startSeconds)}</span>
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
                                  Open at {formatDurationLabel(block.startSeconds)}
                                  <ArrowUpRight aria-hidden="true" />
                                </a>
                              </Button>
                            ) : null}
                          </span>
                        </div>
                        {renderHighlightedContent(block.text, contentHighlightRanges, block.charOffset, false)}
                      </section>
                    ))
                  ) : post.content ? (
                    renderHighlightedContent(post.content, contentHighlightRanges)
                  ) : (
                    <p className="text-[0.9375rem] text-fg-3">No transcript was stored for this video yet.</p>
                  )}
                </div>
              ) : analysisEnabled && highlights.length && post.content ? (
                highlightedContentBlock
              ) : (
                <MarkdownRenderer content={renderContent} />
              )}
            </div>
          </article>

          <PostImageList images={moreImages} />

          {/* ---- Reddit discussion ---- */}
          {isRedditPost && (
            <section className="mt-14" aria-labelledby="post-discussion">
              <SectionHeading
                title="Discussion"
                meta={[
                  comments.length ? plural(comments.length, 'comment') : 'no comments loaded',
                  commentsFetchedAt ? `fetched ${new Date(commentsFetchedAt).toLocaleString()}` : null,
                ].filter(Boolean).join(' · ')}
                actions={(
                  <>
                    <Button size="sm" variant="secondary" onClick={() => void fetchComments(true)} disabled={loadingComments}>
                      <Busy when={loadingComments}>{null}</Busy>
                      {comments.length ? 'Refresh comments' : 'Fetch comments'}
                    </Button>
                    {analysisEnabled ? (
                      <Button size="sm" variant="ghost" onClick={() => void generateCommentsBriefing(true)} disabled={loadingCommentsBriefing}>
                        <Busy when={loadingCommentsBriefing}>{null}</Busy>
                        {commentsBriefing ? 'Refresh briefing' : 'Brief the thread'}
                      </Button>
                    ) : null}
                  </>
                )}
              />
              <span id="post-discussion" className="sr-only">Discussion</span>
              {analysisEnabled && commentsBriefing ? (
                <div className="mb-6 rounded-md border border-line p-4">
                  <h3 className="mb-2 text-[0.875rem] font-semibold text-fg">Thread briefing</h3>
                  <div className="text-[0.9375rem] leading-[1.6]">
                    <MarkdownRenderer content={commentsBriefing} />
                  </div>
                  {commentsBriefingModel ? (
                    <p className="mt-3 text-[0.75rem] tabular-nums text-fg-3">
                      {commentsBriefingModel}
                      {commentsBriefingEstimatedTokens ? ` · ~${formatCount(commentsBriefingEstimatedTokens)} tokens` : ''}
                    </p>
                  ) : null}
                </div>
              ) : null}
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

          {analysisEnabled ? (
          <>
          {/* ---- Story timeline: folded, loaded only when it is opened ---- */}
          <details
            className="group mt-14 rounded-md border border-line"
            onToggle={(event) => {
              if (event.currentTarget.open && !timelineLoaded && !loadingTimeline) void loadTimeline(false);
            }}
          >
            <summary className="flex cursor-pointer list-none items-baseline gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
              <span aria-hidden="true" className="w-3 shrink-0 text-fg-3 group-open:rotate-90">›</span>
              <span className="text-[0.9375rem] font-semibold text-fg">Story</span>
              <span className="min-w-0 truncate text-[0.8125rem] text-fg-3">
                {!timelineLoaded ? 'story and related posts' : storyPrimary ? storyPrimary.canonical_title : 'not attached to a story yet'}
              </span>
            </summary>
            <div className="border-t border-line px-4 pb-4 pt-3">
              <div className="mb-3 flex justify-end">
                <Button size="sm" variant="ghost" onClick={() => void loadTimeline(true)} disabled={loadingTimeline}>
                  <Busy when={loadingTimeline}>{null}</Busy>
                  Refresh
                </Button>
              </div>
              {loadingTimeline && !timelineLoaded ? <LoadingState label="Loading the story" rows={2} /> : (
              <>
            {storyPrimary ? (
              <div className="mb-5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-semibold text-fg [overflow-wrap:anywhere]">{storyPrimary.canonical_title}</span>
                  {storyPrimary.story_kind ? <Chip>{storyPrimary.story_kind}</Chip> : null}
                  {storyPrimary.status ? <Chip variant="quiet">{storyPrimary.status}</Chip> : null}
                </div>
                {storyDetail?.canonical_summary && (
                  <p className="mt-2 text-[0.9375rem] leading-[1.6] text-fg-2">{storyDetail.canonical_summary}</p>
                )}
              </div>
            ) : null}

            {storyTimeline?.current_update || storyTimeline?.earlier_updates?.length || storyTimeline?.later_updates?.length ? (
              <ol className="mb-6 divide-y divide-line rounded-md border border-line">
                {storyTimeline?.later_updates?.map((update) => renderTimelineUpdate(update, 'later'))}
                {storyTimeline?.current_update ? renderTimelineUpdate(storyTimeline.current_update, 'current') : null}
                {storyTimeline?.earlier_updates?.map((update) => renderTimelineUpdate(update, 'earlier'))}
              </ol>
            ) : null}

            <h3 className="mb-2 text-[0.875rem] font-semibold text-fg">
              Related posts <span className="font-normal tabular-nums text-fg-3">{storyCandidates.length ? formatCount(storyCandidates.length) : ''}</span>
            </h3>
            {storyCandidates.length ? (
              <ul className="divide-y divide-line rounded-md border border-line">
                {storyCandidates.map((candidate) => (
                  <li key={candidate.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
                    <div className="min-w-0 flex-1 basis-[16rem]">
                      <button
                        type="button"
                        onClick={() => openRelatedPost(candidate.candidate_post_id)}
                        className="text-left text-[0.9375rem] font-semibold text-fg underline-offset-[0.2em] hover:underline [overflow-wrap:anywhere]"
                      >
                        {candidate.candidate_post?.title || candidate.candidate_post_id}
                      </button>
                      <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[0.75rem] tabular-nums text-fg-3">
                        <span className="[overflow-wrap:anywhere]">{candidate.candidate_post ? postSourceName(candidate.candidate_post) : 'Unknown source'}</span>
                        <span>· {candidate.candidate_post?.platform || 'unknown'}</span>
                        <span>· {formatTimelineDate(candidate.candidate_post?.published_at || candidate.candidate_post?.fetched_at || null)}</span>
                        <span>· {candidate.retrieval_method}</span>
                        <span>· score {candidate.retrieval_score.toFixed(2)}</span>
                        <span className={candidate.decision_status === 'accepted' ? 'font-semibold text-fg' : undefined}>· {candidate.decision_status}</span>
                      </div>
                      {candidate.decision_reason ? (
                        <p className="mt-1 text-[0.875rem] text-fg-2">{candidate.decision_reason}</p>
                      ) : null}
                    </div>
                    <div className="flex gap-1.5">
                      {candidate.decision_status !== 'accepted' && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => void handleCandidateDecision(candidate.id, 'accept')}
                          disabled={actingCandidateId === candidate.id}
                        >
                          <Busy when={actingCandidateId === candidate.id}>{null}</Busy>
                          Accept
                        </Button>
                      )}
                      {candidate.decision_status !== 'rejected' && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void handleCandidateDecision(candidate.id, 'reject')}
                          disabled={actingCandidateId === candidate.id}
                        >
                          Reject
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[0.875rem] text-fg-3">No related posts were found for this timeline window.</p>
            )}
              </>
              )}
            </div>
          </details>

          {/* ---- Tags, topics, reading stats ---- */}
          <section className="mt-14">
            <SectionHeading title="Tags and topics" />
            {categories.length ? (
              <div className="flex flex-wrap gap-1.5">
                {categories.map((category) => (
                  <Chip key={category}>{category}</Chip>
                ))}
              </div>
            ) : (
              <p className="text-[0.875rem] text-fg-3">No tags stored.</p>
            )}
            {topics.length ? (
              <ul className="mt-4 divide-y divide-line rounded-md border border-line">
                {topics.map((topic) => (
                  <li key={topic.id}>
                    <button
                      type="button"
                      onClick={() => navigate(`/briefing?date=${encodeURIComponent(topic.date || '')}&mode=topics&topic=${encodeURIComponent(topic.id)}`)}
                      className="flex w-full items-baseline gap-4 px-4 py-2.5 text-left text-[0.875rem] hover:bg-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-fg"
                    >
                      <span className="w-24 shrink-0 tabular-nums text-fg-3">{topic.date || '—'}</span>
                      <span className="min-w-0 font-medium text-fg [overflow-wrap:anywhere]">{topic.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-[0.875rem] text-fg-3">No connected briefing topics yet.</p>
            )}

            <p className="mt-8 flex flex-wrap gap-x-3 gap-y-1 border-t border-line pt-4 text-[0.75rem] tabular-nums text-fg-3">
              {hasReadingStats ? (
                <>
                  {readerState?.open_count ? <span>opened {plural(readerState.open_count, 'time')}</span> : null}
                  <span>read {formatReadTime(readerState?.total_read_seconds)}</span>
                  {readerState?.first_opened_at ? <span>first {new Date(readerState.first_opened_at).toLocaleString()}</span> : null}
                  {readerState?.last_opened_at ? <span>last {new Date(readerState.last_opened_at).toLocaleString()}</span> : null}
                </>
              ) : (
                <span>first time reading this post</span>
              )}
              {summaryReferenceHighlightIds.size > 0 ? (
                <span>{plural(summaryReferenceHighlightIds.size, 'highlight')} used by the summary</span>
              ) : null}
            </p>
          </section>
          </>
          ) : null}
        </div>

        {/* ---- Notes and chat: a quiet side column on wide screens (analysis only) ---- */}
        {analysisEnabled ? (
        <aside aria-label="Notes and chat" className="min-w-0 xl:sticky xl:top-[calc(var(--topbar-h)+1.5rem)] xl:self-start">
          <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as 'notes' | 'chat')}>
            <TabsList aria-label="Workspace">
              <TabsTrigger value="notes">notes</TabsTrigger>
              <TabsTrigger value="chat">chat</TabsTrigger>
            </TabsList>
            <TabsContent value="notes" className="pt-4">
              <Textarea
                aria-label="Notes for this post"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={16}
                className="font-mono text-[0.8125rem] leading-[1.6]"
              />
              <div className="mt-2 flex justify-end gap-1.5">
                <Button size="sm" variant="ghost" onClick={handleExportNotes}>
                  <Download aria-hidden="true" />
                  Export
                </Button>
                <Button size="sm" variant="primary" onClick={() => void handleSaveNotes()} disabled={savingNotes}>
                  <Busy when={savingNotes}>{null}</Busy>
                  Save notes
                </Button>
              </div>
            </TabsContent>
            <TabsContent value="chat" className="space-y-3 pt-4">
              <p className="text-[0.8125rem] text-fg-2">
                Ask about this post only. The answer draws on the post, its source, tags, your notes, the summary and any fetched comments.
              </p>
              {chatContext && (
                <p className="text-[0.75rem] tabular-nums text-fg-3">
                  Context: {formatCount(chatContext.content_chars || 0)} characters · {plural(chatContext.reddit_comments_loaded || 0, 'comment')} · {plural(chatContext.topics_loaded || 0, 'topic')}
                </p>
              )}
              <div className="max-h-[22rem] min-h-[8rem] space-y-3 overflow-y-auto rounded-md border border-line p-3" aria-live="polite">
                {chatMessages.length === 0 ? (
                  <p className="text-[0.8125rem] text-fg-3">
                    No questions yet. Try what matters here, why, or what it implies.
                  </p>
                ) : (
                  chatMessages.map((message, index) => (
                    <div
                      key={`${message.role}-${index}`}
                      className={message.role === 'assistant' ? 'text-[0.875rem] leading-[1.55]' : 'border-l-2 border-fg pl-2.5 text-[0.875rem] font-medium leading-[1.55]'}
                    >
                      <div className="mb-0.5 text-[0.75rem] text-fg-3">{message.role === 'assistant' ? 'answer' : 'you'}</div>
                      <MarkdownRenderer content={message.content} />
                    </div>
                  ))
                )}
              </div>
              <Textarea
                aria-label="Question about this post"
                value={chatQuestion}
                onChange={(e) => setChatQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    void handleSendChat();
                  }
                }}
                placeholder="Ask a precise question about this post…"
                rows={3}
              />
              <Button
                variant="primary"
                size="sm"
                onClick={() => void handleSendChat()}
                disabled={chatting || !chatQuestion.trim()}
                className="w-full"
              >
                <Busy when={chatting}>{null}</Busy>
                Ask
              </Button>
            </TabsContent>
          </Tabs>
        </aside>
        ) : null}
      </div>

      {analysisEnabled && postId && (
        <Sheet open={inspectorOpen} onOpenChange={setInspectorOpen}>
          <SheetContent title="Post intelligence" className="w-[min(40rem,100vw)]">
            <PostDetailPageErrorBoundary>
              <PostIntelligenceInspector postId={postId} post={post} />
            </PostDetailPageErrorBoundary>
          </SheetContent>
        </Sheet>
      )}
      <ShortcutHelp open={helpOpen} onOpenChange={setHelpOpen} />
      <DevDataSwitch options={POST_FIXTURE_NAMES} />
    </div>
  );
}
