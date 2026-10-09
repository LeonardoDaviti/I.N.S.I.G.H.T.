import Skeleton from '../ui/Skeleton';

/** A skeleton placeholder for a data fetch in flight (Mark IX §F.6), shaped like
 *  the list rows it stands in for. `aria-busy` + a visually hidden label is what
 *  screen readers announce. */
export default function LoadingState({
  label = 'Loading',
  rows = 3,
  className = '',
}: {
  label?: string;
  rows?: number;
  className?: string;
}) {
  return (
    <div role="status" aria-busy="true" aria-live="polite" className={`space-y-2 ${className}`}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: Math.max(1, rows) }, (_, index) => (
        <div key={index} aria-hidden="true" className="flex items-start gap-4 rounded-md border border-line px-4 py-3.5">
          <Skeleton className="mt-0.5 h-3 w-14 shrink-0" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className={index % 2 ? 'h-3 w-1/2' : 'h-3 w-3/4'} />
            <Skeleton className="h-2.5 w-1/3 opacity-70" />
          </div>
        </div>
      ))}
    </div>
  );
}
