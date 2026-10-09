import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { Folder } from '../services/api';
import { sourceLabel } from '../lib/sourceLabel';
import { useSourcesHealth } from './useSourcesHealth';

export const FOLDERS_KEY = ['folders'] as const;

/**
 * Names for the reader's scopes: the tracks (folders) and every source's display
 * name, from the cached `['sources-health']` rows that Settings → Health also uses.
 */
export function useReaderDirectory() {
  const api = useApi();
  const folders = useQuery({
    queryKey: [...FOLDERS_KEY],
    queryFn: async (): Promise<Folder[]> => {
      const response = await api.getFolders();
      if (!response.success) throw new Error(response.error || 'Could not load tracks.');
      return [...(response.folders ?? [])].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name));
    },
    staleTime: 5 * 60_000,
  });
  const health = useSourcesHealth();
  const sourceNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const row of health.data?.rows ?? []) names.set(row.source_id, row.display_name);
    return names;
  }, [health.data]);

  return { folders, health, sourceNames };
}

/** The label of a scope: "All posts", a track's name or a source's name. */
export function scopeLabel(scope: string, folders: Folder[] | undefined, sourceNames: Map<string, string>): string {
  if (scope === 'all') return 'All posts';
  const [kind, id] = scope.split(':');
  if (kind === 'folder') return folders?.find((folder) => folder.id === id)?.name ?? 'Track';
  const name = sourceNames.get(id);
  return name ? sourceLabel(name) : 'Source';
}
