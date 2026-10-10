import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { apiService, type Folder, type Post } from '../services/api';
import { EmptyState, ErrorState, LoadingState } from '../components/states';
import { Button, Chip, Page, PageHeader, Row } from '../components/ui';
import BackLink from '../components/ui/BackLink';
import SlashChoice from '../components/reader/SlashChoice';
import { sourceLabel } from '../lib/sourceLabel';
import { feedDateLabel, feedFullTime } from '../lib/feedDates';
import { formatCount, middleTruncate, plural } from '../lib/format';
import MilestonesRail from '../components/MilestonesRail';
import TrackBriefingPanel from '../components/TrackBriefingPanel';
import { useAnalysisEnabled } from '../hooks/useAnalysis';

const PAGE_SIZE = 25;

type WindowValue = '7' | '30' | 'all';
const WINDOWS: ReadonlyArray<{ value: WindowValue; label: string }> = [
  { value: '7', label: '7d' },
  { value: '30', label: '30d' },
  { value: 'all', label: 'all' },
];

/** First media_urls entry that actually looks like an image. */
function thumbnailOf(post: Post): string | null {
  const urls = Array.isArray(post.media_urls) ? post.media_urls : [];
  for (const url of urls) {
    if (typeof url !== 'string') continue;
    if (/\.(jpe?g|png|webp|gif|avif)(\?|$)/i.test(url)) return url;
    if (/(i\.ytimg\.com|i\.redd\.it|preview\.redd\.it)/i.test(url)) return url;
  }
  return null;
}

