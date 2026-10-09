import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { RefreshCw, Settings } from 'lucide-react';
import { apiService } from '../services/api';
import type {
  ArchiveCatalogEntry,
  ArchiveResponse,
  JobRun,
  LogTailResponse,
  OperationsOverviewResponse,
  RunReport,
  SchedulerConfig,
  SchedulerState,
  SourceWithSettings,
} from '../services/api';
import {
  INGESTION_TABS,
  getIngestionTabHref,
  normalizeIngestionTab,
} from '../lib/ingestionNavigation';
import { compactJobRun, compactOperationsOverview, jobLabel, normalizeSourceHealth } from '../lib/operationsOverview';
import { asRunReport } from '../lib/runReport';
import { localDateISO } from '../lib/dates';
import { formatCount, plural, sourceLabel } from '../lib/format';
import { HEALTH_STATUS_LABELS, sortHealthRows, summarizeHealthRows, withEffectiveStatus } from '../lib/sourceSchedule';
import { useSourcesHealth } from '../hooks/useSourcesHealth';
import { useIngestionRun } from '../hooks/useIngestionRun';
import RunCycleButton from '../components/ops/RunCycleButton';
import RunReportSummary from '../components/ops/RunReportSummary';
import { getSourceDisplayName, getSourceHandleLabel } from '../lib/sourcePresentation';
import SourceAvatar from '../components/SourceAvatar';
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  Input,
  Page,
  PageHeader,
  Select,
  StatusGlyph,
  StatusIcon,
  TextLink,
  tabTriggerClass,
} from '../components/ui';
import type { Status } from '../components/ui';
import { Notice } from '../components/states';
import IngestionStatusNotice from '../components/ops/IngestionStatusNotice';

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

function sourceMatchesQuery(source: Pick<SourceWithSettings, 'id' | 'platform' | 'handle_or_url' | 'settings'>, query: string) {
  const term = query.trim().toLowerCase();
  if (!term) {
    return true;
  }

  return [
    getSourceDisplayName(source),
    getSourceHandleLabel(source),
    source.platform,
    source.id,
  ].some((value) => value.toLowerCase().includes(term));
}

const LOG_LEVEL_GLYPH: Record<LogLevel, Status> = {
  info: 'scheduled',
  success: 'ok',
  error: 'failing',
};

/** Job status -> monochrome glyph (design doc §8). */
function jobGlyph(status?: string | null): Status {
  if (status === 'failed') return 'failing';
  if (status === 'running' || status === 'queued' || status === 'pending') return 'running';
  return 'ok';
}

/** Archive status -> glyph + word: archived is full, partial is half, nothing is a ring. */
function archiveGlyph(status?: string | null): { status: Status; label: string } {
  if (status === 'archived') return { status: 'ok', label: 'archived' };
  if (status === 'partial') return { status: 'due', label: 'partial' };
  return { status: 'scheduled', label: 'not archived' };
}

/** Lowercase tab words (design doc §4: lowercase is the voice of tabs). */
const TAB_WORDS: Record<string, string> = {
  main: 'overview',
  archive: 'archive',
  missions: 'jobs',
  logs: 'logs',
};

/** A scheduler that has not ticked for two tick intervals (or ever) is stalled. */
function schedulerStaleness(state: SchedulerState | null, tickMinutes: number, nowMs: number): string | null {
  if (state === null) return null;
  const last = state.last_tick_at ? new Date(state.last_tick_at).getTime() : NaN;
  if (Number.isNaN(last)) {
    return 'The scheduler has not recorded a tick. Nothing is fetched automatically until the ingestion service runs.';
  }
  if (nowMs - last > Math.max(2 * tickMinutes, 90) * 60_000) {
    return `The scheduler last ticked ${formatTimeRemaining(nowMs - last).replace(/ \d+s$/, '')} ago. Automatic fetching looks stalled; check the ingestion service.`;
  }
  return null;
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

function formatArchiveRatio(entry?: ArchiveCatalogEntry | null) {
  if (!entry) return '0/?';
  const available = typeof entry.available_posts === 'number' ? entry.available_posts.toLocaleString() : '?';
  return `${(entry.stored_posts || 0).toLocaleString()}/${available}`;
}

/** The archive plan's time estimate as "~2h 10m"; null when unknown. */
function formatEta(seconds?: number | null) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return null;
  return `~${formatTimeRemaining(seconds * 1000).replace(/ \d+s$/, '')}`;
}

/** "1,204 in backlog · ~2h" for an archive catalog entry; null when nothing is known. */
function formatBacklog(entry?: ArchiveCatalogEntry | null) {
  if (!entry) return null;
  const parts: string[] = [];
  if (typeof entry.backlog_posts === 'number') {
    parts.push(entry.backlog_posts === 0 ? 'no backlog' : `${formatCount(entry.backlog_posts)} in backlog`);
  }
  const eta = formatEta(entry.estimated_seconds);
  if (eta) {
    const target = typeof entry.remaining_posts === 'number' ? ` for ${formatCount(entry.remaining_posts)} planned` : '';
    parts.push(`${eta}${target}`);
  }
  return parts.length ? parts.join(' · ') : null;
}

