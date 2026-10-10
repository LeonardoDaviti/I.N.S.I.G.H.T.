import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { STATUS_LABEL, type Status } from './styles';

/**
 * Status without colour (design doc §8). Every state is a shape plus a word; the
 * worst state (`failing`) is an inverted block so it is the loudest thing on the
 * screen without red. Glyphs are inline SVG so they never depend on a font.
 */
const R = 4.25; // ring radius in a 10×10 box, inside a 1.5 stroke

function Glyph({ status }: { status: Status }): ReactNode {
  switch (status) {
    case 'ok':
    case 'unread':
      return <circle cx="5" cy="5" r={status === 'unread' ? 3.25 : R + 0.75} fill="currentColor" />;
    case 'read':
    case 'scheduled':
      return <circle cx="5" cy="5" r={R} fill="none" stroke="currentColor" strokeWidth="1.5" />;
    case 'due':
    case 'running':
      return (
        <>
          <circle cx="5" cy="5" r={R} fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d={`M5 ${5 - R} A${R} ${R} 0 0 1 5 ${5 + R} Z`} fill="currentColor" />
        </>
      );
    case 'backoff':
      return <circle cx="5" cy="5" r={R} fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 1.6" />;
    case 'failing':
      return <path d="M2.5 2.5 L7.5 7.5 M7.5 2.5 L2.5 7.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />;
    case 'unavailable':
      return (
        <>
          <circle cx="5" cy="5" r={R} fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M2 8 L8 2" stroke="currentColor" strokeWidth="1.5" />
        </>
      );
    case 'disabled':
      return <path d="M2 5 H8" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />;
    case 'starred':
      return (
        <path
          d="M5 0.6 L6.3 3.6 L9.5 3.9 L7.1 6.05 L7.8 9.2 L5 7.55 L2.2 9.2 L2.9 6.05 L0.5 3.9 L3.7 3.6 Z"
          fill="currentColor"
        />
      );
  }
}

const TONE: Record<Status, string> = {
  ok: 'text-fg-2',
  due: 'text-fg font-semibold',
  scheduled: 'text-fg-3',
  backoff: 'text-fg border border-dashed border-line-strong rounded-sm px-1.5',
  failing: 'bg-inverse text-inverse-fg font-semibold rounded-sm px-1.5',
  unavailable: 'text-fg-2 border border-line-strong rounded-sm px-1.5',
  disabled: 'text-fg-3',
  running: 'text-fg',
  unread: 'text-fg',
  read: 'text-fg-3',
  starred: 'text-fg',
};

/**
 * Without a visible word the chips shrink to the glyph, but `failing` keeps its
 * inverted square: it stays the loudest thing in a dense row, not a twin of `ok`.
 */
const GLYPH_ONLY_TONE: Record<Status, string> = {
  ...TONE,
  backoff: 'text-fg',
  failing: 'bg-inverse text-inverse-fg rounded-sm p-[0.1875rem]',
  unavailable: 'text-fg-2',
};

/** The bare glyph, decorative (`aria-hidden`). Pair it with a word. */
export function StatusIcon({ status, className }: { status: Status; className?: string }) {
  return (
    <svg
      viewBox="0 0 10 10"
      aria-hidden="true"
      focusable="false"
      data-glyph={status}
      className={cn('h-[0.625rem] w-[0.625rem] shrink-0', className)}
    >
      <Glyph status={status} />
    </svg>
  );
}

/**
 * Glyph + label. `hideLabel` keeps the word for screen readers only (for dense
 * rows where the column header already names it). `label` overrides the word
 * ("overdue 3d", "backoff · retry 14:20").
 */
export default function StatusGlyph({
  status,
  label,
  hideLabel = false,
  className,
}: {
  status: Status;
  label?: string;
  hideLabel?: boolean;
  className?: string;
}) {
  const text = label ?? STATUS_LABEL[status];
  return (
    <span
      data-status={status}
      className={cn(
        'inline-flex max-w-full shrink-0 items-center gap-1.5 whitespace-nowrap text-[0.8125rem] leading-[1.45]',
        hideLabel ? GLYPH_ONLY_TONE[status] : TONE[status],
        className,
      )}
    >
      <StatusIcon status={status} />
      <span className={hideLabel ? 'sr-only' : undefined}>{text}</span>
    </span>
  );
}
