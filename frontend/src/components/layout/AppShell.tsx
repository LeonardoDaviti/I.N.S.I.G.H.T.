import { useEffect, useState, type ReactNode } from 'react';
import TopBar from './TopBar';
import QuickSwitcher from './QuickSwitcher';
import { isQuickSwitcherShortcut } from './navigation';
import Toaster from '../ui/Toaster';

/**
 * The frame every route renders in: a skip link, the top bar, the page and the
 * toaster. Owns the ⌘K / Ctrl+K binding for the quick switcher.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  const [switcherOpen, setSwitcherOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isQuickSwitcherShortcut(event)) return;
      event.preventDefault();
      setSwitcherOpen((open) => !open);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <div className="min-h-dvh bg-bg text-fg">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-[60] focus:rounded-md focus:bg-inverse focus:px-3 focus:py-1.5 focus:text-inverse-fg"
      >
        Skip to content
      </a>
      <TopBar onOpenSwitcher={() => setSwitcherOpen(true)} />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        {children}
      </main>
      <QuickSwitcher open={switcherOpen} onOpenChange={setSwitcherOpen} />
      <Toaster />
    </div>
  );
}
