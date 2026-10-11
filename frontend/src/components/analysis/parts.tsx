import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { StatusIcon } from '../ui/StatusGlyph';
import type { Status } from '../ui/styles';

/**
 * Local building blocks for the analysis pages (Stories, Inbox, Tracks), built on
 * the Mark IX tokens (design docs system/tokens.md, system/components.md). The foundation has `Row` for
 * navigating rows; these pages also need a *selectable* row (master/detail), a
 * quiet section heading and a key/value list, so they live here.
 */

/** A section: a `heading`-step title, an optional meta word, actions on the right. */
export function Section({
  title,
  meta,
  actions,
  children,
  className,
  id,
}: {
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section aria-labelledby={headingId} id={id} className={cn('min-w-0', className)}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h2 id={headingId} className="min-w-0 break-words text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">
          {title}
          {meta !== undefined && meta !== null ? (
            <span className="ml-2 text-[0.8125rem] font-normal tabular-nums tracking-normal text-fg-3">{meta}</span>
          ) : null}
        </h2>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

/**
 * A selectable list row for master/detail views: muted meta column, bold title
 * (wraps, clamps at 2 lines), a secondary line. Selected = strong border + raised
 * fill + `aria-current`. No hover animation (used constantly, emil).
 */
export function SelectRow({
  selected,
  onSelect,
  meta,
  title,
  description,
  footer,
  className,
}: {
  selected: boolean;
  onSelect: () => void;
  meta?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
      className={cn(
        'flex w-full min-w-0 items-start gap-4 rounded-md border px-4 py-3 text-left',
        'transition-transform duration-[120ms] ease-out active:scale-[0.995] motion-reduce:transition-none motion-reduce:active:scale-100',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg',
        selected ? 'border-fg bg-raised' : 'border-line bg-bg hover:border-line-strong hover:bg-surface',
        className,
      )}
    >
      {meta !== undefined ? (
        <span className="w-[5.5rem] shrink-0 whitespace-nowrap pt-px text-[0.8125rem] tabular-nums text-fg-3">{meta}</span>
      ) : null}
      <span className="block min-w-0 flex-1">
        <span dir="auto" className="line-clamp-2 break-words font-semibold text-fg [overflow-wrap:anywhere]">{title}</span>
        {description ? (
          <span className="mt-0.5 line-clamp-2 break-words text-[0.8125rem] text-fg-2 [overflow-wrap:anywhere]">{description}</span>
        ) : null}
        {footer ? <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.75rem] tabular-nums text-fg-3">{footer}</span> : null}
      </span>
    </button>
  );
}

/** A key/value list in hairline rows: keys in `text-3`, values in `text`, numbers tabular. */
export function MetaList({ items, className }: { items: Array<[string, ReactNode]>; className?: string }) {
  return (
    <dl className={cn('divide-y divide-line rounded-md border border-line text-[0.8125rem]', className)}>
      {items.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-3 px-3 py-2">
          <dt className="text-fg-3">{key}</dt>
          <dd className="min-w-0 break-words tabular-nums text-fg [overflow-wrap:anywhere]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Glyph + word, for vocabularies that are not source health (story status, inbox status). */
export function StateWord({ glyph, word, strong = false }: { glyph: Status; word: string; strong?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap', strong ? 'font-medium text-fg' : 'text-fg-2')}>
      <StatusIcon status={glyph} />
      {word}
    </span>
  );
}
