/**
 * Frontend feature flags (spec §9). Mark IX ships reading-only: everything that
 * processes posts (summaries, highlights, the intelligence inspector, notes and
 * chat, stories and related posts) is hidden unless the build sets
 * `VITE_INSIGHT_ANALYSIS=on`. Hidden, not deleted: the components stay.
 */
export const ANALYSIS_ENABLED = import.meta.env.VITE_INSIGHT_ANALYSIS === 'on';
