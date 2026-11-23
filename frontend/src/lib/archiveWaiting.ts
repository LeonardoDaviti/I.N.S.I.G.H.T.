/** An archive waiting out a host's limit, in words. Its own module: the main chunk reads it, lib/archive.ts doesn't. Pure. */
import type { ArchiveWaiting } from '../services/api';

const clockFormats = new Map<string, Intl.DateTimeFormat>();

/** "Waiting for bridge.example's limit: continues at 14:05" (reader's zone), or "… to answer" on a timeout;
 *  "continues shortly" once the time has come. */
export function waitingLine({ host, until, reason }: ArchiveWaiting, now: Date = new Date(), timeZone?: string): string {
  const at = new Date(until);
  const lead = reason === 'timeout' ? `Waiting for ${host} to answer` : `Waiting for ${host}'s limit`;
  if (Number.isNaN(at.getTime())) return lead;
  if (at.getTime() <= now.getTime()) return `${lead}: continues shortly`;
  const key = timeZone ?? '';
  let format = clockFormats.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat('en-GB', { timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    clockFormats.set(key, format);
  }
  return `${lead}: continues at ${format.format(at)}`;
}
