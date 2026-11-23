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

/** Background work, in Sources → ingestion → overview: what INSIGHT does on its own after an update and each fetch
 *  run (stories, News and Classics, search index, reading links), so an empty News has a visible reason. Read only. */
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
