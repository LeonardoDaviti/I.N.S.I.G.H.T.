import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ChevronLeft, RefreshCw, ExternalLink, Inbox } from 'lucide-react';
import { apiService, type Folder, type Post } from '../services/api';

const PAGE_SIZE = 25;

function relativeTime(value?: string | null): string {
  if (!value) return '';
  const parsed = new Date(value);
  if (isNaN(parsed.getTime())) return '';
  const minutes = Math.round((Date.now() - parsed.getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return parsed.toLocaleDateString();
}

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
  const navigate = useNavigate();
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

  const load = useCallback(
    async (opts?: { append?: boolean }) => {
      const append = Boolean(opts?.append);
      append ? setLoadingMore(true) : setLoading(true);
      setError(null);
      const response = await apiService.getFolderPosts(trackId, {
        limit: PAGE_SIZE,
        offset: append ? posts.length : 0,
        days,
      });
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
      append ? setLoadingMore(false) : setLoading(false);
    },
    [trackId, days, posts.length],
  );

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackId, days]);

  const setWindow = (value?: number) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set('days', String(value));
    else next.delete('days');
    setSearchParams(next, { replace: true });
  };

  const isTrack = folder?.kind === 'track';

  return (
    <div className="app-shell min-h-screen bg-gray-50">
      <div className="max-w-3xl mx-auto p-6">
        <button
          onClick={() => navigate('/experts')}
          className="mb-3 inline-flex items-center text-sm text-gray-600 hover:text-gray-900"
        >
          <ChevronLeft className="w-4 h-4 mr-1" /> Back to Tracks
        </button>

        <div className="flex items-start justify-between gap-4 mb-1">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold text-gray-900">{folder?.name || 'Track'}</h1>
              {isTrack && (
                <span className="px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 text-xs font-medium">
                  Track
                </span>
              )}
            </div>
            {folder?.description && <p className="text-sm text-gray-600 mt-1">{folder.description}</p>}
          </div>
          <button
            onClick={() => void load()}
            disabled={loading}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-gray-300 bg-white text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500 mb-4">
          <span>{sourceCount} sources</span>
          <span>·</span>
          <span>{total} posts</span>
          {folder?.exclude_from_main_digest && (
            <>
              <span>·</span>
              <span className="text-amber-700">hidden from main digest</span>
            </>
          )}
          <span className="ml-auto inline-flex items-center gap-1">
            {[
              { label: '7d', value: 7 },
              { label: '30d', value: 30 },
              { label: 'All', value: undefined },
            ].map((opt) => (
              <button
                key={opt.label}
                onClick={() => setWindow(opt.value)}
                className={`px-2 py-0.5 rounded ${
                  days === opt.value ? 'bg-gray-900 text-white' : 'bg-white border border-gray-200 hover:bg-gray-50'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </span>
        </div>

        {error && (
          <div className="mb-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-3">{error}</div>
        )}

        {loading && posts.length === 0 && (
          <div className="space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse rounded-xl border border-gray-200 bg-white p-4">
                <div className="h-4 bg-gray-200 rounded w-3/4 mb-2" />
                <div className="h-3 bg-gray-100 rounded w-1/3" />
              </div>
            ))}
          </div>
        )}

        {!loading && posts.length === 0 && !error && (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white p-8 text-center">
            <Inbox className="w-8 h-8 mx-auto text-gray-400 mb-3" />
            <div className="font-medium text-gray-900 mb-1">Nothing collected yet</div>
            <p className="text-sm text-gray-600 max-w-md mx-auto">
              This track has {sourceCount} sources but no posts. Newly added sources have no fetch
              history, so they are collected on the next ingestion cycle. Run one from{' '}
              <button onClick={() => navigate('/ingestion')} className="text-blue-600 hover:underline">
                Ingestion Control
              </button>
              , or wait for the scheduler.
            </p>
          </div>
        )}

        <div className="space-y-3">
          {posts.map((post) => {
            const thumb = thumbnailOf(post);
            return (
              <article
                key={post.id}
                className="rounded-xl border border-gray-200 bg-white p-4 hover:border-gray-300 transition"
              >
                <div className="flex gap-3">
                  {thumb && (
                    <img
                      src={thumb}
                      alt=""
                      loading="lazy"
                      className="w-24 h-16 object-cover rounded-md shrink-0 bg-gray-100"
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <h2 className="font-semibold text-gray-900 leading-snug">
                      {post.title || '(untitled)'}
                    </h2>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                      <span className="px-1.5 py-0.5 rounded bg-gray-100">{post.platform}</span>
                      <span className="truncate max-w-[16rem]">{post.source_display_name}</span>
                      <span>·</span>
                      <span>{relativeTime(post.published_at)}</span>
                    </div>
                    <div className="mt-2 flex items-center gap-3 text-sm">
                      <button
                        onClick={() => navigate(`/posts/${post.id}`)}
                        className="text-blue-600 hover:text-blue-800"
                      >
                        Read
                      </button>
                      {post.url && (
                        <a
                          href={post.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-gray-500 hover:text-gray-700"
                        >
                          Source <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>

        {posts.length > 0 && posts.length < total && (
          <button
            onClick={() => void load({ append: true })}
            disabled={loadingMore}
            className="mt-4 w-full py-2 rounded-md border border-gray-300 bg-white text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {loadingMore ? 'Loading…' : `Load ${Math.min(PAGE_SIZE, total - posts.length)} more`}
          </button>
        )}
      </div>
    </div>
  );
}
