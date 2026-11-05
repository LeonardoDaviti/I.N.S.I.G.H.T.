import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { MarkxTokenView } from '../../services/api';
import { useApi } from '../../services/ApiContext';
import { Button, StatusGlyph } from '../ui';
import { errorMessage } from '../../lib/apiError';

export const MARKX_TOKEN_KEY = ['markx-token'] as const;

/**
 * Sources → Connections → Mark X worker (issue 0086 C): the token scripts/markx-worker sends. Shown only
 * while INSIGHT_MARKX is on (the route answers 404 when off). A new token is shown once and replaces the old.
 */
export default function MarkXToken() {
  const api = useApi();
  const queryClient = useQueryClient();
  const view = useQuery({ queryKey: [...MARKX_TOKEN_KEY], queryFn: () => api.getMarkxToken(), retry: false, staleTime: 60_000 });
  const create = useMutation({
    mutationFn: () => api.createMarkxToken(),
    // the cache keeps the state, never the token
    onSuccess: (made) => queryClient.setQueryData<MarkxTokenView>([...MARKX_TOKEN_KEY],
      { set: made.set, last4: made.last4, updated_at: made.updated_at }),
  });
  if (!view.isSuccess) return null;
  const state = view.data;

  return (
    <section aria-label="Mark X worker" className="mt-6 border-t border-line pt-4" data-provider="markx">
      <div className="flex min-w-0 items-start gap-3 px-1">
        <span className="min-w-0 flex-1">
          <span className="block text-[0.9375rem] font-semibold text-fg">Mark X worker</span>
          <span className="block text-[0.8125rem] text-fg-2">
            The token markx-worker sends from your device to read and judge posts with Haiku. A new token replaces the old one.
          </span>
        </span>
        <span className="shrink-0 pt-0.5">
          <StatusGlyph status={state.set ? 'ok' : 'scheduled'} label={state.set ? `set · ••••${state.last4 ?? ''}` : 'not set'} />
        </span>
      </div>
      <div className="mt-3 space-y-3 pl-1" aria-live="polite">
        <Button size="sm" variant="secondary" onClick={() => create.mutate()} disabled={create.isPending}
          aria-busy={create.isPending || undefined}>
          {create.isPending ? 'generating…' : state.set ? 'replace token' : 'generate token'}
        </Button>
        {create.isError ? (
          <p className="text-[0.8125rem] text-fg [overflow-wrap:anywhere]">
            <span aria-hidden="true" className="mr-1 font-semibold">×</span>Could not generate a token: {errorMessage(create.error)}
          </p>
        ) : null}
        {create.isSuccess ? (
          <div className="space-y-1.5">
            <p className="text-[0.8125rem] text-fg-2">
              Save it in <code>~/.config/insight/markx-token</code> on your device (chmod 600). It is not shown again.
            </p>
            <code data-testid="markx-token" className="block select-all rounded-sm bg-raised px-2 py-1.5 text-[0.8125rem] text-fg [overflow-wrap:anywhere]">
              {create.data.token}
            </code>
          </div>
        ) : null}
      </div>
    </section>
  );
}
