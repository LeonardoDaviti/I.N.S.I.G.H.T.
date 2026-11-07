import { useQuery } from '@tanstack/react-query';

import type { Voice } from '../services/api';
import { voicesApi } from '../services/voices';

export const VOICES_KEY = ['voices'] as const;

/**
 * The voice a reader scope is (issue 0132 A): `voice:<id>` that voice, `source:<id>` the voice that source is a
 * channel of (null when none); undefined while it loads, and for the Main feed and a track.
 */
export function useScopeVoice(scope: string): Voice | null | undefined {
  const [kind, id] = scope.split(':');
  const asks = (kind === 'voice' || kind === 'source') && Boolean(id);
  const query = useQuery({
    queryKey: [...VOICES_KEY, 'scope', scope],
    queryFn: async () => (kind === 'voice' ? (await voicesApi.get(id)).voice : (await voicesApi.ofSource(id)).voice),
    enabled: asks,
    staleTime: 60_000,
    retry: false,
  });
  if (!asks) return undefined;
  if (query.isError) return null;
  return query.data;
}
