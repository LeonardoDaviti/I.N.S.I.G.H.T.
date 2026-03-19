import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  Archive,
  Calendar,
  CheckCircle2,
  ChevronLeft,
  Clock3,
  Database,
  Loader2,
  Play,
  RefreshCw,
  ScrollText,
  Settings,
  Zap,
} from 'lucide-react';
import { apiService } from '../services/api';
import type {
  ArchiveResponse,
  LiveFetchResponse,
  LogTailResponse,
  SourceWithSettings,
} from '../services/api';

type LogLevel = 'info' | 'success' | 'error';

type ActionLog = {
  id: string;
  level: LogLevel;
  message: string;
  at: string;
};

const DEFAULT_LOG_OPTIONS = [
  'application',
  'errors',
  'rss',
  'reddit',
  'youtube',
  'telegram',
  'automated',
];

const LOG_LABELS: Record<string, string> = {
  application: 'Application',
  errors: 'Errors',
  rss: 'RSS Connector',
  reddit: 'Reddit Connector',
  youtube: 'YouTube Connector',
  telegram: 'Telegram Connector',
  automated: 'Automated Operations',
  interactive: 'Interactive Operations',
  recovery: 'Recovery Operations',
};

function levelClasses(level: LogLevel) {
  switch (level) {
    case 'success':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800';
    case 'error':
      return 'border-rose-200 bg-rose-50 text-rose-800';
    default:
      return 'border-slate-200 bg-slate-50 text-slate-700';
  }
}

function formatJson(data: Record<string, any> | null) {
  if (!data) {
    return 'Nothing run in this session yet.';
  }
  return JSON.stringify(data, null, 2);
}

