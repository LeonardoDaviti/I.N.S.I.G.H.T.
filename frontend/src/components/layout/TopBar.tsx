import { Fragment, useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Command, Menu } from 'lucide-react';
import ThemeToggle from '../ThemeToggle';
import Kbd from '../ui/Kbd';
import { iconButtonClass } from '../ui/styles';
import { cn } from '../../lib/utils';
import { activeNavKey, navItems } from './navigation';
import { useAnalysisEnabled } from '../../hooks/useAnalysis';

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/**
 * The one top bar (design docs system/information-architecture.md): the inverted INSIGHT wordmark on the left,
 * the lowercase slash nav (`feed / sources` reading-only) and the ⌘K switcher on the right. A translucent
 * material over the black page; its hairline appears only once content scrolls
 * beneath it (apple §12: no divider where nothing overlaps).
 */
export default function TopBar({ onOpenSwitcher }: { onOpenSwitcher: () => void }) {
  const { pathname } = useLocation();
  const analysisEnabled = useAnalysisEnabled();
  const current = activeNavKey(pathname, analysisEnabled);
  const [scrolled, setScrolled] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // A 2px sentinel at the top of the document: once it leaves the viewport,
  // content is under the bar. An observer instead of a scroll listener, because
  // reading window.scrollY on every scroll event forced a synchronous layout
  // right after React commits (68ms self time while holding j in the feed).
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver(([entry]) => setScrolled(!entry.isIntersecting));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <>
    <div ref={sentinelRef} aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-[2px]" />
    <header
      data-scrolled={scrolled || undefined}
      className={cn(
        'material sticky top-0 z-40 h-[var(--topbar-h)] border-b',
        scrolled ? 'border-line' : 'border-transparent',
      )}
    >
      <div className="flex h-full items-center gap-4 px-4 sm:px-6 lg:px-8">
        <Link
          to="/"
          aria-label="INSIGHT, go to feed"
          className="wordmark shrink-0 rounded-[1px] text-[0.9375rem] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg"
        >
          INSIGHT
        </Link>

        <nav aria-label="Primary" className="ml-auto hidden min-w-0 sm:block">
          <ul className="flex items-center gap-1.5 text-[0.875rem]">
            {navItems(analysisEnabled).map((item, index) => {
              const isCurrent = item.key === current;
              return (
                <Fragment key={item.key}>
                  {index > 0 ? (
                    <li aria-hidden="true" className="select-none text-fg-3">
                      /
                    </li>
                  ) : null}
                  <li>
                    <Link
                      to={item.to}
                      aria-current={isCurrent ? 'page' : undefined}
                      className={cn(
                        'rounded-sm underline decoration-1 underline-offset-[0.22em] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg',
                        isCurrent
                          ? 'font-semibold text-fg decoration-fg'
                          : 'text-fg-2 decoration-fg-3/60 hover:text-fg hover:decoration-fg',
                      )}
                    >
                      {item.label}
                    </Link>
                  </li>
                </Fragment>
              );
            })}
          </ul>
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-1 sm:ml-2">
          <button
            type="button"
            onClick={onOpenSwitcher}
            aria-label="Open quick switcher"
            aria-keyshortcuts={isMac ? 'Meta+K' : 'Control+K'}
            className={cn(
              'hidden min-h-[2rem] items-center gap-2 rounded-md border border-line px-2.5 text-[0.8125rem] text-fg-2 sm:inline-flex',
              'transition-[transform,border-color,color] duration-[120ms] ease-out hover:border-line-strong hover:text-fg active:scale-[0.97] motion-reduce:transition-none',
              'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg',
            )}
          >
            <span>go to</span>
            <Kbd className="gap-0.5">
              {isMac ? <Command aria-hidden="true" className="h-3 w-3" /> : 'Ctrl'}
              {isMac ? 'K' : '+K'}
            </Kbd>
          </button>
          <button type="button" onClick={onOpenSwitcher} aria-label="Open menu" className={cn(iconButtonClass, 'sm:hidden')}>
            <Menu aria-hidden="true" />
          </button>
          <ThemeToggle />
        </div>
      </div>
    </header>
    </>
  );
}
