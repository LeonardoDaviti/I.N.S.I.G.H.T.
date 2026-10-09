import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import { Button, Chip, Field, Page, PageHeader, Select, Skeleton, TextLink } from '../components/ui';
import { Notice } from '../components/states';
import { apiService } from '../services/api';
import type { SourceWithSettings, VerticalBriefingResponse, VerticalBriefingTrack } from '../services/api';
import { formatCount, plural } from '../lib/format';
import { formatIssueRange, formatIssueShort } from '../lib/issueDate';
import { cn } from '../lib/utils';

/**
 * One source read as a live thread (the source-level "vertical" briefing).
 *
 * Mark IX: a newsletter issue for a single source. The page header names the
 * source and the covered window; the briefing sits in the reading measure; the
 * tracks are a plain numbered list that opens in place. Monochrome: a track's
 * kind is a word in an outline chip, not a colour.
 */

/** "project_thread" -> "project thread". */
function kindLabel(kind?: string | null): string {
  return (kind || 'track').replace(/_/g, ' ').toLowerCase();
}

/** Supporting posts beyond this many fold behind a "show all" button, so a
 *  300-post track does not become a wall of links. */
const POSTS_PREVIEW = 12;

function DetailBlock({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <h4 className="mb-1.5 text-[0.8125rem] font-medium lowercase text-fg-3">{label}</h4>
      {children}
    </div>
  );
}

function Quiet({ children }: { children: ReactNode }) {
  return <p className="text-[0.875rem] text-fg-3">{children}</p>;
}

