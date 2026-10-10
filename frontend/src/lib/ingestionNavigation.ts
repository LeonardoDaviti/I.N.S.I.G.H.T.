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

/**
 * Where an old `/ingestion[/:tab]` URL lives reading-only: the ingestion tab
 * under sources (reading-finish R3). The tab is carried across as `sub`
 * (missions and jobs are both `jobs`; the overview is the default), and the
 * rest of the query (a run toast's `?job=`) comes along.
 */
export function sourcesIngestionHref(tab?: string | null, search = ''): string {
  const params = new URLSearchParams({ tab: 'ingestion' });
  const key = normalizeIngestionTab(tab);
  const sub = key === 'missions' ? 'jobs' : key === 'main' ? null : key;
  if (sub) params.set('sub', sub);
  new URLSearchParams(search).forEach((value, name) => {
    if (name !== 'tab' && name !== 'sub') params.set(name, value);
  });
  return `/settings/sources?${params.toString()}`;
}
