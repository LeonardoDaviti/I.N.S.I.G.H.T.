import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';

import { fitView, zoomAt, type Rect, type Size, type View } from './layout';

/** jsdom and a box not laid out yet have no size; plan for a laptop screen. */
const FALLBACK: Size = { width: 1440, height: 800 };
/** A press that moves less than this is a click, not a drag. */
const DRAG_SLOP = 3;
/** Buttons and keys move the view with one short ease-out; gestures track 1:1. */
const EASE = 'transform 240ms cubic-bezier(0.23, 1, 0.32, 1)';
/** The view settles into React state (zoom %, which frames mount) once a gesture rests. */
const SETTLE_MS = 90;

/** A pinch sends small deltas, a mouse wheel ±100 a notch: about 1.35× a notch, smooth for a pinch. */
const wheelZoom = (deltaY: number) => Math.exp(-Math.max(-50, Math.min(50, deltaY)) * 0.006);

const prefersReducedMotion = () => typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function sizeOf(element: HTMLElement | null): Size {
  return element && element.clientWidth && element.clientHeight
    ? { width: element.clientWidth, height: element.clientHeight }
    : FALLBACK;
}

/**
 * Pan and zoom for the Wall: drag anywhere to pan, scroll to pan, pinch or
 * ⌘/ctrl-scroll to zoom about the pointer. Every move writes one `transform`
 * on the world element directly, so a gesture never re-renders React (60fps,
 * transform only); the view reaches React state once it rests. Until you move
 * it, the view keeps the whole wall fitted to the viewport as it resizes.
 */
export function usePanZoom(bounds: Rect) {
  const viewport = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);
  const view = useRef<View>(fitView(bounds, FALLBACK));
  const fitted = useRef(true);
  const [settled, setSettled] = useState<{ view: View; size: Size }>(() => ({ view: view.current, size: FALLBACK }));
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const apply = useCallback((next: View, animate: boolean) => {
    view.current = next;
    const element = world.current;
    if (element) {
      element.style.transition = animate && !prefersReducedMotion() ? EASE : 'none';
      element.style.transform = `translate3d(${next.x}px, ${next.y}px, 0) scale(${next.scale})`;
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setSettled({ view: next, size: sizeOf(viewport.current) }), animate ? 0 : SETTLE_MS);
  }, []);

  const fit = useCallback((animate = true) => {
    fitted.current = true;
    apply(fitView(bounds, sizeOf(viewport.current)), animate);
  }, [apply, bounds]);

  const zoomBy = useCallback((factor: number) => {
    fitted.current = false;
    const size = sizeOf(viewport.current);
    apply(zoomAt(view.current, { x: size.width / 2, y: size.height / 2 }, factor), true);
  }, [apply]);

  // Fit now and whenever the viewport resizes (the walk panel opens), until moved.
  useLayoutEffect(() => {
    fit(false);
    const element = viewport.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => {
      if (fitted.current) fit(false);
      else setSettled({ view: view.current, size: sizeOf(element) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [fit]);

  useEffect(() => () => clearTimeout(timer.current), []);

  // Wheel and pinch: a native listener, so the page itself does not scroll or zoom.
  useEffect(() => {
    const element = viewport.current;
    if (!element) return undefined;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      fitted.current = false;
      const current = view.current;
      if (event.ctrlKey || event.metaKey) {
        const box = element.getBoundingClientRect();
        apply(zoomAt(current, { x: event.clientX - box.left, y: event.clientY - box.top }, wheelZoom(event.deltaY)), false);
      } else {
        apply({ ...current, x: current.x - event.deltaX, y: current.y - event.deltaY }, false);
      }
    };
    element.addEventListener('wheel', onWheel, { passive: false });
    return () => element.removeEventListener('wheel', onWheel);
  }, [apply]);

  const drag = useRef<{ id: number; x: number; y: number; from: View; moved: boolean } | null>(null);
  const [dragging, setDragging] = useState(false);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as Element).closest('a, button')) return;
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, from: view.current, moved: false };
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current || current.id !== event.pointerId) return;
    const dx = event.clientX - current.x;
    const dy = event.clientY - current.y;
    if (!current.moved) {
      if (Math.hypot(dx, dy) < DRAG_SLOP) return;
      current.moved = true;
      fitted.current = false;
      event.currentTarget.setPointerCapture?.(event.pointerId);
      setDragging(true);
    }
    apply({ ...current.from, x: current.from.x + dx, y: current.from.y + dy }, false);
  };
  const onPointerEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (drag.current?.id !== event.pointerId) return;
    drag.current = null;
    setDragging(false);
  };

  return {
    viewport,
    world,
    settled,
    dragging,
    fit,
    zoomBy,
    handlers: { onPointerDown, onPointerMove, onPointerUp: onPointerEnd, onPointerCancel: onPointerEnd },
  };
}
