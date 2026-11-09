import { Link } from 'react-router-dom';

import type { SearchEntity } from '../../services/api';
import { plural } from '../../lib/format';

/**
 * The entities the search's words name (issue 0139), above the results while Mark X is on: up to 3
 * hairline rows, each the entity's name (a merged one shows the entity it was merged into), its type
 * and maker, and its posts and voices; the row opens the entity's page (`/markx/entities/:id`).
 */
export default function SearchEntities({ entities }: { entities: SearchEntity[] }) {
  return (
    <ul aria-label="Entities" data-search-entities className="mb-3 flex flex-col gap-2">
      {entities.map((entity) => {
        const kind = [entity.type, entity.maker ? `by ${entity.maker}` : null].filter(Boolean).join(' · ');
        return (
          <li key={entity.id}>
            <Link
              to={`/markx/entities/${entity.id}`}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 rounded-md border border-line px-3 py-2 hover:border-line-strong sm:px-4"
            >
              <span dir="auto" className="min-w-0 font-semibold text-fg [overflow-wrap:anywhere]">{entity.name}</span>
              {kind ? <span dir="auto" className="min-w-0 text-[0.8125rem] text-fg-2 [overflow-wrap:anywhere]">{kind}</span> : null}
              <span className="ml-auto text-[0.8125rem] tabular-nums text-fg-3">
                {plural(entity.posts, 'post')} · {plural(entity.voices, 'voice')}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
