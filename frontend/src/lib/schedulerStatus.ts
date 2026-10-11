/**
 * The scheduler's clock as the Ingestion tab shows it: whether it looks
 * stalled, and when it next ticks. The one place for that math. Pure; `nowMs`
 * is injected.
 */
import type { SchedulerState } from '../services/api';
import { toDate } from './dates.ts';
import { formatTimeRemaining } from './duration.ts';

/** Why the scheduler looks stopped: it has not ticked for two tick intervals
 *  (at least 90 minutes), or ever. Null when it looks alive or is unknown. */
export function schedulerStaleness(state: SchedulerState | null, tickMinutes: number, nowMs: number): string | null {
  if (state === null) return null;
  const last = toDate(state.last_tick_at)?.getTime();
  if (last === undefined) {
    return 'The scheduler has not recorded a tick. Nothing is fetched automatically until the ingestion service runs.';
  }
  if (nowMs - last > Math.max(2 * tickMinutes, 90) * 60_000) {
    return `The scheduler last ticked ${formatTimeRemaining(nowMs - last, { seconds: false })} ago. Automatic fetching looks stalled; check the ingestion service.`;
  }
  return null;
}

/** "next tick in 1h 5m", "next tick due now"; null when the next tick is unknown. */
export function nextTickLabel(state: SchedulerState | null | undefined, nowMs: number): string | null {
  const next = toDate(state?.next_tick_at);
  if (!next) return null;
  const remaining = next.getTime() - nowMs;
  return remaining <= 0 ? 'next tick due now' : `next tick in ${formatTimeRemaining(remaining, { seconds: false })}`;
}
