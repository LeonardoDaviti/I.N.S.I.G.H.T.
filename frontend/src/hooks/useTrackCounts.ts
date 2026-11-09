import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { request } from '../lib/request';
import { UNREAD_COUNTS_KEY } from './useFeed';
import { useMarkxOn } from './useMarkxOn';

/** A topic track's count (v10.12.1): its unread track items plus its Discover suggestions not yet labelled. */
export interface TopicTrackCount { unread: number; discover: number; count: number }

/** Only tracks that are topics are listed; a plain folder keeps its sources' unread count. */
export interface TopicTrackCounts { by_track: Record<string, TopicTrackCount> }

export const TRACK_COUNTS_KEY = ['markx-track-counts'] as const;

export const trackCountsApi = {
  counts: () => request<TopicTrackCounts>('/api/markx/tracks/counts'),
};

/** The track page's key (TrackTopic's, `['markx-track', id]`): a label refetches it, and then these counts. */
const TRACK_PAGE_ROOT = 'markx-track';

/**
 * The topic tracks' counts (issue 0145, v10.12.1), while Mark X is on: which tracks are topics, and the sidebar
 * count for each. Refreshed when the unread counts or a track page are fetched again (a read, a label), so it
 * follows them without being patched by the reader's optimistic count changes.
 */
export function useTrackCounts(enabled = true) {
  const markxOn = useMarkxOn();
  const client = useQueryClient();
  const on = enabled && markxOn;
  const query = useQuery({
    queryKey: [...TRACK_COUNTS_KEY],
    queryFn: () => trackCountsApi.counts(),
    enabled: on,
    staleTime: 30_000,
    retry: false,
  });
  useEffect(() => {
    if (!on) return undefined;
    return client.getQueryCache().subscribe((event) => {
      if (event.type !== 'updated' || event.action.type !== 'success' || event.action.manual) return;
      const root = event.query.queryKey[0];
      if (root === UNREAD_COUNTS_KEY[0] || root === TRACK_PAGE_ROOT) {
        void client.invalidateQueries({ queryKey: [...TRACK_COUNTS_KEY] });
      }
    });
  }, [client, on]);
  return { ...query, on, pending: on && query.isPending };
}

/** Whether a folder is a topic track (`undefined` while not known). */
export function isTopicTrack(counts: TopicTrackCounts | undefined, folderId: string): boolean {
  return Boolean(counts?.by_track[folderId]);
}
