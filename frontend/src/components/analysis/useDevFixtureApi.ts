import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useApi } from '../../services/ApiContext';
import type { Api } from '../../services/api';

/**
 * The dev-only `?data=` seam (spec §F.7, break-ui): when the URL names a fixture
 * set, the page talks to a fixture API instead of the live one. The fixture API
 * inherits every live method and overrides the ones the page reads (and turns its
 * writes into no-ops), so the swap happens at the data boundary, not in markup.
 */
export function useDevFixtureApi(build: (name: string, live: Api) => Partial<Api> | null): { api: Api; fixture: string | null } {
  const live = useApi();
  const [searchParams] = useSearchParams();
  const name = import.meta.env.DEV ? searchParams.get('data') : null;
  return useMemo(() => {
    if (!name) return { api: live, fixture: null };
    const overrides = build(name, live);
    if (!overrides) return { api: live, fixture: null };
    return { api: Object.assign(Object.create(live) as Api, overrides), fixture: name };
    // `build` is a module-level function in every caller.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, name]);
}
