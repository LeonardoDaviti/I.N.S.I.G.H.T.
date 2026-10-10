import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { Slot } from '@radix-ui/react-slot';
import type { VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/utils';
import { buttonVariants } from './styles';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  /** Render the child element (a router <Link>, an <a>) with button styling. */
  asChild?: boolean;
}

/**
 * The one button: see `buttonVariants` in ./styles for the variants. A `danger`
 * button leads with the monochrome destructive mark "×" (as ConfirmDialog's
 * title does), so every destructive confirmation reads the same.
 */
const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild = false, type, children, ...props },
  ref,
) {
  const className_ = cn(buttonVariants({ variant, size }), className);
  if (asChild) {
    return <Slot ref={ref} className={className_} {...props}>{children}</Slot>;
  }
  return (
    <button ref={ref} className={className_} type={type ?? 'button'} {...props}>
      {variant === 'danger' ? <span aria-hidden="true" data-danger-mark>×</span> : null}
      {children}
    </button>
  );
});

export default Button;
