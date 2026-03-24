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
  return 'main';
}

export function getIngestionTabHref(tab: IngestionTabKey): string {
  return tab === 'main' ? '/ingestion' : `/ingestion/${tab}`;
}
