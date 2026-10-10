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
export const ANALYSIS_ENABLED = import.meta.env.VITE_INSIGHT_ANALYSIS === 'on';
