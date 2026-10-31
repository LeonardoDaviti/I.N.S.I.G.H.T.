import { useQuery } from '@tanstack/react-query';

import { useNow } from '../../hooks/useNow';
import { backgroundWorkBusy, backgroundWorkLines } from '../../lib/backgroundWork';
import { useApi } from '../../services/ApiContext';
import { StatusGlyph } from '../ui';

const BACKGROUND_WORK_KEY = ['operations', 'background'] as const;

/** Every 5 seconds while something runs, else every minute. */
function useBackgroundWork() {
  const api = useApi();
  return useQuery({
    queryKey: [...BACKGROUND_WORK_KEY],
    queryFn: () => api.getBackgroundWork(),
    refetchInterval: (query) => (backgroundWorkBusy(query.state.data) ? 5_000 : 60_000),
  });
}

/**
 * Background work (issue 0062), in Sources → ingestion → overview: what INSIGHT does on its own
 * after an update and after each fetch run (stories, News and Classics; the search index; reading
 * links), so an empty "covered by" or News has a reason you can see. Read only: no buttons, no
 * settings (owner: checkable, not controllable). Refreshes every 5 seconds while work runs.
 */
export default function BackgroundWork({ titleClass }: { titleClass: string }) {
  const work = useBackgroundWork();
  const now = useNow(30_000);

  return (
    <section aria-labelledby="ingestion-background" className="space-y-3">
      <h2 id="ingestion-background" className={titleClass}>Background work</h2>
      {work.data ? (
        <dl className="divide-y divide-line border-y border-line text-[0.875rem]">
          {backgroundWorkLines(work.data, now).map((line) => (
            <div key={line.key} data-work={line.key} className="grid gap-x-6 gap-y-0.5 py-2.5 sm:grid-cols-[9rem_minmax(0,1fr)]">
              <dt className="font-medium text-fg">{line.label}</dt>
              <dd className="min-w-0 space-y-0.5">
                <StatusGlyph status={line.status} label={line.word} className="whitespace-normal text-[0.875rem] tabular-nums" />
                {line.details.map((detail) => (
                  <p key={detail} className="break-words text-[0.8125rem] tabular-nums text-fg-3">{detail}</p>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-[0.875rem] text-fg-2">
          {work.isError ? 'Could not read the background work.' : 'Reading the background work…'}
        </p>
      )}
    </section>
  );
}
