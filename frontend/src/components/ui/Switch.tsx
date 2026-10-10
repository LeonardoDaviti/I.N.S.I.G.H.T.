import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

export interface SwitchProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onChange' | 'role' | 'aria-checked'> {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

/**
 * The one on/off switch (design doc §11): an inverted pill when on, a hairline
 * when off, never a hue. One size everywhere; on touch the hit area grows to
 * 44px without moving the layout. The knob moves in 120ms (an occasional,
 * deliberate act) and not at all under reduced motion. Name it with
 * `aria-label` or `aria-labelledby` (or a `<label htmlFor>`).
 */
const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  { checked, onCheckedChange, className, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-[120ms] motion-reduce:transition-none',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg disabled:opacity-40',
        "coarse:before:absolute coarse:before:-inset-3 coarse:before:content-['']",
        checked ? 'border-inverse bg-inverse' : 'border-line-strong bg-transparent',
        className,
      )}
      {...props}
    >
      <span
        aria-hidden="true"
        className={cn(
          'absolute h-3.5 w-3.5 rounded-full transition-transform duration-[120ms] ease-out motion-reduce:transition-none',
          checked ? 'translate-x-[1.125rem] bg-inverse-fg' : 'translate-x-[0.1875rem] bg-fg-3',
        )}
      />
    </button>
  );
});

export default Switch;
