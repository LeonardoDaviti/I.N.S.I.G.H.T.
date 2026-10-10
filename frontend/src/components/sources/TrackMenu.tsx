import { useEffect, useId, useRef, useState } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { Button } from '../ui';

/**
 * The ⋯ menu beside a track title: rare, destructive actions live here, off the
 * scanning path. A small hand-rolled menu (button + role="menu"): Escape, outside
 * click and Tab close it, focus moves into it on open and back to ⋯ on close.
 */
export default function TrackMenu({ name, onDelete }: { name: string; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return undefined;
    rootRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
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
          onKeyDown={(event) => {
            if (event.key === 'Escape') { event.preventDefault(); close(true); }
            if (event.key === 'Tab') close(false);
          }}
          className="absolute right-0 origin-top-right motion-safe:animate-[pop-in_150ms_cubic-bezier(0.23,1,0.32,1)] top-full z-30 mt-1 min-w-[11rem] rounded-md border border-line-strong bg-raised p-1 text-[0.8125rem] text-fg shadow-overlay"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => { close(true); onDelete(); }}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left outline-none hover:bg-inverse hover:text-inverse-fg focus-visible:bg-inverse focus-visible:text-inverse-fg coarse:py-2.5"
          >
            <span aria-hidden="true" className="w-3 text-center font-semibold">×</span>
            Delete track…
          </button>
        </div>
      ) : null}
    </div>
  );
}
