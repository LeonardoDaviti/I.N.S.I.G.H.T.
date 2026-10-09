import type { ReactNode } from 'react';
import { FOCUS_RING, PRESS_FEEDBACK } from './press';

export interface EmptyStateAction {
  label: string;
  onClick?: () => void;
  /** Render the action as a link instead of a button. */
  href?: string;
  disabled?: boolean;
}

/** A fetch that succeeded with nothing to show: copy plus one primary action
 *  ("Fetch this track", "Show all", "Add a source"), Mark IX §F.6. */
export default function EmptyState({
  title,
  description,
  action,
  children,
  className = '',
}: {
  title: string;
  description?: ReactNode;
  action?: EmptyStateAction;
  children?: ReactNode;
  className?: string;
}) {
  const actionClass = `inline-flex min-h-[44px] items-center justify-center rounded-lg bg-[var(--interactive-accent)] px-4 text-sm font-medium text-[var(--text-on-accent)] hover:bg-[var(--interactive-accent-hover)] disabled:opacity-50 ${PRESS_FEEDBACK} ${FOCUS_RING}`;
  return (
    <div
      className={`rounded-2xl border border-dashed border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-6 py-10 text-center ${className}`}
    >
      <p className="break-words text-base font-semibold text-[var(--text-normal)]">{title}</p>
      {description ? <div className="mx-auto mt-2 max-w-prose text-sm text-[var(--text-muted)]">{description}</div> : null}
      {action ? (
        <div className="mt-5">
          {action.href ? (
            <a href={action.href} className={actionClass}>
              {action.label}
            </a>
          ) : (
            <button type="button" onClick={action.onClick} disabled={action.disabled} className={actionClass}>
              {action.label}
            </button>
          )}
        </div>
      ) : null}
      {children}
    </div>
  );
}
