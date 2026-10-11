import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import { Button, ExternalLink, FilterChip, Page, PageHeader, TextLink } from '../components/ui';
import { EmptyState, ErrorState, LoadingState, Notice } from '../components/states';
import DevDataSwitch from '../components/ops/DevDataSwitch';
import { MetaList, Section, SelectRow, StateWord } from '../components/analysis/parts';
import { dateTime, humanize, percent, shortDate } from '../components/analysis/format';
import { useDevFixtureApi } from '../components/analysis/useDevFixtureApi';
import { formatRelativeTime } from '../lib/dates';
import { middleTruncate, plural } from '../lib/format';
import type { Post, StoryCard, StoryDetail, StoryUpdateEntry } from '../services/api';
import type { Status } from '../components/ui/styles';
import { STORY_FIXTURE_NAMES, storiesFixtureApi } from './StoriesExplorerPage.fixtures';

/**
 * Stories (design docs parked/stories.md): a master/detail view of the story graph. The list is
 * smol-style rows (date column, bold title, one meta line); the detail is a
 * reading column with the summary, a key/value list, the timeline and the posts.
 * Status is a glyph plus a word, never a hue.
 */

const STATUS_OPTIONS = ['active', 'candidate', 'merged', 'archived', 'superseded'] as const;
const KIND_OPTIONS = ['project_thread', 'recurring_theme', 'one_off_update'] as const;

const STATUS_GLYPH: Record<string, Status> = {
  active: 'ok',
  candidate: 'due',
  merged: 'read',
  archived: 'disabled',
  superseded: 'disabled',
};

function StoryStatus({ status }: { status?: string | null }) {
  if (!status) return null;
  const key = status.toLowerCase();
  return <StateWord glyph={STATUS_GLYPH[key] ?? 'scheduled'} word={humanize(status)} strong={key === 'active'} />;
}

function withExtra(options: readonly string[], current: string) {
  return current && !options.includes(current) ? [...options, current] : [...options];
}

function FilterGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly string[];
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 w-12 shrink-0 text-[0.75rem] font-medium text-fg-3">{label}</span>
      <FilterChip selected={!value} onClick={() => onChange('')}>all</FilterChip>
      {withExtra(options, value).map((option) => (
        <FilterChip key={option} selected={value === option} onClick={() => onChange(value === option ? '' : option)}>
          {humanize(option)}
        </FilterChip>
      ))}
    </div>
  );
}

/** One post, as a line: the title links to the reader's post view, the original opens in a new tab. */
function PostLine({ post, extra }: { post: Post; extra?: string }) {
  const title = post.title?.trim() || 'Untitled post';
  const source = post.source_display_name || post.source || post.handle_or_url || 'unknown source';
  return (
    <li className="flex min-w-0 items-start gap-4 px-3 py-2.5">
      <span className="w-[5.5rem] shrink-0 whitespace-nowrap pt-px text-[0.8125rem] tabular-nums text-fg-3">
        {shortDate(post.published_at || post.date)}
      </span>
      <span className="min-w-0 flex-1">
        {post.id ? (
          <TextLink to={`/posts/${encodeURIComponent(post.id)}`} className="line-clamp-2 break-words font-medium [overflow-wrap:anywhere]">
            {title}
          </TextLink>
        ) : (
          <span className="line-clamp-2 break-words font-medium [overflow-wrap:anywhere]">{title}</span>
        )}
        <span className="mt-0.5 block text-[0.8125rem] text-fg-2">
          <span title={source} className="break-words [overflow-wrap:anywhere]">{middleTruncate(source, 48)}</span>
          {extra ? <span className="tabular-nums text-fg-3"> · {extra}</span> : null}
        </span>
      </span>
      {post.url ? (
        <ExternalLink href={post.url} title={post.url} className="shrink-0 whitespace-nowrap pt-px text-[0.8125rem] text-fg-2">
          original ↗
        </ExternalLink>
      ) : null}
    </li>
  );
}

function PostList({ children }: { children: ReactNode }) {
  return <ul className="divide-y divide-line rounded-md border border-line">{children}</ul>;
}

