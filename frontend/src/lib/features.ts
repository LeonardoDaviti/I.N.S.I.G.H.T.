/**
 * Frontend feature flags (spec §9). Mark IX ships reading-only: everything that
 * processes posts (summaries, highlights, the intelligence inspector, notes and
 * chat, stories and related posts) is hidden unless the build sets
 * `VITE_INSIGHT_ANALYSIS=on`. Hidden, not deleted: the components stay.
 *
 * This is the build-time default only. Components read `useAnalysis()` /
 * `useAnalysisEnabled()` (hooks/useAnalysis.ts), where the backend's
 * GET /api/config answer wins over it.
 */
const TRUTHY = new Set(['on', 'true', '1', 'yes']);

/** The same words the backend's INSIGHT_ANALYSIS accepts (backend/insight_core/settings.py). */
export function parseAnalysisFlag(raw: string | undefined | null): boolean {
  return TRUTHY.has(String(raw ?? '').trim().toLowerCase());
}

export const ANALYSIS_ENABLED = parseAnalysisFlag(import.meta.env?.VITE_INSIGHT_ANALYSIS);
