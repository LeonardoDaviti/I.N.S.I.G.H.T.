import { Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
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
import { WALK, WALK_MESSAGE } from '../wall/walk';

function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <AppErrorBoundary resetKey={location.pathname}>{children}</AppErrorBoundary>;
}

/** The frame's address in its memory router, on `html[data-frame-path]`, for the walk to wait on. */
function PathMark() {
  const { pathname, search } = useLocation();
  useEffect(() => {
    document.documentElement.dataset.framePath = `${pathname}${search}`;
  }, [pathname, search]);
  return null;
}

/** Renders once the routes' lazy page resolved (it sits inside their Suspense boundary). */
function Resolved({ onResolved }: { onResolved: () => void }) {
  useEffect(onResolved, [onResolved]);
  return null;
}

const IDLE_CHECK_MS = 40;

/**
 * Waits until the page is settled: the route resolved and every query answered,
 * except the requests a loading state holds forever (`pending()`), checked twice
 * in a row so a query that starts after another finishes is not missed.
 */
function settled(
  resolved: Promise<void>,
  queryClient: QueryClient,
  report: BootedFrame['report'],
  alive: () => boolean,
): Promise<void> {
  return resolved.then(() => new Promise<void>((done) => {
    let idleOnce = false;
    const check = () => {
      if (!alive()) return;
      const idle = queryClient.isFetching() <= report.stalled();
      if (idle && idleOnce) return done();
      idleOnce = idle;
      setTimeout(check, IDLE_CHECK_MS);
    };
    setTimeout(check, IDLE_CHECK_MS);
  }));
}

/**
 * Runs the scenario's steps once the page is up, then marks the frame ready
 * (`html[data-frame-ready]`) once the page settled, for screenshots and the walk.
 */
function useScenarioSetup(
  scenario: FrameScenario | null,
  ready: (alive: () => boolean) => Promise<void>,
  onError: (message: string) => void,
) {
  const ran = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    // Once per frame: StrictMode runs effects twice, and ⌘K pressed twice is closed again.
    if (ran.current || !scenario) return;
    ran.current = true;
    const root = document.documentElement;
    const steps = scenario.setup ? scenario.setup(createFrameDriver(document)) : Promise.resolve();
    steps.then(() => ready(() => alive.current)).then(
      () => { if (alive.current) root.dataset.frameReady = 'true'; },
      (error: unknown) => {
        if (!alive.current) return;
        root.dataset.frameReady = 'failed';
        onError(error instanceof Error ? error.message : String(error));
      },
    );
  }, [scenario, ready, onError]);
}

/**
 * A walk frame (the Wall's walk) listens to the studio, its parent on the same
 * origin: `run` a step of the walk in this document, answer `done`. One step
 * at a time; a step sent while one runs waits behind it.
 */
function useWalkCommands(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return undefined;
    const studio = window.parent;
    const origin = window.location.origin;
    const driver = createFrameDriver(document);
    let queue = Promise.resolve();
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== origin || event.source !== studio) return;
      const { type, step } = (event.data ?? {}) as { type?: string; step?: number };
      if (type !== WALK_MESSAGE.run || typeof step !== 'number' || !WALK[step]) return;
      queue = queue.then(() => WALK[step].run(driver)).then(
        () => studio.postMessage({ type: WALK_MESSAGE.done, step, ok: true, path: document.documentElement.dataset.framePath }, origin),
        (error: unknown) => studio.postMessage({ type: WALK_MESSAGE.done, step, ok: false, error: error instanceof Error ? error.message : String(error) }, origin),
      );
    };
    window.addEventListener('message', onMessage);
    studio.postMessage({ type: WALK_MESSAGE.ready }, origin);
    return () => window.removeEventListener('message', onMessage);
  }, [enabled]);
}

/**
 * A frame's page (Design Studio D4): the real routes inside the app's own
 * providers and shell, at the scenario's URL, on a fresh query cache that does
 * not retry (an error state shows at once). The top bar shows, so the Wall
 * reads like the site. Its router is in memory: links move inside the frame.
 * A prototype frame (D6) wraps the routes in the prototype's component, which
 * may restyle the page (an override) or render something else instead.
 */
export default function FrameRoot({ booted, prototype: Prototype, walk = false }: {
  booted: BootedFrame;
  prototype?: PrototypeComponent;
  walk?: boolean;
}) {
  const { scenario, location, report } = booted;
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  const [setupError, setSetupError] = useState<string | null>(null);
  const [route] = useState(() => {
    let resolve = () => {};
    const promise = new Promise<void>((done) => { resolve = done; });
    return { promise, resolve };
  });
  const ready = useCallback((alive: () => boolean) => settled(route.promise, queryClient, report, alive), [route, queryClient, report]);
  useScenarioSetup(scenario, ready, setSetupError);
  useWalkCommands(walk && scenario !== null);

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
            <PathMark />
            <AppShell>
              <RouteErrorBoundary>
                <Suspense fallback={<div className="mx-auto w-full max-w-3xl px-4 pt-10 sm:px-6"><LoadingState label="Loading page" rows={4} /></div>}>
                  {Prototype ? <Prototype><AppRoutes /></Prototype> : <AppRoutes />}
                  <Resolved onResolved={route.resolve} />
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
