import { errorMessage } from '../../lib/apiError';
import { FOCUS_RING, PRESS_FEEDBACK } from './press';

/** A fetch that failed: the clean `ApiError.message` and a Retry button (Mark IX §F.6). */
export default function ErrorState({
  error,
  onRetry,
  title = 'Something went wrong',
  className = '',
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={`rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-6 py-8 text-center ${className}`}
    >
      <p className="break-words text-base font-semibold text-[var(--text-normal)]">{title}</p>
      <p className="mx-auto mt-2 max-w-prose break-words text-sm text-[var(--text-error)]">{errorMessage(error)}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className={`mt-5 inline-flex min-h-[44px] items-center justify-center rounded-lg border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-4 text-sm font-medium text-[var(--text-normal)] hover:bg-[var(--background-secondary-alt)] ${PRESS_FEEDBACK} ${FOCUS_RING}`}
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
