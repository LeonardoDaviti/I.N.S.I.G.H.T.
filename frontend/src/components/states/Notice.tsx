import type { ReactNode } from 'react';
import { FOCUS_RING, PRESS_FEEDBACK } from './press';

/** The four feedback kinds of spec F.7: status (a run in progress), completion
 *  (a run report), warning (backoff, kind unavailable) and error. */
export type NoticeTone = 'status' | 'completion' | 'warning' | 'error';

const TONE_CLASS: Record<NoticeTone, string> = {
  status: 'border-[var(--background-modifier-border)] bg-[var(--background-secondary)]',
  completion: 'border-[var(--accent-main)] bg-[var(--accent-soft)]',
  warning: 'border-[var(--background-modifier-border)] bg-[var(--text-highlight-bg)]',
  error: 'border-[var(--text-error)] bg-[var(--background-primary)]',
};

/** One consistent inline notice. Status and completion are polite announcements
 *  (`role="status"`); warning and error interrupt (`role="alert"`). */
export default function Notice({
  tone,
  title,
  message,
  action,
  children,
  className = '',
}: {
  tone: NoticeTone;
  title: ReactNode;
  message?: ReactNode;
  action?: { label: string; onClick: () => void };
  children?: ReactNode;
  className?: string;
}) {
  const role = tone === 'warning' || tone === 'error' ? 'alert' : 'status';
  return (
    <div
      role={role}
      data-tone={tone}
      className={`flex flex-wrap items-start justify-between gap-3 rounded-xl border px-4 py-3 text-sm ${TONE_CLASS[tone]} ${className}`}
    >
      <div className="min-w-0 flex-1">
        <p className="break-words font-medium text-[var(--text-normal)]">{title}</p>
        {message ? (
          <div className={`mt-1 break-words ${tone === 'error' ? 'text-[var(--text-error)]' : 'text-[var(--text-muted)]'}`}>
            {message}
          </div>
        ) : null}
        {children}
      </div>
      {action ? (
        <button
          type="button"
          onClick={action.onClick}
          className={`inline-flex min-h-[44px] items-center rounded-lg border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-3 font-medium text-[var(--text-normal)] hover:bg-[var(--background-secondary-alt)] ${PRESS_FEEDBACK} ${FOCUS_RING}`}
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
