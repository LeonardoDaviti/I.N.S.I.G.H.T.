import { useSyncExternalStore } from 'react';

import type { FrameReport } from './boot';
import type { TransportEvent } from './transport';

/** The same request repeated (a refetch, StrictMode) counts once, with its total. */
function tally(events: readonly TransportEvent[]): { event: TransportEvent; count: number }[] {
  const seen = new Map<string, { event: TransportEvent; count: number }>();
  for (const event of events) {
    const key = `${event.kind} ${event.method} ${event.path}`;
    const entry = seen.get(key);
    if (entry) entry.count += 1;
    else seen.set(key, { event, count: 1 });
  }
  return [...seen.values()];
}

/**
 * What the fixtures did not cover, inside the frame (D4): every unmocked read,
 * loud, and every write the frame answered without sending, quiet. Nothing
 * when the frame stayed inside its fixtures and wrote nothing.
 */
export default function RequestBar({ report, setupError }: { report: FrameReport; setupError?: string | null }) {
  const events = useSyncExternalStore(report.subscribe, report.events, report.events);
  const lines = tally(events);
  if (!lines.length && !setupError) return null;
  return (
    <div
      role="status"
      aria-label="Frame requests"
      className="fixed inset-x-0 bottom-0 z-[100] max-h-[40dvh] overflow-auto border-t border-line-strong bg-raised font-mono text-[11px] leading-5 text-fg"
    >
      {setupError && <p className="bg-inverse px-3 py-1 text-inverse-fg">frame setup failed: {setupError}</p>}
      {lines.map(({ event, count }) => (
        <p
          key={`${event.kind} ${event.method} ${event.path}`}
          className={`break-all px-3 py-0.5 ${event.kind === 'unmocked' ? 'bg-inverse text-inverse-fg' : 'text-fg-2'}`}
        >
          {event.kind === 'unmocked' ? 'unmocked request' : 'write, not sent'}: {event.method} {event.path}
          {count > 1 ? ` ×${count}` : ''}
        </p>
      ))}
    </div>
  );
}
