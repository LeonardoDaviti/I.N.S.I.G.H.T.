import { useQuery } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import { runningFetchJob } from '../lib/jobRuns';

/** Cache keys for the operations endpoints (Sources → ingestion). */
export const OPERATIONS_OVERVIEW_KEY = ['operations', 'overview'] as const;
/** GET /api/operations/running: the recent jobs only, for every page's top bar. */
export const RUNNING_JOBS_KEY = ['operations', 'running'] as const;
export const SCHEDULER_KEY = ['operations', 'scheduler'] as const;
export const operationJobKey = (id: string | null) => ['operations', 'job', id] as const;

/** Recent jobs, alerts, source health and counts, every 5 s while a fetch job runs, else 15. Ingestion tab only. */
export function useOperationsOverview() {
  const api = useApi();
  return useQuery({
    queryKey: [...OPERATIONS_OVERVIEW_KEY],
    queryFn: () => api.getOperationsOverview(),
    refetchInterval: (query) => (runningFetchJob(query.state.data?.jobs) ? 5_000 : 15_000),
  });
}

/** The recent jobs alone, every 5 s while a fetch job runs, else 15: the one source of "what is running"
 *  outside the Ingestion tab. */
export function useRunningJobs() {
  const api = useApi();
  return useQuery({
    queryKey: [...RUNNING_JOBS_KEY],
    queryFn: () => api.getRunningJobs(),
    refetchInterval: (query) => (runningFetchJob(query.state.data?.jobs) ? 5_000 : 15_000),
  });
}

/** The running ingestion run or archive job; null when nothing fetches. */
export function useRunningFetchJob() {
  return runningFetchJob(useRunningJobs().data?.jobs);
}

/** The scheduler's settings and state, every 30 seconds. */
export function useSchedulerConfig() {
  const api = useApi();
  return useQuery({
    queryKey: [...SCHEDULER_KEY],
    queryFn: async () => {
      const response = await api.getSchedulerConfig();
      if (!response.scheduler) throw new Error('Could not read the scheduler.');
      return response.scheduler;
    },
    refetchInterval: 30_000,
  });
}

/** One job in full; polled every 5 s while it runs, every 30 while it waits or is queued. Idle without an id. */
export function useOperationJob(id: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: [...operationJobKey(id)],
    queryFn: async () => {
      const response = await api.getOperationJob(id as string);
      if (!response.job) throw new Error('Could not load the job.');
      return response.job;
    },
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'running' ? 5_000 : status === 'waiting' || status === 'queued' ? 30_000 : false;
    },
  });
}
