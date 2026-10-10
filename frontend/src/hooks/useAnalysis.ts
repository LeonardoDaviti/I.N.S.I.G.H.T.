import { useQuery } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import { ANALYSIS_ENABLED } from '../lib/features';

export const CONFIG_KEY = ['config'] as const;

export interface AnalysisFlag {
  /** Whether the analysis surfaces are shown (spec §9, reading-finish R3). */
  enabled: boolean;
  /** False only while GET /api/config is in flight: route guards wait for it, so
   *  a deep link is not redirected away before the runtime value is known. */
  settled: boolean;
}

/**
 * The analysis switch: `VITE_INSIGHT_ANALYSIS` at build time, overridden by the
 * backend's `GET /api/config` → `{ analysis_enabled }` so the two can't disagree.
 * The runtime value wins; the build flag decides only while the backend has not
 * answered, or when it can't (an older backend without the route). Fetched once.
 */
export function useAnalysis(): AnalysisFlag {
  const api = useApi();
  const config = useQuery({
    queryKey: [...CONFIG_KEY],
    queryFn: () => api.getConfig(),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const runtime = config.data?.analysis_enabled;
  return {
    enabled: typeof runtime === 'boolean' ? runtime : ANALYSIS_ENABLED,
    settled: !config.isPending,
  };
}

/** Shorthand for components that only need the boolean. */
export function useAnalysisEnabled(): boolean {
  return useAnalysis().enabled;
}