function TrackItem({
  track,
  index,
  postsById,
}: {
  track: VerticalBriefingTrack;
  index: number;
  postsById: Record<string, { title?: string | null; source_display_name?: string | null; source?: string | null }>;
}) {
  const [showAllPosts, setShowAllPosts] = useState(false);
  const storyTitles = track.story_titles || [];
  const entityHints = track.entity_hints || [];
  const postIds = track.post_ids || [];
  const timeline = track.timeline || [];
  const visiblePostIds = showAllPosts ? postIds : postIds.slice(0, POSTS_PREVIEW);

  return (
    <li className="border-t border-line first:border-t-0">
      <details className="group">
        <summary
          className={cn(
            'grid cursor-pointer list-none grid-cols-[1.75rem_minmax(0,1fr)_auto] items-start gap-x-2 rounded-sm py-3.5 [&::-webkit-details-marker]:hidden',
            'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg',
          )}
        >
          <span aria-hidden="true" className="pt-px text-[0.8125rem] tabular-nums text-fg-3">
            {String(index + 1).padStart(2, '0')}
          </span>
          <span className="min-w-0">
            <span className="block break-words font-semibold leading-[1.35] text-fg [overflow-wrap:anywhere]">
              {track.title || 'Untitled track'}
            </span>
            <span className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[0.8125rem] tabular-nums text-fg-2">
              <Chip variant="outline">{kindLabel(track.track_kind)}</Chip>
              <span>{plural(track.unique_post_count ?? 0, 'unique post')}</span>
              <span aria-hidden="true" className="text-fg-3">·</span>
              <span>{plural(track.raw_post_count ?? 0, 'raw post')}</span>
            </span>
          </span>
          <ChevronRight aria-hidden="true" className="mt-0.5 h-4 w-4 text-fg-3 group-open:rotate-90 group-hover:text-fg" />
        </summary>

        <div className="space-y-5 pb-6 pl-[2.25rem]">
          {track.summary ? (
            <p className="max-w-reading break-words leading-[1.65] text-fg [overflow-wrap:anywhere]">{track.summary}</p>
          ) : null}

          <DetailBlock label="Stories">
            {storyTitles.length ? (
              <ul className="list-disc space-y-1 pl-4 text-[0.875rem] text-fg-2 marker:text-fg-3">
                {storyTitles.map((title, i) => (
                  <li key={`${title}-${i}`} className="break-words [overflow-wrap:anywhere]">{title}</li>
                ))}
              </ul>
            ) : (
              <Quiet>No story titles recorded.</Quiet>
            )}
          </DetailBlock>

          <DetailBlock label="Entities">
            {entityHints.length ? (
              <div className="flex flex-wrap gap-1">
                {entityHints.map((hint, i) => (
                  <Chip key={`${hint}-${i}`} variant="quiet" className="max-w-full" title={hint}>
                    <span className="min-w-0 truncate">{hint}</span>
                  </Chip>
                ))}
              </div>
            ) : (
              <Quiet>No entity hints recorded.</Quiet>
            )}
          </DetailBlock>

          <DetailBlock label={`Supporting posts (${formatCount(postIds.length)})`}>
            {postIds.length ? (
              <>
                <ul className="space-y-1 text-[0.875rem]">
                  {visiblePostIds.map((postId) => {
                    const post = postsById[postId];
                    const label = post?.title || post?.source_display_name || post?.source || postId;
                    return (
                      <li key={postId} className="min-w-0">
                        <Link
                          to={`/posts/${encodeURIComponent(postId)}`}
                          className="text-link line-clamp-2 break-words rounded-sm [overflow-wrap:anywhere] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg"
                        >
                          {label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
                {postIds.length > POSTS_PREVIEW ? (
                  <Button variant="ghost" size="sm" className="mt-1 -ml-2.5" onClick={() => setShowAllPosts((v) => !v)}>
                    {showAllPosts ? 'show fewer' : `show all ${formatCount(postIds.length)}`}
                  </Button>
                ) : null}
              </>
            ) : (
              <Quiet>No post ids were stored for this track.</Quiet>
            )}
          </DetailBlock>

          <DetailBlock label="Timeline">
            {timeline.length ? (
              <ol className="space-y-2.5">
                {timeline.map((entry, i) => (
                  <li key={`${track.id}-${i}`} className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 text-[0.875rem]">
                    <span className="whitespace-nowrap pt-px tabular-nums text-fg-3">{formatIssueShort(entry.date)}</span>
                    <span className="min-w-0">
                      {entry.summary ? (
                        <span className="block break-words leading-[1.55] text-fg [overflow-wrap:anywhere]">{entry.summary}</span>
                      ) : null}
                      {entry.post_ids?.length ? (
                        <span className="block text-[0.8125rem] tabular-nums text-fg-3">{plural(entry.post_ids.length, 'post')}</span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <Quiet>No timeline entries recorded.</Quiet>
            )}
          </DetailBlock>
        </div>
      </details>
    </li>
  );
}

export default function VerticalBriefingPage() {
  const { sourceId: sourceIdParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const initialSourceId = sourceIdParam || searchParams.get('sourceId') || '';
  const initialStart = searchParams.get('start') || '';
  const initialEnd = searchParams.get('end') || '';

  const [sources, setSources] = useState<SourceWithSettings[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState(initialSourceId);
  const [startDate, setStartDate] = useState(initialStart);
  const [endDate, setEndDate] = useState(initialEnd);
  const [briefing, setBriefing] = useState<VerticalBriefingResponse | null>(null);
  const [loadingSources, setLoadingSources] = useState(true);
  const [loadingBriefing, setLoadingBriefing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedSource = useMemo(
    () => sources.find((source) => source.id === selectedSourceId) || sources[0] || null,
    [sources, selectedSourceId],
  );
  const briefingText = briefing?.briefing || briefing?.vertical_briefing || '';
  const tracks = briefing?.tracks || [];
  const postsById = briefing?.posts || {};
  const sourceName =
    briefing?.source_label || selectedSource?.settings?.display_name || selectedSource?.handle_or_url || 'No source selected';
  const busy = loadingBriefing || refreshing;

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

  const loadSources = async () => {
    setLoadingSources(true);
    setError(null);
    const response = await apiService.getSourcesWithSettings();
    if (!response.success) {
      setError(response.error || 'Failed to load sources');
      setLoadingSources(false);
      return;
    }

    const nextSources = response.sources || [];
    setSources(nextSources);
    if (!selectedSourceId && nextSources[0]) {
      setSelectedSourceId(nextSources[0].id);
      syncSearchParams({ sourceId: nextSources[0].id, start: initialStart || null, end: initialEnd || null });
    }
    setLoadingSources(false);
  };

  const loadBriefing = async (refresh = false) => {
    const sourceId = selectedSourceId || sources[0]?.id;
    if (!sourceId) {
      setError('No source selected');
      return;
    }

    setError(null);
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoadingBriefing(true);
    }

    const response = refresh
      ? await apiService.refreshVerticalBriefing(sourceId, startDate || undefined, endDate || undefined)
      : await apiService.getVerticalBriefing(sourceId, startDate || undefined, endDate || undefined);

    if (!response.success) {
      setError(response.error || 'Failed to load vertical briefing');
      setBriefing(null);
    } else {
      setBriefing(response);
      setStartDate(response.start_date || '');
      setEndDate(response.end_date || '');
      syncSearchParams({ sourceId, start: response.start_date || null, end: response.end_date || null });
    }

    setLoadingBriefing(false);
    setRefreshing(false);
  };

  useEffect(() => {
    void loadSources();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!sources.length || !selectedSourceId) {
      return;
    }
    void loadBriefing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources.length, selectedSourceId]);

  const handleSourceChange = (value: string) => {
    setSelectedSourceId(value);
    setBriefing(null);
    setStartDate('');
    setEndDate('');
    syncSearchParams({ sourceId: value, start: null, end: null });
  };

  const windowLabel = startDate && endDate ? formatIssueRange(startDate, endDate) : 'full stored history';

  return (
    <Page width="wide">
      <PageHeader
        title="Vertical briefing"
        meta={
          <>
            <span className="break-words [overflow-wrap:anywhere]">{sourceName}</span>
            {selectedSource?.platform ? <> · {selectedSource.platform}</> : null}
            {' · '}
            {windowLabel}
            {briefing ? <> · {briefing.cached ? 'cached' : 'fresh'}</> : null}
          </>
        }
        actions={
          <>
            <Button variant="secondary" onClick={() => void loadBriefing(false)} disabled={busy || !selectedSourceId}>
              {loadingBriefing ? 'Loading…' : 'Reload'}
            </Button>
            <Button
              variant="primary"
              onClick={() => void loadBriefing(true)}
              disabled={busy || !selectedSourceId}
              title="Rebuild the cached briefing for this source"
            >
              {refreshing ? 'Rebuilding…' : 'Rebuild'}
            </Button>
          </>
        }
      />

      <div className="mb-8 flex flex-wrap items-end gap-x-8 gap-y-4 border-b border-line pb-6">
        <Field label="Source" htmlFor="vertical-source" className="w-full max-w-sm">
          <Select
            id="vertical-source"
            value={selectedSourceId}
            onChange={(e) => handleSourceChange(e.target.value)}
            disabled={loadingSources}
            className="w-full"
          >
            <option value="">Select a source</option>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.settings?.display_name || source.handle_or_url || source.id}
              </option>
            ))}
          </Select>
        </Field>
        <dl className="flex flex-wrap gap-x-6 gap-y-2 text-[0.8125rem]">
          {[
            ['tracks', formatCount(tracks.length)],
            ['posts processed', formatCount(briefing?.posts_processed ?? 0)],
            ['estimated tokens', formatCount(briefing?.estimated_tokens ?? 0)],
          ].map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-fg-3">{label}</dt>
              <dd className="font-semibold tabular-nums text-fg">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="w-full text-[0.8125rem] text-fg-3">
          Uses every stored post for this source by default. For one day across all sources, read the{' '}
          <TextLink to="/briefing">daily briefing</TextLink>.
        </p>
      </div>

      {error ? <Notice tone="error" title="The briefing did not load" message={error} className="mb-8" /> : null}

      <div className="grid gap-x-12 gap-y-10 xl:grid-cols-[minmax(0,68ch)_minmax(0,1fr)]">
        <article aria-labelledby="vertical-briefing-title" aria-busy={busy || undefined} className="min-w-0">
          <p className="text-[0.8125rem] tabular-nums text-fg-3">{windowLabel}</p>
          <h2
            id="vertical-briefing-title"
            className="mt-1 break-words text-[1.375rem] font-semibold leading-[1.25] tracking-[-0.02em] text-fg [overflow-wrap:anywhere]"
          >
            {sourceName}
          </h2>
          <div className="mt-5">
            {briefingText ? (
              <div className={cn('min-w-0 break-words text-[1.0625rem] leading-[1.7] text-fg [overflow-wrap:anywhere]', busy && 'opacity-50')}>
                <MarkdownRenderer content={briefingText} />
              </div>
            ) : loadingBriefing ? (
              <div role="status" aria-busy="true" className="space-y-2.5">
                <span className="sr-only">Loading the briefing</span>
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-11/12" />
                <Skeleton className="h-3 w-4/5" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            ) : (
              <Quiet>
                {error
                  ? 'Nothing to read for this source yet.'
                  : 'Select a source to read its briefing across the full stored history.'}
              </Quiet>
            )}
          </div>
          {briefing ? (
            <p className="mt-6 border-t border-line pt-3 text-[0.75rem] tabular-nums text-fg-3">
              scope {briefing.scope_type || 'source'} · variant {briefing.variant || 'default'}
              {briefing.subject_key ? <> · {briefing.subject_key}</> : null}
            </p>
          ) : null}
        </article>

        <section aria-labelledby="vertical-tracks-title" className="min-w-0">
          <h2 id="vertical-tracks-title" className="text-[1.0625rem] font-semibold tracking-[-0.01em] text-fg">
            Tracks <span className="font-normal tabular-nums text-fg-3">{formatCount(tracks.length)}</span>
          </h2>
          <p className="mt-0.5 text-[0.8125rem] text-fg-2">Repeated posts collapsed into threads, themes and one-off updates.</p>
          <div className="mt-3">
            {tracks.length ? (
              <ol className="list-none border-t border-line">
                {tracks.map((track, index) => (
                  <TrackItem key={track.id || index} track={track} index={index} postsById={postsById} />
                ))}
              </ol>
            ) : loadingBriefing ? (
              <div role="status" aria-busy="true" className="space-y-3 border-t border-line pt-4">
                <span className="sr-only">Loading tracks</span>
                <Skeleton className="h-3 w-2/3" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-line-strong px-4 py-3 text-[0.875rem] text-fg-2">
                No tracks were generated for this window.
              </div>
            )}
          </div>
        </section>
      </div>
    </Page>
  );
}
