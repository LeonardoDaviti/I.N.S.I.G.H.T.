import { useQuery } from '@tanstack/react-query';
import { useApi } from '../services/ApiContext';

export const MARKX_ON_KEY = ['markx-on'] as const;

/** Whether Mark X is on: GET /api/markx/on answers, or 404s while off. Asked once a session; `undefined` while asking. */
export function useMarkxState(): boolean | undefined {
  const api = useApi();
  const query = useQuery({
    queryKey: [...MARKX_ON_KEY],
    queryFn: async () => (await api.getMarkxOn()).on === true,
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
  });
  if (query.isError) return false;
  return query.data;
}

/** Mark X is on (false while asking or off). */
export function useMarkxOn(): boolean {
  return useMarkxState() === true;
}
