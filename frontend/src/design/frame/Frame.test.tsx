import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';

import Frame from './Frame';

/** A ResizeObserver the test drives: `resize(width)` reports a new box width. */
function stubResizeObserver() {
  let callback: ResizeObserverCallback = () => {};
  vi.stubGlobal('ResizeObserver', class {
    constructor(cb: ResizeObserverCallback) { callback = cb; }
    observe() {}
    disconnect() {}
    unobserve() {}
  });
  return (width: number) => act(() => {
    callback([{ contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver);
  });
}

afterEach(() => vi.unstubAllGlobals());

describe('<Frame>', () => {
  it('is a lazy iframe of the frame route for its page, state, theme and data, inert unless interactive', () => {
    stubResizeObserver();
    const { rerender } = render(<Frame page="reader" state="worst" theme="light" data="live" width={390} />);
    const frame = screen.getByTitle('reader · worst · 390px · light');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute('src', '/design/frame/reader/worst?theme=light&data=live');
    expect(frame).toHaveAttribute('loading', 'lazy');
    expect(frame).toHaveAttribute('tabindex', '-1');
    expect(frame.style.pointerEvents).toBe('none');

    rerender(<Frame page="reader" state="worst" theme="light" data="live" width={390} interactive />);
    expect(frame.style.pointerEvents).toBe('auto');
    expect(frame).not.toHaveAttribute('tabindex');
  });

  it('shows a prototype on its page\'s state when given one (D6)', () => {
    stubResizeObserver();
    render(<Frame page="post" prototype="2026-10-10-title-wrap" state="long-title" />);
    expect(screen.getByTitle('2026-10-10-title-wrap · long-title · 1400px · dark'))
      .toHaveAttribute('src', '/design/frame/prototype/2026-10-10-title-wrap/long-title?theme=dark&data=fixtures');
  });

  it('keeps a real viewport width and scales it down to fit its box', () => {
    const resize = stubResizeObserver();
    render(<Frame page="sources" state="dense" width={1400} height={900} />);
    const frame = screen.getByTitle(/sources · dense/);
    expect(frame.style.width).toBe('1400px');
    expect(frame.style.height).toBe('900px');

    resize(700);
    expect(frame.style.transform).toBe('scale(0.5)');
    expect(frame.parentElement!.style.height).toBe('450px');

    resize(2000);
    expect(frame.style.transform).toBe('scale(1)');
    expect(frame.parentElement!.style.height).toBe('900px');
  });
});
