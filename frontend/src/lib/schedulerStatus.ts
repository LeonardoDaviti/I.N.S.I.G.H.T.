import type { SchedulerState } from '../services/api';

/** "2d 3h 4m", "1h 5m 2s", "4m 10s", "9s". */
export function formatTimeRemaining(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

/** Why the scheduler looks stopped: it has not ticked for two tick intervals
 *  (at least 90 minutes), or ever. Null when it looks alive or is unknown. */
export function schedulerStaleness(state: SchedulerState | null, tickMinutes: number, nowMs: number): string | null {
  if (state === null) return null;
  const last = state.last_tick_at ? new Date(state.last_tick_at).getTime() : NaN;
  if (Number.isNaN(last)) {
    return 'The scheduler has not recorded a tick. Nothing is fetched automatically until the ingestion service runs.';
  }
  if (nowMs - last > Math.max(2 * tickMinutes, 90) * 60_000) {
    return `The scheduler last ticked ${formatTimeRemaining(nowMs - last).replace(/ \d+s$/, '')} ago. Automatic fetching looks stalled; check the ingestion service.`;
  }
  return null;
}