function SchedulerSettingsModal({
  open,
  schedulerConfig,
  schedulerDirty,
  savingScheduler,
  onClose,
  onSave,
  onIntervalChange,
  onTickChange,
  onToggle,
}: {
  open: boolean;
  schedulerConfig: SchedulerConfig | null;
  schedulerDirty: boolean;
  savingScheduler: boolean;
  onClose: () => void;
  onSave: () => void;
  onIntervalChange: (value: number) => void;
  onTickChange: (value: number) => void;
  onToggle: (key: keyof SchedulerConfig, checked: boolean) => void;
}) {
  if (!schedulerConfig) {
    return null;
  }
  const label = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent title="Scheduler" description="How often the scheduler looks for due sources and writes briefings.">
        <form className="mt-5 space-y-5" onSubmit={(event) => { event.preventDefault(); onSave(); }}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="scheduler-tick" className={label}>Check for due sources every (minutes)</label>
              <Input
                id="scheduler-tick"
                type="number"
                min={15}
                step={5}
                value={schedulerConfig.ingest_tick_minutes ?? 60}
                onChange={(e) => onTickChange(Math.max(15, Number(e.target.value) || 15))}
                className="tabular-nums"
              />
              <p className="mt-1 text-[0.75rem] text-fg-3">At least 15. Each source still waits for its own cadence.</p>
            </div>
            <div>
              <label htmlFor="scheduler-interval" className={label}>Write briefings every (hours)</label>
              <Input
                id="scheduler-interval"
                type="number"
                min={0.25}
                step={0.25}
                value={schedulerConfig.interval_hours}
                onChange={(e) => onIntervalChange(Math.max(0.25, Number(e.target.value) || 0.25))}
                className="tabular-nums"
              />
            </div>
          </div>

          <fieldset className="divide-y divide-line rounded-md border border-line">
            <legend className="sr-only">Each cycle</legend>
            {[
              ['sync_sources_each_cycle', 'Sync sources.json every cycle'],
              ['generate_daily_briefing', 'Write the daily briefing'],
              ['generate_topic_briefing', 'Write the topic briefing'],
            ].map(([key, text]) => (
              <label key={key} className="flex min-h-[2.75rem] cursor-pointer items-center justify-between gap-3 px-3 text-[0.875rem] text-fg">
                <span>{text}</span>
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[rgb(var(--text))]"
                  checked={Boolean(schedulerConfig[key as keyof SchedulerConfig])}
                  onChange={(e) => onToggle(key as keyof SchedulerConfig, e.target.checked)}
                />
              </label>
            ))}
          </fieldset>

          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={savingScheduler || !schedulerDirty}>
              {savingScheduler ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function IngestionControl() {
  const { tab: tabParam } = useParams();
  const [searchParams] = useSearchParams();
  const activeTab = normalizeIngestionTab(tabParam);
  const [sources, setSources] = useState<SourceWithSettings[]>([]);
  const [loadingSources, setLoadingSources] = useState(true);
  const [selectedDate, setSelectedDate] = useState(() => localDateISO());
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [desiredPosts, setDesiredPosts] = useState(200);
  const [liveFetchLimit, setLiveFetchLimit] = useState(20);
  const [archiveSourceQuery, setArchiveSourceQuery] = useState('');
  const [selectedLogName, setSelectedLogName] = useState('application');
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [savingScheduler, setSavingScheduler] = useState(false);
  const [schedulerDirty, setSchedulerDirty] = useState(false);
  const [cycleReport, setCycleReport] = useState<RunReport | null>(null);
  const [sourceFetchReport, setSourceFetchReport] = useState<RunReport | null>(null);
  const [schedulerState, setSchedulerState] = useState<SchedulerState | null>(null);
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
  const [selectedJobId, setSelectedJobId] = useState<string | null>(() => searchParams.get('job'));
  const [selectedJob, setSelectedJob] = useState<JobRun | null>(null);
  const [loadingSelectedJob, setLoadingSelectedJob] = useState(false);
  const [logs, setLogs] = useState<ActionLog[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dismissedAlertIds, setDismissedAlertIds] = useState<string[]>([]);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [schedulerModalOpen, setSchedulerModalOpen] = useState(false);

  const { run: runIngestion, isRunning: isIngestionRunning } = useIngestionRun();
  // Every source's row, so the summary can count by last attempt (the overview carries only the worst few).
  const healthQuery = useSourcesHealth();

  // A ?job= link (from an ingestion toast) selects that mission.
  useEffect(() => {
    const jobParam = searchParams.get('job');
    if (jobParam) setSelectedJobId(jobParam);
  }, [searchParams]);

  useEffect(() => {
    const tickId = window.setInterval(() => {
      if (document.visibilityState === 'hidden') return;
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

    setOperationsOverview(compactOperationsOverview(response));
    if (!schedulerDirty && response.scheduler) {
      setSchedulerConfig(response.scheduler);
    }
    if (!selectedJobId && response.jobs?.[0]?.id) {
      setSelectedJobId(response.jobs[0].id);
    }
    setLoadingOverview(false);
  };

  /** The scheduler's tick times (GET /api/operations/scheduler carries `state`). */
  const loadSchedulerState = async () => {
    const response = await apiService.getSchedulerConfig();
    if (response.success && response.scheduler) {
      setSchedulerState(response.scheduler.state ?? {});
    }
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

    setSelectedJob(compactJobRun(response.job, 'detail'));
    setLoadingSelectedJob(false);
  };

  useEffect(() => {
    loadSources();
    loadOperationsOverview();
    void loadSchedulerState();
    if (activeTab === 'archive') {
      loadArchiveCatalog();
    }
    if (activeTab === 'logs') {
      loadLogTail(selectedLogName);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'archive') {
      void loadArchiveCatalog();
    }
    if (activeTab === 'logs') {
      void loadLogTail(selectedLogName);
    }
    if (activeTab === 'missions' && selectedJobId) {
      void loadSelectedJob(selectedJobId, { silent: true });
    }
  }, [activeTab, selectedLogName, selectedJobId]);

  // Polling pauses while the tab is hidden and catches up as soon as it is visible again.
  useEffect(() => {
    const refresh = () => {
      void loadOperationsOverview({ silent: true });
      void loadSchedulerState();
      if (activeTab === 'archive') {
        void loadArchiveCatalog({ silent: true });
      }
      if (activeTab === 'logs') {
        void loadLogTail(selectedLogName, { silent: true });
      }
      if (activeTab === 'missions' && selectedJobId) {
        void loadSelectedJob(selectedJobId, { silent: true });
      }
    };
    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      refresh();
    }, activeTab === 'missions' ? 12000 : 15000);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        setNowMs(Date.now());
        refresh();
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [activeTab, selectedLogName, selectedJobId]);

  const enabledSources = useMemo(
    () => sources.filter((source) => source.enabled),
    [sources],
  );

  const filteredEnabledSources = useMemo(
    () => enabledSources.filter((source) => sourceMatchesQuery(source, archiveSourceQuery)),
    [archiveSourceQuery, enabledSources],
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

  const filteredArchiveCatalog = useMemo(() => {
    const term = archiveSourceQuery.trim().toLowerCase();
    if (!term) {
      return archiveCatalog;
    }

    return archiveCatalog.filter((entry) => [
      entry.display_name,
      entry.platform,
      entry.source_id,
    ].some((value) => (value || '').toLowerCase().includes(term)));
  }, [archiveCatalog, archiveSourceQuery]);

  // The countdown is the scheduler's own next ingestion tick (scheduler_state.next_tick_at).
  const schedulerNextRunAt = useMemo(() => {
    const nextTick = schedulerState?.next_tick_at;
    if (!nextTick) return null;
    const ms = new Date(nextTick).getTime();
    return Number.isNaN(ms) ? null : ms;
  }, [schedulerState?.next_tick_at]);

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
    if (activeTab === 'missions') {
      void loadSelectedJob(selectedJobId, { silent: true });
    }
  }, [activeTab, selectedJobId]);

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

      if (
        activeTab === 'archive'
        || ['archive-status', 'archive-plan', 'archive-run', 'archive-run-fresh', 'sync-json-to-db', 'sync-db-to-json'].includes(actionKey)
      ) {
        await loadSources({ silent: true });
        await loadArchiveCatalog({ silent: true });
      }
      await loadOperationsOverview({ silent: true });
      if (activeTab === 'logs') {
        await loadLogTail(selectedLogName, { silent: true });
      }
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
      return false;
    }

    setSavingScheduler(true);
    const response = await apiService.updateSchedulerConfig(schedulerConfig);
    if (!response.success || !response.scheduler) {
      setError(response.error || 'Failed to save scheduler config');
      setSavingScheduler(false);
      return false;
    }

    setSchedulerConfig(response.scheduler);
    setSchedulerDirty(false);
    appendLog('success', `Scheduler updated to ${response.scheduler.interval_hours} hour cycle`);
    await loadOperationsOverview({ silent: true });
    setSavingScheduler(false);
    return true;
  };

  const sectionTitle = 'text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg';
  const fieldLabel = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';
  const hint = 'mt-1 text-[0.75rem] text-fg-3';
  const busy = runningAction !== null;
  const sourceOptionLabel = (source: SourceWithSettings) => `${sourceLabel(source.settings?.display_name, source.handle_or_url)} · ${source.platform}`;
  // Status by last attempt: a source whose last fetch failed counts as failing, not
  // due. The full health list decides when loaded; the overview's few rows otherwise.
  const sourceHealth = (() => {
    const overview = normalizeSourceHealth(operationsOverview?.source_health);
    if (healthQuery.data) {
      const rows = withEffectiveStatus(healthQuery.data.rows, new Date(nowMs));
      return { summary: summarizeHealthRows(rows), rows: sortHealthRows(rows).slice(0, Math.max(overview.rows.length, 8)) };
    }
    const rows = withEffectiveStatus(overview.rows, new Date(nowMs));
    const shown = summarizeHealthRows(overview.rows);
    const derived = summarizeHealthRows(rows);
    // Rows the overview called due/scheduled but whose last attempt failed move to failing.
    const summary = {
      ...overview.summary,
      due_now: Math.max(0, overview.summary.due_now - (shown.due_now - derived.due_now)),
      deferred: Math.max(0, overview.summary.deferred - (shown.deferred - derived.deferred)),
      errors: overview.summary.errors + (derived.errors - shown.errors),
      backoff: overview.summary.backoff + (derived.backoff - shown.backoff),
    };
    return { summary, rows: sortHealthRows(rows) };
  })();
  const stats = operationsOverview?.stats ?? {};
  const staleWarning = schedulerStaleness(schedulerState, Number(schedulerConfig?.ingest_tick_minutes ?? 60), nowMs);

  const onCycleReport = (report: RunReport) => {
    setCycleReport(report);
    appendLog(report.status === 'failed' ? 'error' : 'success', report.summary || `Run finished: ${report.status}`);
    void loadOperationsOverview({ silent: true });
    void loadSchedulerState();
  };

  const renderStatusSection = () => (
    <section aria-labelledby="ingest-status" className="space-y-4">
      <h2 id="ingest-status" className={sectionTitle}>Status</h2>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-4">
        {[
          ['Sources', stats.sources_monitored ?? sources.length],
          ['Enabled', stats.enabled_sources ?? enabledSources.length],
          ['Posts', stats.total_posts],
          ['Topics', stats.total_topics],
          ['Briefings', stats.total_briefings],
          ['Failed jobs (recent)', stats.recent_failures],
        ].map(([term, value]) => (
          <div key={String(term)} className="min-w-0 border-l border-line pl-3">
            <dt className="text-[0.75rem] text-fg-3">{term}</dt>
            <dd className="text-[1.0625rem] font-semibold tabular-nums text-fg">{formatCount(typeof value === 'number' ? value : null)}</dd>
          </div>
        ))}
      </dl>
      <div className="space-y-2 border-t border-line pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-[0.875rem] font-semibold text-fg">Source health</h3>
          <TextLink to="/settings/sources?tab=health" className="text-[0.8125rem]">All sources</TextLink>
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-[0.8125rem] tabular-nums text-fg-2">
          <li className="inline-flex items-center gap-1.5 font-semibold text-fg"><StatusIcon status="due" />{formatCount(sourceHealth.summary.due_now)} due</li>
          <li className="inline-flex items-center gap-1.5"><StatusIcon status="scheduled" />{formatCount(sourceHealth.summary.deferred)} scheduled</li>
          <li>
            <Link to="/settings/sources?tab=health&status=error" className="rounded-sm hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-fg">
              {sourceHealth.summary.errors + sourceHealth.summary.backoff > 0 ? (
                <StatusGlyph status="failing" label={`${formatCount(sourceHealth.summary.errors + sourceHealth.summary.backoff)} failing`} />
              ) : (
                <span className="inline-flex items-center gap-1.5"><StatusIcon status="ok" />0 failing</span>
              )}
            </Link>
          </li>
          <li className="inline-flex items-center gap-1.5"><StatusIcon status="unavailable" />{formatCount(sourceHealth.summary.unavailable)} unavailable</li>
        </ul>
        {sourceHealth.rows.length ? (
          <ul className="divide-y divide-line border-y border-line">
            {sourceHealth.rows.map((row) => (
              <li key={row.source_id} className="flex min-w-0 items-start justify-between gap-3 py-2 text-[0.8125rem]">
                <div className="min-w-0">
                  <div className="truncate font-medium text-fg" title={row.display_name}>{sourceLabel(row.display_name || row.source_id)}</div>
                  <div className="truncate text-[0.75rem] text-fg-3" title={row.last_error || row.decision_detail || undefined}>
                    {row.platform} · {plural(row.stored_posts, 'post')}
                    {row.last_error ? ` · ${row.last_error}` : row.decision_detail ? ` · ${row.decision_detail}` : ''}
                  </div>
                </div>
                <StatusGlyph
                  status={row.status === 'error' ? 'failing' : row.status === 'deferred' ? 'scheduled' : row.status}
                  label={HEALTH_STATUS_LABELS[row.status] ?? row.status}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );

  const renderImmediateActionsSection = () => (
    <div className="space-y-10">
      <section aria-labelledby="ingest-last-run" className="space-y-3">
        <h2 id="ingest-last-run" className={sectionTitle}>Last run</h2>
        {cycleReport || sourceFetchReport ? (
          <div className="space-y-3">
            {cycleReport ? <RunReportSummary report={cycleReport} title="Run cycle" /> : null}
            {sourceFetchReport ? <RunReportSummary report={sourceFetchReport} title="Single source" /> : null}
          </div>
        ) : (
          <p className="text-[0.875rem] text-fg-2">
            Nothing run in this session. <span className="text-fg">Run due sources</span> fetches what is due now, exactly as the next
            scheduler tick would; each source keeps its own cadence and backoff. Past runs are under{' '}
            <TextLink to={getIngestionTabHref('missions')}>jobs</TextLink>.
          </p>
        )}
      </section>

      <section aria-labelledby="ingest-one" className="space-y-3">
        <h2 id="ingest-one" className={sectionTitle}>Fetch one source</h2>
        <form
          className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_7rem_auto] sm:items-end"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!selectedSourceId) return;
            const report = await runIngestion({
              kind: 'source',
              id: selectedSourceId,
              name: selectedSource ? sourceLabel(selectedSource.settings?.display_name, selectedSource.handle_or_url) : undefined,
              limit: liveFetchLimit,
            });
            if (report) {
              setSourceFetchReport(report);
              appendLog(report.status === 'failed' ? 'error' : 'success', report.summary || `Fetch finished: ${report.status}`);
              await loadSources({ silent: true });
              await loadOperationsOverview({ silent: true });
            }
          }}
        >
          <div className="min-w-0">
            <label htmlFor="fetch-source" className={fieldLabel}>Source</label>
            <Select id="fetch-source" value={selectedSourceId} onChange={(e) => setSelectedSourceId(e.target.value)} className="w-full">
              {enabledSources.map((source) => (
                <option key={source.id} value={source.id}>{sourceOptionLabel(source)}</option>
              ))}
            </Select>
          </div>
          <div>
            <label htmlFor="fetch-limit" className={fieldLabel}>Post limit</label>
            <Input
              id="fetch-limit"
              type="number"
              min={1}
              value={liveFetchLimit}
              onChange={(e) => setLiveFetchLimit(Math.max(1, Number(e.target.value) || 1))}
              className="tabular-nums"
            />
          </div>
          <Button
            type="submit"
            variant="secondary"
            disabled={!selectedSourceId || isIngestionRunning({ kind: 'source', id: selectedSourceId })}
          >
            {selectedSourceId && isIngestionRunning({ kind: 'source', id: selectedSourceId }) ? 'Fetching…' : 'Fetch now'}
          </Button>
        </form>
        {selectedSource ? (
          <p className="text-[0.75rem] tabular-nums text-fg-3">
            {plural(selectedSource.post_count, 'stored post')} · priority {selectedSource.settings.priority ?? 999} · ignores cadence and backoff
          </p>
        ) : loadingSources ? <p className={hint}>Loading sources…</p> : null}
      </section>

      <section aria-labelledby="ingest-briefings" className="space-y-3">
        <h2 id="ingest-briefings" className={sectionTitle}>Write a briefing</h2>
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-full sm:w-auto">
            <label htmlFor="briefing-date" className={fieldLabel}>Date</label>
            <Input id="briefing-date" type="date" value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)} className="tabular-nums sm:w-44" />
          </div>
          <Button
            variant="secondary"
            onClick={() => runAction(
              'briefing',
              `Daily briefing requested for ${selectedDate}`,
              () => apiService.generateBriefing(selectedDate),
              (result) => setBriefingResult(result),
            )}
            disabled={busy}
          >
            {runningAction === 'briefing' ? 'Writing…' : 'Daily briefing'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => runAction(
              'topic-briefing',
              `Topic briefing requested for ${selectedDate}`,
              () => apiService.generateBriefingWithTopics(selectedDate),
              (result) => setTopicBriefingResult(result),
            )}
            disabled={busy}
          >
            {runningAction === 'topic-briefing' ? 'Writing…' : 'Topic briefing'}
          </Button>
        </div>
        {briefingResult || topicBriefingResult ? (
          <details className="rounded-md border border-line px-3 py-2">
            <summary className="cursor-pointer select-none text-[0.8125rem] text-fg-2 hover:text-fg">Briefing responses (raw)</summary>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[0.75rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
              {formatJson({ daily: briefingResult, topics: topicBriefingResult })}
            </pre>
          </details>
        ) : null}
      </section>

      <section aria-labelledby="ingest-registry" className="space-y-3">
        <h2 id="ingest-registry" className={sectionTitle}>Source registry</h2>
        <p className="text-[0.8125rem] text-fg-2">Copy the source list between <code className="font-mono text-[0.75rem]">sources.json</code> and the database.</p>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => runAction('sync-json-to-db', 'Source registry sync JSON -> DB started', () => apiService.syncSources('json-to-db'), () => undefined)}
            disabled={busy}
          >
            {runningAction === 'sync-json-to-db' ? 'Syncing…' : 'JSON → database'}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => runAction('sync-db-to-json', 'Source registry sync DB -> JSON started', () => apiService.syncSources('db-to-json'), () => undefined)}
            disabled={busy}
          >
            {runningAction === 'sync-db-to-json' ? 'Syncing…' : 'Database → JSON'}
          </Button>
        </div>
      </section>
    </div>
  );

  const archiveOptions = {
    resume: archiveResume,
    pageDelaySeconds: archivePageDelay,
    batchSize: archiveBatchSize,
    batchCooldownSeconds: archiveBatchCooldown,
  };

  const renderArchiveControlSection = () => (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <section aria-labelledby="archive-run" className="min-w-0 space-y-5">
        <h2 id="archive-run" className={sectionTitle}>Archive one source</h2>
        <p className="-mt-3 text-[0.8125rem] text-fg-2">Walk back through a source&rsquo;s history, in batches, until it holds the posts you ask for.</p>

        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
          <div className="min-w-0">
            <label htmlFor="archive-source" className={fieldLabel}>Source</label>
            <Select id="archive-source" value={selectedSourceId} onChange={(e) => setSelectedSourceId(e.target.value)} className="w-full">
              {filteredEnabledSources.length > 0 ? filteredEnabledSources.map((source) => (
                <option key={source.id} value={source.id}>{sourceOptionLabel(source)}</option>
              )) : (
                <option value="" disabled>No matching sources</option>
              )}
            </Select>
          </div>
          <div>
            <label htmlFor="archive-desired" className={fieldLabel}>Posts wanted</label>
            <Input
              id="archive-desired"
              type="number"
              min={1}
              value={desiredPosts}
              onChange={(e) => setDesiredPosts(Math.max(1, Number(e.target.value) || 1))}
              className="tabular-nums"
            />
          </div>
        </div>

        {selectedSource ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.75rem] tabular-nums text-fg-3">
            {selectedArchiveEntry ? <StatusGlyph {...archiveGlyph(selectedArchiveEntry.archive_status)} /> : null}
            <span>{plural(selectedSource.post_count, 'stored post')}</span>
            <span>{selectedArchiveEntry?.resume_ready ? 'checkpoint saved' : 'no checkpoint'}</span>
            {selectedArchiveEntry?.kind ? <span>kind {selectedArchiveEntry.kind}</span> : null}
            {formatBacklog(selectedArchiveEntry) ? <span>{formatBacklog(selectedArchiveEntry)}</span> : null}
          </div>
        ) : null}

        <label className="flex min-h-[2.25rem] cursor-pointer items-center gap-2 text-[0.875rem] text-fg">
          <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--text))]" checked={archiveResume} onChange={(e) => setArchiveResume(e.target.checked)} />
          Resume from the saved checkpoint
        </label>

        <details className="rounded-md border border-line px-3 py-2">
          <summary className="cursor-pointer select-none text-[0.8125rem] text-fg-2 hover:text-fg">Rate limits</summary>
          <div className="mt-3 grid gap-3 pb-1 sm:grid-cols-3">
            {([
              ['archive-delay', 'Page delay (s)', archivePageDelay, 0, setArchivePageDelay],
              ['archive-batch', 'Batch size', archiveBatchSize, 1, setArchiveBatchSize],
              ['archive-cooldown', 'Batch cooldown (s)', archiveBatchCooldown, 0, setArchiveBatchCooldown],
            ] as const).map(([id, text, value, min, set]) => (
              <div key={id}>
                <label htmlFor={id} className={fieldLabel}>{text}</label>
                <Input
                  id={id}
                  type="number"
                  min={min}
                  value={value}
                  onChange={(e) => set(Math.max(min, Number(e.target.value) || min))}
                  className="tabular-nums"
                />
              </div>
            ))}
          </div>
        </details>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            onClick={() => selectedSourceId && runAction(
              'archive-run',
              archiveResume ? 'Archive resume started' : 'Archive run started',
              () => apiService.runArchive(selectedSourceId, desiredPosts, archiveOptions),
              (result) => setArchiveResult(result),
            )}
            disabled={!selectedSourceId || busy}
          >
            {runningAction === 'archive-run' ? 'Archiving…' : archiveResume ? 'Continue archive' : 'Run archive'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => selectedSourceId && runAction(
              'archive-plan',
              'Archive plan requested',
              () => apiService.planArchive(selectedSourceId, desiredPosts, archiveOptions),
              (result) => setArchiveResult(result),
            )}
            disabled={!selectedSourceId || busy}
          >
            Plan
          </Button>
          <Button
            variant="secondary"
            onClick={() => selectedSourceId && runAction(
              'archive-status',
              'Archive status requested',
              () => apiService.getArchiveStatus(selectedSourceId),
              (result) => setArchiveResult(result),
            )}
            disabled={!selectedSourceId || busy}
          >
            Status
          </Button>
          <Button
            variant="ghost"
            onClick={() => selectedSourceId && runAction(
              'archive-run-fresh',
              'Fresh archive run started',
              () => apiService.runArchive(selectedSourceId, desiredPosts, { ...archiveOptions, resume: false }),
              (result) => setArchiveResult(result),
            )}
            disabled={!selectedSourceId || busy}
          >
            {runningAction === 'archive-run-fresh' ? 'Starting…' : 'Start fresh'}
          </Button>
        </div>

        {archiveResult ? (
          <Notice
            tone={archiveResult.success === false ? 'error' : 'completion'}
            title={archiveResult.success === false
              ? archiveResult.error || archiveResult.detail || 'The archive request failed'
              : archiveResult.message || (archiveResult.status ? `Archive ${String(archiveResult.status)}` : 'Done')}
          >
            <details className="mt-2">
              <summary className="cursor-pointer select-none text-[0.75rem] text-fg-3 hover:text-fg">Raw response</summary>
              <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap font-mono text-[0.75rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
                {formatJson(archiveResult as Record<string, any>)}
              </pre>
            </details>
          </Notice>
        ) : null}
      </section>

      <section aria-labelledby="archive-catalog" className="min-w-0 space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 id="archive-catalog" className={sectionTitle}>Catalog</h2>
          {loadingArchiveCatalog ? <span className="text-[0.75rem] text-fg-3">Refreshing…</span> : null}
        </div>
        <label htmlFor="archive-search" className="sr-only">Search sources</label>
        <Input
          id="archive-search"
          type="search"
          value={archiveSourceQuery}
          onChange={(e) => setArchiveSourceQuery(e.target.value)}
          placeholder="Search sources"
        />
        <ul className="max-h-[32rem] space-y-1.5 overflow-y-auto">
          {filteredArchiveCatalog.map((entry) => {
            const isSelected = entry.source_id === selectedSourceId;
            const name = sourceLabel(entry.display_name || entry.source_id);
            const glyph = archiveGlyph(entry.archive_status);
            return (
              <li key={entry.source_id}>
                <button
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => setSelectedSourceId(entry.source_id)}
                  className={`flex w-full min-w-0 items-center gap-3 rounded-md border px-3 py-2 text-left text-[0.8125rem] transition-[transform,border-color,background-color] duration-[120ms] ease-out active:scale-[0.99] focus-visible:outline focus-visible:outline-2 focus-visible:outline-fg motion-reduce:transition-none ${
                    isSelected ? 'border-fg bg-raised' : 'border-line bg-surface hover:border-line-strong'
                  }`}
                >
                  <SourceAvatar source={{ id: entry.source_id, platform: entry.platform, display_name: entry.display_name }} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold text-fg" title={entry.display_name ?? undefined}>{name}</div>
                    <div className="truncate text-[0.75rem] tabular-nums text-fg-3">
                      {entry.platform} · {formatArchiveRatio(entry)}
                      {formatBacklog(entry) ? ` · ${formatBacklog(entry)}` : ''}
                    </div>
                  </div>
                  <StatusGlyph status={glyph.status} label={glyph.label} hideLabel className="sm:hidden" />
                  <StatusGlyph status={glyph.status} label={glyph.label} className="max-sm:hidden" />
                </button>
              </li>
            );
          })}
          {filteredArchiveCatalog.length === 0 ? (
            <li className="rounded-md border border-dashed border-line px-3 py-6 text-center text-[0.8125rem] text-fg-3">
              {loadingArchiveCatalog ? 'Loading the catalog…' : 'No matching sources.'}
            </li>
          ) : null}
        </ul>
      </section>
    </div>
  );

  const renderMissionFeedSection = () => {
    const jobs = operationsOverview?.jobs || [];
    const missionEvents = selectedJob && Array.isArray(selectedJob.payload?.events) ? selectedJob.payload?.events : [];
    const report = selectedJob?.job_type === 'ingestion_run' ? asRunReport(selectedJob.payload) : null;
    return (
      <div className="space-y-6">
        {visibleMissionAlerts.length > 0 ? (
          <div className="space-y-2">
            {visibleMissionAlerts.map((alert) => (
              <Notice
                key={alert.id}
                tone={alert.severity === 'high' || alert.severity === 'critical' ? 'error' : 'warning'}
                title={(alert as { label?: string }).label || alert.title}
                message={alert.message}
                action={{ label: 'Dismiss', onClick: () => setDismissedAlertIds((prev) => [...prev, alert.id]) }}
              />
            ))}
          </div>
        ) : null}

        <div className="grid gap-8 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
          <section aria-labelledby="jobs-recent" className="min-w-0 space-y-3">
            <div className="flex items-baseline justify-between gap-3">
              <h2 id="jobs-recent" className={sectionTitle}>Recent jobs</h2>
              <span className="text-[0.75rem] tabular-nums text-fg-3">
                {loadingOverview && !jobs.length ? 'Loading…' : plural(jobs.length, 'job')}
              </span>
            </div>
            <ul className="max-h-[36rem] space-y-1.5 overflow-y-auto">
              {jobs.map((job) => {
                const isSelected = selectedJobId === job.id;
                const started = formatJobTimestamp(job.started_at);
                const duration = formatJobDuration(job.started_at, job.finished_at);
                return (
                  <li key={job.id}>
                    <button
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() => setSelectedJobId(job.id)}
                      className={`w-full min-w-0 rounded-md border px-3 py-2.5 text-left text-[0.8125rem] transition-[transform,border-color,background-color] duration-[120ms] ease-out active:scale-[0.99] focus-visible:outline focus-visible:outline-2 focus-visible:outline-fg motion-reduce:transition-none ${
                        isSelected ? 'border-fg bg-raised' : 'border-line bg-surface hover:border-line-strong'
                      }`}
                    >
                      <div className="flex min-w-0 items-start justify-between gap-3">
                        <div className="min-w-0 break-words font-semibold text-fg [overflow-wrap:anywhere]">
                          {jobLabel(job)}
                          {job.source_display_name ? <span className="font-normal text-fg-2"> · {sourceLabel(job.source_display_name)}</span> : null}
                        </div>
                        <StatusGlyph status={jobGlyph(job.status)} label={job.status} />
                      </div>
                      {job.message ? <p className="mt-0.5 line-clamp-2 text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]">{job.message}</p> : null}
                      {job.status === 'running' && typeof job.progress === 'number' && job.progress > 0 ? (
                        <div className="mt-2 h-0.5 overflow-hidden rounded-full bg-raised" role="progressbar" aria-valuenow={Math.round(job.progress)} aria-valuemin={0} aria-valuemax={100}>
                          <div className="h-full bg-fg" style={{ width: `${Math.min(100, job.progress)}%` }} />
                        </div>
                      ) : null}
                      <div className="mt-1 flex flex-wrap gap-x-3 text-[0.75rem] tabular-nums text-fg-3">
                        {started ? <span>{started}</span> : null}
                        {duration ? <span>{duration}</span> : null}
                        {job.event_count ? <span>{plural(job.event_count, 'event')}</span> : null}
                      </div>
                    </button>
                  </li>
                );
              })}
              {jobs.length === 0 && !loadingOverview ? (
                <li className="rounded-md border border-dashed border-line px-3 py-8 text-center text-[0.8125rem] text-fg-3">
                  No jobs yet. Run due sources, fetch a source or write a briefing and it shows up here.
                </li>
              ) : null}
            </ul>
          </section>

          <section aria-labelledby="jobs-detail" className="min-w-0 space-y-4">
            <div className="flex items-baseline justify-between gap-3">
              <h2 id="jobs-detail" className={sectionTitle}>{selectedJob ? jobLabel(selectedJob) : 'Job detail'}</h2>
              {loadingSelectedJob ? <span className="text-[0.75rem] text-fg-3">Loading…</span> : null}
            </div>
            {selectedJob ? (
              <>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-3 sm:grid-cols-3">
                  {[
                    ['Status', <StatusGlyph key="s" status={jobGlyph(selectedJob.status)} label={selectedJob.status} />],
                    ['Source', selectedJob.source_display_name ? sourceLabel(selectedJob.source_display_name) : 'All sources'],
                    ['Started', formatJobTimestamp(selectedJob.started_at) || '—'],
                    ['Finished', formatJobTimestamp(selectedJob.finished_at) || 'still running'],
                    ['Duration', formatJobDuration(selectedJob.started_at, selectedJob.finished_at) || '—'],
                    ['Estimated tokens', extractEstimatedTokens(selectedJob.payload) || '—'],
                  ].map(([term, value]) => (
                    <div key={String(term)} className="min-w-0 border-l border-line pl-3">
                      <dt className="text-[0.75rem] text-fg-3">{term}</dt>
                      <dd className="break-words text-[0.8125rem] tabular-nums text-fg [overflow-wrap:anywhere]">{value}</dd>
                    </div>
                  ))}
                </dl>
                {selectedJob.status === 'running' ? (
                  <div>
                    <div className="h-0.5 overflow-hidden rounded-full bg-raised">
                      <div className="h-full bg-fg" style={{ width: `${Math.min(100, Number(selectedJob.progress || 0))}%` }} />
                    </div>
                    <p className="mt-1 text-[0.75rem] tabular-nums text-fg-3">{Math.round(Number(selectedJob.progress || 0))}% complete</p>
                  </div>
                ) : null}
                {report ? <RunReportSummary report={report} /> : null}
                <div>
                  <h3 className="mb-2 text-[0.875rem] font-semibold text-fg">Events</h3>
                  {missionEvents.length ? (
                    <ol className="max-h-[18rem] divide-y divide-line overflow-y-auto rounded-md border border-line bg-surface font-mono text-[0.75rem] leading-5">
                      {missionEvents.map((event: any, index: number) => (
                        <li key={`${event.at || 'event'}-${index}`} className="flex min-w-0 gap-3 px-3 py-1.5">
                          <span className="shrink-0 tabular-nums text-fg-3">{formatJobTimestamp(event.at) || '—'}</span>
                          <span className={`shrink-0 ${event.level === 'error' ? 'font-semibold text-fg' : 'text-fg-3'}`}>
                            {event.level === 'error' ? '× error' : event.level || 'info'}
                          </span>
                          <span className="min-w-0 break-words text-fg-2 [overflow-wrap:anywhere]">
                            {event.message || 'No message'}
                            {typeof event.progress === 'number' ? ` (${Math.round(Number(event.progress))}%)` : ''}
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="text-[0.8125rem] text-fg-3">No events were recorded for this job.</p>
                  )}
                </div>
                <details className="rounded-md border border-line px-3 py-2">
                  <summary className="cursor-pointer select-none text-[0.8125rem] text-fg-2 hover:text-fg">Payload (raw)</summary>
                  <pre className="mt-2 max-h-[14rem] overflow-auto whitespace-pre-wrap font-mono text-[0.75rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
                    {formatJson(selectedJob.payload || null)}
                  </pre>
                </details>
              </>
            ) : (
              <p className="rounded-md border border-dashed border-line px-3 py-10 text-center text-[0.8125rem] text-fg-3">
                Choose a job to see its events, report and payload.
              </p>
            )}
          </section>
        </div>
      </div>
    );
  };

  const renderLogsSection = () => (
    <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <section aria-labelledby="logs-tail" className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="logs-tail" className={sectionTitle}>Log tail</h2>
          <div className="flex items-center gap-2">
            <label htmlFor="log-file" className="sr-only">Log file</label>
            <Select id="log-file" value={selectedLogName} onChange={(e) => setSelectedLogName(e.target.value)}>
              {availableLogs.map((logOption) => (
                <option key={logOption} value={logOption}>{LOG_LABELS[logOption] || logOption}</option>
              ))}
            </Select>
            <Button variant="ghost" size="icon" onClick={() => loadLogTail(selectedLogName)} aria-label="Refresh the log" title="Refresh">
              <RefreshCw aria-hidden="true" className={loadingLogs ? 'motion-safe:animate-spin' : undefined} />
            </Button>
          </div>
        </div>
        <p className="text-[0.75rem] text-fg-3">
          {LOG_LABELS[selectedLogName] || selectedLogName} · {logTail?.exists ? `last ${plural(logTail?.lines?.length ?? 0, 'line')}` : 'not created yet'}
        </p>
        <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-md border border-line bg-surface p-3 font-mono text-[0.75rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
          {loadingLogs && !logTail
            ? 'Loading logs…'
            : logTail?.lines?.length
              ? logTail.lines.join('\n')
              : 'No lines in this log yet.'}
        </pre>
      </section>

      <section aria-labelledby="logs-session" className="min-w-0 space-y-3">
        <h2 id="logs-session" className={sectionTitle}>This session</h2>
        {logs.length === 0 ? (
          <p className="text-[0.8125rem] text-fg-3">Actions you take on this page are listed here.</p>
        ) : (
          <ol className="max-h-[32rem] divide-y divide-line overflow-y-auto border-y border-line">
            {logs.map((entry) => (
              <li key={entry.id} className="flex min-w-0 items-start gap-2 py-2 text-[0.8125rem]">
                <StatusIcon status={LOG_LEVEL_GLYPH[entry.level]} className="mt-[0.3rem]" />
                <span className="sr-only">{entry.level}:</span>
                <span className={`min-w-0 flex-1 break-words [overflow-wrap:anywhere] ${entry.level === 'error' ? 'font-semibold text-fg' : 'text-fg-2'}`}>
                  {entry.message}
                </span>
                <span className="shrink-0 text-[0.75rem] tabular-nums text-fg-3">{entry.at}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );

  const schedulerMeta = (() => {
    const parts: string[] = [];
    if (schedulerConfig) parts.push(`checks for due sources every ${formatCount(Number(schedulerConfig.ingest_tick_minutes ?? 60))} min`);
    if (schedulerNextRunAt && schedulerCountdown) {
      parts.push(schedulerCountdown === 'due now' ? 'next tick due now' : `next tick in ${schedulerCountdown}`);
    }
    if (schedulerConfig) parts.push(`briefings every ${schedulerConfig.interval_hours}h`);
    const text = parts.join(' · ');
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Reading the scheduler…';
  })();

  return (
    <Page width="wide">
      <PageHeader
        title="Ingestion"
        meta={schedulerMeta}
        actions={(
          <>
            <RunCycleButton onReport={onCycleReport} />
            {schedulerConfig ? (
              <Button variant="ghost" onClick={() => setSchedulerModalOpen(true)}>
                <Settings aria-hidden="true" /> Scheduler
              </Button>
            ) : null}
          </>
        )}
      />

      <div className="space-y-3">
        {staleWarning ? <IngestionStatusNotice state="stopped" message={staleWarning} /> : null}
        {error ? <Notice tone="error" title={error} action={{ label: 'Dismiss', onClick: () => setError(null) }} /> : null}
      </div>

      <nav aria-label="Ingestion views" className={`flex max-w-full items-end gap-5 overflow-x-auto border-b border-line ${staleWarning || error ? 'mt-6' : ''}`}>
        {INGESTION_TABS.map((tab) => (
          <Link
            key={tab.key}
            to={getIngestionTabHref(tab.key)}
            aria-current={tab.key === activeTab ? 'page' : undefined}
            className={tabTriggerClass}
          >
            {TAB_WORDS[tab.key] ?? tab.label.toLowerCase()}
          </Link>
        ))}
      </nav>

      <div className="pt-8">
        {activeTab === 'main' && (
          <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
            <div className="min-w-0 lg:order-1">{renderImmediateActionsSection()}</div>
            <aside className="min-w-0 lg:order-2">{renderStatusSection()}</aside>
          </div>
        )}
        {activeTab === 'archive' && renderArchiveControlSection()}
        {activeTab === 'missions' && renderMissionFeedSection()}
        {activeTab === 'logs' && renderLogsSection()}
      </div>

      <SchedulerSettingsModal
        open={schedulerModalOpen}
        schedulerConfig={schedulerConfig}
        schedulerDirty={schedulerDirty}
        savingScheduler={savingScheduler}
        onClose={() => setSchedulerModalOpen(false)}
        onSave={async () => {
          const saved = await saveSchedulerConfig();
          if (saved) {
            setSchedulerModalOpen(false);
          }
        }}
        onIntervalChange={(value) => {
          setSchedulerDirty(true);
          setSchedulerConfig((prev) => prev ? ({ ...prev, interval_hours: value }) : prev);
        }}
        onTickChange={(value) => {
          setSchedulerDirty(true);
          setSchedulerConfig((prev) => prev ? ({ ...prev, ingest_tick_minutes: value }) : prev);
        }}
        onToggle={(key, checked) => {
          setSchedulerDirty(true);
          setSchedulerConfig((prev) => prev ? ({ ...prev, [key]: checked }) as SchedulerConfig : prev);
        }}
      />
    </Page>
  );
}
