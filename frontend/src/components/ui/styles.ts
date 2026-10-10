import { cva } from 'class-variance-authority';
import { cn } from '../../lib/utils';

// Class recipes and vocabularies shared by the primitives (plan/INSIGHT_mark_ix_design.md).
// They live outside the component files so React fast refresh keeps working.

/**
 * The one button. Monochrome (design doc §11): `primary` is the inverted block
 * (one per view), `secondary` an outline, `ghost` text-only, `danger` an
 * inverted block with an inner hairline (and, from <Button/>, a leading "×"),
 * reserved for confirmed destructive actions, so it never passes for the
 * primary action without a hue. Press feedback is
 * instant (`scale(0.97)`, 120ms, transform only); hover only on fine pointers.
 */
export const buttonVariants = cva(
  [
    'inline-flex shrink-0 select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-md border font-medium',
    'transition-[transform,background-color,border-color,color] duration-[120ms] ease-out active:scale-[0.97]',
    'motion-reduce:transition-none motion-reduce:active:scale-100',
    'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg',
    'disabled:pointer-events-none disabled:opacity-40 aria-disabled:pointer-events-none aria-disabled:opacity-40',
    '[&_svg]:h-4 [&_svg]:w-4 [&_svg]:shrink-0',
  ].join(' '),
  {
    variants: {
      variant: {
        primary: 'border-inverse bg-inverse text-inverse-fg hover:bg-inverse/85',
        secondary: 'border-line-strong bg-transparent text-fg hover:bg-raised',
        ghost: 'border-transparent bg-transparent text-fg-2 hover:bg-raised hover:text-fg',
        danger: 'border-inverse bg-inverse text-inverse-fg font-semibold shadow-[inset_0_0_0_2px_rgb(var(--inverse)),inset_0_0_0_3px_rgb(var(--inverse-text))] hover:bg-inverse/85',
      },
      size: {
        sm: 'min-h-[2rem] px-2.5 text-[0.8125rem]',
        md: 'min-h-[2.25rem] px-3.5 text-[0.875rem]',
        lg: 'min-h-[2.75rem] px-4 text-[0.9375rem]',
        icon: 'h-9 w-9 p-0 coarse:h-11 coarse:w-11',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
);

/** For icon-only controls outside <Button/> (e.g. the theme toggle). */
export const iconButtonClass = buttonVariants({ variant: 'ghost', size: 'icon' });

/** Shared field look: surface fill, 1px hairline, focus = stronger border + outline. */
export const fieldClass = cn(
  'w-full min-w-0 rounded-md border border-line bg-surface px-3 text-[0.875rem] text-fg placeholder:text-fg-3',
  'transition-[border-color] duration-[120ms] hover:border-line-strong',
  'focus-visible:border-line-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-fg',
  'disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-fg',
);

/** Lowercase underline tab; also usable on router links with `aria-current="page"`. */
export const tabTriggerClass = cn(
  '-mb-px inline-flex min-h-[2.5rem] shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 border-transparent pb-px text-[0.875rem] lowercase text-fg-2',
  'hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg',
  'data-[state=active]:border-fg data-[state=active]:font-semibold data-[state=active]:text-fg',
  'aria-[current=page]:border-fg aria-[current=page]:font-semibold aria-[current=page]:text-fg',
);

/**
 * Status without colour (design doc §8). Every state is a shape plus a word.
 */
export type Status =
  | 'ok'
  | 'due'
  | 'scheduled'
  | 'backoff'
  | 'failing'
  | 'unavailable'
  | 'disabled'
  | 'running'
  | 'unread'
  | 'read'
  | 'starred';

export const STATUS_LABEL: Record<Status, string> = {
  ok: 'ok',
  due: 'due',
  scheduled: 'scheduled',
  backoff: 'backoff',
  failing: 'failing',
  unavailable: 'unavailable',
  disabled: 'disabled',
  running: 'running',
  unread: 'unread',
  read: 'read',
  starred: 'starred',
};
