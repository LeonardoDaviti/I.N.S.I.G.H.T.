import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { useApi } from '../services/ApiContext';
import type { JobAccepted, RunReport } from '../services/api';
import { errorMessage, isAbortError } from '../lib/apiError';
import { summarizeRunReport } from '../lib/runReport';

/** What a fetch run targets (the UI side of the backend's SourceSelector). */
export type IngestionTarget =
  | { kind: 'all'; force?: boolean }
  | { kind: 'folder'; id: string; name?: string }
  | { kind: 'source'; id: string; name?: string; limit?: number };

/** Stable key for "is this target running?". A forced and a due cycle share one key. */
export function targetKey(target: IngestionTarget): string {
  return target.kind === 'all' ? 'all' : `${target.kind}:${target.id}`;
}

function startMessage(target: IngestionTarget): string {
  if (target.kind === 'all') return target.force ? 'Fetching every source…' : 'Fetching due sources…';
  const name = target.name || (target.kind === 'folder' ? 'this track' : 'this source');
  return `Fetching ${name}…`;
}

function contextLine(target: IngestionTarget): string | null {
  if (target.kind === 'all') return null;
  return target.name || null;
}

/** Query keys a finished run makes stale. Never `['feed']`: the reader shows a
 *  "N new posts" pill instead of reordering what is on screen (spec §F.3). */
export const INGESTION_INVALIDATES = [['unread-counts'], ['sources-health']] as const;

/**
 * Start a fetch run, poll its job, toast the run report and refresh the counts
 * (spec §F.3). Each run shows one sonner toast that goes from "Fetching…" to the
 * report's headline, with a link to the job. `run` never throws: it resolves the
 * RunReport, or null when the request failed (the error is toasted and kept in
 * `lastError`). Several targets may run at once (one per health-table row).
 */
export function useIngestionRun(options: { onReport?: (report: RunReport, target: IngestionTarget) => void } = {}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [running, setRunning] = useState<ReadonlySet<string>>(() => new Set());
  const [lastReport, setLastReport] = useState<RunReport | null>(null);
  const [lastError, setLastError] = useState<unknown>(null);
  const mounted = useRef(true);
  const onReportRef = useRef(options.onReport);
  onReportRef.current = options.onReport;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const setKey = useCallback((key: string, on: boolean) => {
    if (!mounted.current) return;
    setRunning((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);

  const run = useCallback(async (target: IngestionTarget): Promise<RunReport | null> => {
    const key = targetKey(target);
    const toastId = `ingestion:${key}:${Date.now()}`;
    let jobId: string | null = null;
    const onAccepted = (job: JobAccepted) => {
      jobId = job.job_id;
    };
    const viewJob = () => {
      if (jobId) navigate(`/ingestion/missions?job=${encodeURIComponent(jobId)}`);
    };

    setKey(key, true);
    toast.loading(startMessage(target), { id: toastId });
    try {
      let report: RunReport;
      if (target.kind === 'all') {
        report = await api.runIngestionCycle({ force: Boolean(target.force), onAccepted });
      } else if (target.kind === 'folder') {
        report = await api.fetchFolderNow(target.id, { onAccepted });
      } else {
        report = await api.fetchSourceNow(target.id, { limit: target.limit, onAccepted });
      }
      jobId = jobId ?? report.run_id;

      for (const queryKey of INGESTION_INVALIDATES) {
        void queryClient.invalidateQueries({ queryKey: [...queryKey] });
      }

      const summary = summarizeRunReport(report);
      const description = [contextLine(target), summary.lines[0]].filter(Boolean).join(' · ') || undefined;
      const toastOptions = {
        id: toastId,
        description,
        action: jobId ? { label: 'View job', onClick: viewJob } : undefined,
      };
      if (summary.tone === 'error') toast.error(summary.headline, toastOptions);
      else if (summary.tone === 'warning') toast.warning(summary.headline, toastOptions);
      else toast.success(summary.headline, toastOptions);

      if (mounted.current) {
        setLastReport(report);
        setLastError(null);
      }
      onReportRef.current?.(report, target);
      return report;
    } catch (error) {
      // The run may still have changed fetch state before the request failed.
      void queryClient.invalidateQueries({ queryKey: ['sources-health'] });
      if (isAbortError(error)) {
        toast.dismiss(toastId);
      } else {
        toast.error(errorMessage(error), {
          id: toastId,
          description: contextLine(target) ?? undefined,
          action: jobId ? { label: 'View job', onClick: viewJob } : undefined,
        });
      }
      if (mounted.current) setLastError(error);
      return null;
    } finally {
      setKey(key, false);
    }
  }, [api, navigate, queryClient, setKey]);

  const isRunning = useCallback((target?: IngestionTarget) => (
    target ? running.has(targetKey(target)) : running.size > 0
  ), [running]);

  return { run, isRunning, lastReport, lastError };
}
