import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { cn } from '../../lib/utils';

const ROW =
  'group flex min-w-0 items-start gap-4 rounded-md border border-line bg-bg px-4 py-3 text-left';
const ROW_INTERACTIVE =
  'transition-[transform,border-color,background-color] duration-[120ms] ease-out hover:border-line-strong hover:bg-surface active:scale-[0.995] motion-reduce:transition-none motion-reduce:active:scale-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg';

/**
 * The smol-style list row: a muted meta column (date, count; tabular, never
 * truncated), a bold title that wraps and clamps at 2 lines, an optional
 * description, and a chevron when it navigates.
 */
export default function Row({
  meta,
  title,
  description,
  trailing,
  to,
  href,
  muted = false,
  className,
}: {
  meta?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  trailing?: ReactNode;
  /** Router path: the whole row becomes one link. */
  to?: string;
  /** External URL: opens in a new tab. */
  href?: string;
  /** A read/disabled row: regular weight, secondary colour. */
  muted?: boolean;
  className?: string;
}) {
  const body = (
    <>
      {meta !== undefined ? (
        <div className="w-[5.5rem] shrink-0 whitespace-nowrap pt-px text-[0.8125rem] tabular-nums text-fg-3">{meta}</div>
      ) : null}
      <div className="min-w-0 flex-1">
        <div
          className={cn(
            'line-clamp-2 break-words [overflow-wrap:anywhere]',
            muted ? 'font-normal text-fg-2' : 'font-semibold text-fg',
          )}
        >
          {title}
        </div>
        {description ? <div className="mt-0.5 line-clamp-2 break-words text-[0.8125rem] text-fg-2">{description}</div> : null}
      </div>
      {trailing ? <div className="flex shrink-0 items-center gap-2">{trailing}</div> : null}
      {to || href ? (
        <ChevronRight aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-fg-3 group-hover:text-fg" />
      ) : null}
    </>
  );
  if (to) return <Link to={to} className={cn(ROW, ROW_INTERACTIVE, className)}>{body}</Link>;
  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener" className={cn(ROW, ROW_INTERACTIVE, className)}>
        {body}
      </a>
    );
  }
  return <div className={cn(ROW, className)}>{body}</div>;
}
