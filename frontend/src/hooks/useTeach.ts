import { useMutation, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { InterestAnswer, InterestDim, InterestTeach } from '../services/api';
import { FEED_ROOT_KEY } from './useFeed';

export interface Target { dim: InterestDim; key: string; name: string; label: string; answer: InterestAnswer | null }

/** v10.42: what a row or a post offers to teach, as chips: each of its things, its kind of news, its source. */
export function targetsOf(teach: InterestTeach): Target[] {
  return [
    ...teach.things.map((t) => ({ dim: 'thing' as const, key: t.id, name: t.name, label: t.name, answer: t.answer })),
    ...(teach.kind ? [{ dim: 'kind' as const, key: teach.kind.key, name: teach.kind.words,
      label: `this kind: ${teach.kind.words}`, answer: teach.kind.answer }] : []),
    ...(teach.source ? [{ dim: 'source' as const, key: teach.source.id, name: teach.source.name ?? '',
      label: `this source: ${teach.source.name ?? 'its source'}`, answer: teach.source.answer }] : []),
  ];
}

/** One tap teaches INSIGHT: kept as your label (POST /api/markx/interests), News ordered by it at once. */
export function useTeach(context: { row?: string | null; post?: string | null }, onTaught?: () => void) {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (t: { dim: InterestDim; key: string; name?: string; answer: InterestAnswer }) =>
      api.teachInterest({ ...t, row: context.row ?? null, post: context.post ?? null }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [...FEED_ROOT_KEY, 'news'] });
      onTaught?.();
    },
  });
}
