/**
 * Settings → Data's words (issue 0079): sizes, times, the export's link and the
 * restore command. Pure, so `node --test` checks them.
 */
import type { ExportInfo } from '../services/api';

/** 1,234,567,890 → "1.2 GB" (decimal units, as a file manager shows them). */
export function formatBytes(bytes: number): string {
  const units = ['bytes', 'KB', 'MB', 'GB', 'TB'];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  if (unit === 0) return `${Math.round(value)} bytes`;
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

/** 1 → "about a second", 25 → "about 25 seconds", 150 → "about 3 minutes". */
export function formatDuration(seconds: number): string {
  if (seconds < 1.5) return 'about a second';
  if (seconds < 90) return `about ${Math.round(seconds)} seconds`;
  return `about ${Math.round(seconds / 60)} minutes`;
}

const dayMonth = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' });

/** What the estimate is from (issue 0105): "from the rows stored now", or "from the last export, 5 Nov:
 *  243 MB in about 28 seconds"; null when the API doesn't say. */
export function estimateBasis(info: Pick<ExportInfo, 'estimate_basis' | 'last_export'>): string | null {
  const last = info.last_export;
  if (info.estimate_basis === 'last_export' && last) {
    const at = new Date(last.at);
    const when = Number.isNaN(at.getTime()) ? '' : `, ${dayMonth.format(at)}`;
    return `from the last export${when}: ${formatBytes(last.bytes)} in ${formatDuration(last.seconds)}`;
  }
  return info.estimate_basis === 'live_rows' ? 'from the rows stored now' : null;
}

/** The path the download opens; `token` lets the page follow its progress. */
export function exportPath(token: string, includeLogins: boolean): string {
  const query = new URLSearchParams({ token });
  if (includeLogins) query.set('logins', 'true');
  return `/api/export/everything?${query.toString()}`;
}

/** A token for one download (crypto.randomUUID needs a secure context; the server may be plain http). */
export function newExportToken(random: () => number = Math.random): string {
  return Array.from({ length: 24 }, () => 'abcdefghijklmnopqrstuvwxyz0123456789'[Math.floor(random() * 36)]).join('');
}

/** The restore, run on the server in the INSIGHT folder with the file beside it (DEPLOYMENT.md). */
export function restoreCommand(fileName: string): string {
  return `docker compose run --rm -v "$PWD/${fileName}:/tmp/${fileName}:ro" backend \\\n`
    + `  python insight_core/db/import_export.py /tmp/${fileName} --into insight_restored`;
}
