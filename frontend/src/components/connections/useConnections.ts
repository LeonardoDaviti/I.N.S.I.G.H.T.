import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useApi } from '../../services/ApiContext';
import type { CredentialProviderView, CredentialsResponse } from '../../services/api';
import { SOURCES_HEALTH_KEY } from '../../hooks/useSourcesHealth';

export const CREDENTIALS_KEY = ['credentials'] as const;

/** Every connection (write-only views). */
export function useConnections(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: [...CREDENTIALS_KEY],
    queryFn: () => api.getCredentials(),
    staleTime: 15_000,
    enabled,
  });
}

/** Put one provider's fresh view into the cached list (a write returns it). */
export function useReplaceProvider() {
  const queryClient = useQueryClient();
  return (view: CredentialProviderView) => {
    queryClient.setQueryData<CredentialsResponse>([...CREDENTIALS_KEY], (current) => (
      current
        ? { providers: current.providers.map((p) => (p.provider === view.provider ? view : p)) }
        : { providers: [view] }
    ));
  };
}

/** Save one secret; the cache gets the view (never the value). */
export function useSaveCredential() {
  const api = useApi();
  const queryClient = useQueryClient();
  const replace = useReplaceProvider();
  return useMutation({
    mutationFn: ({ provider, key, value }: { provider: string; key: string; value: string }) => api.putCredential(provider, key, value),
    onSuccess: (view) => {
      replace(view);
      // A new credential changes what the health table says (credential_notice, unavailable).
      void queryClient.invalidateQueries({ queryKey: [...SOURCES_HEALTH_KEY] });
    },
  });
}
