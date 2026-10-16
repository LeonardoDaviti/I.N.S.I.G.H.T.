import { cn } from '../../lib/utils';
import { DIR_ARROWS, DIR_WORDS, SORT_BY_LABELS, type SortBy, type SortDir } from './sourceList';

/**
 * One sortable column: the column headers and the narrow-screen sort choices
 * are both these. The active one is pressed, carries the arrow and says its
 * direction; pressing it again reverses (nextSort).
 */
export default function SortButton({
  column,
  sort,
  dir,
  onSort,
  className,
}: {
  column: SortBy;
  sort: SortBy;
  dir: SortDir;
  onSort: (column: SortBy) => void;
  className?: string;
}) {
  const active = column === sort;
  const label = SORT_BY_LABELS[column];
  return (
    <button
      type="button"
      onClick={() => onSort(column)}
      aria-pressed={active}
      aria-label={active ? `Sort by ${label}, ${DIR_WORDS[dir]}` : `Sort by ${label}`}
      className={cn(
        'inline-flex items-center gap-0.5 whitespace-nowrap rounded-sm hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg',
        active && 'font-medium text-fg',
        className,
      )}
    >
      {label}
      {active ? <span aria-hidden="true">{DIR_ARROWS[dir]}</span> : null}
    </button>
  );
}
