export type IngestionTabKey = 'main' | 'archive' | 'missions' | 'logs';

export type IngestionTab = {
  key: IngestionTabKey;
  label: string;
  description: string;
};

export const INGESTION_TABS: IngestionTab[] = [
  {
    key: 'main',
    label: 'Main',
    description: 'Immediate actions and system snapshots.',
  },
  {
    key: 'archive',
    label: 'Archive Control',
    description: 'Plan and run one-source archive jobs.',
  },
  {
    key: 'missions',
    label: 'Mission Feed',
    description: 'Inspect jobs, alerts, and source health.',
  },
  {
    key: 'logs',
    label: 'Logs',
    description: 'Read runtime and session logs.',
  },
];

export function normalizeIngestionTab(tab?: string | null): IngestionTabKey {
  if (tab === 'archive' || tab === 'missions' || tab === 'logs') {
    return tab;
  }
  // The tab is labelled "jobs", so /ingestion/jobs must open it, not the overview.
  if (tab === 'jobs') {
    return 'missions';
  }
  return 'main';
}

export function getIngestionTabHref(tab: IngestionTabKey): string {
  return tab === 'main' ? '/ingestion' : `/ingestion/${tab}`;
}

/** The ingestion tab's views under sources, as `?sub=`: the overview (default), archive backfill, the job history and the logs. */
export const INGESTION_SUB_VIEWS = ['overview', 'archive', 'jobs', 'logs'] as const;
export type IngestionSubView = (typeof INGESTION_SUB_VIEWS)[number];

export function normalizeIngestionSubView(sub?: string | null): IngestionSubView {
  return (INGESTION_SUB_VIEWS as readonly (string | null | undefined)[]).includes(sub) ? sub as IngestionSubView : 'overview';
}

/** The `?tab=ingestion` link to one of its views. */
export function ingestionSubViewHref(sub: IngestionSubView): string {
  return sub === 'overview' ? '?tab=ingestion' : `?tab=ingestion&sub=${sub}`;
}

/** The old page's tabs -> the sub-view that holds them now. */
const SUB_VIEW_FOR_TAB: Record<IngestionTabKey, IngestionSubView> = {
  main: 'overview',
  archive: 'archive',
  missions: 'jobs',
  logs: 'logs',
};

/**
 * Where an old `/ingestion[/:tab]` URL lives reading-only: the ingestion tab
 * under sources (reading-finish R3). The tab is carried across as `sub`
 * (missions and jobs are both `jobs`); the overview is the default and needs none. The rest of the query (a run
 * toast's `?job=`) comes along.
 */
export function sourcesIngestionHref(tab?: string | null, search = ''): string {
  const params = new URLSearchParams({ tab: 'ingestion' });
  const sub = SUB_VIEW_FOR_TAB[normalizeIngestionTab(tab)];
  if (sub !== 'overview') params.set('sub', sub);
  new URLSearchParams(search).forEach((value, name) => {
    if (name !== 'tab' && name !== 'sub') params.set(name, value);
  });
  return `/settings/sources?${params.toString()}`;
}
