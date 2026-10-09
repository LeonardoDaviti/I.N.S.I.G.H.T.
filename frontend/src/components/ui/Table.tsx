import { forwardRef, type HTMLAttributes, type TdHTMLAttributes, type ThHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

/**
 * A data table: 1px hairlines, small text, tabular numbers, no zebra and no
 * coloured header (design doc §11). Wrap it in `TableFrame` for the bordered,
 * horizontally scrollable box. `stickyHeader` puts the header on the
 * translucent material just under the top bar.
 */
export function TableFrame({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('w-full overflow-x-auto rounded-md border border-line', className)} {...props} />;
}

export const Table = forwardRef<HTMLTableElement, HTMLAttributes<HTMLTableElement>>(function Table({ className, ...props }, ref) {
  return <table ref={ref} className={cn('w-full border-collapse text-left text-[0.8125rem] tabular-nums', className)} {...props} />;
});

export const THead = forwardRef<HTMLTableSectionElement, HTMLAttributes<HTMLTableSectionElement> & { sticky?: boolean }>(
  function THead({ className, sticky = false, ...props }, ref) {
    return (
      <thead
        ref={ref}
        className={cn(sticky && 'material sticky-under-bar sticky z-10', 'border-b border-line', className)}
        {...props}
      />
    );
  },
);

export const TBody = forwardRef<HTMLTableSectionElement, HTMLAttributes<HTMLTableSectionElement>>(function TBody(
  { className, ...props },
  ref,
) {
  return <tbody ref={ref} className={cn('[&>tr:last-child]:border-b-0', className)} {...props} />;
});

export const Tr = forwardRef<HTMLTableRowElement, HTMLAttributes<HTMLTableRowElement>>(function Tr({ className, ...props }, ref) {
  return <tr ref={ref} className={cn('border-b border-line align-top', className)} {...props} />;
});

export const Th = forwardRef<HTMLTableCellElement, ThHTMLAttributes<HTMLTableCellElement>>(function Th(
  { className, scope = 'col', ...props },
  ref,
) {
  return (
    <th
      ref={ref}
      scope={scope}
      className={cn('whitespace-nowrap px-3 py-2 text-[0.75rem] font-medium tracking-[0.01em] text-fg-3', className)}
      {...props}
    />
  );
});

export const Td = forwardRef<HTMLTableCellElement, TdHTMLAttributes<HTMLTableCellElement>>(function Td({ className, ...props }, ref) {
  return <td ref={ref} className={cn('px-3 py-2.5 text-fg', className)} {...props} />;
});
