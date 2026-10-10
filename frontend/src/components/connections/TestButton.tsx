import { useMutation } from '@tanstack/react-query';
import type { CredentialProviderView } from '../../services/api';
import { useApi } from '../../services/ApiContext';
import { Button, StatusGlyph } from '../ui';
import { errorMessage } from '../../lib/apiError';
import { formatRelativeTime } from '../../lib/dates';
import { useReplaceProvider } from './useConnections';

/** "test" and its inline result: the last stored test, or the request's own error. */
export default function TestButton({ view, now = new Date() }: { view: CredentialProviderView; now?: Date }) {
  const api = useApi();
  const replace = useReplaceProvider();
  const test = useMutation({
    mutationFn: () => api.testCredential(view.provider),
    onSuccess: replace,
  });
  const anySet = view.fields.some((f) => f.set);
  const result = view.test;

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5" aria-live="polite">
      <Button
        size="sm"
        variant="secondary"
        onClick={() => test.mutate()}
        disabled={test.isPending || !anySet}
        aria-busy={test.isPending || undefined}
      >
        {test.isPending ? 'testing…' : 'test'}
      </Button>
      {test.isPending ? null : test.isError ? (
        <span data-testid="test-result" className="min-w-0 flex-1 basis-64 text-[0.8125rem] text-fg [overflow-wrap:anywhere]">
          <span aria-hidden="true" className="mr-1 font-semibold">×</span>
          Could not run the test: {errorMessage(test.error)}
        </span>
      ) : result ? (
        <p data-testid="test-result" className="min-w-0 flex-1 basis-64 text-[0.8125rem] leading-[1.6]">
          <StatusGlyph status={result.ok ? 'ok' : 'failing'} label={result.ok ? 'ok' : 'failed'} className="mr-2 align-[-0.1em]" />
          <span className="text-fg-2 [overflow-wrap:anywhere]">{result.message}</span>
          {result.tested_at ? <span className="whitespace-nowrap tabular-nums text-fg-3"> · {formatRelativeTime(result.tested_at, now)}</span> : null}
        </p>
      ) : !anySet ? (
        <span className="text-[0.75rem] text-fg-3">Save a value first.</span>
      ) : null}
    </div>
  );
}
