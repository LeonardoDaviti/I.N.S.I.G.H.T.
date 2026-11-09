import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { discoveredLine } from '../../lib/archiveCoverage';
import { errorMessage } from '../../lib/apiError';
import { formatRelativeTime } from '../../lib/dates';
import { sourceSettingsHref } from '../../lib/feedContext';
import { smartArchiveApi } from '../../services/smartArchive';

export const DISCOVERIES_KEY = ['source-discoveries'] as const;
const SHOWN = 8;

/**
 * "Discovered through this source" (issue 0143): on the source sheet, what INSIGHT found because of this source,
 * read from what Discover and Mark X already store: the sites and accounts it linked that Discover lists (what you
 * followed first, then the most voices), the sources you added after it linked them, the pages and originals
 * collected because of it, and the entities it named before any other source. One GET; quiet when there is nothing.
 */
export default function SourceDiscoveries({ sourceId }: { sourceId: string }) {
  const query = useQuery({
    queryKey: [...DISCOVERIES_KEY, sourceId],
    queryFn: () => smartArchiveApi.discoveries(sourceId),
    staleTime: 60_000,
    retry: false,
  });
  const heading = <div className="text-[0.8125rem] font-medium text-fg">Discovered through this source</div>;
  if (query.isPending) return <section aria-label="Discovered through this source">{heading}<p className="text-[0.75rem] text-fg-3">Loading…</p></section>;
  if (query.isError) {
    return (
      <section aria-label="Discovered through this source">
        {heading}
        <p className="text-[0.75rem] text-fg-3">Unavailable: {errorMessage(query.error)}</p>
      </section>
    );
  }
  const found = query.data;
  const now = new Date();
  const nothing = !found.sites.length && !found.originals.length && !found.entities.length;
  const item = 'flex min-w-0 flex-wrap items-baseline gap-x-2 text-[0.8125rem]';
  const quiet = 'text-[0.75rem] text-fg-3';
  return (
    <section aria-label="Discovered through this source" className="space-y-3" data-discoveries>
      {heading}
      {nothing ? (
        <p className={quiet}>
          {found.discover_counted ? 'Nothing yet: no site it links is one Discover lists, and it named no entity first.'
            : 'Nothing yet: Discover has not counted your links.'}
        </p>
      ) : null}
      {found.followed_from_here.length ? (
        <div>
          <div className={quiet}>You followed after it linked them</div>
          <ul>
            {found.followed_from_here.map((followed) => (
              <li key={followed.id} className={item}>
                <Link className="truncate text-link" to={sourceSettingsHref(followed.id)}>{followed.name}</Link>
                {followed.added_at ? <span className={quiet}>added {formatRelativeTime(followed.added_at, now)}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {found.sites.length ? (
        <div>
          <div className={quiet}>Sites and accounts it linked that Discover lists</div>
          <ul>
            {found.sites.slice(0, SHOWN).map((site) => (
              <li key={site.key} className={item}>
                <span className="truncate font-medium text-fg [overflow-wrap:anywhere]">{site.key}</span>
                <span className={quiet}>{discoveredLine(site)}</span>
              </li>
            ))}
          </ul>
          {found.sites.length > SHOWN ? <p className={quiet}>and {found.sites.length - SHOWN} more</p> : null}
        </div>
      ) : null}
      {found.originals.length ? (
        <div>
          <div className={quiet}>Pages collected because of it</div>
          <ul>
            {found.originals.slice(0, SHOWN).map((original) => (
              <li key={`${original.kind}:${original.url}`} className={item}>
                {original.post_id ? (
                  <Link className="truncate text-link" to={`/posts/${encodeURIComponent(original.post_id)}`}>
                    {original.title || original.url}
                  </Link>
                ) : <span className="truncate text-fg-2 [overflow-wrap:anywhere]">{original.url}</span>}
                <span className={quiet}>{original.outcome.replace(/_/g, ' ')}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {found.entities.length ? (
        <div>
          <div className={quiet}>Named here first</div>
          <ul className="flex flex-wrap gap-x-3 gap-y-1">
            {found.entities.slice(0, SHOWN * 2).map((entity) => (
              <li key={entity.id} className="text-[0.8125rem]">
                <Link className="text-link" to={`/markx/entities/${encodeURIComponent(entity.id)}`}>{entity.name}</Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
