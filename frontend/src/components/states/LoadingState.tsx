/** A skeleton placeholder for a data fetch in flight (Mark IX §F.6).
 *  `aria-busy` + a visually hidden label is what screen readers announce. */
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
    <div role="status" aria-busy="true" aria-live="polite" className={`space-y-3 ${className}`}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: Math.max(1, rows) }, (_, index) => (
        <div
          key={index}
          aria-hidden="true"
          className="motion-safe:animate-pulse rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4"
        >
          <div className="h-3 w-2/3 rounded bg-[var(--background-secondary-alt)]" />
          <div className="mt-3 h-3 w-full rounded bg-[var(--background-secondary-alt)]" />
        </div>
      ))}
    </div>
  );
}
