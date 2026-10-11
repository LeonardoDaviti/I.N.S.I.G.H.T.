import { useLayoutEffect, useRef, useState } from 'react';

import { frameUrl, prototypeFrameUrl, type FrameTheme } from './frameUrl';
import type { FrameData } from './transport';

export interface FrameProps {
  /** A page doc's name: `reader`, `post`, `sources`, `shell`. */
  page: string;
  /** A prototype's folder name (D6): the frame shows it, on the page's fixtures for `state`. */
  prototype?: string;
  /** One of the page's states (design/fixtures/scenarios.ts). */
  state: string;
  /** The viewport width the page renders at, in CSS px (1400 desktop, 390 phone). */
  width?: number;
  /** The viewport height; 900 from 768px wide, 844 below. */
  height?: number;
  theme?: FrameTheme;
  /** Fixtures (default) or the real API, read-only. */
  data?: FrameData;
  /** Clicks, keys and scrolling reach the page (the Wall's walk); otherwise the frame is a picture. */
  interactive?: boolean;
  /** The iframe's accessible name; defaults to page · state · width · theme. */
  title?: string;
  className?: string;
}

/**
 * A specimen (Design Studio D4): the real page in an iframe at a real viewport
 * width, so breakpoints and `100dvh` behave as on a device, scaled down to fit
 * its box (never up). The iframe loads lazily, so a wall of frames only renders
 * what is on screen. Its box takes the scaled height, so frames stack cleanly.
 */
export default function Frame({
  page, prototype, state, width = 1400, height, theme = 'dark', data = 'fixtures', interactive = false, title, className,
}: FrameProps) {
  const box = useRef<HTMLDivElement>(null);
  const [boxWidth, setBoxWidth] = useState<number | null>(null);
  const viewportHeight = height ?? (width >= 768 ? 900 : 844);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return undefined;
    if (element.clientWidth) setBoxWidth(element.clientWidth);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => setBoxWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const scale = boxWidth ? Math.min(1, boxWidth / width) : 1;

  return (
    <div
      ref={box}
      className={className}
      style={{ position: 'relative', width: '100%', maxWidth: width, height: viewportHeight * scale, overflow: 'hidden' }}
    >
      <iframe
        src={prototype ? prototypeFrameUrl(prototype, state, { theme, data }) : frameUrl(page, state, { theme, data })}
        title={title ?? `${prototype ?? page} · ${state} · ${width}px · ${theme}`}
        loading="lazy"
        tabIndex={interactive ? undefined : -1}
        style={{
          width,
          height: viewportHeight,
          border: 0,
          transform: `scale(${scale})`,
          transformOrigin: '0 0',
          pointerEvents: interactive ? 'auto' : 'none',
          display: 'block',
        }}
      />
    </div>
  );
}
