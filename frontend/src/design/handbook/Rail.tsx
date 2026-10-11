import { Link, useLocation, useNavigate } from 'react-router-dom';
import { cn } from '../../lib/utils';
import { Select } from '../../components/ui/Input';
import type { RailGroup, RailItem } from '../studio';

const FOCUS_RING = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg';

/** A place is current on its own URL; a parent is open while one of its children is. */
function isWithin(pathname: string, item: RailItem): boolean {
  return pathname === item.href || (item.children ?? []).some((child) => child.href === pathname);
}

function RailLink({ item, pathname, nested = false }: { item: RailItem; pathname: string; nested?: boolean }) {
  const current = pathname === item.href;
  return (
    <Link
      to={item.href}
      aria-current={current ? 'page' : undefined}
      className={cn(
        'flex items-center rounded-md border px-2.5 coarse:min-h-[2.75rem]',
        nested ? 'ml-3 min-h-[1.875rem] text-[0.8125rem]' : 'min-h-[2.125rem] text-[0.875rem]',
        current
          ? 'border-line-strong bg-surface font-semibold text-fg'
          : isWithin(pathname, item)
            ? 'border-transparent font-semibold text-fg hover:bg-raised'
            : 'border-transparent text-fg-2 hover:bg-raised hover:text-fg',
        FOCUS_RING,
      )}
    >
      <span className="min-w-0 truncate">{item.label}</span>
    </Link>
  );
}

/**
 * The Handbook rail, like the reader's: lowercase group words in the third
 * tone, places as quiet rows, the current one a surface row in weight 600.
 * System and Components open their children while you are inside them.
 */
export function Rail({ groups }: { groups: readonly RailGroup[] }) {
  const { pathname } = useLocation();
  return (
    <nav aria-label="Design studio" className="pb-8">
      {groups.map((group) => (
        <section key={group.label} aria-labelledby={`rail-${group.label}`}>
          <h2 id={`rail-${group.label}`} className="px-2.5 pb-1.5 pt-6 text-[0.8125rem] lowercase text-fg-3 first:pt-0">
            {group.label}
          </h2>
          {group.items.length === 0 ? (
            <p className="px-2.5 text-[0.8125rem] text-fg-3">none open</p>
          ) : (
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.href}>
                  <RailLink item={item} pathname={pathname} />
                  {item.children?.length && isWithin(pathname, item) ? (
                    <ul className="mt-0.5 space-y-0.5">
                      {item.children.map((child) => (
                        <li key={child.href}>
                          <RailLink item={child} pathname={pathname} nested />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </nav>
  );
}

/** Below the md breakpoint the rail folds into one native picker (mobile pickers for free). */
export function RailPicker({ groups }: { groups: readonly RailGroup[] }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  return (
    <Select aria-label="Go to a studio page" value={pathname} onChange={(event) => navigate(event.target.value)} className="w-full">
      {groups.map((group) => (
        <optgroup key={group.label} label={group.label}>
          {group.items.flatMap((item) => [item, ...(item.children ?? []).map((child) => ({ ...child, label: `  ${child.label}` }))]).map((item) => (
            <option key={item.href} value={item.href}>{item.label}</option>
          ))}
        </optgroup>
      ))}
    </Select>
  );
}
