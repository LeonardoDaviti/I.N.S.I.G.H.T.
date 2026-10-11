/**
 * Durations, the one place that turns a length of time into words. Each screen
 * keeps its own style, so there is one named function per style:
 *
 *   formatClock         4:02:07, 0:45            video lengths and positions
 *   formatElapsed       <1s, 42s, 2m 5s, 1h 2m   how long a job or run took
 *   formatSpan          25m, 3h, 5d              one unit, floored ("in 3h", "3h ago")
 *   formatTimeRemaining 2d 3h 4m, 1h 5m 2s, 9s   the scheduler's countdown
 *   formatEstimate      under a minute, ~2h 10m  the archive plan's estimate
 *   formatHours         30m, 1.5h, 2d            cadence intervals given in hours
 *
 * Pure.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** 4:02:07 / 12:34 / 0:45 for video durations; missing counts as 0:00. */
export function formatClock(seconds?: number | null): string {
  const total = Math.max(0, Math.round(Number(seconds || 0)));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/**
 * "<1s", "42s", "2m 5s", "1h 2m"; null when unknown. `hours: false` keeps
 * counting in minutes past the hour ("75m 0s"), as the run report does.
 */
export function formatElapsed(seconds: number | null | undefined, { hours = true }: { hours?: boolean } = {}): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return null;
  if (seconds < 1) return '<1s';
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60 || !hours) return `${minutes}m ${total % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** A positive duration as "25m", "3h", "5d" (floored, so "in 3h" never overstates; at least 1m). */
export function formatSpan(ms: number): string {
  if (ms < HOUR) return `${Math.max(1, Math.floor(ms / MINUTE))}m`;
  if (ms < DAY) return `${Math.floor(ms / HOUR)}h`;
  return `${Math.floor(ms / DAY)}d`;
}

/**
 * "2d 3h 4m", "1h 5m 2s", "4m 10s", "9s": the two or three largest units.
 * `seconds: false` drops the trailing seconds once there are minutes ("1h 5m", "4m").
 */
export function formatTimeRemaining(milliseconds: number, { seconds: withSeconds = true }: { seconds?: boolean } = {}): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const tail = withSeconds ? ` ${seconds}s` : '';

  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m${tail}`;
  if (minutes > 0) return `${minutes}m${tail}`;
  return `${seconds}s`;
}

/** "under a minute", "~5m", "~2h 10m"; null when there is no estimate. */
export function formatEstimate(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return null;
  if (seconds < 60) return 'under a minute';
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `~${minutes}m`;
  return rest ? `~${hours}h ${rest}m` : `~${hours}h`;
}

function trim(value: number): string {
  return String(Number(value.toFixed(1)));
}

/** Hours as "30m", "6h", "1.5h", "2d", "1.5d"; "—" when unknown. */
export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || !Number.isFinite(hours) || hours < 0) return '—';
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${trim(hours)}h`;
  return `${trim(hours / 24)}d`;
}
