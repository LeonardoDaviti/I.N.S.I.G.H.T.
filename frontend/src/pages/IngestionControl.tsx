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
  X,
  Zap,
} from 'lucide-react';
import { apiService } from '../services/api';
import type {
  ArchiveCatalogEntry,
  ArchiveResponse,
  JobRun,
  LiveFetchResponse,
  LogTailResponse,
  OperationsOverviewResponse,
  SchedulerConfig,
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

function formatJobTimestamp(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString();
}

function formatJobDuration(startedAt?: string | null, finishedAt?: string | null) {
  if (!startedAt || !finishedAt) return null;
  const started = new Date(startedAt).getTime();
  const finished = new Date(finishedAt).getTime();
  if (Number.isNaN(started) || Number.isNaN(finished) || finished < started) return null;
  const elapsedMs = finished - started;
  if (elapsedMs < 1000) return '<1s';
  const totalSeconds = Math.round(elapsedMs / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function formatEstimatedTokens(value: unknown) {
  const num = Number(value || 0);
  if (!Number.isFinite(num) || num <= 0) return null;
  return num.toLocaleString();
}

function formatTimeRemaining(milliseconds: number) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function extractEstimatedTokens(payload?: Record<string, any> | null) {
  return formatEstimatedTokens(payload?.estimated_tokens ?? payload?.token_usage?.estimated_tokens);
}

function archiveDotClasses(status?: string | null) {
  switch (status) {
    case 'archived':
      return 'bg-emerald-500';
    case 'partial':
      return 'bg-amber-500';
    default:
      return 'bg-rose-500';
  }
}

function formatArchiveRatio(entry?: ArchiveCatalogEntry | null) {
  if (!entry) return '0/?';
  const available = typeof entry.available_posts === 'number' ? entry.available_posts.toLocaleString() : '?';
  return `${(entry.stored_posts || 0).toLocaleString()}/${available}`;
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
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [savingScheduler, setSavingScheduler] = useState(false);
  const [schedulerDirty, setSchedulerDirty] = useState(false);
  const [ingestResult, setIngestResult] = useState<Record<string, any> | null>(null);
  const [safeIngestResult, setSafeIngestResult] = useState<Record<string, any> | null>(null);
  const [sourceFetchResult, setSourceFetchResult] = useState<LiveFetchResponse | null>(null);
  const [briefingResult, setBriefingResult] = useState<Record<string, any> | null>(null);
  const [topicBriefingResult, setTopicBriefingResult] = useState<Record<string, any> | null>(null);
  const [archiveResult, setArchiveResult] = useState<ArchiveResponse | null>(null);
  const [archiveCatalog, setArchiveCatalog] = useState<ArchiveCatalogEntry[]>([]);
  const [loadingArchiveCatalog, setLoadingArchiveCatalog] = useState(false);
  const [archiveResume, setArchiveResume] = useState(true);
  const [archivePageDelay, setArchivePageDelay] = useState(5);
  const [archiveBatchSize, setArchiveBatchSize] = useState(10);
  const [archiveBatchCooldown, setArchiveBatchCooldown] = useState(30);
  const [logTail, setLogTail] = useState<LogTailResponse | null>(null);
  const [operationsOverview, setOperationsOverview] = useState<OperationsOverviewResponse | null>(null);
  const [schedulerConfig, setSchedulerConfig] = useState<SchedulerConfig | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<JobRun | null>(null);
  const [loadingSelectedJob, setLoadingSelectedJob] = useState(false);
  const [logs, setLogs] = useState<ActionLog[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dismissedAlertIds, setDismissedAlertIds] = useState<string[]>([]);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [manualTimerAnchorMs, setManualTimerAnchorMs] = useState<number | null>(null);

  useEffect(() => {
    const tickId = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);

    return () => {
      window.clearInterval(tickId);
    };
  }, []);

  useEffect(() => {
    const activeAlertIds = new Set((operationsOverview?.alerts || []).map((alert) => alert.id));
    setDismissedAlertIds((prev) => prev.filter((id) => activeAlertIds.has(id)));
  }, [operationsOverview?.alerts]);

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

  const loadOperationsOverview = async (options?: { silent?: boolean }) => {
    setLoadingOverview(true);
    const response = await apiService.getOperationsOverview();
    if (!response.success) {
      const message = response.error || 'Failed to load operations overview';
      if (!options?.silent) {
        setError(message);
        appendLog('error', message);
      }
      setLoadingOverview(false);
      return;
    }

    setOperationsOverview(response);
    if (!schedulerDirty && response.scheduler) {
      setSchedulerConfig(response.scheduler);
    }
    if (!selectedJobId && response.jobs?.[0]?.id) {
      setSelectedJobId(response.jobs[0].id);
    }
    setLoadingOverview(false);
  };

  const loadArchiveCatalog = async (options?: { silent?: boolean }) => {
    setLoadingArchiveCatalog(true);
    const response = await apiService.getArchiveCatalog();
    if (!response.success) {
      if (!options?.silent) {
        const message = response.error || 'Failed to load archive catalog';
        setError(message);
        appendLog('error', message);
      }
      setLoadingArchiveCatalog(false);
      return;
    }
    setArchiveCatalog(response.sources || []);
    setLoadingArchiveCatalog(false);
  };

  const loadSelectedJob = async (jobId: string, options?: { silent?: boolean }) => {
    setLoadingSelectedJob(true);
    const response = await apiService.getOperationJob(jobId);
    if (!response.success || !response.job) {
      if (!options?.silent) {
        const message = response.error || 'Failed to load mission details';
        setError(message);
        appendLog('error', message);
      }
      setLoadingSelectedJob(false);
      return;
    }

    setSelectedJob(response.job);
    setLoadingSelectedJob(false);
  };

  useEffect(() => {
    loadSources();
    loadOperationsOverview();
    loadArchiveCatalog();
  }, []);

  useEffect(() => {
    loadLogTail(selectedLogName);

    const intervalId = window.setInterval(() => {
      loadLogTail(selectedLogName, { silent: true });
      loadOperationsOverview({ silent: true });
      loadArchiveCatalog({ silent: true });
      if (selectedJobId) {
        loadSelectedJob(selectedJobId, { silent: true });
      }
    }, 8000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [selectedLogName, selectedJobId]);

  const enabledSources = useMemo(
    () => sources.filter((source) => source.enabled),
    [sources],
  );

  const selectedSource = useMemo(
    () => enabledSources.find((source) => source.id === selectedSourceId) || null,
    [enabledSources, selectedSourceId],
  );

  const availableLogs = logTail?.available_logs?.length ? logTail.available_logs : DEFAULT_LOG_OPTIONS;

  const visibleMissionAlerts = useMemo(
    () => (operationsOverview?.alerts || []).filter((alert) => !dismissedAlertIds.includes(alert.id)).slice(0, 3),
    [dismissedAlertIds, operationsOverview?.alerts],
  );

  const selectedArchiveEntry = useMemo(
    () => archiveCatalog.find((entry) => entry.source_id === selectedSourceId) || null,
    [archiveCatalog, selectedSourceId],
  );

  const schedulerNextRunAt = useMemo(() => {
    if (!schedulerConfig?.interval_hours) return null;

    const schedulerJobs = (operationsOverview?.jobs || []).filter(
      (job) => job.job_type === 'scheduler_cycle' && job.trigger === 'scheduler',
    );
    if (!schedulerJobs.length) return null;

    const latestSchedulerJob = schedulerJobs.reduce((latest, current) => {
      const latestAt = new Date(latest.finished_at || latest.started_at || '').getTime();
      const currentAt = new Date(current.finished_at || current.started_at || '').getTime();
      return currentAt > latestAt ? current : latest;
    });

    const baselineAt = latestSchedulerJob.finished_at || latestSchedulerJob.started_at;
    const baselineMsFromJobs = baselineAt ? new Date(baselineAt).getTime() : NaN;
    const safeBaselineFromJobs = Number.isNaN(baselineMsFromJobs) ? null : baselineMsFromJobs;
    const effectiveBaselineMs = Math.max(
      safeBaselineFromJobs || 0,
      manualTimerAnchorMs || 0,
    );
    if (!effectiveBaselineMs) return null;

    return effectiveBaselineMs + (Number(schedulerConfig.interval_hours) * 60 * 60 * 1000);
  }, [manualTimerAnchorMs, operationsOverview?.jobs, schedulerConfig?.interval_hours]);

  const schedulerCountdown = useMemo(() => {
    if (!schedulerNextRunAt) return null;
    const remaining = schedulerNextRunAt - nowMs;
    if (remaining <= 0) return 'due now';
    return formatTimeRemaining(remaining);
  }, [schedulerNextRunAt, nowMs]);

  useEffect(() => {
    if (!enabledSources.length) {
      return;
    }

    if (!enabledSources.some((source) => source.id === selectedSourceId)) {
      setSelectedSourceId(enabledSources[0].id);
    }
  }, [enabledSources, selectedSourceId]);

  useEffect(() => {
    if (!selectedSource) {
      return;
    }

    setLiveFetchLimit(selectedSource.settings.max_posts_per_fetch || 20);
    const archiveSettings = selectedSource.settings.archive || {};
    const archiveRateLimit = archiveSettings.rate_limit || {};
    setArchiveResume(Boolean(archiveSettings.resume_ready));
    setArchivePageDelay(Number(archiveRateLimit.page_delay_seconds || (selectedSource.platform === 'reddit' ? 2 : 5)));
    setArchiveBatchSize(Number(archiveRateLimit.batch_size || 10));
    setArchiveBatchCooldown(Number(archiveRateLimit.batch_cooldown_seconds || 30));
  }, [selectedSource?.id]);

  useEffect(() => {
    if (!selectedJobId) {
      setSelectedJob(null);
      return;
    }
    loadSelectedJob(selectedJobId, { silent: true });
  }, [selectedJobId]);

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

      if (['ingest', 'safe-ingest', 'source-fetch', 'archive-run', 'archive-run-fresh', 'sync-json-to-db', 'sync-db-to-json'].includes(actionKey)) {
        await loadSources({ silent: true });
        await loadArchiveCatalog({ silent: true });
      }
      await loadOperationsOverview({ silent: true });
      await loadLogTail(selectedLogName, { silent: true });
    } catch (actionError) {
      const message = actionError instanceof Error ? actionError.message : 'Unknown error';
      setError(message);
      appendLog('error', message);
    } finally {
      setRunningAction(null);
    }
  };

  const saveSchedulerConfig = async () => {
    if (!schedulerConfig) {
      return;
    }

    setSavingScheduler(true);
    const response = await apiService.updateSchedulerConfig(schedulerConfig);
    if (!response.success || !response.scheduler) {
      setError(response.error || 'Failed to save scheduler config');
      setSavingScheduler(false);
      return;
    }

    setSchedulerConfig(response.scheduler);
    setSchedulerDirty(false);
    appendLog('success', `Scheduler updated to ${response.scheduler.interval_hours} hour cycle`);
    await loadOperationsOverview({ silent: true });
    setSavingScheduler(false);
  };

  return (
    <div className="app-shell min-h-screen">
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
              Force a fetch without waiting for the next scheduler cycle, inspect recent runtime logs,
              sync the registry, and run archive jobs for one source at a time.
            </p>
          </div>
          <div className="app-panel px-4 py-3">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Scheduler</div>
            <div className="mt-1 flex items-center gap-2 text-sm font-medium text-slate-900">
              <Clock3 className="h-4 w-4 text-indigo-600" />
              {schedulerConfig ? `${schedulerConfig.interval_hours}-hour automatic cycle` : 'Loading...'}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {schedulerConfig
                ? schedulerNextRunAt
                  ? `Next ingestion in ${schedulerCountdown}`
                  : 'Next ingestion countdown will appear after the first scheduler cycle is recorded.'
                : 'Reading scheduler status...'}
            </div>
            <button
              type="button"
              onClick={() => runAction(
                'ingest-now',
                'Manual full ingestion started',
                () => apiService.ingestPosts(),
                (result) => {
                  setIngestResult(result);
                  setManualTimerAnchorMs(Date.now());
                },
              )}
              disabled={runningAction !== null}
              className="mt-2 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {runningAction === 'ingest-now' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Ingest Now
            </button>
          </div>
        </div>

        {error && (
          <div className="flex items-start justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            <div className="flex min-w-0 items-start gap-3">
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
              <div className="min-w-0 break-words">{error}</div>
            </div>
            <button
              type="button"
              onClick={() => setError(null)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-rose-200 bg-white/70 text-rose-600 transition hover:bg-white hover:text-rose-800"
              aria-label="Dismiss error"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[1.25fr_0.75fr]">
          <div className="space-y-6">
            <section className="app-panel p-5">
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
                      {enabledSources.map((source) => (
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

            <section className="app-panel p-5">
              <div className="mb-4 flex items-center gap-2">
                <Archive className="h-5 w-5 text-amber-600" />
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Archive Control</h2>
                  <p className="mt-1 text-sm text-slate-500">
                    Plan or run a one-source archive job without touching the automatic scheduler.
                  </p>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-[1.2fr_0.8fr_0.8fr]">
                <div>
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                    Source
                  </label>
                  <select
                    value={selectedSourceId}
                    onChange={(e) => setSelectedSourceId(e.target.value)}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                  >
                    {enabledSources.map((source) => (
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
                <label className="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 md:mt-7">
                  <span>Resume from checkpoint</span>
                  <input
                    type="checkbox"
                    checked={archiveResume}
                    onChange={(e) => setArchiveResume(e.target.checked)}
                  />
                </label>
              </div>

              {selectedSource && (
                <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  <div className="font-semibold text-slate-900">{selectedSource.settings.display_name || selectedSource.handle_or_url}</div>
                  <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-600">
                    <span>Platform: {selectedSource.platform}</span>
                    <span>Enabled: {selectedSource.enabled ? 'yes' : 'no'}</span>
                    <span>Stored posts: {selectedSource.post_count}</span>
                    {selectedArchiveEntry?.archive_status && <span>Archive status: {selectedArchiveEntry.archive_status}</span>}
                    {selectedArchiveEntry?.resume_ready ? <span>Resume ready</span> : <span>No checkpoint</span>}
                  </div>
                </div>
              )}

              <div className="mt-4 rounded-3xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">Rate Limit Control</div>
                    <div className="mt-1 text-xs text-slate-500">
                      Fine-tune archive pacing for the selected source before planning or running it.
                    </div>
                  </div>
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  <div>
                    <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                      Page Delay
                    </label>
                    <input
                      type="number"
                      min={0}
                      value={archivePageDelay}
                      onChange={(e) => setArchivePageDelay(Math.max(0, Number(e.target.value) || 0))}
                      className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                    />
                  </div>
                  <div>
                    <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                      Batch Size
                    </label>
                    <input
                      type="number"
                      min={1}
                      value={archiveBatchSize}
                      onChange={(e) => setArchiveBatchSize(Math.max(1, Number(e.target.value) || 1))}
                      className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                    />
                  </div>
                  <div>
                    <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                      Batch Cooldown
                    </label>
                    <input
                      type="number"
                      min={0}
                      value={archiveBatchCooldown}
                      onChange={(e) => setArchiveBatchCooldown(Math.max(0, Number(e.target.value) || 0))}
                      className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                    />
                  </div>
                </div>
              </div>

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
                    () => apiService.planArchive(selectedSourceId, desiredPosts, {
                      resume: archiveResume,
                      pageDelaySeconds: archivePageDelay,
                      batchSize: archiveBatchSize,
                      batchCooldownSeconds: archiveBatchCooldown,
                    }),
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
                    archiveResume ? 'Archive resume started' : 'Archive run started',
                    () => apiService.runArchive(selectedSourceId, desiredPosts, {
                      resume: archiveResume,
                      pageDelaySeconds: archivePageDelay,
                      batchSize: archiveBatchSize,
                      batchCooldownSeconds: archiveBatchCooldown,
                    }),
                    (result) => setArchiveResult(result),
                  )}
                  disabled={!selectedSourceId || runningAction !== null}
                  className="rounded-2xl bg-amber-500 px-4 py-3 text-sm font-medium text-white hover:bg-amber-600 disabled:opacity-50"
                >
                  {runningAction === 'archive-run' ? 'Archiving…' : archiveResume ? 'Continue Archive' : 'Run Archive'}
                </button>
                <button
                  type="button"
                  onClick={() => selectedSourceId && runAction(
                    'archive-run-fresh',
                    'Fresh archive run started',
                    () => apiService.runArchive(selectedSourceId, desiredPosts, {
                      resume: false,
                      pageDelaySeconds: archivePageDelay,
                      batchSize: archiveBatchSize,
                      batchCooldownSeconds: archiveBatchCooldown,
                    }),
                    (result) => setArchiveResult(result),
                  )}
                  disabled={!selectedSourceId || runningAction !== null}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  {runningAction === 'archive-run-fresh' ? 'Starting…' : 'Start Fresh'}
                </button>
              </div>

              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-950 p-4 text-sm text-slate-100">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Archive Result</div>
                <pre className="overflow-x-auto whitespace-pre-wrap text-xs leading-6">
                  {formatJson(archiveResult as Record<string, any> | null)}
                </pre>
              </div>

              <div className="mt-4 rounded-3xl border border-slate-200 bg-slate-50 p-4">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">Archive Catalog</div>
                    <div className="mt-1 text-xs text-slate-500">
                      Enabled sources only. Green means full archive, orange partial, red untouched.
                    </div>
                  </div>
                  {loadingArchiveCatalog ? <Loader2 className="h-4 w-4 animate-spin text-slate-500" /> : null}
                </div>
                <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
                  {archiveCatalog.map((entry) => {
                    const isSelected = entry.source_id === selectedSourceId;
                    return (
                      <button
                        key={entry.source_id}
                        type="button"
                        onClick={() => setSelectedSourceId(entry.source_id)}
                        className={`flex w-full items-center justify-between rounded-2xl border px-4 py-3 text-left text-sm transition ${
                          isSelected
                            ? 'border-amber-300 bg-amber-50'
                            : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <span className={`h-2.5 w-2.5 rounded-full ${archiveDotClasses(entry.archive_status)}`} />
                          <div>
                            <div className="font-medium text-slate-900">{entry.display_name}</div>
                            <div className="text-xs text-slate-500">
                              {entry.platform} · {formatArchiveRatio(entry)}
                            </div>
                          </div>
                        </div>
                        <div className="text-right text-[11px] uppercase tracking-[0.14em] text-slate-400">
                          <div>{entry.archive_status || 'not_archived'}</div>
                          <div>{entry.resume_ready ? 'resume ready' : 'fresh only'}</div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </section>
          </div>

          <div className="space-y-6">
            {schedulerConfig && (
              <section className="app-panel p-5">
                <div className="mb-4 flex items-center gap-2">
                  <Clock3 className="h-5 w-5 text-indigo-600" />
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900">Scheduler Control</h2>
                    <p className="mt-1 text-sm text-slate-500">
                      Change the automatic cycle and scheduled tasks without touching container env files.
                    </p>
                  </div>
                </div>

                <div className="space-y-4">
                  <div>
                    <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                      Interval Hours
                    </label>
                    <input
                      type="number"
                      min={0.25}
                      step={0.25}
                      value={schedulerConfig.interval_hours}
                      onChange={(e) => {
                        setSchedulerDirty(true);
                        setSchedulerConfig((prev) => prev ? ({
                          ...prev,
                          interval_hours: Math.max(0.25, Number(e.target.value) || 0.25),
                        }) : prev);
                      }}
                      className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                    />
                  </div>

                  <div className="grid gap-3">
                    {[
                      ['sync_sources_each_cycle', 'Sync sources.json every cycle'],
                      ['generate_daily_briefing', 'Generate daily briefing'],
                      ['generate_topic_briefing', 'Generate topic briefing'],
                    ].map(([key, label]) => (
                      <label key={key} className="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                        <span>{label}</span>
                        <input
                          type="checkbox"
                          checked={Boolean(schedulerConfig[key as keyof SchedulerConfig])}
                          onChange={(e) => {
                            setSchedulerDirty(true);
                            setSchedulerConfig((prev) => prev ? ({
                              ...prev,
                              [key]: e.target.checked,
                            }) as SchedulerConfig : prev);
                          }}
                        />
                      </label>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={saveSchedulerConfig}
                    disabled={savingScheduler || !schedulerDirty}
                    className="rounded-2xl bg-indigo-600 px-4 py-3 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {savingScheduler ? 'Saving…' : 'Save Scheduler'}
                  </button>
                </div>
              </section>
            )}

            <section className="app-panel p-5">
              <div className="mb-4 flex items-center gap-2">
                <Settings className="h-5 w-5 text-indigo-600" />
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">System Snapshot</h2>
                  <p className="mt-1 text-sm text-slate-500">Quick read of the current registry before you trigger work.</p>
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Sources</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">{sources.length}</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Enabled Sources</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">
                    {operationsOverview?.stats?.enabled_sources ?? enabledSources.length}
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Total Posts</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">
                    {operationsOverview?.stats?.total_posts ?? 0}
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Topics Count</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">
                    {operationsOverview?.stats?.total_topics ?? 0}
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Briefings Count</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">
                    {operationsOverview?.stats?.total_briefings ?? 0}
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Selected Source</div>
                  <div className="mt-2 break-words text-sm font-medium text-slate-900">
                    {selectedSource?.settings.display_name || selectedSource?.handle_or_url || 'None'}
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Recent Failures</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">
                    {operationsOverview?.stats?.recent_failures ?? 0}
                  </div>
                </div>
              </div>
            </section>

            <section className="app-panel p-5">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900">Mission Feed</h2>
                    <p className="mt-1 text-sm text-slate-500">Structured job history, failures, and source health.</p>
                  </div>
                </div>
                {loadingOverview && <Loader2 className="h-4 w-4 animate-spin text-slate-500" />}
              </div>

              {visibleMissionAlerts.length > 0 && (
                <div className="mb-4 grid gap-3 xl:grid-cols-2">
                  {visibleMissionAlerts.map((alert) => (
                    <div
                      key={alert.id}
                      className="flex items-start justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
                    >
                      <div className="min-w-0">
                        <div className="font-semibold">{alert.title}</div>
                        <div className="mt-1 break-words">{alert.message}</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => setDismissedAlertIds((prev) => [...prev, alert.id])}
                        className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-rose-200 bg-white/70 text-rose-600 transition hover:bg-white hover:text-rose-800"
                        aria-label={`Dismiss ${alert.title}`}
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="grid gap-4 2xl:grid-cols-[minmax(20rem,0.92fr)_minmax(0,1.08fr)]">
                <div className="min-w-0 rounded-3xl border border-slate-200 bg-slate-50/80 p-3">
                  <div className="mb-3 flex items-center justify-between gap-3 px-2">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Recent Missions</div>
                      <div className="mt-1 text-sm text-slate-500">Select a job to inspect progress, payload, and event traces.</div>
                    </div>
                    <div className="rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                      {(operationsOverview?.jobs || []).length} tracked
                    </div>
                  </div>

                  <div className="max-h-[32rem] space-y-3 overflow-y-auto pr-1">
                  {(operationsOverview?.jobs || []).map((job) => {
                    const estimatedTokens = extractEstimatedTokens(job.payload);
                    const isSelected = selectedJobId === job.id;
                    return (
                      <button
                        key={job.id}
                        type="button"
                        onClick={() => setSelectedJobId(job.id)}
                        className={`w-full rounded-2xl border px-4 py-3 text-left text-sm transition ${
                          isSelected
                            ? 'border-indigo-300 bg-indigo-50 shadow-sm ring-1 ring-indigo-100'
                            : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-semibold text-slate-900">
                            {job.job_type}
                            {job.source_display_name ? ` · ${job.source_display_name}` : ''}
                          </div>
                          <span className={`rounded-full px-2 py-1 text-[11px] uppercase tracking-[0.14em] ${
                            job.status === 'failed'
                              ? 'bg-rose-100 text-rose-700'
                              : job.status === 'running'
                                ? 'bg-amber-100 text-amber-700'
                                : 'bg-emerald-100 text-emerald-700'
                          }`}>
                            {job.status}
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-slate-500">{job.message || 'No message'}</div>
                        {typeof job.progress === 'number' && job.progress > 0 ? (
                          <div className="mt-3">
                            <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                              <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(100, job.progress)}%` }} />
                            </div>
                          </div>
                        ) : null}
                        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] uppercase tracking-[0.14em] text-slate-400">
                          {formatJobTimestamp(job.started_at) && <span>Started {formatJobTimestamp(job.started_at)}</span>}
                          {formatJobTimestamp(job.finished_at) && <span>Finished {formatJobTimestamp(job.finished_at)}</span>}
                          {formatJobDuration(job.started_at, job.finished_at) && <span>Duration {formatJobDuration(job.started_at, job.finished_at)}</span>}
                          {estimatedTokens && <span>Estimated tokens {estimatedTokens}</span>}
                          {job.event_count ? <span>Events {job.event_count}</span> : null}
                        </div>
                      </button>
                    );
                  })}
                  {(operationsOverview?.jobs || []).length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
                      No missions recorded yet. Run an ingest, fetch, or briefing to populate the feed.
                    </div>
                  ) : null}
                  </div>
                </div>

                <div className="min-w-0 overflow-hidden rounded-3xl border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Mission Detail</div>
                      <div className="mt-1 text-lg font-semibold text-slate-900">
                        {selectedJob?.job_type || 'Select a mission'}
                      </div>
                    </div>
                    {loadingSelectedJob ? <Loader2 className="h-4 w-4 animate-spin text-slate-500" /> : null}
                  </div>

                  {selectedJob ? (
                    <div className="space-y-4">
                      {(() => {
                        const missionEvents = Array.isArray(selectedJob.payload?.events) ? selectedJob.payload?.events : [];
                        return (
                          <>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm">
                          <div className="text-xs uppercase tracking-[0.14em] text-slate-400">Source</div>
                          <div className="mt-2 font-medium text-slate-900">{selectedJob.source_display_name || 'Global job'}</div>
                        </div>
                        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm">
                          <div className="text-xs uppercase tracking-[0.14em] text-slate-400">Status</div>
                          <div className="mt-2 font-medium text-slate-900">{selectedJob.status}</div>
                        </div>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm">
                          <div className="text-xs uppercase tracking-[0.14em] text-slate-400">Started</div>
                          <div className="mt-2 font-medium text-slate-900">{formatJobTimestamp(selectedJob.started_at) || 'Unknown'}</div>
                        </div>
                        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm">
                          <div className="text-xs uppercase tracking-[0.14em] text-slate-400">Finished</div>
                          <div className="mt-2 font-medium text-slate-900">{formatJobTimestamp(selectedJob.finished_at) || 'Still running'}</div>
                        </div>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm">
                          <div className="text-xs uppercase tracking-[0.14em] text-slate-400">Duration</div>
                          <div className="mt-2 font-medium text-slate-900">{formatJobDuration(selectedJob.started_at, selectedJob.finished_at) || 'In progress'}</div>
                        </div>
                        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm">
                          <div className="text-xs uppercase tracking-[0.14em] text-slate-400">Estimated Tokens</div>
                          <div className="mt-2 font-medium text-slate-900">{extractEstimatedTokens(selectedJob.payload) || 'n/a'}</div>
                        </div>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm">
                        <div className="text-xs uppercase tracking-[0.14em] text-slate-400">Progress</div>
                        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
                          <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(100, Number(selectedJob.progress || 0))}%` }} />
                        </div>
                        <div className="mt-2 text-xs text-slate-500">{Math.round(Number(selectedJob.progress || 0))}% complete</div>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-slate-950 p-4 text-slate-100">
                        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Mission Log</div>
                        <div className="max-h-[16rem] space-y-3 overflow-y-auto pr-1 text-xs leading-6">
                          {missionEvents.length ? missionEvents.map((event: any, index: number) => (
                            <div key={`${event.at || 'event'}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-900 px-3 py-2">
                              <div className="flex items-center justify-between gap-3 text-[11px] uppercase tracking-[0.14em] text-slate-400">
                                <span>{event.level || 'info'}</span>
                                <span>{formatJobTimestamp(event.at) || event.at || 'Unknown time'}</span>
                              </div>
                              <div className="mt-2 text-slate-100">{event.message || 'No message'}</div>
                              {typeof event.progress === 'number' ? (
                                <div className="mt-1 text-slate-400">Progress: {Math.round(Number(event.progress))}%</div>
                              ) : null}
                            </div>
                          )) : (
                            <div className="text-slate-400">No mission events were recorded for this job.</div>
                          )}
                        </div>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-white p-4">
                        <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Payload</div>
                        <pre className="max-h-[14rem] overflow-auto whitespace-pre-wrap text-xs leading-6 text-slate-700">
                          {formatJson(selectedJob.payload || null)}
                        </pre>
                      </div>
                          </>
                        );
                      })()}
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-10 text-center text-sm text-slate-500">
                      Choose a mission from the feed to inspect its progress, payload, and full mission log.
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-4 space-y-2">
                <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Source Health</div>
                {(operationsOverview?.source_health || []).slice(0, 8).map((source) => (
                  <div key={source.source_id} className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm">
                    <div>
                      <div className="font-medium text-slate-900">{source.display_name}</div>
                      <div className="text-xs text-slate-500">{source.platform} · {source.stored_posts} stored posts</div>
                    </div>
                    <span className={`rounded-full px-2 py-1 text-[11px] uppercase tracking-[0.14em] ${
                      source.status === 'error'
                        ? 'bg-rose-100 text-rose-700'
                        : source.status === 'healthy'
                          ? 'bg-emerald-100 text-emerald-700'
                          : 'bg-slate-100 text-slate-700'
                    }`}>
                      {source.status}
                    </span>
                  </div>
                ))}
              </div>
            </section>

            <section className="app-panel p-5">
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

            <section className="app-panel p-5">
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
