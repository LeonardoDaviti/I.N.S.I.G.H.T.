import type { ReactNode } from 'react';
import Button from '../ui/Button';
import { StatusIcon } from '../ui/StatusGlyph';
import type { Status } from '../ui/styles';

/** The four feedback kinds of spec F.7: status (a run in progress), completion
 *  (a run report), warning (backoff, kind unavailable) and error. */
export type NoticeTone = 'status' | 'completion' | 'warning' | 'error';

/** Monochrome: tone is carried by glyph, border style and inversion (design docs system/status.md). */
const TONE: Record<NoticeTone, { box: string; glyph: Status; word: string }> = {
  status: { box: 'border-line', glyph: 'running', word: 'Status' },
  completion: { box: 'border-line-strong', glyph: 'ok', word: 'Done' },
  warning: { box: 'border-dashed border-line-strong', glyph: 'backoff', word: 'Warning' },
  error: { box: 'border-fg', glyph: 'failing', word: 'Error' },
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
  const spec = TONE[tone];
  return (
    <div
      role={role}
      data-tone={tone}
      className={`flex flex-wrap items-start justify-between gap-3 rounded-md border bg-bg px-4 py-3 text-[0.875rem] ${spec.box} ${className}`}
    >
      <span
        className={`mt-[0.2rem] inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-sm ${tone === 'error' ? 'bg-inverse text-inverse-fg' : 'text-fg'}`}
      >
        <StatusIcon status={spec.glyph} className={tone === 'error' ? 'h-2.5 w-2.5' : undefined} />
        <span className="sr-only">{spec.word}:</span>
      </span>
      <div className="min-w-0 flex-1">
        <p className="break-words font-semibold text-fg">{title}</p>
        {message ? <div className="mt-0.5 break-words text-fg-2 [overflow-wrap:anywhere]">{message}</div> : null}
        {children}
      </div>
      {action ? (
        <Button size="sm" variant="secondary" onClick={action.onClick}>
          {action.label}
        </Button>
      ) : null}
    </div>
  );
}
