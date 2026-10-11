import { Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';

import { AppRoutes } from '../../App';
import AppErrorBoundary from '../../components/AppErrorBoundary';
import AppShell from '../../components/layout/AppShell';
import { ThemeProvider } from '../../components/ThemeProvider';
import { LoadingState } from '../../components/states';
import { ApiProvider } from '../../services/ApiContext';
import type { FrameScenario } from '../fixtures/scenarios';
import type { PrototypeComponent } from '../prototypeRegistry';
import type { BootedFrame } from './boot';
import { createFrameDriver } from './driver';
import RequestBar from './RequestBar';

function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <AppErrorBoundary resetKey={location.pathname}>{children}</AppErrorBoundary>;
}

/** Runs the scenario's steps once the page is up, then marks the frame ready (`html[data-frame-ready]`). */
function useScenarioSetup(scenario: FrameScenario | null, onError: (message: string) => void) {
  const ran = useRef(false);
  useEffect(() => {
    // Once per frame: StrictMode runs effects twice, and ⌘K pressed twice is closed again.
    if (ran.current || !scenario) return;
    ran.current = true;
    const root = document.documentElement;
    const steps = scenario.setup ? scenario.setup(createFrameDriver(document)) : Promise.resolve();
    steps.then(
      () => { root.dataset.frameReady = 'true'; },
      (error: unknown) => {
        root.dataset.frameReady = 'failed';
        onError(error instanceof Error ? error.message : String(error));
      },
    );
  }, [scenario, onError]);
}

/**
 * A frame's page (Design Studio D4): the real routes inside the app's own
 * providers and shell, at the scenario's URL, on a fresh query cache that does
 * not retry (an error state shows at once). The top bar shows, so the Wall
 * reads like the site. Its router is in memory: links move inside the frame.
 * A prototype frame (D6) wraps the routes in the prototype's component, which
 * may restyle the page (an override) or render something else instead.
 */
export default function FrameRoot({ booted, prototype: Prototype }: { booted: BootedFrame; prototype?: PrototypeComponent }) {
  const { scenario, location, report } = booted;
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  const [setupError, setSetupError] = useState<string | null>(null);
  useScenarioSetup(scenario, setSetupError);

  if (location.prototype && !Prototype) {
    return (
      <div className="min-h-dvh bg-bg p-6 font-mono text-[13px] text-fg">
        no prototype {location.prototype} (design/prototypes/{location.prototype}/index.tsx)
      </div>
    );
  }

  if (!scenario) {
    return (
      <div className="min-h-dvh bg-bg p-6 font-mono text-[13px] text-fg">
        no frame scenario for {location.page}/{location.state} (design/fixtures/scenarios.ts)
      </div>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider>
        <ThemeProvider>
          <MemoryRouter initialEntries={[scenario.url]}>
            <AppShell>
              <RouteErrorBoundary>
                <Suspense fallback={<div className="mx-auto w-full max-w-3xl px-4 pt-10 sm:px-6"><LoadingState label="Loading page" rows={4} /></div>}>
                  {Prototype ? <Prototype><AppRoutes /></Prototype> : <AppRoutes />}
                </Suspense>
              </RouteErrorBoundary>
            </AppShell>
          </MemoryRouter>
          <RequestBar report={report} setupError={setupError} />
        </ThemeProvider>
      </ApiProvider>
    </QueryClientProvider>
  );
}
