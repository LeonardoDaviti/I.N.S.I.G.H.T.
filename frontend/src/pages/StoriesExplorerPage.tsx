import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  BookOpen,
  ChevronRight,
  Loader2,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import { apiService } from '../services/api';
import type { StoryCard, StoryDetail, StoryUpdateEntry } from '../services/api';

function formatDate(value?: string | null) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatShortDate(value?: string | null) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString();
}

function formatScore(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return null;
  }
  return `${Math.round(Number(value) * 100)}%`;
}

function tone(kind?: string) {
  switch ((kind || '').toLowerCase()) {
    case 'project_thread':
      return 'border-indigo-200 bg-indigo-50 text-indigo-700';
    case 'recurring_theme':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    case 'one_off_update':
      return 'border-amber-200 bg-amber-50 text-amber-700';
    default:
      return 'border-slate-200 bg-slate-50 text-slate-700';
  }
}

function stateTone(state?: string) {
  switch ((state || '').toLowerCase()) {
    case 'active':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    case 'candidate':
      return 'border-amber-200 bg-amber-50 text-amber-700';
    case 'archived':
    case 'superseded':
      return 'border-slate-200 bg-slate-50 text-slate-500';
    case 'merged':
      return 'border-indigo-200 bg-indigo-50 text-indigo-700';
    default:
      return 'border-[var(--background-modifier-border)] bg-[var(--background-secondary)] text-[var(--text-muted)]';
  }
}

