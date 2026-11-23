import { useQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import { TeachPanel } from '../reader/Teach';

/**
 * v10.42: the post page's "More or less like this": More / Less of one of the post's things, its News row's kind of
 * news, or its source, one tap each (kept as your label; News is ordered by it at once).
 */
export default function PostTeach({ postId }: { postId: string }) {
  const api = useApi();
  const query = useQuery({ queryKey: ['post-interest', postId], queryFn: () => api.getPostInterest(postId), staleTime: 60_000 });
  const data = query.data;
  if (!data || (!data.things.length && !data.kind && !data.source)) return null;
  return (
    <section aria-label="More or less like this" className="mt-4 text-[0.8125rem] leading-5 text-fg-3">
      <span className="font-medium text-fg-2">More or less like this</span>
      <TeachPanel teach={data} row={data.row} post={postId} onTaught={() => void query.refetch()} />
    </section>
  );
}
