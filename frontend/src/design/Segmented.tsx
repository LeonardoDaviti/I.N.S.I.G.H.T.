import { useEffect, useRef } from 'react';
import { cn } from '../lib/utils';

/**
 * A segmented control: one choice of a few, as a radio group in a hairline
 * track, the chosen segment the inverted block (P2). The change is instant:
 * it is switched often, and motion on frequent actions is latency (P12). It
 * owns no arrow keys; the studio steps modes with ← → on the whole page, and
 * focus follows the choice when it was inside the group.
 */
export default function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  size = 'md',
  className,
}: {
  label: string;
  value: T;
  options: readonly T[];
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
  className?: string;
}) {
  const group = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = group.current;
    if (!element?.contains(document.activeElement)) return;
    element.querySelector<HTMLElement>('[aria-checked="true"]')?.focus();
  }, [value]);

  return (
    <div
      ref={group}
      role="radiogroup"
      aria-label={label}
      className={cn('inline-flex max-w-full flex-wrap gap-0.5 rounded-md border border-line bg-surface p-0.5', className)}
    >
      {options.map((option) => {
        const checked = option === value;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            onClick={() => onChange(option)}
            className={cn(
              'inline-flex items-center justify-center whitespace-nowrap rounded-[0.3125rem] lowercase',
              'transition-transform duration-[120ms] ease-out active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100',
              'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-fg',
              size === 'sm' ? 'min-h-[1.625rem] px-2 text-[0.75rem] coarse:min-h-[2.75rem]' : 'min-h-[1.875rem] px-3 text-[0.8125rem] coarse:min-h-[2.75rem]',
              checked ? 'bg-inverse font-semibold text-inverse-fg' : 'text-fg-2 hover:bg-raised hover:text-fg',
            )}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}
