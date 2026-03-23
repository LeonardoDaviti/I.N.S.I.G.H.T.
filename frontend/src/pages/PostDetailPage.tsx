import { useEffect, useMemo, useRef, useState, Component } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  BookOpen,
  Check,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  MessageSquareText,
  NotebookPen,
  RefreshCw,
  Save,
  Split,
  Sparkles,
  Star,
  Tags,
  X,
  MessagesSquare,
} from 'lucide-react';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import PostIntelligenceInspector from '../components/PostIntelligenceInspector';
import { apiService } from '../services/api';
import type {
  BriefingReference,
  Post,
  PostHighlight,
  PostTimelineResponse,
  ReaderState,
  RedditComment,
  StoryCandidateLink,
  StoryCard,
  StoryDetail,
  StoryUpdateEntry,
} from '../services/api';

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
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
        <section className="app-panel p-6">
          <div className="text-lg font-semibold text-[var(--text-normal)]">Post intelligence unavailable</div>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            One of the post-detail render blocks failed to load. The rest of the post view remains available.
          </p>
        </section>
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

type ResolvedHighlightRange = {
  start: number;
  end: number;
  usedInSummary: boolean;
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

function renderHighlightedContent(content: string, ranges: ResolvedHighlightRange[]) {
  if (!ranges.length) {
    return (
      <div className="whitespace-pre-wrap leading-8 text-[var(--text-normal)]">
        {content}
      </div>
    );
  }

  const nodes: ReactNode[] = [];
  let cursor = 0;

  ranges.forEach((range, index) => {
    if (range.start > cursor) {
      nodes.push(
        <span key={`plain-${index}-${cursor}`}>
          {content.slice(cursor, range.start)}
        </span>,
      );
    }

    nodes.push(
      <mark
        key={`mark-${index}-${range.start}`}
        className={`rounded px-1 py-0.5 text-[var(--text-normal)] ${
          range.usedInSummary
            ? 'bg-yellow-300/85 shadow-[inset_0_-0.45em_0_rgba(253,224,71,0.45)]'
            : 'bg-yellow-200/80 shadow-[inset_0_-0.45em_0_rgba(253,230,138,0.4)]'
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

  return (
    <div className="whitespace-pre-wrap leading-8 text-[var(--text-normal)]">
      {nodes}
    </div>
  );
}

export default function PostDetailPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { postId } = useParams();
  const [post, setPost] = useState<Post | null>(null);
  const [notes, setNotes] = useState('');
  const [summary, setSummary] = useState<string | null>(null);
  const [summaryModel, setSummaryModel] = useState<string | null>(null);
  const [summaryEstimatedTokens, setSummaryEstimatedTokens] = useState<number | null>(null);
  const [summaryTakeaway, setSummaryTakeaway] = useState<string | null>(null);
  const [highlights, setHighlights] = useState<PostHighlight[]>([]);
  const [summaryReferences, setSummaryReferences] = useState<BriefingReference[]>([]);
  const [readerState, setReaderState] = useState<ReaderState | null>(null);
  const [storyPrimary, setStoryPrimary] = useState<StoryCard | null>(null);
  const [storyDetail, setStoryDetail] = useState<StoryDetail | null>(null);
  const [storyTimeline, setStoryTimeline] = useState<PostTimelineResponse['timeline'] | null>(null);
  const [storyCandidates, setStoryCandidates] = useState<StoryCandidateLink[]>([]);
  const [comments, setComments] = useState<RedditComment[]>([]);
  const [commentsFetchedAt, setCommentsFetchedAt] = useState<string | null>(null);
  const [commentsBriefing, setCommentsBriefing] = useState<string | null>(null);
  const [commentsBriefingModel, setCommentsBriefingModel] = useState<string | null>(null);
  const [commentsBriefingEstimatedTokens, setCommentsBriefingEstimatedTokens] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<'notes' | 'chat'>('notes');
  const [chatQuestion, setChatQuestion] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [loadingHighlights, setLoadingHighlights] = useState(false);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [loadingComments, setLoadingComments] = useState(false);
  const [loadingCommentsBriefing, setLoadingCommentsBriefing] = useState(false);
  const [savingNotes, setSavingNotes] = useState(false);
  const [togglingFavorite, setTogglingFavorite] = useState(false);
  const [actingCandidateId, setActingCandidateId] = useState<string | null>(null);
  const [chatting, setChatting] = useState(false);
  const [chatContext, setChatContext] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sessionStartRef = useRef<number | null>(null);
  const openRecordedRef = useRef(false);

  const sourceLabel = useMemo(
    () => post?.source_display_name || post?.source || 'Unknown source',
    [post],
  );

  const loadSummary = async (refresh = false) => {
    if (!postId) return;
    setLoadingSummary(true);
    setError(null);
    const response = await apiService.getPostSummary(postId, refresh);
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
    const response = await apiService.getPostHighlights(postId, refresh);
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
    const response = await apiService.getPostTimeline(postId, refresh);
    if (!response.success) {
      setError(response.error || 'Failed to load story timeline');
      setLoadingTimeline(false);
      return;
    }
    setStoryPrimary(response.primary_story || null);
    setStoryDetail(response.story || null);
    setStoryTimeline(response.timeline || null);
    setStoryCandidates(Array.isArray(response.related_candidates) ? response.related_candidates : []);
    setLoadingTimeline(false);
  };

  useEffect(() => {
    let active = true;

    const loadPost = async () => {
      if (!postId) {
        if (active) {
          setError('Missing post id');
          setLoading(false);
        }
        return;
      }

      if (active) {
        setLoading(true);
        setError(null);
      }

      const response = await apiService.getPostDetail(postId);
      if (!active) {
        return;
      }

      if (!response.success || !response.post) {
        setError(response.error || 'Failed to load post');
        setLoading(false);
        return;
      }

      setPost(response.post);
      setNotes(response.notes?.notes_markdown || defaultNotesTemplate(response.post));
      setSummary(response.summary?.summary_markdown || null);
      setSummaryModel(response.summary?.model || null);
      setSummaryEstimatedTokens(response.summary?.estimated_tokens ?? null);
      setSummaryTakeaway(response.summary?.one_sentence_takeaway || null);
      setSummaryReferences(Array.isArray(response.summary_references) ? response.summary_references : []);
      setHighlights(Array.isArray(response.highlights) ? response.highlights : []);
      setReaderState(response.reader_state || null);
      const metadata = response.post.metadata && typeof response.post.metadata === 'object' && !Array.isArray(response.post.metadata)
        ? response.post.metadata as Record<string, unknown>
        : null;
      const discussion = metadata?.reddit_discussion && typeof metadata.reddit_discussion === 'object' && !Array.isArray(metadata.reddit_discussion)
        ? metadata.reddit_discussion as Record<string, unknown>
        : null;
      setComments(Array.isArray(discussion?.comments) ? discussion.comments as RedditComment[] : []);
      setCommentsFetchedAt(discussion?.fetched_at || null);
      const briefing = discussion?.briefing && typeof discussion.briefing === 'object' && !Array.isArray(discussion.briefing)
        ? discussion.briefing as Record<string, unknown>
        : null;
      setCommentsBriefing(typeof briefing?.summary_markdown === 'string' ? briefing.summary_markdown : null);
      setCommentsBriefingModel(typeof briefing?.model === 'string' ? briefing.model : null);
      setCommentsBriefingEstimatedTokens(typeof briefing?.estimated_tokens === 'number' ? briefing.estimated_tokens : null);
      setLoading(false);
    };

    void loadPost();
    return () => {
      active = false;
    };
  }, [postId]);

  useEffect(() => {
    void loadTimeline(false);
  }, [postId]);

  useEffect(() => {
    sessionStartRef.current = Date.now();
    openRecordedRef.current = false;
  }, [postId]);

  useEffect(() => {
    if (!postId || !post) {
      return undefined;
    }

    if (!openRecordedRef.current) {
      openRecordedRef.current = true;
      void apiService.recordPostOpen(postId, {
        title: post.title,
        source: post.source,
        platform: post.platform,
      }).then((response) => {
        if (!response.success) {
          return;
        }
        const recordedAt = response.event?.created_at || new Date().toISOString();
        setReaderState((current) => {
          if (!current) {
            return {
              post_id: postId,
              is_favorited: false,
              open_count: 1,
              first_opened_at: recordedAt,
              last_opened_at: recordedAt,
              total_read_seconds: 0,
            };
          }
          return {
            ...current,
            open_count: (current.open_count || 0) + 1,
            first_opened_at: current.first_opened_at || recordedAt,
            last_opened_at: recordedAt,
          };
        });
      });
    }

    return () => {
      const startedAt = sessionStartRef.current;
      if (!startedAt) {
        return;
      }
      const durationSeconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
      void apiService.recordPostReadingSession(postId, durationSeconds, {
        title: post.title,
        source: post.source,
        platform: post.platform,
      });
    };
  }, [postId, post?.id]);

  const fetchComments = async (refresh = false) => {
    if (!postId) return;
    setLoadingComments(true);
    setError(null);
    const response = await apiService.fetchRedditComments(postId, { limit: 80, refresh });
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
    const response = await apiService.generateRedditCommentsBriefing(postId, { limit: 80, refresh });
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
    const response = await apiService.savePostNotes(postId, notes);
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
    const response = await apiService.chatAboutPost(postId, question);
    setChatMessages((prev) => [
      ...prev,
      {
        role: 'assistant',
        content: response.answer || response.error || 'No response returned.',
      },
    ]);
    setChatContext(response.context && typeof response.context === 'object' && !Array.isArray(response.context) ? response.context as Record<string, unknown> : null);
    setChatting(false);
  };

  const handleToggleFavorite = async () => {
    if (!postId) return;
    setTogglingFavorite(true);
    const nextFavorited = !(readerState?.is_favorited ?? false);
    const response = await apiService.togglePostFavorite(postId, nextFavorited);
    if (!response.success) {
      setError(response.error || 'Failed to update favorite state');
      setTogglingFavorite(false);
      return;
    }
    if (response.reader_state) {
      setReaderState(response.reader_state);
    } else {
      setReaderState((current) => current ? { ...current, is_favorited: response.favorited } : current);
    }
    setTogglingFavorite(false);
  };

  const handleCandidateDecision = async (candidateId: string, decision: 'accept' | 'reject') => {
    setActingCandidateId(candidateId);
    setError(null);
    const response = decision === 'accept'
      ? await apiService.acceptStoryCandidate(candidateId)
      : await apiService.rejectStoryCandidate(candidateId);
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
  const platformLabel = typeof post?.platform === 'string' ? post.platform.toUpperCase() : '';
  const renderContent = typeof post?.content_html === 'string'
    ? post.content_html
    : typeof post?.content === 'string'
      ? post.content
      : '';
  const summaryReferenceHighlightIds = useMemo(
    () => new Set(
      summaryReferences
        .map((reference) => reference.highlight_id)
        .filter((highlightId): highlightId is string => Boolean(highlightId)),
    ),
    [summaryReferences],
  );
  const contentHighlightRanges = useMemo(
    () => buildResolvedHighlightRanges(post?.content || '', highlights, summaryReferenceHighlightIds),
    [highlights, post?.content, summaryReferenceHighlightIds],
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
  const renderTimelineUpdate = (update: StoryUpdateEntry, relationLabel: string) => (
    <div key={update.id} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">
        <span>{relationLabel}</span>
        <span>{formatTimelineDate(update.update_date)}</span>
        {typeof update.importance_score === 'number' ? <span>Importance {update.importance_score.toFixed(2)}</span> : null}
        {update.post_count ? <span>{update.post_count} posts</span> : null}
      </div>
      <div className="mt-2 text-base font-semibold text-[var(--text-normal)]">{update.title}</div>
      <div className="mt-2 text-sm leading-7 text-[var(--text-muted)]">{update.summary}</div>
      {update.posts?.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {update.posts.map((entry) => (
            <button
              key={`${update.id}-${entry.post_id}`}
              type="button"
              onClick={() => openRelatedPost(entry.post_id)}
              className={`rounded-full border px-3 py-1 text-xs transition ${
                entry.post_id === postId
                  ? 'border-[var(--accent-strong)] bg-[var(--text-highlight-bg)] text-[var(--text-normal)]'
                  : 'border-[var(--background-modifier-border)] bg-[var(--background-primary)] text-[var(--text-muted)] hover:border-[var(--accent-strong)] hover:text-[var(--text-normal)]'
              }`}
            >
              {entry.post?.title || entry.post_id}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );

  if (loading) {
    return (
      <div className="app-shell flex min-h-screen items-center justify-center">
        <div className="app-panel flex items-center gap-3 px-5 py-4 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading post intelligence workspace...
        </div>
      </div>
    );
  }

  if (!post) {
    return (
      <div className="app-shell flex min-h-screen items-center justify-center">
        <div className="app-panel max-w-lg p-6">
          <div className="text-lg font-semibold">Post not found</div>
          <p className="mt-2 text-sm text-[var(--text-muted)]">{error || 'This post does not exist in the database.'}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell min-h-screen px-6 py-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <button
              type="button"
              onClick={() => {
                const returnTo = (location.state as { returnTo?: string } | null)?.returnTo;
                if (returnTo) {
                  navigate(returnTo);
                  return;
                }
                if (window.history.length > 1) {
                  navigate(-1);
                  return;
                }
                navigate('/briefing');
              }}
              className="mb-3 inline-flex items-center gap-2 text-sm text-[var(--text-muted)] transition-colors hover:text-[var(--text-normal)]"
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </button>
            <h1 className="text-3xl font-bold leading-tight text-[var(--text-normal)]">
              {post.title || 'Untitled Post'}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-[var(--text-muted)]">
              <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                {sourceLabel}
              </span>
              <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                {platformLabel}
              </span>
              {post.published_at && (
                <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                  {new Date(post.published_at).toLocaleString()}
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => loadSummary(true)}
              className="app-inline-button"
            >
              {loadingSummary ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {summary ? 'Refresh Summary' : 'Generate Summary'}
            </button>
            <button
              type="button"
              onClick={() => loadHighlights(true)}
              className="app-inline-button"
            >
              {loadingHighlights ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {highlights.length ? 'Refresh Highlights' : 'Generate Highlights'}
            </button>
            <button
              type="button"
              onClick={handleToggleFavorite}
              className={`app-inline-button ${isFavorited ? 'app-inline-button--primary' : ''}`}
              disabled={togglingFavorite}
            >
              {togglingFavorite ? <Loader2 className="h-4 w-4 animate-spin" /> : <Star className={`h-4 w-4 ${isFavorited ? 'fill-current' : ''}`} />}
              {isFavorited ? 'Unfavorite' : 'Favorite'}
            </button>
            {isRedditPost && (
              <>
                <button
                  type="button"
                  onClick={() => fetchComments(true)}
                  className="app-inline-button"
                >
                  {loadingComments ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessagesSquare className="h-4 w-4" />}
                  Fetch Comments
                </button>
                <button
                  type="button"
                  onClick={() => generateCommentsBriefing(true)}
                  className="app-inline-button"
                >
                  {loadingCommentsBriefing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                  Brief Comments
                </button>
              </>
            )}
            {post.url && (
              <a href={post.url} target="_blank" rel="noopener noreferrer" className="app-inline-button">
                <ExternalLink className="h-4 w-4" />
                Open Original
              </a>
            )}
          </div>
        </div>

        {error && (
          <div className="rounded-2xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[1.25fr_0.75fr]">
          <div className="space-y-6">
            <section className="app-panel p-6">
              <div className="mb-4 flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-[var(--accent-strong)]" />
                <h2 className="text-lg font-semibold text-[var(--text-normal)]">AI Summary</h2>
              </div>
              {loadingSummary && !summary ? (
                <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Generating summary...
                </div>
              ) : summary ? (
                <div className="prose max-w-none">
                  <MarkdownRenderer content={summary} />
                </div>
              ) : (
                <div className="text-sm text-[var(--text-muted)]">Generate a summary on demand for this post.</div>
              )}
              {summaryModel && (
                <div className="mt-3 flex flex-wrap gap-3 text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">
                  <span>Model: {summaryModel}</span>
                  {summaryEstimatedTokens ? <span>Estimated tokens: {summaryEstimatedTokens}</span> : null}
                  {summaryReferences.length ? <span>References: {summaryReferences.length}</span> : null}
                </div>
              )}
            </section>

            <section className="app-panel p-6">
              <div className="mb-4 text-lg font-semibold text-[var(--text-normal)]">Original Content</div>
              {highlights.length ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--text-muted)]">
                    <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                      {highlights.length} stored highlights
                    </span>
                    <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                      {mappedHighlightCount} applied in reader view
                    </span>
                    {summaryReferenceHighlightIds.size > 0 ? (
                      <span className="rounded-full border border-[var(--background-modifier-border)] bg-[rgba(253,224,71,0.18)] px-3 py-1">
                        Darker yellow marks were used in the summary
                      </span>
                    ) : null}
                  </div>
                  <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-5">
                    {post?.content ? highlightedContentBlock : (
                      <div className="prose max-w-none">
                        <MarkdownRenderer content={renderContent} />
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="prose max-w-none">
                  <MarkdownRenderer content={renderContent} />
                </div>
              )}
            </section>

            <section className="app-panel p-6">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <BookOpen className="h-5 w-5 text-[var(--accent-strong)]" />
                  <h2 className="text-lg font-semibold text-[var(--text-normal)]">Story Timeline</h2>
                </div>
                <button type="button" onClick={() => loadTimeline(true)} className="app-inline-button">
                  {loadingTimeline ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Refresh Timeline
                </button>
              </div>

              {storyPrimary ? (
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-semibold text-[var(--text-normal)]">{storyPrimary.canonical_title}</span>
                    {storyPrimary.story_kind ? (
                      <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                        {storyPrimary.story_kind}
                      </span>
                    ) : null}
                    {storyPrimary.status ? (
                      <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                        {storyPrimary.status}
                      </span>
                    ) : null}
                  </div>
                  {storyDetail?.canonical_summary && (
                    <div className="mt-3 text-sm leading-7 text-[var(--text-muted)]">{storyDetail.canonical_summary}</div>
                  )}
                </div>
              ) : (
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4 text-sm text-[var(--text-muted)]">
                  This post is not attached to a durable story yet. Candidate related posts are shown below.
                </div>
              )}

              {storyTimeline?.current_update ? (
                <div className="mt-4 space-y-3">
                  <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Current Story Slice</div>
                  {renderTimelineUpdate(storyTimeline.current_update, 'Current')}
                </div>
              ) : null}

              {storyTimeline?.earlier_updates?.length ? (
                <div className="mt-4 space-y-3">
                  <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Earlier Updates</div>
                  {storyTimeline.earlier_updates.map((update) => renderTimelineUpdate(update, 'Earlier'))}
                </div>
              ) : null}

              {storyTimeline?.later_updates?.length ? (
                <div className="mt-4 space-y-3">
                  <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Later Updates</div>
                  {storyTimeline.later_updates.map((update) => renderTimelineUpdate(update, 'Later'))}
                </div>
              ) : null}

              <div className="mt-4 space-y-3">
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">
                  <Split className="h-4 w-4" />
                  Candidate Narrative Links
                </div>
                {storyCandidates.length ? storyCandidates.map((candidate) => (
                  <div key={candidate.id} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <button
                          type="button"
                          onClick={() => openRelatedPost(candidate.candidate_post_id)}
                          className="text-left"
                        >
                          <div className="text-sm font-semibold text-[var(--text-normal)]">
                            {candidate.candidate_post?.title || candidate.candidate_post_id}
                          </div>
                        </button>
                        <div className="mt-1 flex flex-wrap gap-2 text-xs text-[var(--text-faint)]">
                          <span>{candidate.candidate_post?.source_display_name || candidate.candidate_post?.source || 'Unknown source'}</span>
                          <span>{candidate.candidate_post?.platform || 'unknown'}</span>
                          <span>{formatTimelineDate(candidate.candidate_post?.published_at || candidate.candidate_post?.fetched_at || null)}</span>
                          <span>{candidate.retrieval_method}</span>
                          <span>Score {candidate.retrieval_score.toFixed(2)}</span>
                          <span>{candidate.decision_status}</span>
                        </div>
                        {candidate.decision_reason ? (
                          <div className="mt-2 text-sm leading-7 text-[var(--text-muted)]">{candidate.decision_reason}</div>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {candidate.decision_status !== 'accepted' && (
                          <button
                            type="button"
                            onClick={() => void handleCandidateDecision(candidate.id, 'accept')}
                            disabled={actingCandidateId === candidate.id}
                            className="app-inline-button"
                          >
                            {actingCandidateId === candidate.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                            Accept
                          </button>
                        )}
                        {candidate.decision_status !== 'rejected' && (
                          <button
                            type="button"
                            onClick={() => void handleCandidateDecision(candidate.id, 'reject')}
                            disabled={actingCandidateId === candidate.id}
                            className="app-inline-button"
                          >
                            {actingCandidateId === candidate.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
                            Reject
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                )) : (
                  <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4 text-sm text-[var(--text-muted)]">
                    No related post candidates were found for this timeline window.
                  </div>
                )}
              </div>
            </section>

            {isRedditPost && (
              <section className="app-panel p-6">
                <div className="mb-4 flex items-center gap-2">
                  <MessagesSquare className="h-5 w-5 text-[var(--accent-strong)]" />
                  <h2 className="text-lg font-semibold text-[var(--text-normal)]">Reddit Discussion</h2>
                </div>
                <div className="mb-4 flex flex-wrap items-center gap-3">
                  <button type="button" onClick={() => fetchComments(true)} className="app-inline-button">
                    {loadingComments ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessagesSquare className="h-4 w-4" />}
                    Refresh Comments
                  </button>
                  <button type="button" onClick={() => generateCommentsBriefing(true)} className="app-inline-button">
                    {loadingCommentsBriefing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                    {commentsBriefing ? 'Refresh Comment Briefing' : 'Generate Comment Briefing'}
                  </button>
                  {commentsFetchedAt && (
                    <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">
                      Comments fetched {new Date(commentsFetchedAt).toLocaleString()}
                    </div>
                  )}
                </div>
                <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
                  <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                    <div className="mb-3 text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">
                      Thread Briefing
                    </div>
                    {commentsBriefing ? (
                      <div className="prose max-w-none">
                        <MarkdownRenderer content={commentsBriefing} />
                      </div>
                    ) : (
                      <div className="text-sm text-[var(--text-muted)]">
                        No discussion briefing yet. Generate it on demand from the fetched Reddit comments.
                      </div>
                    )}
                    {commentsBriefingModel && (
                      <div className="mt-3 flex flex-wrap gap-3 text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">
                        <span>Model: {commentsBriefingModel}</span>
                        {commentsBriefingEstimatedTokens ? <span>Estimated tokens: {commentsBriefingEstimatedTokens}</span> : null}
                      </div>
                    )}
                  </div>
                  <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                    <div className="mb-3 text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">
                      Comments {comments.length ? `(${comments.length})` : ''}
                    </div>
                    {comments.length ? (
                      <div className="max-h-[28rem] space-y-3 overflow-y-auto pr-1">
                        {comments.map((comment) => (
                          <div key={comment.id || `${comment.author || 'unknown'}-${comment.created_at || 'unknown'}-${safeCommentPreview(comment)}`} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-4 py-3">
                            <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">
                              <span>{comment.author || 'unknown'}</span>
                              <span>Score {comment.score ?? 0}</span>
                              <span>Depth {comment.depth ?? 0}</span>
                            </div>
                            <div className="text-sm leading-7 text-[var(--text-normal)] whitespace-pre-wrap">
                              {typeof comment.body === 'string' ? comment.body : ''}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-sm text-[var(--text-muted)]">
                        No comments loaded yet. Fetch the thread on demand when you need discussion context.
                      </div>
                    )}
                  </div>
                </div>
              </section>
            )}

            <section className="app-panel p-6">
              <div className="mb-4 flex items-center gap-2">
                <Tags className="h-5 w-5 text-[var(--accent-strong)]" />
                <h2 className="text-lg font-semibold text-[var(--text-normal)]">Post Intelligence</h2>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4 text-sm">
                  <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Tags</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {categories.length ? (
                      categories.map((category) => (
                        <span key={category} className="rounded-full bg-[var(--text-highlight-bg)] px-3 py-1 text-xs font-medium text-[var(--text-normal)]">
                          {category}
                        </span>
                      ))
                    ) : (
                      <span className="text-[var(--text-muted)]">No tags stored</span>
                    )}
                  </div>
                </div>
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4 text-sm">
                  <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Connected Topics</div>
                  <div className="mt-2 space-y-2">
                    {topics.length ? (
                      topics.map((topic) => (
                        <button
                          key={topic.id}
                          type="button"
                          onClick={() => navigate(`/briefing?date=${encodeURIComponent(topic.date || '')}&mode=topics&topic=${encodeURIComponent(topic.id)}`)}
                          className="block w-full rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-3 py-2 text-left transition hover:border-[var(--accent-strong)] hover:bg-[var(--background-primary-alt)]"
                        >
                          <div className="font-medium text-[var(--text-normal)]">{topic.title}</div>
                          {topic.date && <div className="text-xs text-[var(--text-muted)]">{topic.date}</div>}
                        </button>
                      ))
                    ) : (
                      <span className="text-[var(--text-muted)]">No topic associations yet.</span>
                    )}
                  </div>
                </div>
              </div>
            </section>

            {postId && (
              <PostDetailPageErrorBoundary>
                <PostIntelligenceInspector postId={postId} post={post} />
              </PostDetailPageErrorBoundary>
            )}

            <section className="app-panel p-6">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <FileText className="h-5 w-5 text-[var(--accent-strong)]" />
                  <h2 className="text-lg font-semibold text-[var(--text-normal)]">Explainability</h2>
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-[var(--text-muted)]">
                  {readerState?.open_count !== undefined && (
                    <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                      Opened {readerState.open_count}x
                    </span>
                  )}
                  {readerState?.total_read_seconds !== undefined && (
                    <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                      Read {readerState.total_read_seconds}s
                    </span>
                  )}
                  {readerState?.first_opened_at && (
                    <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                      First {new Date(readerState.first_opened_at).toLocaleString()}
                    </span>
                  )}
                  {readerState?.last_opened_at && (
                    <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                      Last {new Date(readerState.last_opened_at).toLocaleString()}
                    </span>
                  )}
                  <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                    {isFavorited ? 'Favorited' : 'Not favorited'}
                  </span>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                  <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Takeaway</div>
                  <div className="mt-2 text-sm leading-7 text-[var(--text-normal)]">
                    {summaryTakeaway || 'No takeaway available yet. Generate summary or highlights when you need a compressed read.'}
                  </div>
                </div>
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                  <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Evidence Trace</div>
                  <div className="mt-2 space-y-2 text-sm text-[var(--text-normal)]">
                    <div>{highlights.length} stored highlights</div>
                    <div>{mappedHighlightCount} mapped into the reader view</div>
                    <div>{summaryReferenceHighlightIds.size} highlight references used by the summary</div>
                  </div>
                  <div className="mt-3 text-xs leading-6 text-[var(--text-muted)]">
                    The original content above is now the main explainability surface. Yellow marks show the exact passages the system considered important.
                  </div>
                </div>
              </div>
            </section>
          </div>

          <aside className="space-y-6">
            <section className="app-panel sticky top-24 p-5">
              <div className="flex rounded-2xl bg-[var(--background-secondary)] p-1">
                <button
                  type="button"
                  onClick={() => setActiveTab('notes')}
                  className={`workspace-tab ${activeTab === 'notes' ? 'is-active' : ''}`}
                >
                  <NotebookPen className="h-4 w-4" />
                  Note
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('chat')}
                  className={`workspace-tab ${activeTab === 'chat' ? 'is-active' : ''}`}
                >
                  <MessageSquareText className="h-4 w-4" />
                  Chat
                </button>
              </div>

              {activeTab === 'notes' ? (
                <div className="mt-5">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <h3 className="text-xl font-semibold text-[var(--text-normal)]">Notes</h3>
                    <div className="flex items-center gap-2">
                      <button type="button" onClick={handleExportNotes} className="app-inline-button">
                        <Download className="h-4 w-4" />
                        Export
                      </button>
                      <button type="button" onClick={handleSaveNotes} className="app-inline-button app-inline-button--primary">
                        {savingNotes ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                        Save
                      </button>
                    </div>
                  </div>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    className="workspace-editor"
                    rows={20}
                  />
                </div>
              ) : (
                <div className="mt-5 space-y-4">
                  <div>
                    <h3 className="text-xl font-semibold text-[var(--text-normal)]">Chat</h3>
                    <p className="mt-1 text-sm text-[var(--text-muted)]">
                      Ask the AI to reason only from this post. Context includes the full stored post, source metadata, tags, notes, cached summary, and fetched Reddit comments.
                    </p>
                  </div>
                  {chatContext && (
                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-4 py-3 text-xs text-[var(--text-muted)]">
                      Context loaded: {chatContext.content_chars || 0} chars of post content, {chatContext.reddit_comments_loaded || 0} Reddit comments, {chatContext.topics_loaded || 0} connected topics.
                    </div>
                  )}
                  <div className="workspace-chat-feed">
                    {chatMessages.length === 0 ? (
                      <div className="text-sm text-[var(--text-muted)]">
                        No questions yet. Start with what matters, why it matters, or what this post implies.
                      </div>
                    ) : (
                      chatMessages.map((message, index) => (
                        <div key={`${message.role}-${index}`} className={`workspace-chat-bubble ${message.role === 'assistant' ? 'is-assistant' : 'is-user'}`}>
                          <div className="mb-1 text-[11px] uppercase tracking-[0.14em] text-[var(--text-faint)]">
                            {message.role}
                          </div>
                          <MarkdownRenderer content={message.content} />
                        </div>
                      ))
                    )}
                  </div>
                  <div className="space-y-3">
                    <textarea
                      value={chatQuestion}
                      onChange={(e) => setChatQuestion(e.target.value)}
                      className="workspace-editor min-h-[120px]"
                      placeholder="Ask a precise question about this post..."
                    />
                    <button
                      type="button"
                      onClick={handleSendChat}
                      disabled={chatting || !chatQuestion.trim()}
                      className="app-inline-button app-inline-button--primary w-full justify-center"
                    >
                      {chatting ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquareText className="h-4 w-4" />}
                      Ask About This Post
                    </button>
                  </div>
                </div>
              )}
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}
