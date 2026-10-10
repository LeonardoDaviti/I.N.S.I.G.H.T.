import type { ReactNode } from 'react';
import Button from '../ui/Button';

export interface EmptyStateAction {
  label: string;
  onClick?: () => void;
  /** Render the action as a link instead of a button. */
  href?: string;
  disabled?: boolean;
  /** A plain text link instead of the inverted button (a pointer elsewhere, not the next step). */
  quiet?: boolean;
}

/** A load that succeeded with nothing to show: copy plus one action ("Show all",
 *  "Add a source", or a quiet link to Sources), Mark IX §F.6. Quiet: a hairline
 *  box, a short headline, the action as the one inverted button or a text link. */
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
  return (
    <div className={`rounded-md border border-line px-6 py-12 text-center ${className}`}>
      <p className="break-words text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">{title}</p>
      {description ? <div className="mx-auto mt-1.5 max-w-prose text-[0.875rem] text-fg-2">{description}</div> : null}
      {action ? (
        <div className="mt-5">
          {action.href && action.quiet ? (
            <a href={action.href} className="text-[0.875rem] text-fg-2 underline decoration-line-strong underline-offset-4 hover:text-fg">
              {action.label}
            </a>
          ) : action.href ? (
            <Button asChild variant="primary">
              <a href={action.href}>{action.label}</a>
            </Button>
          ) : (
            <Button variant="primary" onClick={action.onClick} disabled={action.disabled}>
              {action.label}
            </Button>
          )}
        </div>
      ) : null}
      {children}
    </div>
  );
}
