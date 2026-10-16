import { useQuery } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import { runningFetchJob } from '../lib/jobRuns';

/** Cache keys for the operations endpoints (Sources → ingestion). */
export const OPERATIONS_OVERVIEW_KEY = ['operations', 'overview'] as const;
export const SCHEDULER_KEY = ['operations', 'scheduler'] as const;
export const operationJobKey = (id: string | null) => ['operations', 'job', id] as const;

/** Recent jobs and alerts: every 5 seconds while a fetch job runs, else every 15.
 *  The one source of "what is running" (the top bar's sign, the Ingestion tab, the reader's counts). */
export function useOperationsOverview() {
  const api = useApi();
  return useQuery({
    queryKey: [...OPERATIONS_OVERVIEW_KEY],
    queryFn: () => api.getOperationsOverview(),
    refetchInterval: (query) => (runningFetchJob(query.state.data?.jobs) ? 5_000 : 15_000),
  });
}

/** The running ingestion run or archive job, from the overview; null when nothing fetches. */
export function useRunningFetchJob() {
  return runningFetchJob(useOperationsOverview().data?.jobs);
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

/** One job in full; polled every 5 seconds while it runs. Idle without an id. */
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
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 5_000 : false),
  });
}