function TimelineEntry({ entry }: { entry: StoryUpdateEntry }) {
  const importance = entry.importance_score !== undefined && entry.importance_score !== null ? percent(entry.importance_score) : null;
  return (
    <li>
      <details className="group rounded-md border border-line open:border-line-strong">
        <summary className="flex min-w-0 cursor-pointer list-none items-start gap-4 rounded-md px-4 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg [&::-webkit-details-marker]:hidden">
          <span className="w-[5.5rem] shrink-0 whitespace-nowrap pt-px text-[0.8125rem] tabular-nums text-fg-3">{shortDate(entry.update_date)}</span>
          <span className="min-w-0 flex-1">
            <span className="line-clamp-2 break-words font-semibold text-fg [overflow-wrap:anywhere]">{entry.title?.trim() || 'Untitled update'}</span>
            <span className="mt-0.5 block text-[0.75rem] tabular-nums text-fg-3">
              {plural(entry.posts?.length ?? entry.post_count ?? 0, 'post')}
              {importance ? ` · importance ${importance}` : ''}
            </span>
          </span>
          <span aria-hidden="true" className="shrink-0 pt-px text-[0.8125rem] text-fg-3 group-open:hidden">show</span>
          <span aria-hidden="true" className="hidden shrink-0 pt-px text-[0.8125rem] text-fg-3 group-open:inline">hide</span>
        </summary>
        <div className="space-y-3 px-4 pb-4">
          {entry.summary ? (
            <div className="prose prose-sm max-w-[68ch] break-words [overflow-wrap:anywhere]">
              <MarkdownRenderer content={entry.summary} />
            </div>
          ) : null}
          {entry.posts?.length ? (
            <PostList>
              {entry.posts.map((p) => <PostLine key={`${entry.id}-${p.post_id}`} post={p.post} />)}
            </PostList>
          ) : (
            <p className="text-[0.8125rem] text-fg-3">No posts are attached to this update.</p>
          )}
        </div>
      </details>
    </li>
  );
}

