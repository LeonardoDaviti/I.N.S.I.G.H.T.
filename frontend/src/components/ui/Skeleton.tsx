import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

/** A placeholder block in the raised tone; pulses only when motion is allowed. */
export default function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn('rounded-sm bg-raised motion-safe:animate-pulse', className)} {...props} />;
}
