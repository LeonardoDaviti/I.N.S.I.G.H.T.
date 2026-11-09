import { useQuery } from '@tanstack/react-query';

import { tracksApi } from '../../services/tracks';
import { useMarkxOn } from '../../hooks/useMarkxOn';
import { folderReadPath } from '../../lib/feedContext';
import TextLink from '../ui/TextLink';
import { suggestionLine } from './trackWords';

/**
 * Discover's line on the sources your tracks found (issue 0145, Mark X): a source you don't read in a track that
 * brought it 3+ posts in 30 days; the track's page makes it active in one tap. Nothing while Mark X is off.
 */
export default function TrackSourceLines() {
  const on = useMarkxOn();
  const query = useQuery({ queryKey: ['markx-track-suggestions'], queryFn: () => tracksApi.suggestions(), enabled: on, staleTime: 60_000 });
  if (!on || !query.data?.length) return null;
  return (
    <section aria-label="Sources your tracks found" className="mb-4 border-b border-line pb-3">
      <h2 className="text-[0.8125rem] font-semibold text-fg-2">Sources your tracks found</h2>
      <ul className="mt-1">
        {query.data.map((s) => (
          <li key={`${s.track}:${s.source_id}`} className="text-[0.8125rem] leading-6 text-fg-2">
            <TextLink to={`${folderReadPath(s.track)}?view=topic`} muted>{suggestionLine(s)}</TextLink>
          </li>
        ))}
      </ul>
    </section>
  );
}