function SectionCard({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="app-panel p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text-normal)]">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-[var(--text-muted)]">{subtitle}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export default function StoriesExplorerPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const initialStoryId = searchParams.get('storyId') || '';
  const initialStatus = searchParams.get('status') || '';
  const initialKind = searchParams.get('storyKind') || '';

  const [stories, setStories] = useState<StoryCard[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedStoryId, setSelectedStoryId] = useState(initialStoryId);
  const [statusFilter, setStatusFilter] = useState(initialStatus);
  const [kindFilter, setKindFilter] = useState(initialKind);
  const [storyDetail, setStoryDetail] = useState<StoryDetail | null>(null);
  const [timeline, setTimeline] = useState<StoryUpdateEntry[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedStory = useMemo(
    () => stories.find((story) => story.id === selectedStoryId) || storyDetail || null,
    [stories, selectedStoryId, storyDetail],
  );

  const syncSearchParams = (patch: Record<string, string | null | undefined>) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([key, value]) => {
      if (!value) {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    });
    setSearchParams(next, { replace: true });
  };

  const loadStories = async () => {
    setLoadingList(true);
    setError(null);

    const response = await apiService.getStories({
      status: statusFilter.trim() || undefined,
      storyKind: kindFilter.trim() || undefined,
      limit: 100,
      offset: 0,
    });

    if (!response.success) {
      setStories([]);
      setTotal(0);
      setError(response.error || 'Failed to load stories');
      setLoadingList(false);
      return;
    }

    const nextStories = response.stories || [];
    setStories(nextStories);
    setTotal(response.total ?? nextStories.length);

    if (!selectedStoryId && nextStories[0]) {
      setSelectedStoryId(nextStories[0].id);
      syncSearchParams({ storyId: nextStories[0].id });
    }

    setLoadingList(false);
  };

  const loadStoryDetail = async (storyId: string) => {
    if (!storyId) {
      setStoryDetail(null);
      setTimeline([]);
      return;
    }

    setError(null);
    setLoadingDetail(true);
    const [detailResponse, timelineResponse] = await Promise.all([
      apiService.getStory(storyId),
      apiService.getStoryTimeline(storyId),
    ]);

    const detail = detailResponse.story || timelineResponse.story || null;
    if (!detail && !detailResponse.success && !timelineResponse.success) {
      setStoryDetail(null);
      setTimeline([]);
      setError(detailResponse.error || timelineResponse.error || 'Failed to load story detail');
      setLoadingDetail(false);
      return;
    }

    setStoryDetail(detail);
    setTimeline(timelineResponse.timeline || detail?.timeline || []);
    setLoadingDetail(false);
  };

  useEffect(() => {
    void loadStories();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedStoryId) {
      setStoryDetail(null);
      setTimeline([]);
      return;
    }
    void loadStoryDetail(selectedStoryId);
  }, [selectedStoryId]);

  const selectStory = (storyId: string) => {
    setSelectedStoryId(storyId);
    syncSearchParams({ storyId });
  };

  const applyFilters = () => {
    syncSearchParams({
      status: statusFilter.trim() || null,
      storyKind: kindFilter.trim() || null,
      storyId: selectedStoryId || null,
    });
    void loadStories();
  };

  const refreshCurrentStory = () => {
    if (!selectedStoryId) return;
    void loadStoryDetail(selectedStoryId);
  };

  const detailPostsByRole = storyDetail?.posts_by_role || {};
  const detailPosts = storyDetail?.posts || [];
  const anchorPost = storyDetail?.anchor_post;

  return (
    <div className="app-shell min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="app-panel overflow-hidden">
          <div className="grid gap-0 lg:grid-cols-[1.15fr_0.85fr]">
            <div className="relative p-6 sm:p-8 lg:p-10">
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(76,141,255,0.16),transparent_42%),radial-gradient(circle_at_bottom_left,rgba(29,78,216,0.10),transparent_34%)]" />
              <div className="relative space-y-5">
                <button
                  type="button"
                  onClick={() => navigate('/')}
                  className="inline-flex items-center gap-2 text-sm text-[var(--text-muted)] transition hover:text-[var(--text-normal)]"
                >
                  <ArrowLeft className="h-4 w-4" />
                  Back to hub
                </button>
                <div className="inline-flex rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[var(--text-faint)]">
                  Story Explorer
                </div>
                <div className="space-y-3">
                  <h1 className="text-3xl font-bold tracking-tight text-[var(--text-normal)] sm:text-4xl">
                    Follow stories across posts, updates, and timelines.
                  </h1>
                  <p className="max-w-2xl text-sm leading-7 text-[var(--text-muted)] sm:text-base">
                    This view turns the backend story graph into a readable workspace. Select a story to inspect its anchor, attached posts, update trail, and the timeline that ties the thread together.
                  </p>
                </div>
                <div className="flex flex-wrap gap-3">
                  <button type="button" onClick={applyFilters} className="app-inline-button app-inline-button--primary">
                    <Sparkles className="h-4 w-4" />
                    Apply Filters
                  </button>
                  <button type="button" onClick={loadStories} className="app-inline-button">
                    <RefreshCw className={`h-4 w-4 ${loadingList ? 'animate-spin' : ''}`} />
                    Reload Stories
                  </button>
                  <Link to="/briefing" className="app-inline-button">
                    <BookOpen className="h-4 w-4" />
                    Open Daily Briefing
                  </Link>
                </div>
              </div>
            </div>

            <div className="border-t border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-6 lg:border-l lg:border-t-0">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-faint)]">Stories loaded</div>
                  <div className="mt-2 text-3xl font-bold text-[var(--text-normal)]">{total.toLocaleString()}</div>
                  <div className="mt-1 text-sm text-[var(--text-muted)]">
                    Browse every story candidate stored in the database.
                  </div>
                </div>
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-faint)]">Selected story</div>
                  <div className="mt-2 text-lg font-semibold text-[var(--text-normal)]">
                    {selectedStory?.canonical_title || 'None selected'}
                  </div>
                  <div className="mt-1 text-sm text-[var(--text-muted)]">
                    {selectedStory?.story_kind || 'Pick a story from the list to inspect it.'}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </header>

        {error && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
          </div>
        )}

        <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
          <aside className="space-y-6">
            <SectionCard title="Filters" subtitle="Narrow the story graph by status or kind.">
              <div className="grid gap-3">
                <label className="space-y-2 text-sm">
                  <span className="text-[var(--text-muted)]">Status</span>
                  <input
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    placeholder="active, archived, candidate..."
                    className="workspace-editor py-3 font-sans"
                  />
                </label>
                <label className="space-y-2 text-sm">
                  <span className="text-[var(--text-muted)]">Story kind</span>
                  <input
                    value={kindFilter}
                    onChange={(e) => setKindFilter(e.target.value)}
                    placeholder="project_thread, recurring_theme..."
                    className="workspace-editor py-3 font-sans"
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={applyFilters} className="app-inline-button app-inline-button--primary">
                    <RefreshCw className={`h-4 w-4 ${loadingList ? 'animate-spin' : ''}`} />
                    Update list
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setStatusFilter('');
                      setKindFilter('');
                      syncSearchParams({ status: null, storyKind: null });
                      void loadStories();
                    }}
                    className="app-inline-button"
                  >
                    Clear
                  </button>
                </div>
                <div className="text-xs text-[var(--text-faint)]">
                  Leave either field blank to search across all values.
                </div>
              </div>
            </SectionCard>

            <SectionCard
              title={`Stories (${stories.length})`}
              subtitle={loadingList ? 'Loading story index...' : 'Select a story to inspect. '}
              actions={loadingList ? <Loader2 className="h-4 w-4 animate-spin text-[var(--text-faint)]" /> : null}
            >
              <div className="max-h-[38rem] space-y-2 overflow-y-auto pr-1">
                {stories.length ? stories.map((story) => {
                  const isSelected = story.id === selectedStoryId;
                  return (
                    <button
                      key={story.id}
                      type="button"
                      onClick={() => selectStory(story.id)}
                      className={`block w-full rounded-2xl border p-4 text-left transition ${
                        isSelected
                          ? 'border-[var(--accent-strong)] bg-[var(--text-highlight-bg)] shadow-[0_14px_30px_rgba(76,141,255,0.12)]'
                          : 'border-[var(--background-modifier-border)] bg-[var(--background-primary)] hover:border-[var(--accent-strong)] hover:bg-[var(--background-primary-alt)]'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold text-[var(--text-normal)]">
                            {story.canonical_title}
                          </div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <span className={`rounded-full border px-2 py-0.5 text-xs ${tone(story.story_kind)}`}>
                              {story.story_kind || 'story'}
                            </span>
                            <span className={`rounded-full border px-2 py-0.5 text-xs ${stateTone(story.status)}`}>
                              {story.status || 'unknown'}
                            </span>
                          </div>
                        </div>
                        <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-[var(--text-faint)]" />
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-[var(--text-muted)]">
                        <span>{story.post_count || 0} posts</span>
                        <span>{story.update_count || 0} updates</span>
                        {formatScore(story.anchor_confidence) && <span>anchor {formatScore(story.anchor_confidence)}</span>}
                      </div>
                      {story.canonical_summary && (
                        <div className="mt-3 line-clamp-3 text-sm leading-6 text-[var(--text-muted)]">
                          {story.canonical_summary}
                        </div>
                      )}
                    </button>
                  );
                }) : (
                  <div className="rounded-2xl border border-dashed border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4 text-sm text-[var(--text-muted)]">
                    {loadingList ? 'Loading stories...' : 'No stories match the current filters.'}
                  </div>
                )}
              </div>
            </SectionCard>
          </aside>

          <main className="space-y-6">
            <SectionCard
              title={storyDetail?.canonical_title || 'Story detail'}
              subtitle={storyDetail ? `Updated ${formatDate(storyDetail.updated_at || storyDetail.created_at)}` : 'Choose a story from the list.'}
              actions={
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={refreshCurrentStory} className="app-inline-button">
                    <RefreshCw className={`h-4 w-4 ${loadingDetail ? 'animate-spin' : ''}`} />
                    Refresh Detail
                  </button>
                  {storyDetail?.anchor_post_id && (
                    <Link to={`/posts/${encodeURIComponent(storyDetail.anchor_post_id)}`} className="app-inline-button">
                      <BookOpen className="h-4 w-4" />
                      Open Anchor Post
                    </Link>
                  )}
                </div>
              }
            >
              {loadingDetail && !storyDetail ? (
                <div className="flex items-center gap-2 py-8 text-sm text-[var(--text-muted)]">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading story detail...
                </div>
              ) : storyDetail ? (
                <div className="space-y-5">
                  <div className="flex flex-wrap gap-2">
                    <span className={`rounded-full border px-3 py-1 text-xs ${tone(storyDetail.story_kind)}`}>
                      {storyDetail.story_kind || 'story'}
                    </span>
                    <span className={`rounded-full border px-3 py-1 text-xs ${stateTone(storyDetail.status)}`}>
                      {storyDetail.status || 'unknown'}
                    </span>
                    {formatScore(storyDetail.anchor_confidence) && (
                      <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                        Anchor {formatScore(storyDetail.anchor_confidence)}
                      </span>
                    )}
                    <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                      {storyDetail.post_count || 0} posts
                    </span>
                    <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                      {storyDetail.update_count || 0} updates
                    </span>
                  </div>

                  {storyDetail.canonical_summary ? (
                    <div className="prose max-w-none">
                      <MarkdownRenderer content={storyDetail.canonical_summary} />
                    </div>
                  ) : (
                    <div className="text-sm text-[var(--text-muted)]">
                      No canonical summary has been stored for this story yet.
                    </div>
                  )}

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Anchor post</div>
                      {anchorPost ? (
                        <div className="mt-3 space-y-3">
                          <div className="font-medium text-[var(--text-normal)]">{anchorPost.title || 'Untitled anchor post'}</div>
                          <div className="flex flex-wrap gap-2 text-xs text-[var(--text-muted)]">
                            <span>{anchorPost.platform?.toUpperCase() || 'POST'}</span>
                            <span>{anchorPost.source_display_name || anchorPost.handle_or_url || 'unknown source'}</span>
                            <span>{formatShortDate(anchorPost.published_at)}</span>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {anchorPost.id && (
                              <Link to={`/posts/${encodeURIComponent(anchorPost.id)}`} className="app-inline-button">
                                Open post
                              </Link>
                            )}
                            {anchorPost.url && (
                              <a href={anchorPost.url} target="_blank" rel="noreferrer" className="app-inline-button">
                                Open original
                              </a>
                            )}
                          </div>
                        </div>
                      ) : (
                        <div className="mt-3 text-sm text-[var(--text-muted)]">No anchor post is attached.</div>
                      )}
                    </div>
                    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Story metadata</div>
                      <div className="mt-3 space-y-2 text-sm text-[var(--text-muted)]">
                        <div>Created by: {storyDetail.created_by_method || 'unknown'}</div>
                        <div>Resolution: {storyDetail.resolution_version || 'unversioned'}</div>
                        <div>First seen: {formatDate(storyDetail.first_seen_at)}</div>
                        <div>Last seen: {formatDate(storyDetail.last_seen_at)}</div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="rounded-2xl border border-dashed border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-6 text-sm text-[var(--text-muted)]">
                  Select a story from the index to load the full record.
                </div>
              )}
            </SectionCard>

            {storyDetail && (
              <>
                <SectionCard title="Timeline" subtitle="Chronological updates attached to the selected story.">
                  <div className="space-y-3">
                    {(timeline.length ? timeline : storyDetail.timeline || []).length ? (timeline.length ? timeline : storyDetail.timeline || []).map((update) => (
                      <details key={update.id} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                        <summary className="cursor-pointer list-none">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium text-[var(--text-normal)]">{update.title}</span>
                            {update.update_date && (
                              <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
                                {formatShortDate(update.update_date)}
                              </span>
                            )}
                            {formatScore(update.importance_score) && (
                              <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
                                importance {formatScore(update.importance_score)}
                              </span>
                            )}
                          </div>
                        </summary>
                        <div className="mt-3 space-y-3">
                          {update.summary && (
                            <div className="prose max-w-none">
                              <MarkdownRenderer content={update.summary} />
                            </div>
                          )}
                          {update.posts?.length ? (
                            <div className="space-y-2">
                              <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Posts in update</div>
                              <div className="grid gap-2 md:grid-cols-2">
                                {update.posts.map((entry) => (
                                  <div key={`${update.id}-${entry.post_id}`} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3">
                                    <div className="font-medium text-[var(--text-normal)]">{entry.post.title || 'Untitled post'}</div>
                                    <div className="mt-1 text-xs text-[var(--text-muted)]">
                                      {entry.post.source_display_name || entry.post.source} • {formatShortDate(entry.post.published_at || entry.post.date)}
                                    </div>
                                    <div className="mt-3 flex flex-wrap gap-2">
                                      {entry.post.id && (
                                        <Link to={`/posts/${encodeURIComponent(entry.post.id)}`} className="app-inline-button">
                                          Open post
                                        </Link>
                                      )}
                                      {entry.post.url && (
                                        <a href={entry.post.url} target="_blank" rel="noreferrer" className="app-inline-button">
                                          Open original
                                        </a>
                                      )}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      </details>
                    )) : (
                      <div className="text-sm text-[var(--text-muted)]">No timeline entries yet.</div>
                    )}
                  </div>
                </SectionCard>

                <SectionCard title="Posts by Role" subtitle="How the story connects to specific posts.">
                  <div className="space-y-4">
                    {Object.keys(detailPostsByRole).length ? Object.entries(detailPostsByRole).map(([role, entries]) => (
                      <div key={role} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                        <div className="mb-3 flex flex-wrap items-center gap-2">
                          <span className="rounded-full border border-[var(--accent-strong)] px-2 py-0.5 text-xs text-[var(--text-normal)]">
                            {role}
                          </span>
                          <span className="text-xs text-[var(--text-faint)]">{entries.length} post(s)</span>
                        </div>
                        <div className="grid gap-3 md:grid-cols-2">
                          {entries.map((entry) => (
                            <div key={`${role}-${entry.post_id}`} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3">
                              <div className="font-medium text-[var(--text-normal)]">{entry.post.title || 'Untitled post'}</div>
                              <div className="mt-1 text-xs text-[var(--text-muted)]">
                                {entry.post.source_display_name || entry.post.source} • {formatShortDate(entry.post.published_at || entry.post.date)}
                              </div>
                              <div className="mt-3 flex flex-wrap gap-2 text-xs text-[var(--text-muted)]">
                                <span>relevance {formatScore(entry.relevance_score) || 'n/a'}</span>
                                <span>anchor {formatScore(entry.anchor_score) || 'n/a'}</span>
                                <span>weight {formatScore(entry.evidence_weight) || 'n/a'}</span>
                              </div>
                              <div className="mt-3 flex flex-wrap gap-2">
                                {entry.post.id && (
                                  <Link to={`/posts/${encodeURIComponent(entry.post.id)}`} className="app-inline-button">
                                    Open post
                                  </Link>
                                )}
                                {entry.post.url && (
                                  <a href={entry.post.url} target="_blank" rel="noreferrer" className="app-inline-button">
                                    Open original
                                  </a>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )) : detailPosts.length ? (
                      <div className="grid gap-3 md:grid-cols-2">
                        {detailPosts.map((entry) => (
                          <div key={`${entry.story_id}-${entry.post_id}`} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                            <div className="font-medium text-[var(--text-normal)]">{entry.post.title || 'Untitled post'}</div>
                            <div className="mt-1 text-xs text-[var(--text-muted)]">
                              {entry.post.source_display_name || entry.post.source} • {formatShortDate(entry.post.published_at || entry.post.date)}
                            </div>
                            <div className="mt-3 flex flex-wrap gap-2">
                              {entry.post.id && (
                                <Link to={`/posts/${encodeURIComponent(entry.post.id)}`} className="app-inline-button">
                                  Open post
                                </Link>
                              )}
                              {entry.post.url && (
                                <a href={entry.post.url} target="_blank" rel="noreferrer" className="app-inline-button">
                                  Open original
                                </a>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-sm text-[var(--text-muted)]">No posts are attached to this story yet.</div>
                    )}
                  </div>
                </SectionCard>
              </>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
