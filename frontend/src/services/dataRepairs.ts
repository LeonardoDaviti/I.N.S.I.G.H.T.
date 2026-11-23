// v10.43: the one-time data repairs (backend services/data_repairs.py). The jobs process runs each after a deploy,
// once per version; the page reads what each changed and asks for a run again or a preview. The API runs nothing.
import { request } from '../lib/request';

export interface RepairSample {
  label: string;
  url?: string | null;
  post_id?: string | null;
  source_id?: string | null;
  track_id?: string | null;
}
export interface RepairResult {
  at: string;
  version: string;
  dry_run: boolean;
  counts?: Record<string, number>;
  sample?: RepairSample[];
  seconds?: number;
  error?: string;
}
export type RepairMode = 'run' | 'preview';
export interface DataRepair {
  name: string; title: string; about: string; version: string;
  /** The version last run for real without an error; null: never. */
  ran_version: string | null;
  due: boolean;
  last_run: RepairResult | null;
  last_preview: RepairResult | null;
  requested: RepairMode | null;
  requested_at: string | null;
  running: RepairMode | null;
  running_since: string | null;
  undo: boolean;
}

export const dataRepairsApi = {
  list: () => request<{ repairs: DataRepair[] }>('/api/operations/repairs'),
  ask: (name: string, mode: RepairMode) =>
    request<DataRepair>(`/api/operations/repairs/${encodeURIComponent(name)}/${mode}`, { method: 'POST' }),
};

/** Something waits for the jobs process or runs in it: the page looks again soon. */
export function repairsBusy(repairs: DataRepair[] | undefined): boolean {
  return (repairs ?? []).some((r) => r.requested !== null || r.running !== null);
}

/** "12 listing pages · 3 sources", the zero counts left out ("Nothing to change" when all are zero). */
export function countsLine(counts: Record<string, number> | undefined): string {
  const parts = Object.entries(counts ?? {}).filter(([, n]) => n).map(([what, n]) => `${n} ${what.replace(/_/g, ' ')}`);
  return parts.length ? parts.join(' · ') : 'Nothing to change';
}

/** Where a sample row links: its post's page, its track, its source's feed, else its address. */
export function sampleHref(s: RepairSample): { to: string; external: boolean } | null {
  if (s.post_id) return { to: `/posts/${encodeURIComponent(s.post_id)}`, external: false };
  if (s.track_id) return { to: `/tracks/${encodeURIComponent(s.track_id)}`, external: false };
  if (s.url) return { to: s.url, external: true };
  if (s.source_id) return { to: `/read/source/${encodeURIComponent(s.source_id)}`, external: false };
  return null;
}