function StoryDetailView({
  story,
  timeline,
  refreshing,
  onRefresh,
}: {
  story: StoryDetail;
  timeline: StoryUpdateEntry[];
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const anchor = story.anchor_post;
  const byRole = story.posts_by_role || {};
  const roles = Object.entries(byRole);
  const posts = story.posts || [];
  const entries = timeline.length ? timeline : story.timeline || [];
  const anchorConfidence = story.anchor_confidence !== undefined && story.anchor_confidence !== null ? percent(story.anchor_confidence) : null;
  const anchorSource = anchor ? anchor.source_display_name || anchor.handle_or_url || 'unknown source' : '';

  return (
    <article aria-labelledby="story-title" className="min-w-0 space-y-8">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem] text-fg-2">
          <span>{humanize(story.story_kind, 'story')}</span>
          <StoryStatus status={story.status} />
        </div>
        <h2 id="story-title" dir="auto" className="break-words text-[1.375rem] font-semibold leading-[1.25] tracking-[-0.02em] text-fg [overflow-wrap:anywhere]">
          {story.canonical_title?.trim() || 'Untitled story'}
        </h2>
        <p className="text-[0.8125rem] tabular-nums text-fg-2">
          updated {formatRelativeTime(story.updated_at || story.created_at || story.last_seen_at)}
          {' · '}
          {plural(story.post_count ?? 0, 'post')} · {plural(story.update_count ?? 0, 'update')}
          {anchorConfidence ? ` · anchor ${anchorConfidence}` : ''}
        </p>
        <div className="flex flex-wrap gap-2 pt-2">
          {story.anchor_post_id ? (
            <Button asChild size="sm" variant="secondary">
              <Link to={`/posts/${encodeURIComponent(story.anchor_post_id)}`}>Open anchor post</Link>
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={onRefresh} disabled={refreshing}>
            <RefreshCw aria-hidden="true" />
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
      </header>

      {story.canonical_summary ? (
        <div className="prose max-w-[68ch] break-words [overflow-wrap:anywhere]">
          <MarkdownRenderer content={story.canonical_summary} />
        </div>
      ) : (
        <p className="text-[0.875rem] text-fg-3">No summary has been written for this story yet.</p>
      )}

      <MetaList
        items={[
          [
            'Anchor post',
            anchor ? (
              <span className="block">
                {anchor.id ? (
                  <TextLink to={`/posts/${encodeURIComponent(anchor.id)}`}>{anchor.title?.trim() || 'Untitled anchor post'}</TextLink>
                ) : (
                  anchor.title?.trim() || 'Untitled anchor post'
                )}
                <span className="mt-0.5 block text-fg-2">
                  <span title={anchorSource}>{middleTruncate(anchorSource, 48)}</span> · {shortDate(anchor.published_at)}
                  {anchor.url ? (
                    <>
                      {' · '}
                      <ExternalLink href={anchor.url} title={anchor.url} className="text-fg-2">original ↗</ExternalLink>
                    </>
                  ) : null}
                </span>
              </span>
            ) : (
              <span className="text-fg-3">none attached</span>
            ),
          ],
          ['Created by', humanize(story.created_by_method, 'unknown')],
          ['Resolution', story.resolution_version || 'unversioned'],
          ['First seen', dateTime(story.first_seen_at)],
          ['Last seen', dateTime(story.last_seen_at)],
        ]}
      />

      <Section title="Timeline" meta={entries.length || undefined} id="story-timeline">
        {entries.length ? (
          <ol className="space-y-2">
            {entries.map((entry) => <TimelineEntry key={entry.id} entry={entry} />)}
          </ol>
        ) : (
          <p className="text-[0.875rem] text-fg-3">No timeline entries yet.</p>
        )}
      </Section>

      <Section title="Posts" meta={(roles.reduce((n, [, list]) => n + list.length, 0) || posts.length) || undefined} id="story-posts">
        {roles.length ? (
          <div className="space-y-5">
            {roles.map(([role, list]) => (
              <div key={role}>
                <h3 className="mb-2 text-[0.8125rem] font-semibold text-fg">
                  {humanize(role)} <span className="font-normal tabular-nums text-fg-3">{list.length}</span>
                </h3>
                <PostList>
                  {list.map((entry) => (
                    <PostLine
                      key={`${role}-${entry.post_id}`}
                      post={entry.post}
                      extra={`relevance ${percent(entry.relevance_score)} · anchor ${percent(entry.anchor_score)} · weight ${percent(entry.evidence_weight)}`}
                    />
                  ))}
                </PostList>
              </div>
            ))}
          </div>
        ) : posts.length ? (
          <PostList>
            {posts.map((entry) => <PostLine key={`${entry.story_id}-${entry.post_id}`} post={entry.post} />)}
          </PostList>
        ) : (
          <p className="text-[0.875rem] text-fg-3">No posts are attached to this story yet.</p>
        )}
      </Section>
    </article>
  );
}

export default function StoriesExplorerPage() {
  const { api } = useDevFixtureApi(storiesFixtureApi);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const detailRef = useRef<HTMLDivElement>(null);

  const [selectedStoryId, setSelectedStoryId] = useState(searchParams.get('storyId') || '');
  const selectedRef = useRef(selectedStoryId);
  selectedRef.current = selectedStoryId;
  const [statusFilter, setStatusFilter] = useState(searchParams.get('status') || '');
  const [kindFilter, setKindFilter] = useState(searchParams.get('storyKind') || '');
  const [stories, setStories] = useState<StoryCard[]>([]);
  const [total, setTotal] = useState(0);
  const [storyDetail, setStoryDetail] = useState<StoryDetail | null>(null);
  const [timeline, setTimeline] = useState<StoryUpdateEntry[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const syncSearchParams = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          Object.entries(patch).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)));
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const loadStories = useCallback(
    async (status: string, kind: string) => {
      setLoadingList(true);
      setListError(null);
      const response = await api.getStories({ status: status || undefined, storyKind: kind || undefined, limit: 100, offset: 0 });
      if (!response.success) {
        setStories([]);
        setTotal(0);
        setListError(response.error || 'Failed to load stories');
        setLoadingList(false);
        return;
      }
      const next = response.stories || [];
      setStories(next);
      setTotal(response.total ?? next.length);
      // Keep a selection that is still in the list (or a deep link); otherwise open the first story.
      const current = selectedRef.current;
      if (!next.some((s) => s.id === current) && next.length) {
        setSelectedStoryId(next[0].id);
        syncSearchParams({ storyId: next[0].id });
      }
      setLoadingList(false);
    },
    [api, syncSearchParams],
  );

  const loadStoryDetail = useCallback(
    async (storyId: string) => {
      setDetailError(null);
      setLoadingDetail(true);
      const [detailResponse, timelineResponse] = await Promise.all([api.getStory(storyId), api.getStoryTimeline(storyId)]);
      const detail = detailResponse.story || timelineResponse.story || null;
      if (!detail) {
        setStoryDetail(null);
        setTimeline([]);
        setDetailError(detailResponse.error || timelineResponse.error || 'Failed to load the story');
      } else {
        setStoryDetail(detail as StoryDetail);
        setTimeline(timelineResponse.timeline || (detail as StoryDetail).timeline || []);
      }
      setLoadingDetail(false);
    },
    [api],
  );

  useEffect(() => {
    void loadStories(statusFilter, kindFilter);
    // Filters reload explicitly through `changeFilter`; this is the first load (and a fixture switch).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadStories]);

  useEffect(() => {
    if (!selectedStoryId) {
      setStoryDetail(null);
      setTimeline([]);
      return;
    }
    void loadStoryDetail(selectedStoryId);
  }, [selectedStoryId, loadStoryDetail]);

  const changeFilter = (kind: 'status' | 'storyKind', value: string) =>
    changeFilters(kind === 'status' ? value : statusFilter, kind === 'storyKind' ? value : kindFilter);

  const changeFilters = (nextStatus: string, nextKind: string) => {
    setStatusFilter(nextStatus);
    setKindFilter(nextKind);
    syncSearchParams({ status: nextStatus || null, storyKind: nextKind || null });
    void loadStories(nextStatus, nextKind);
  };

  const selectStory = (storyId: string) => {
    setSelectedStoryId(storyId);
    syncSearchParams({ storyId });
    // Stacked layout (below xl): bring the detail into view; in two columns it is already there.
    if (typeof window !== 'undefined' && window.matchMedia && !window.matchMedia('(min-width: 1280px)').matches) {
      detailRef.current?.scrollIntoView?.({ block: 'start' });
    }
  };

  const filtered = Boolean(statusFilter || kindFilter);
  const nothing = !listError && !loadingList && !stories.length;
  const meta = useMemo(() => {
    if (loadingList && !stories.length) return 'loading…';
    const count = plural(total, 'story', 'stories');
    return stories.length < total ? `${count} · showing the first ${stories.length}` : count;
  }, [loadingList, stories.length, total]);

  return (
    <Page width="wide">
      <PageHeader
        title="Stories"
        meta={meta}
        actions={
          <Button variant="secondary" onClick={() => void loadStories(statusFilter, kindFilter)} disabled={loadingList}>
            <RefreshCw aria-hidden="true" />
            Reload
          </Button>
        }
      >
        {nothing && !filtered ? null : (
          <div className="space-y-2">
            <FilterGroup label="status" options={STATUS_OPTIONS} value={statusFilter} onChange={(v) => changeFilter('status', v)} />
            <FilterGroup label="kind" options={KIND_OPTIONS} value={kindFilter} onChange={(v) => changeFilter('storyKind', v)} />
          </div>
        )}
      </PageHeader>

      {listError ? (
        <ErrorState error={listError} title="Couldn’t load stories" onRetry={() => void loadStories(statusFilter, kindFilter)} />
      ) : nothing ? (
        filtered ? (
          <EmptyState
            title="No stories match these filters"
            description="Try another status or kind."
            action={{ label: 'Show all', onClick: () => changeFilters('', '') }}
          />
        ) : (
          <EmptyState
            title="No stories yet"
            description="Stories appear once the resolver has tied posts together. Read the feed in the meantime."
            action={{ label: 'Open the feed', onClick: () => navigate('/') }}
          />
        )
      ) : (
        <div className="grid gap-x-10 gap-y-10 xl:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
          <nav aria-label="Stories" className="min-w-0 xl:sticky xl:top-[calc(var(--topbar-h)+1rem)] xl:max-h-[calc(100dvh-var(--topbar-h)-2rem)] xl:self-start xl:overflow-y-auto xl:pr-1">
            {loadingList && !stories.length ? (
              <LoadingState label="Loading stories" rows={5} />
            ) : (
              <ol className="space-y-2" aria-busy={loadingList || undefined}>
                {stories.map((story) => (
                  <li key={story.id}>
                    <SelectRow
                      selected={story.id === selectedStoryId}
                      onSelect={() => selectStory(story.id)}
                      meta={shortDate(story.last_seen_at || story.updated_at)}
                      title={story.canonical_title?.trim() || 'Untitled story'}
                      description={story.canonical_summary || undefined}
                      footer={
                        <>
                          <StoryStatus status={story.status} />
                          {story.story_kind ? <span>{humanize(story.story_kind)}</span> : null}
                          <span>{plural(story.post_count ?? 0, 'post')}</span>
                          <span>{plural(story.update_count ?? 0, 'update')}</span>
                        </>
                      }
                    />
                  </li>
                ))}
              </ol>
            )}
          </nav>

          <div ref={detailRef} className="min-w-0 scroll-mt-[calc(var(--topbar-h)+1rem)]">
            {detailError ? (
              <Notice tone="error" title="Couldn’t load this story" message={detailError} action={{ label: 'Retry', onClick: () => void loadStoryDetail(selectedStoryId) }} />
            ) : storyDetail ? (
              <StoryDetailView story={storyDetail} timeline={timeline} refreshing={loadingDetail} onRefresh={() => void loadStoryDetail(selectedStoryId)} />
            ) : loadingDetail ? (
              <LoadingState label="Loading story" rows={3} />
            ) : stories.length ? (
              <p className="rounded-md border border-dashed border-line-strong px-4 py-10 text-center text-[0.875rem] text-fg-2">
                Select a story to read its summary, timeline and posts.
              </p>
            ) : null}
          </div>
        </div>
      )}
      <DevDataSwitch options={STORY_FIXTURE_NAMES} />
    </Page>
  );
}
