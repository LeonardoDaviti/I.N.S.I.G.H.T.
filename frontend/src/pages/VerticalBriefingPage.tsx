import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, CalendarDays, ChevronRight, Loader2, RefreshCw, Sparkles, WandSparkles } from 'lucide-react';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import { apiService } from '../services/api';
import type { SourceWithSettings, VerticalBriefingResponse, VerticalBriefingTrack } from '../services/api';

function formatDate(value?: string | null) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString();
}

function formatCount(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '0';
  }
  return Number(value).toLocaleString();
}

function trackTone(kind?: string) {
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

export default function VerticalBriefingPage() {
  const navigate = useNavigate();
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

  return (
    <div className="app-shell min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="app-panel overflow-hidden">
          <div className="grid gap-0 lg:grid-cols-[1.1fr_0.9fr]">
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
                  Vertical Briefing
                </div>
                <div className="space-y-3">
                  <h1 className="text-3xl font-bold tracking-tight text-[var(--text-normal)] sm:text-4xl">
                    Read one source as a live thread.
                  </h1>
                  <p className="max-w-2xl text-sm leading-7 text-[var(--text-muted)] sm:text-base">
                    This page exposes the source-level briefing builder from the backend. Repeated posts collapse into project threads, recurring themes, and one-off updates so you can inspect the actual vertical structure.
                  </p>
                </div>
                <div className="flex flex-wrap gap-3">
                  <button type="button" onClick={() => void loadBriefing(false)} className="app-inline-button app-inline-button--primary">
                    <Sparkles className="h-4 w-4" />
                    Load Briefing
                  </button>
                  <button type="button" onClick={() => void loadBriefing(true)} className="app-inline-button">
                    <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                    Refresh Cached
                  </button>
                  <Link to="/briefing" className="app-inline-button">
                    <CalendarDays className="h-4 w-4" />
                    Open Daily Briefing
                  </Link>
                </div>
              </div>
            </div>

            <div className="border-t border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-6 lg:border-l lg:border-t-0">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-faint)]">Current source</div>
                  <div className="mt-2 text-lg font-semibold text-[var(--text-normal)]">
                    {selectedSource?.settings?.display_name || selectedSource?.handle_or_url || 'Select a source'}
                  </div>
                  <div className="mt-1 text-sm text-[var(--text-muted)]">
                    {selectedSource?.platform || 'source'} • {selectedSource?.id || 'no source selected'}
                  </div>
                </div>
                <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-faint)]">Briefing range</div>
                  <div className="mt-2 text-lg font-semibold text-[var(--text-normal)]">
                    {startDate && endDate ? `${startDate} to ${endDate}` : 'Full stored source history'}
                  </div>
                  <div className="mt-1 text-sm text-[var(--text-muted)]">
                    {briefing?.cached ? 'Cached briefing over the full stored range' : 'Auto-derived from every stored post for this source'}
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

        <section className="app-panel p-5">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
              <label className="space-y-2 text-sm">
                <span className="text-[var(--text-muted)]">Source</span>
                <select
                  value={selectedSourceId}
                  onChange={(e) => handleSourceChange(e.target.value)}
                  className="workspace-editor py-3 font-sans"
                  disabled={loadingSources}
                >
                  <option value="">Select a source</option>
                  {sources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.settings?.display_name || source.handle_or_url || source.id}
                    </option>
                  ))}
                </select>
              </label>
              <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-4 py-3">
                <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Coverage window</div>
                <div className="mt-2 text-sm font-semibold text-[var(--text-normal)]">
                  {startDate && endDate ? `${formatDate(startDate)} to ${formatDate(endDate)}` : 'Automatically using every stored post'}
                </div>
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  Vertical briefing now uses the full source archive by default.
                </div>
              </div>
            </div>

            <div className="flex items-end justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                  full source range
                </span>
                <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                  {tracks.length} tracks
                </span>
                <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                  {formatCount(briefing?.posts_processed)} posts processed
                </span>
                <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                  {formatCount(briefing?.estimated_tokens)} estimated tokens
                </span>
                <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                  {briefing?.cached ? 'cached' : 'fresh'}
                </span>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => void loadBriefing(false)} className="app-inline-button">
                  <Loader2 className={`h-4 w-4 ${loadingBriefing ? 'animate-spin' : ''}`} />
                  Reload
                </button>
                <button type="button" onClick={() => void loadBriefing(true)} className="app-inline-button app-inline-button--primary">
                  <WandSparkles className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                  Rebuild
                </button>
              </div>
            </div>
          </div>
        </section>

        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <SectionCard
            title="Briefing"
            subtitle={briefing?.subject_key ? `Subject key: ${briefing.subject_key}` : 'The rendered vertical briefing markdown.'}
            actions={loadingBriefing ? <Loader2 className="h-4 w-4 animate-spin text-[var(--text-faint)]" /> : null}
          >
            {briefingText ? (
              <div className="prose max-w-none">
                <MarkdownRenderer content={briefingText} />
              </div>
            ) : loadingBriefing ? (
              <div className="flex items-center gap-2 py-8 text-sm text-[var(--text-muted)]">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading briefing...
              </div>
            ) : (
              <div className="text-sm text-[var(--text-muted)]">
                Select a source to generate the vertical briefing across its full stored history.
              </div>
            )}
            <div className="mt-5 flex flex-wrap gap-2 text-xs text-[var(--text-muted)]">
              <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                scope {briefing?.scope_type || 'source'}
              </span>
              <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                variant {briefing?.variant || 'default'}
              </span>
              <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1">
                source {briefing?.source_label || selectedSource?.settings?.display_name || selectedSource?.handle_or_url || 'unknown'}
              </span>
            </div>
          </SectionCard>

          <SectionCard
            title={`Tracks (${tracks.length})`}
            subtitle="Collapsible track summaries with the supporting post ids and timeline signals."
            actions={loadingBriefing ? <Loader2 className="h-4 w-4 animate-spin text-[var(--text-faint)]" /> : null}
          >
            <div className="space-y-3">
              {tracks.length ? tracks.map((track: VerticalBriefingTrack) => (
                <details
                  key={track.id}
                  className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4"
                >
                  <summary className="cursor-pointer list-none">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-base font-semibold text-[var(--text-normal)]">{track.title}</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <span className={`rounded-full border px-2 py-0.5 text-xs ${trackTone(track.track_kind)}`}>
                            {track.track_kind || 'track'}
                          </span>
                          <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
                            {formatCount(track.unique_post_count)} unique posts
                          </span>
                          <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
                            {formatCount(track.raw_post_count)} raw posts
                          </span>
                        </div>
                      </div>
                      <ChevronRight className="h-4 w-4 text-[var(--text-faint)]" />
                    </div>
                  </summary>

                  <div className="mt-4 space-y-4">
                    {track.summary && (
                      <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4 text-sm leading-7 text-[var(--text-normal)]">
                        {track.summary}
                      </div>
                    )}

                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                        <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Story titles</div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(track.story_titles || []).length ? track.story_titles?.map((title) => (
                            <span key={title} className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                              {title}
                            </span>
                          )) : (
                            <span className="text-sm text-[var(--text-muted)]">No story titles recorded.</span>
                          )}
                        </div>
                      </div>

                      <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                        <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Entity hints</div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(track.entity_hints || []).length ? track.entity_hints?.map((hint) => (
                            <span key={hint} className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                              {hint}
                            </span>
                          )) : (
                            <span className="text-sm text-[var(--text-muted)]">No entity hints recorded.</span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                        <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Supporting posts</div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(track.post_ids || []).length ? track.post_ids?.map((postId) => {
                            const post = postsById[postId];
                            const label = post?.title || post?.source_display_name || post?.source || postId;
                            return (
                              <Link
                                key={postId}
                                to={`/posts/${encodeURIComponent(postId)}`}
                                className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)] transition hover:border-[var(--accent-strong)] hover:text-[var(--text-normal)]"
                              >
                                {label}
                              </Link>
                            );
                          }) : (
                            <span className="text-sm text-[var(--text-muted)]">No post ids were stored for this track.</span>
                          )}
                        </div>
                      </div>

                      <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4">
                        <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-faint)]">Timeline</div>
                        <div className="mt-3 space-y-2">
                          {(track.timeline || []).length ? track.timeline?.map((entry, index) => (
                            <div key={`${track.id}-${index}`} className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-3 text-sm">
                              <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--text-faint)]">
                                <span>{formatDate(entry.date)}</span>
                                {entry.post_ids?.length ? <span>{entry.post_ids.length} post(s)</span> : null}
                              </div>
                              {entry.summary && <div className="mt-2 leading-6 text-[var(--text-normal)]">{entry.summary}</div>}
                            </div>
                          )) : (
                            <div className="text-sm text-[var(--text-muted)]">No timeline entries recorded.</div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </details>
              )) : (
                <div className="rounded-2xl border border-dashed border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4 text-sm text-[var(--text-muted)]">
                  {loadingBriefing ? 'Loading tracks...' : 'No tracks were generated for this briefing window.'}
                </div>
              )}
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
