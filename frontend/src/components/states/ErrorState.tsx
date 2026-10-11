import { errorMessage } from '../../lib/apiError';
import Button from '../ui/Button';
import { StatusIcon } from '../ui/StatusGlyph';

/** A fetch that failed: the clean `ApiError.message` and a Retry button (Mark IX §F.6).
 *  No red: the inverted "×" block and the word "error" carry it (design docs system/status.md). */
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
    <div role="alert" className={`rounded-md border border-line-strong px-6 py-10 text-center ${className}`}>
      <span className="mx-auto inline-flex h-6 w-6 items-center justify-center rounded-sm bg-inverse text-inverse-fg">
        <StatusIcon status="failing" className="h-3 w-3" />
        <span className="sr-only">Error:</span>
      </span>
      <p className="mt-3 break-words text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">{title}</p>
      <p className="mx-auto mt-1.5 max-w-prose break-words text-[0.875rem] text-fg-2 [overflow-wrap:anywhere]">{errorMessage(error)}</p>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry} className="mt-5">
          Retry
        </Button>
      ) : null}
    </div>
  );
}