export default function TrackPage() {
  const { trackId = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const [folder, setFolder] = useState<Folder | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [total, setTotal] = useState(0);
  const [sourceCount, setSourceCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const days = useMemo(() => {
    const raw = searchParams.get('days');
    const parsed = raw ? parseInt(raw, 10) : NaN;
    return Number.isFinite(parsed) ? parsed : undefined;
  }, [searchParams]);

  // The newest arguments and request, so a slow response for an old window (or a
  // reload that awaited a fetch run) never lands on the list for a newer one.
  const latest = useRef({ trackId, days, count: 0 });
  latest.current = { trackId, days, count: posts.length };
  const generation = useRef(0);

  const load = useCallback(async (opts?: { append?: boolean }) => {
    const append = Boolean(opts?.append);
    const { trackId: id, days: window, count } = latest.current;
    const request = ++generation.current;
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError(null);
    const response = await apiService.getFolderPosts(id, {
      limit: PAGE_SIZE,
      offset: append ? count : 0,
      days: window,
    });
    if (request !== generation.current) return;
    if (!response.success) {
      setError(response.error || 'Failed to load this track');
    } else {
      setFolder(response.folder ?? null);
      setSourceCount(response.source_count ?? 0);
      setTotal(response.total ?? 0);
      setPosts((prev) => {
        const merged = append ? [...prev, ...response.posts] : response.posts;
        // Offset pagination can re-return a row if ingestion writes mid-scroll.
        return Array.from(new Map(merged.map((p, i) => [p.id ?? p.url ?? `idx:${i}`, p])).values());
      });
    }
    setLoading(false);
    setLoadingMore(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load, trackId, days]);

  const setWindow = (value?: number) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set('days', String(value));
    else next.delete('days');
    setSearchParams(next, { replace: true });
  };

  const isTrack = folder?.kind === 'track';
  // Reading-only (Decision 2): no tracks list to go back to, no briefing panel,
  // no milestones rail. The page is the track's posts.
  const analysisEnabled = useAnalysisEnabled();

  const windowValue: WindowValue = days === 7 ? '7' : days === 30 ? '30' : 'all';
  const meta = [
    plural(sourceCount, 'source'),
    plural(total, 'post'),
    folder?.exclude_from_main_digest ? 'hidden from the main digest' : null,
  ].filter(Boolean).join(' · ');

  return (
    <Page width={analysisEnabled ? 'wide' : 'reading'} className="pt-6 sm:pt-8">
      {analysisEnabled ? <BackLink to="/tracks" label="tracks" /> : <BackLink to="/" label="feed" />}

      <PageHeader
        title={(
          <span className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="[overflow-wrap:anywhere]">{folder?.name || 'Track'}</span>
            {isTrack ? <Chip className="relative -top-px">track</Chip> : null}
          </span>
        )}
        meta={(
          <>
            {loading && !folder ? 'Loading…' : meta}
            {folder?.description ? (
              <span className="mt-2 block max-w-prose break-words text-[0.875rem] [overflow-wrap:anywhere]">{folder.description}</span>
            ) : null}
          </>
        )}
        // No fetch here: fetching is an ingestion job (Sources → the track's ⋯ menu).
        actions={(
          <Button
            variant="ghost"
            size="icon"
            onClick={() => void load()}
            disabled={loading}
            aria-label="Refresh"
            title="Refresh this list"
          >
            <RefreshCw aria-hidden="true" className={loading ? 'motion-safe:animate-spin' : ''} />
          </Button>
        )}
      />

      {/* Analysis on: two columns from lg up, reading feed left, milestones rail
          right. The rail is LAST in the DOM, so on mobile it stacks below the
          feed. Reading-only: one column of posts. */}
      <div className={analysisEnabled ? 'lg:grid lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start lg:gap-10' : undefined}>
        <div className="min-w-0">
          {analysisEnabled ? <TrackBriefingPanel folderId={trackId} className="mb-6" /> : null}

          <div className="mb-2 flex items-center justify-between gap-3">
            <h2 className="text-[0.8125rem] lowercase text-fg-3">posts</h2>
            <SlashChoice
              label="Time window"
              value={windowValue}
              options={WINDOWS}
              onChange={(value) => setWindow(value === 'all' ? undefined : Number(value))}
              className="-mr-1"
            />
          </div>

          {error ? (
            <ErrorState title="Could not load this track" error={error} onRetry={() => void load()} className="mb-4" />
          ) : null}

          {loading && posts.length === 0 ? <LoadingState label="Loading posts" rows={4} /> : null}

          {!loading && posts.length === 0 && !error ? (
            <EmptyState
              title="No posts yet"
              description={
                sourceCount === 0
                  ? 'This track has no sources yet. Add some from Settings → Sources.'
                  : `This track has ${plural(sourceCount, 'source')} but no posts${days ? ` in the last ${days} days` : ''}. Posts appear once ingestion collects them.`
              }
              action={
                sourceCount === 0
                  ? { label: 'Add a source', href: '/settings/sources' }
                  : { label: 'This track in Sources', href: '/settings/sources', quiet: true }
              }
            />
          ) : null}

          {posts.length > 0 ? (
            <div className="flex flex-col gap-2">
              {posts.map((post, index) => {
                const thumb = thumbnailOf(post);
                const source = sourceLabel(post.source_display_name);
                return (
                  <Row
                    key={post.id ?? post.url ?? `idx:${index}`}
                    to={post.id ? `/posts/${post.id}` : undefined}
                    href={post.id ? undefined : post.url ?? undefined}
                    meta={(
                      <time dateTime={post.published_at ?? undefined} title={post.published_at ? feedFullTime(post.published_at) : undefined}>
                        {post.published_at ? feedDateLabel(post.published_at) : '—'}
                      </time>
                    )}
                    title={<span dir="auto">{post.title?.trim() || 'Untitled post'}</span>}
                    description={(
                      <span className="flex min-w-0 items-center gap-1.5 text-fg-3">
                        <span className="min-w-0 truncate" title={post.source_display_name ?? undefined}>{middleTruncate(source, 56)}</span>
                        {post.platform ? (
                          <>
                            <span aria-hidden="true">/</span>
                            <span className="shrink-0 lowercase">{post.platform}</span>
                          </>
                        ) : null}
                      </span>
                    )}
                    trailing={thumb ? <Thumb src={thumb} /> : undefined}
                    // The reader's date column width: Row's default 5.5rem costs a
                    // phone title a third of its line.
                    className="gap-3 px-3 sm:gap-4 sm:px-4 [&>div:first-child]:w-[3.25rem] sm:[&>div:first-child]:w-[4.25rem]"
                  />
                );
              })}
            </div>
          ) : null}

          {posts.length > 0 && posts.length < total ? (
            <Button
              variant="secondary"
              size="lg"
              onClick={() => void load({ append: true })}
              disabled={loadingMore}
              className="mt-4 w-full"
            >
              {loadingMore ? 'Loading…' : `Load ${formatCount(Math.min(PAGE_SIZE, total - posts.length))} more`}
            </Button>
          ) : posts.length > 0 ? (
            <p className="py-6 text-center text-[0.8125rem] text-fg-3">You’ve reached the end.</p>
          ) : null}
        </div>

        {/* A long rail must not trap the page: it scrolls inside itself when it
            outgrows the viewport. */}
        {analysisEnabled ? (
          <div className="mt-10 lg:sticky lg:top-6 lg:mt-0 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto">
            <MilestonesRail folderId={trackId} />
          </div>
        ) : null}
      </div>
    </Page>
  );
}

/** A small grayscale preview; it removes itself when the image fails. Hidden on phones. */
function Thumb({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <span className="hidden aspect-video w-20 overflow-hidden rounded-[0.25rem] border border-line bg-surface sm:block">
      <img src={src} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} className="h-full w-full object-cover grayscale" />
    </span>
  );
}
