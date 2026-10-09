import { Fragment } from 'react';

import { FOCUS_RING } from '../states';

/**
 * A radio group drawn in the top bar's language: lowercase words separated by
 * slashes, the current one bold and underlined. No pills, no fills. Each word is
 * a 36px target (44px on touch), padded so the slash gaps do not shrink it.
 */
export default function SlashChoice<T extends string>({ label, value, options, onChange, className = '' }: {
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={`inline-flex shrink-0 items-center gap-0.5 text-[0.875rem] ${className}`}>
      {options.map((option, index) => {
        const active = option.value === value;
        return (
          <Fragment key={option.value}>
            {index > 0 ? <span aria-hidden="true" className="select-none text-fg-3">/</span> : null}
            <button
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(option.value)}
              className={`inline-flex min-h-[2.25rem] items-center whitespace-nowrap rounded-sm px-1 lowercase underline decoration-1 underline-offset-[0.22em] coarse:min-h-[2.75rem] ${active ? 'font-semibold text-fg decoration-fg' : 'text-fg-2 decoration-transparent hover:text-fg hover:decoration-fg-3'} ${FOCUS_RING}`}
            >
              {option.label}
            </button>
          </Fragment>
        );
      })}
    </div>
  );
}
