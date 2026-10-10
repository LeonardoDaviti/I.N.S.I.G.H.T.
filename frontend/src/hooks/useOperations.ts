import { useQuery } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';

/** Cache keys for the operations endpoints (Sources → ingestion). */
export const OPERATIONS_OVERVIEW_KEY = ['operations', 'overview'] as const;
export const SCHEDULER_KEY = ['operations', 'scheduler'] as const;
export const operationJobKey = (id: string | null) => ['operations', 'job', id] as const;

/** Recent jobs and alerts, every 15 seconds. */
export function useOperationsOverview() {
  const api = useApi();
  return useQuery({
    queryKey: [...OPERATIONS_OVERVIEW_KEY],
    queryFn: async () => {
      const response = await api.getOperationsOverview();
      if (response.success === false) throw new Error(response.error || 'Could not load the job history.');
      return response;
    },
    refetchInterval: 15_000,
  });
}

/** The scheduler's settings and state, every 30 seconds. */
export function useSchedulerConfig() {
  const api = useApi();
  return useQuery({
    queryKey: [...SCHEDULER_KEY],
    queryFn: async () => {
      const response = await api.getSchedulerConfig();
      if (!response.success || !response.scheduler) throw new Error(response.error || 'Could not read the scheduler.');
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
      if (!response.success || !response.job) throw new Error(response.error || 'Could not load the job.');
      return response.job;
    },
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 5_000 : false),
  });
}