export default function IngestionControl() {
  const navigate = useNavigate();
  const [sources, setSources] = useState<SourceWithSettings[]>([]);
  const [loadingSources, setLoadingSources] = useState(true);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [desiredPosts, setDesiredPosts] = useState(200);
  const [liveFetchLimit, setLiveFetchLimit] = useState(20);
  const [selectedLogName, setSelectedLogName] = useState('application');
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [ingestResult, setIngestResult] = useState<Record<string, any> | null>(null);
  const [safeIngestResult, setSafeIngestResult] = useState<Record<string, any> | null>(null);
  const [sourceFetchResult, setSourceFetchResult] = useState<LiveFetchResponse | null>(null);
  const [briefingResult, setBriefingResult] = useState<Record<string, any> | null>(null);
  const [topicBriefingResult, setTopicBriefingResult] = useState<Record<string, any> | null>(null);
  const [archiveResult, setArchiveResult] = useState<ArchiveResponse | null>(null);
  const [logTail, setLogTail] = useState<LogTailResponse | null>(null);
  const [logs, setLogs] = useState<ActionLog[]>([]);
  const [error, setError] = useState<string | null>(null);

  const appendLog = (level: LogLevel, message: string) => {
    setLogs((prev) => [
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        level,
        message,
        at: new Date().toLocaleTimeString(),
      },
      ...prev,
    ].slice(0, 80));
  };

  const loadSources = async (options?: { silent?: boolean }) => {
    setLoadingSources(true);
    if (!options?.silent) {
      setError(null);
    }

    const response = await apiService.getSourcesWithSettings();
    if (!response.success) {
      const message = response.error || 'Failed to load sources';
      setError(message);
      if (!options?.silent) {
        appendLog('error', message);
      }
      setLoadingSources(false);
      return;
    }

    setSources(response.sources);
    if (!selectedSourceId && response.sources[0]) {
      setSelectedSourceId(response.sources[0].id);
    }
    if (!options?.silent) {
      appendLog('success', `Loaded ${response.sources.length} sources from the database`);
    }
    setLoadingSources(false);
  };

  const loadLogTail = async (logName = selectedLogName, options?: { silent?: boolean }) => {
    setLoadingLogs(true);
    const response = await apiService.getIngestionLogs(logName, 180);
    if (!response.success) {
      const message = response.error || 'Failed to load ingestion logs';
      if (!options?.silent) {
        setError(message);
        appendLog('error', message);
      }
      setLoadingLogs(false);
      return;
    }

    setLogTail(response);
    setLoadingLogs(false);
  };

  useEffect(() => {
    loadSources();
  }, []);

  useEffect(() => {
    loadLogTail(selectedLogName);

    const intervalId = window.setInterval(() => {
      loadLogTail(selectedLogName, { silent: true });
    }, 8000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [selectedLogName]);

  const enabledSources = useMemo(
    () => sources.filter((source) => source.enabled),
    [sources],
  );

  const selectedSource = useMemo(
    () => sources.find((source) => source.id === selectedSourceId) || null,
    [sources, selectedSourceId],
  );

  const availableLogs = logTail?.available_logs?.length ? logTail.available_logs : DEFAULT_LOG_OPTIONS;

  useEffect(() => {
    if (!selectedSource) {
      return;
    }

    setLiveFetchLimit(selectedSource.settings.max_posts_per_fetch || 20);
  }, [selectedSource?.id]);

  const runAction = async (
    actionKey: string,
    startMessage: string,
    fn: () => Promise<Record<string, any>>,
    onSuccess: (result: Record<string, any>) => void,
  ) => {
    setRunningAction(actionKey);
    setError(null);
    appendLog('info', startMessage);

    try {
      const result = await fn();
      if (result.success === false) {
        const message = result.error || 'Action failed';
        setError(message);
        appendLog('error', message);
        return;
      }

      onSuccess(result);
      appendLog('success', `${startMessage} completed`);

      if (['ingest', 'safe-ingest', 'source-fetch', 'archive-run', 'sync-json-to-db', 'sync-db-to-json'].includes(actionKey)) {
        await loadSources({ silent: true });
      }
      await loadLogTail(selectedLogName, { silent: true });
    } catch (actionError) {
      const message = actionError instanceof Error ? actionError.message : 'Unknown error';
      setError(message);
      appendLog('error', message);
    } finally {
      setRunningAction(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100">
      <div className="mx-auto max-w-7xl px-6 py-8 space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <button
              type="button"
              onClick={() => navigate('/briefing')}
              className="mb-3 inline-flex items-center text-sm text-slate-600 transition-colors hover:text-slate-900"
            >
              <ChevronLeft className="mr-1 h-4 w-4" /> Back to Briefing
            </button>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">Ingestion Control</h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-600">
              Force a fetch without waiting for the 20-hour scheduler, inspect recent runtime logs,
              sync the registry, and run archive jobs for one source at a time.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Scheduler</div>
            <div className="mt-1 flex items-center gap-2 text-sm font-medium text-slate-900">
              <Clock3 className="h-4 w-4 text-indigo-600" />
              20-hour automatic cycle
            </div>
          </div>
        </div>

        {error && (
          <div className="flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            <AlertCircle className="mt-0.5 h-5 w-5" />
            <div>{error}</div>
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[1.25fr_0.75fr]">
          <div className="space-y-6">
            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Immediate Actions</h2>
                  <p className="mt-1 text-sm text-slate-500">
                    Run global ingestion, trigger a single source instantly, or generate a briefing on demand.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => loadSources()}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                >
                  <RefreshCw className={`h-4 w-4 ${loadingSources ? 'animate-spin' : ''}`} />
                  Refresh
                </button>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <button
                  type="button"
                  onClick={() => runAction(
                    'ingest',
                    'Manual full ingestion started',
                    () => apiService.ingestPosts(),
                    (result) => setIngestResult(result),
                  )}
                  disabled={runningAction !== null}
                  className="rounded-2xl bg-indigo-600 px-4 py-4 text-left text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
                >
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    {runningAction === 'ingest' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    Run Full Ingestion
                  </div>
                  <div className="mt-2 text-xs text-indigo-100">Fetch all enabled sources immediately.</div>
                </button>

                <button
                  type="button"
                  onClick={() => runAction(
                    'safe-ingest',
                    'Manual safe ingestion started',
                    () => apiService.safeIngestPosts(),
                    (result) => setSafeIngestResult(result),
                  )}
                  disabled={runningAction !== null}
                  className="rounded-2xl bg-emerald-600 px-4 py-4 text-left text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
                >
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    {runningAction === 'safe-ingest' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />}
                    Run Safe Ingestion
                  </div>
                  <div className="mt-2 text-xs text-emerald-100">Only fetch sources that are new or stale.</div>
                </button>
              </div>

              <div className="mt-5 rounded-3xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-amber-600" />
                  <div className="text-sm font-semibold text-slate-900">Fetch A Single Source Now</div>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  Use this after adding a source so you do not have to wait for the next automatic cycle.
                </p>

                <div className="mt-4 grid gap-3 md:grid-cols-[1.6fr_0.8fr_auto] md:items-end">
                  <div>
                    <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                      Source
                    </label>
                    <select
                      value={selectedSourceId}
                      onChange={(e) => setSelectedSourceId(e.target.value)}
                      className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                    >
                      {sources.map((source) => (
                        <option key={source.id} value={source.id}>
                          {source.settings.display_name || source.handle_or_url} · {source.platform}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                      Live Fetch Limit
                    </label>
                    <input
                      type="number"
                      min={1}
                      value={liveFetchLimit}
                      onChange={(e) => setLiveFetchLimit(Math.max(1, Number(e.target.value) || 1))}
                      className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => selectedSourceId && runAction(
                      'source-fetch',
                      'Single-source fetch started',
                      () => apiService.fetchSourceNow(selectedSourceId, liveFetchLimit),
                      (result) => setSourceFetchResult(result as LiveFetchResponse),
                    )}
                    disabled={!selectedSourceId || runningAction !== null}
                    className="rounded-2xl bg-slate-900 px-4 py-3 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    {runningAction === 'source-fetch' ? 'Fetching…' : 'Fetch Source Now'}
                  </button>
                </div>

                {selectedSource && (
                  <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-700">
                    <div className="font-semibold text-slate-900">
                      {selectedSource.settings.display_name || selectedSource.handle_or_url}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-600">
                      <span>Platform: {selectedSource.platform}</span>
                      <span>Enabled: {selectedSource.enabled ? 'yes' : 'no'}</span>
                      <span>Stored posts: {selectedSource.post_count}</span>
                      <span>Priority: {selectedSource.settings.priority ?? 999}</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-5 grid gap-3 md:grid-cols-2">
                <button
                  type="button"
                  onClick={() => runAction(
                    'sync-json-to-db',
                    'Source registry sync JSON -> DB started',
                    () => apiService.syncSources('json-to-db'),
                    () => undefined,
                  )}
                  disabled={runningAction !== null}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  Sync JSON → DB
                </button>
                <button
                  type="button"
                  onClick={() => runAction(
                    'sync-db-to-json',
                    'Source registry sync DB -> JSON started',
                    () => apiService.syncSources('db-to-json'),
                    () => undefined,
                  )}
                  disabled={runningAction !== null}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  Sync DB → JSON
                </button>
              </div>

              <div className="mt-5 grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-end">
                <div>
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                    Briefing Date
                  </label>
                  <div className="relative">
                    <Calendar className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      type="date"
                      value={selectedDate}
                      onChange={(e) => setSelectedDate(e.target.value)}
                      className="w-full rounded-2xl border border-slate-200 bg-white py-3 pl-10 pr-3 text-sm text-slate-900 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                    />
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => runAction(
                    'briefing',
                    `Daily briefing requested for ${selectedDate}`,
                    () => apiService.generateBriefing(selectedDate),
                    (result) => setBriefingResult(result),
                  )}
                  disabled={runningAction !== null}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  {runningAction === 'briefing' ? 'Generating…' : 'Generate Daily'}
                </button>
                <button
                  type="button"
                  onClick={() => runAction(
                    'topic-briefing',
                    `Topic briefing requested for ${selectedDate}`,
                    () => apiService.generateBriefingWithTopics(selectedDate),
                    (result) => setTopicBriefingResult(result),
                  )}
                  disabled={runningAction !== null}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  {runningAction === 'topic-briefing' ? 'Generating…' : 'Generate Topics'}
                </button>
              </div>

              <div className="mt-5 grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-950 p-4 text-slate-100">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Last Full Ingestion</div>
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs leading-6">
                    {formatJson(ingestResult)}
                  </pre>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-950 p-4 text-slate-100">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Last Safe Ingestion</div>
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs leading-6">
                    {formatJson(safeIngestResult)}
                  </pre>
                </div>
              </div>

              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-950 p-4 text-slate-100">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Last Single-Source Fetch</div>
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs leading-6">
                    {formatJson(sourceFetchResult as Record<string, any> | null)}
                  </pre>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-950 p-4 text-slate-100">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Last Briefing Actions</div>
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs leading-6">
                    {formatJson({
                      daily: briefingResult,
                      topics: topicBriefingResult,
                    })}
                  </pre>
                </div>
              </div>
            </section>

            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <Archive className="h-5 w-5 text-amber-600" />
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Archive Control</h2>
                  <p className="mt-1 text-sm text-slate-500">
                    Plan or run a one-source archive job without touching the automatic scheduler.
                  </p>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-[1.6fr_0.8fr]">
                <div>
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                    Source
                  </label>
                  <select
                    value={selectedSourceId}
                    onChange={(e) => setSelectedSourceId(e.target.value)}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                  >
                    {sources.map((source) => (
                      <option key={source.id} value={source.id}>
                        {source.settings.display_name || source.handle_or_url} · {source.platform}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                    Desired Posts
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={desiredPosts}
                    onChange={(e) => setDesiredPosts(Math.max(1, Number(e.target.value) || 1))}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                  />
                </div>
              </div>

              {selectedSource && (
                <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  <div className="font-semibold text-slate-900">{selectedSource.settings.display_name || selectedSource.handle_or_url}</div>
                  <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-600">
                    <span>Platform: {selectedSource.platform}</span>
                    <span>Enabled: {selectedSource.enabled ? 'yes' : 'no'}</span>
                    <span>Stored posts: {selectedSource.post_count}</span>
                    {selectedSource.settings.archive?.status && <span>Archive status: {selectedSource.settings.archive.status}</span>}
                  </div>
                </div>
              )}

              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => selectedSourceId && runAction(
                    'archive-status',
                    'Archive status requested',
                    () => apiService.getArchiveStatus(selectedSourceId),
                    (result) => setArchiveResult(result),
                  )}
                  disabled={!selectedSourceId || runningAction !== null}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  Status
                </button>
                <button
                  type="button"
                  onClick={() => selectedSourceId && runAction(
                    'archive-plan',
                    'Archive plan requested',
                    () => apiService.planArchive(selectedSourceId, desiredPosts),
                    (result) => setArchiveResult(result),
                  )}
                  disabled={!selectedSourceId || runningAction !== null}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  Plan Archive
                </button>
                <button
                  type="button"
                  onClick={() => selectedSourceId && runAction(
                    'archive-run',
                    'Archive run started',
                    () => apiService.runArchive(selectedSourceId, desiredPosts),
                    (result) => setArchiveResult(result),
                  )}
                  disabled={!selectedSourceId || runningAction !== null}
                  className="rounded-2xl bg-amber-500 px-4 py-3 text-sm font-medium text-white hover:bg-amber-600 disabled:opacity-50"
                >
                  {runningAction === 'archive-run' ? 'Archiving…' : 'Run Archive'}
                </button>
              </div>

              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-950 p-4 text-sm text-slate-100">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Archive Result</div>
                <pre className="overflow-x-auto whitespace-pre-wrap text-xs leading-6">
                  {formatJson(archiveResult as Record<string, any> | null)}
                </pre>
              </div>
            </section>
          </div>

          <div className="space-y-6">
            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <Settings className="h-5 w-5 text-indigo-600" />
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">System Snapshot</h2>
                  <p className="mt-1 text-sm text-slate-500">Quick read of the current registry before you trigger work.</p>
                </div>
              </div>
              <div className="grid gap-3">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Sources</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">{sources.length}</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Enabled Sources</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">{enabledSources.length}</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Selected Source</div>
                  <div className="mt-2 break-words text-sm font-medium text-slate-900">
                    {selectedSource?.settings.display_name || selectedSource?.handle_or_url || 'None'}
                  </div>
                </div>
              </div>
            </section>

            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <ScrollText className="h-5 w-5 text-slate-700" />
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900">Runtime Log Tail</h2>
                    <p className="mt-1 text-sm text-slate-500">
                      Shared log files from the backend and scheduler containers.
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => loadLogTail(selectedLogName)}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                >
                  <RefreshCw className={`h-4 w-4 ${loadingLogs ? 'animate-spin' : ''}`} />
                  Refresh
                </button>
              </div>

              <div className="mb-4">
                <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                  Log File
                </label>
                <select
                  value={selectedLogName}
                  onChange={(e) => setSelectedLogName(e.target.value)}
                  className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                >
                  {availableLogs.map((logOption) => (
                    <option key={logOption} value={logOption}>
                      {LOG_LABELS[logOption] || logOption}
                    </option>
                  ))}
                </select>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-950 p-4 text-slate-100">
                <div className="flex items-center justify-between gap-3 text-xs uppercase tracking-[0.14em] text-slate-400">
                  <span>{LOG_LABELS[selectedLogName] || selectedLogName}</span>
                  <span>{logTail?.exists ? 'available' : 'not created yet'}</span>
                </div>
                <pre className="mt-3 max-h-[24rem] overflow-auto whitespace-pre-wrap text-xs leading-6">
                  {loadingLogs && !logTail
                    ? 'Loading logs...'
                    : logTail?.lines?.length
                      ? logTail.lines.join('\n')
                      : 'No lines available for this log yet.'}
                </pre>
              </div>
            </section>

            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Session Log</h2>
                  <p className="mt-1 text-sm text-slate-500">Action history for operations triggered from this screen.</p>
                </div>
              </div>

              <div className="max-h-[30rem] space-y-3 overflow-y-auto pr-1">
                {logs.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
                    No manual actions yet.
                  </div>
                ) : (
                  logs.map((entry) => (
                    <div key={entry.id} className={`rounded-2xl border px-4 py-3 ${levelClasses(entry.level)}`}>
                      <div className="flex items-center justify-between gap-3 text-xs uppercase tracking-[0.14em]">
                        <span>{entry.level}</span>
                        <span>{entry.at}</span>
                      </div>
                      <div className="mt-2 text-sm font-medium">{entry.message}</div>
                    </div>
                  ))
                )}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
