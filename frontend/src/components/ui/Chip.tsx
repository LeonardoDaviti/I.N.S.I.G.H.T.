import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { formatCount } from '../../lib/format';

type ChipVariant = 'outline' | 'solid' | 'quiet' | 'dashed';

const CHIP_VARIANT: Record<ChipVariant, string> = {
  outline: 'border-line-strong text-fg-2',
  // Inverted: the loudest a monochrome chip gets (selected, failing).
  solid: 'border-inverse bg-inverse text-inverse-fg',
  quiet: 'border-transparent bg-raised text-fg-2',
  dashed: 'border-dashed border-line-strong text-fg',
};

const CHIP_BASE =
  'inline-flex max-w-full shrink-0 items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 py-px text-[0.75rem] font-medium leading-[1.35] tracking-[0.01em]';

/** A static label (tag, platform, tier). Never a colour carrier: use variant + words. */
export function Chip({
  variant = 'outline',
  className,
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { variant?: ChipVariant; children: ReactNode }) {
  return (
    <span className={cn(CHIP_BASE, CHIP_VARIANT[variant], className)} {...props}>
      {children}
    </span>
  );
}

/** Alias: a tag is a chip. */
export const Tag = Chip;

/**
 * A toggle chip for filters ("failing 3"). Selected = inverted block, with
 * `aria-pressed`; the count is tabular and formatted (`Intl.NumberFormat`).
 */
export const FilterChip = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { selected: boolean; count?: number | null; children: ReactNode }
>(function FilterChip({ selected, count, className, children, type, ...props }, ref) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      aria-pressed={selected}
      className={cn(
        'inline-flex min-h-[2rem] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border px-2.5 text-[0.8125rem] font-medium coarse:min-h-[2.75rem]',
        'transition-transform duration-[120ms] ease-out active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg',
        selected
          ? 'border-inverse bg-inverse text-inverse-fg'
          : 'border-line text-fg-2 hover:border-line-strong hover:text-fg',
        className,
      )}
      {...props}
    >
      <span>{children}</span>
      {count !== undefined && count !== null ? (
        <span className={cn('tabular-nums', selected ? 'text-inverse-fg/70' : 'text-fg-3')}>{formatCount(count)}</span>
      ) : null}
    </button>
  );
});

export default Chip;
