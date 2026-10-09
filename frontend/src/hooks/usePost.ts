import { useCallback } from 'react';
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { Api, PostDetailResponse } from '../services/api';

export const postKey = (postId: string) => ['post', postId] as const;

/** The post detail as react-query data: a failed load throws, so ErrorState renders it. */
export function postQueryOptions(api: Api, postId: string) {
  return {
    queryKey: postKey(postId),
    queryFn: async (): Promise<PostDetailResponse> => {
      const response = await api.getPostDetail(postId);
      if (!response.success || !response.post) throw new Error(response.error || 'Could not load this post.');
      return response;
    },
    staleTime: 5 * 60_000,
  };
}

/** `useQuery(['post', id])` (spec §F.3); the reader prefetches it so `o` opens from cache. */
export function usePost(postId: string | undefined) {
  const api = useApi();
  return useQuery({ ...postQueryOptions(api, postId ?? ''), enabled: Boolean(postId) });
}

export function prefetchPost(queryClient: QueryClient, api: Api, postId: string) {
  return queryClient.prefetchQuery(postQueryOptions(api, postId));
}

/** A stable `prefetch(id)` for effects. */
export function usePrefetchPost() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useCallback((postId: string) => {
    void prefetchPost(queryClient, api, postId);
  }, [api, queryClient]);
}
