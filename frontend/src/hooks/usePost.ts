import { useCallback } from 'react';
import { keepPreviousData, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { Api, PostDetailResponse } from '../services/api';

export const postKey = (postId: string, fixture?: string | null) => (
  fixture ? ['post', postId, 'fixture', fixture] as const : ['post', postId] as const
);

/** The post detail as react-query data: a failed load throws, so ErrorState renders it. */
export function postQueryOptions(api: Api, postId: string, fixture?: string | null) {
  return {
    queryKey: postKey(postId, fixture),
    queryFn: async (): Promise<PostDetailResponse> => {
      const response = await api.getPostDetail(postId);
      if (!response.success || !response.post) throw new Error(response.error || 'Could not load this post.');
      return response;
    },
    staleTime: 5 * 60_000,
  };
}

/**
 * `useQuery(['post', id])` (spec §F.3); the reader prefetches it so `o` opens from
 * cache. `override` is the post page's dev-only `?data=` fixture API (cached apart).
 * While the next post loads, the last one stays: the page keeps its stream (issue 0014).
 */
export function usePost(postId: string | undefined, override?: { api: Api; fixture: string | null }) {
  const live = useApi();
  const api = override?.api ?? live;
  return useQuery({ ...postQueryOptions(api, postId ?? '', override?.fixture), enabled: Boolean(postId), placeholderData: keepPreviousData });
}

export function prefetchPost(queryClient: QueryClient, api: Api, postId: string) {
  return queryClient.prefetchQuery(postQueryOptions(api, postId));
}

/** A stable `prefetch(id)` for effects. */
export function usePrefetchPost(override?: Api) {
  const live = useApi();
  const api = override ?? live;
  const queryClient = useQueryClient();
  return useCallback((postId: string) => {
    void prefetchPost(queryClient, api, postId);
  }, [api, queryClient]);
}
