/**
 * The running version on the Ingestion tab (issue 0020), in the project's Mark
 * scheme: `I.N.S.I.G.H.T. Mark IX v9.1 · b9fcc6e · 27 Oct 2026`. The web app's
 * build is stamped by Vite from `VITE_INSIGHT_*`; the API's comes from
 * GET /api/version. Both come from the repo's `VERSION` file through `update`.
 */
import type { BuildVersion } from '../services/api';

// Possibly undefined: the node test runner has no import.meta.env.
const env = import.meta.env as ImportMetaEnv | undefined;

/** This web app's build; nulls in local dev and tests. */
export const WEB_BUILD: BuildVersion = {
  version: env?.VITE_INSIGHT_VERSION || null,
  commit: env?.VITE_INSIGHT_COMMIT || null,
  commit_date: env?.VITE_INSIGHT_COMMIT_DATE || null,
};

const month = new Intl.DateTimeFormat('en', { month: 'short', timeZone: 'UTC' });

/** `2026-10-27` → `27 Oct 2026`; null for anything else. */
function commitDate(raw: string | null): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw ?? '');
  if (!match) return null;
  const [, year, mm, dd] = match;
  return `${Number(dd)} ${month.format(new Date(Date.UTC(Number(year), Number(mm) - 1, 1)))} ${year}`;
}

/** `Mark IX v9.1 · b9fcc6e`, or `dev build` when nothing was stamped. */
function label(version: string | null, commit: string | null): string {
  return [version, commit].filter(Boolean).join(' · ') || 'dev build';
}

/** `Mark IX v9.1` → `Mark IX`; null without a Mark. */
function mark(version: string | null): string | null {
  return version?.match(/^(Mark \S+) /)?.[1] ?? null;
}

/**
 * The line for the web build and the API's (`undefined` until it answers, or
 * when it can't). Different builds say both, plainly, with their shared Mark
 * written once.
 */
export function versionLine(web: BuildVersion, api: BuildVersion | undefined): string {
  if (!api || (api.version === web.version && api.commit === web.commit)) {
    return ['I.N.S.I.G.H.T. ' + label(web.version, web.commit), commitDate(web.commit_date)].filter(Boolean).join(' · ');
  }
  const shared = mark(web.version) === mark(api.version) ? mark(web.version) : null;
  const release = (version: string | null) => (shared && version ? version.slice(shared.length + 1) : version);
  const builds = `Web ${label(release(web.version), web.commit)} · API ${label(release(api.version), api.commit)}, out of step`;
  return `I.N.S.I.G.H.T. ${shared ? `${shared} · ` : ''}${builds}`;
}
