import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

/**
 * Page anatomy (design doc §10): title, an optional meta line in the secondary
 * tone ("90 sources · as of just now"), actions on the right (one primary).
 */
export default function PageHeader({
  title,
  meta,
  actions,
  children,
  className,
}: {
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  /** Rendered under the title row, e.g. <Tabs/>. */
  children?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn('mb-6', className)}>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1 basis-[16rem]">
          <h1 className="break-words text-[1.375rem] font-semibold leading-[1.25] tracking-[-0.02em] text-fg">{title}</h1>
          {meta ? <p className="mt-1 text-[0.8125rem] tabular-nums text-fg-2">{meta}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children ? <div className="mt-5">{children}</div> : null}
    </header>
  );
}

/**
 * The page container. Two widths only, so page edges and headers never jump
 * between routes: `reading` (max-w-3xl) for single-column pages you read top to
 * bottom, `ops` (max-w-6xl) for tables and pages with a side rail. `list` and
 * `wide` are the older names for the same two widths.
 */
export function Page({
  width = 'ops',
  className,
  children,
}: {
  width?: 'reading' | 'ops' | 'list' | 'wide';
  className?: string;
  children: ReactNode;
}) {
  const max = width === 'reading' || width === 'list' ? 'max-w-3xl' : 'max-w-6xl';
  return <div className={cn('mx-auto w-full px-4 pb-24 pt-8 sm:px-6 sm:pt-10', max, className)}>{children}</div>;
}
