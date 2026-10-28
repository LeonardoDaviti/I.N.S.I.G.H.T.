import { lazy, Suspense, useEffect, useId, useRef, useState } from 'react';
import { Button } from '../ui';

const ReadingSettingsPanel = lazy(() => import('./ReadingSettingsPanel'));

/**
 * The Aa control in the post page's navigation band (issue 0045): a small popover
 * with the reading settings, over the text it changes, so each choice previews on
 * the post itself. Not modal: Escape, a click outside or focus leaving closes it,
 * and focus returns to Aa. The panel's code loads on first open.
 */
export default function ReadingSettingsButton() {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return undefined;
    popoverRef.current?.focus();
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (popoverRef.current?.contains(target) || buttonRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  return (
    <div className="relative shrink-0">
      <Button
        ref={buttonRef}
        variant="ghost"
        size="sm"
        aria-label="Reading settings"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        title="Reading settings: font, size, width"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && open) {
            event.preventDefault();
            close(false);
          }
        }}
        className="px-2 font-semibold tracking-[-0.01em]"
      >
        <span aria-hidden="true">Aa</span>
      </Button>
      {open ? (
        <div
          ref={popoverRef}
          id={panelId}
          role="dialog"
          aria-label="Reading settings"
          tabIndex={-1}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            close(true);
          }}
          onBlur={(event) => {
            const next = event.relatedTarget as Node | null;
            if (next && !popoverRef.current?.contains(next) && !buttonRef.current?.contains(next)) setOpen(false);
          }}
          className="absolute right-0 top-full z-40 mt-1 w-[min(19rem,calc(100vw-2rem))] rounded-lg border border-line-strong bg-raised px-4 py-3 text-fg shadow-overlay focus:outline-none"
        >
          <Suspense fallback={<p className="text-[0.8125rem] text-fg-3">Loading…</p>}>
            <ReadingSettingsPanel />
          </Suspense>
        </div>
      ) : null}
    </div>
  );
}
