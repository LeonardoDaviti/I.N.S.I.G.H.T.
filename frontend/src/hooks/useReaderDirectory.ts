import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { Folder } from '../services/api';
import { sourceLabel } from '../lib/sourceLabel';
import type { SearchableSource } from '../lib/sourceSearch';
import { useSourcesHealth } from './useSourcesHealth';

export const FOLDERS_KEY = ['folders'] as const;
export const SOURCE_URLS_KEY = ['reader-source-urls'] as const;

/**
 * Names for the reader's scopes: the tracks (folders) and every source's display
 * name, from the cached `['sources-health']` rows that Settings → Health also uses.
 */
export function useReaderDirectory() {
  const folders = useFolders();
  const health = useSourcesHealth();
  const sourceNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const row of health.data?.rows ?? []) names.set(row.source_id, row.display_name);
    return names;
  }, [health.data]);

  return { folders, health, sourceNames };
}

/** The tracks (folders) in their sort order; the reader rail and ⌘K share the cache. */
export function useFolders({ enabled = true }: { enabled?: boolean } = {}) {
  const api = useApi();
  return useQuery({
    enabled,
    queryKey: [...FOLDERS_KEY],
    queryFn: async (): Promise<Folder[]> => {
      const response = await api.getFolders();
      if (!response.success) throw new Error(response.error || 'Could not load tracks.');
      return [...(response.folders ?? [])].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name));
    },
    staleTime: 5 * 60_000,
  });
}

/** The label of a scope: "All posts", a track's name or a source's name. */
export function scopeLabel(scope: string, folders: Folder[] | undefined, sourceNames: Map<string, string>): string {
  if (scope === 'all') return 'All posts';
  const [kind, id] = scope.split(':');
  if (kind === 'folder') return folders?.find((folder) => folder.id === id)?.name ?? 'Track';
  const name = sourceNames.get(id);
  return name ? sourceLabel(name) : 'Source';
}

export interface DirectorySource extends SearchableSource {
  id: string;
}

/**
 * Every source the reader can open, for the rail's filter: all health rows
 * (enabled or not, in the main digest or not) with their readable label, kind
 * and, once `withUrls` is on, their feed URL. The URLs come from
 * GET /api/sources/with-settings, fetched only when the owner starts filtering;
 * until then (or if it fails) a source matches on its names and kind.
 */
export function useSourceDirectory(withUrls: boolean): { sources: DirectorySource[]; isPending: boolean } {
  const api = useApi();
  const health = useSourcesHealth();
  const urls = useQuery({
    queryKey: [...SOURCE_URLS_KEY],
    queryFn: async (): Promise<Map<string, string>> => {
      const response = await api.getSourcesWithSettings();
      return new Map(response.sources.map((source) => [source.id, source.handle_or_url]));
    },
    enabled: withUrls,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const sources = useMemo(() => (health.data?.rows ?? []).map((row): DirectorySource => ({
    id: row.source_id,
    name: row.display_name,
    label: sourceLabel(row.display_name),
    url: urls.data?.get(row.source_id) ?? null,
    kind: row.kind,
    platform: row.platform,
  })), [health.data, urls.data]);
  return { sources, isPending: health.isPending };
}
