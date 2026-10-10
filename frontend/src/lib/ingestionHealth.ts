/**
 * Has ingestion stopped? Read from the source health rows the reader already
 * caches: when no enabled source has been attempted for a day, nothing is
 * fetching, and an empty unread feed means "stopped", not "caught up".
 */
export const INGESTION_STOPPED_AFTER_MS = 24 * 60 * 60 * 1000;

export interface IngestionActivity {
  stopped: boolean;
  /** The newest attempt over the enabled sources; null when none was ever attempted. */
  lastAttemptAt: string | null;
}

export function ingestionActivity(
  rows: ReadonlyArray<{ enabled: boolean; last_attempt_at: string | null }> | undefined,
  now: number = Date.now(),
): IngestionActivity | null {
  const enabled = (rows ?? []).filter((row) => row.enabled);
  // Unknown (not loaded) or nothing to fetch: no claim either way.
  if (!enabled.length) return null;
  let newest: number | null = null;
  let newestIso: string | null = null;
  for (const row of enabled) {
    const at = row.last_attempt_at ? Date.parse(row.last_attempt_at) : NaN;
    if (Number.isFinite(at) && (newest === null || at > newest)) {
      newest = at;
      newestIso = row.last_attempt_at;
    }
  }
  return { stopped: newest === null || now - newest > INGESTION_STOPPED_AFTER_MS, lastAttemptAt: newestIso };
}
