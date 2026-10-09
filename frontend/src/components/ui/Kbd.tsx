import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

/** A key cap: micro mono text in a 1px box. */
export default function Kbd({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        'inline-flex min-w-[1.25rem] items-center justify-center rounded-sm border border-line-strong px-1 font-mono text-[0.6875rem] leading-[1.25rem] text-fg-2',
        className,
      )}
      {...props}
    />
  );
}
