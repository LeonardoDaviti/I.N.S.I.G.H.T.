import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

/** A specimen's grid of variants: two columns where there's room. */
export function Variants({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('grid gap-x-10 gap-y-7 sm:grid-cols-2', className)}>{children}</div>;
}

/** One variant or state, named in mono above it. `wide` spans the grid. */
export function Variant({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={cn('min-w-0', wide && 'sm:col-span-2')}>
      <p className="mb-2.5 font-mono text-[0.75rem] text-fg-3">{label}</p>
      <div className="flex min-w-0 flex-wrap items-center gap-3">{children}</div>
    </div>
  );
}
