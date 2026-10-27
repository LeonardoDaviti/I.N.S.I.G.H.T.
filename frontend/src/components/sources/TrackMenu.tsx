import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Check, Minus, MoreHorizontal } from 'lucide-react';
import { Button } from '../ui';

const ITEM =
  'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left outline-none hover:bg-inverse hover:text-inverse-fg '
  + 'focus-visible:bg-inverse focus-visible:text-inverse-fg coarse:py-2.5';

/**
 * The ⋯ menu beside a track title: rare actions live here, off the scanning
 * path (rename, the main-digest switch, delete; on a phone also fetch now). A small hand-rolled menu
 * (button + role="menu"): arrows and Home/End move, Escape, outside click and
 * Tab close it, focus moves into it on open and back to ⋯ on close.
 */
export default function TrackMenu({
  name,
  inMainDigest,
  onFetch,
  onRename,
  onMainDigest,
  onDelete,
}: {
  name: string;
  /** From the track's sources: all in, none, or mixed (a press puts them all in); null while unknown: the item is disabled. */
  inMainDigest: boolean | 'mixed' | null;
  /** Phones only: the header has no room for its own fetch button there. */
  onFetch?: () => void;
  onRename: () => void;
  onMainDigest: (on: boolean) => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  // Items hidden at this width (display: none) have no layout box and are skipped.
  const visibleItems = () => [...(rootRef.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not([disabled])') ?? [])]
    .filter((item) => getComputedStyle(item).display !== 'none');

  useEffect(() => {
    if (!open) return undefined;
    visibleItems()[0]?.focus();
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  };
  const pick = (action: () => void) => () => { close(true); action(); };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); close(true); return; }
    if (event.key === 'Tab') { close(false); return; }
    const items = visibleItems();
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 }[event.key];
    if (next === undefined || !items.length) return;
    event.preventDefault();
    items[(next + items.length) % items.length].focus();
  };

  return (
    <div ref={rootRef} className="relative">
      <Button
        ref={triggerRef}
        variant="ghost"
        size="icon"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`More actions for track ${name}`}
        title="More"
        onClick={() => setOpen((value) => !value)}
      >
        <MoreHorizontal aria-hidden="true" />
      </Button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          aria-label={`Track ${name}`}
          onKeyDown={onKeyDown}
          className="absolute right-0 origin-top-right motion-safe:animate-[pop-in_150ms_cubic-bezier(0.23,1,0.32,1)] top-full z-30 mt-1 min-w-[13.5rem] rounded-md border border-line-strong bg-raised p-1 text-[0.8125rem] text-fg shadow-overlay"
        >
          {onFetch ? (
            <button type="button" role="menuitem" onClick={pick(onFetch)} className={`${ITEM} sm:hidden`}>
              <span aria-hidden="true" className="w-3" />
              Fetch now
            </button>
          ) : null}
          <button type="button" role="menuitem" onClick={pick(onRename)} className={ITEM}>
            <span aria-hidden="true" className="w-3" />
            Rename…
          </button>
          <button
            type="button"
            role="menuitemcheckbox"
            aria-checked={inMainDigest ?? false}
            disabled={inMainDigest === null}
            onClick={pick(() => onMainDigest(inMainDigest !== true))}
            className={`${ITEM} disabled:text-fg-3`}
          >
            <span aria-hidden="true" className="inline-flex w-3 justify-center">
              {inMainDigest === 'mixed' ? <Minus className="h-3.5 w-3.5" /> : inMainDigest ? <Check className="h-3.5 w-3.5" /> : null}
            </span>
            In main feed and digest
          </button>
          <div role="separator" className="my-1 h-px bg-line" />
          <button type="button" role="menuitem" onClick={pick(onDelete)} className={`${ITEM} font-medium`}>
            <span aria-hidden="true" className="w-3 text-center font-semibold">×</span>
            Delete track…
          </button>
        </div>
      ) : null}
    </div>
  );
}
