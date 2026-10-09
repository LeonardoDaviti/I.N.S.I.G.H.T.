import { useQuery, type QueryClient } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { SourceHealthRow, SourcesHealthResponse } from '../services/api';

/** The one cache key for GET /api/sources/health (useIngestionRun invalidates it). */
export const SOURCES_HEALTH_KEY = ['sources-health'] as const;

/** Every source's health row. `fixture` (dev-only `?data=`) replaces the API call. */
export function useSourcesHealth(fixture?: () => SourcesHealthResponse, fixtureName?: string) {
  const api = useApi();
  return useQuery({
    queryKey: fixture ? [...SOURCES_HEALTH_KEY, 'fixture', fixtureName ?? 'custom'] : [...SOURCES_HEALTH_KEY],
    queryFn: fixture ? async () => fixture() : () => api.getSourcesHealth(),
    staleTime: 30_000,
  });
}

/** Put the fresh row a cadence PUT returned into every cached health response. */
export function replaceHealthRow(queryClient: QueryClient, row: SourceHealthRow) {
  queryClient.setQueriesData<SourcesHealthResponse>({ queryKey: [...SOURCES_HEALTH_KEY] }, (current) => (
    current ? { ...current, rows: current.rows.map((existing) => (existing.source_id === row.source_id ? row : existing)) } : current
  ));
}
