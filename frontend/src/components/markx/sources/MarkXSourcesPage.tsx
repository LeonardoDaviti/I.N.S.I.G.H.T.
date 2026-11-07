import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { Page, PageHeader, TextLink } from '../../ui';
import { EmptyState, ErrorState, LoadingState } from '../../states';
import { useApi } from '../../../services/ApiContext';
import { markxSourcesApi } from '../../../services/api';
import { COLUMN_TITLES, cellText, sortRows, sourceHref, type Sort } from './format';

/**
 * The source analysis list (0132 B, `/markx/sources`): one row per voice, and per source with no voice; the role, posts
 * a week, first to report, News yield, cited by and solo share, each sortable (the ranker is the sort). There is no
 * overall score (the owner's decision 5). A number counted over too few says "too few". On a phone each row is a block.
 */
export default function MarkXSourcesPage() {
  const api = markxSourcesApi(useApi());
  const query = useQuery({ queryKey: ['markx-sources'], queryFn: () => api.getMarkxSources(), staleTime: 60_000 });
  const [sort, setSort] = useState<Sort>({ by: 'name', desc: false });
  const rows = useMemo(() => (query.data ? sortRows(query.data.rows, sort) : []), [query.data, sort]);
  if (query.isPending) return <Page><LoadingState label="Loading" rows={8} /></Page>;
  if (query.isError) return <Page><ErrorState error={query.error} onRetry={() => query.refetch()} /></Page>;
  const d = query.data;
  const columns = d.columns;
  const pick = (by: string) => setSort((s) => (s.by === by ? { by, desc: !s.desc } : { by, desc: by !== 'name' && by !== 'role' }));
  const header = (by: string, title: string) => (
    <button type="button" onClick={() => pick(by)} title={d.formulas[by] ?? undefined}
      aria-label={`Sort by ${title.toLowerCase()}`}
      className="whitespace-nowrap text-left font-semibold text-fg-2 hover:text-fg">
      {title}{sort.by === by ? (sort.desc ? ' ↓' : ' ↑') : ''}
    </button>
  );
  return (
    <Page>
      <PageHeader title="Sources" meta={d.computed_at ? `Computed ${d.computed_at.slice(0, 16).replace('T', ' ')} UTC` : 'Not computed yet'}>
        <div className="space-y-4">
          <p className="text-[0.8125rem] text-fg-2">
            <TextLink to="/markx" muted>Mark X</TextLink> · every number with its formula and evidence on the source&apos;s
            page. No overall score: sort by the column you care about.
          </p>
          {!rows.length ? (
            <EmptyState title="No sources computed yet" description="The stats job runs nightly and after a regroup." />
          ) : (
            <>
              <table className="hidden w-full text-[0.8125rem] sm:table" aria-label="Sources">
                <thead>
                  <tr className="border-b border-line">
                    <th className="py-2 pr-3 text-left">{header('name', 'Name')}</th>
                    {columns.map((c) => <th key={c} className="py-2 pr-3 text-left">{header(c, COLUMN_TITLES[c] ?? c)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.kind}:${r.id}`} className="border-b border-line">
                      <td className="max-w-[16rem] truncate py-1.5 pr-3">
                        <TextLink to={sourceHref(r.id)}>{r.name || 'a source'}</TextLink>
                        <span className="ml-2 text-fg-3">{r.kind === 'voice' ? `voice · ${r.channels} channels` : r.platform}</span>
                      </td>
                      {columns.map((c) => (
                        <td key={c} className={`py-1.5 pr-3 tabular-nums ${r.stats[c]?.too_few && c !== 'role' ? 'text-fg-3' : ''}`}>
                          {cellText(c, r.stats[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="sm:hidden" data-phone-list>
                <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-[0.75rem]" role="group" aria-label="Sort">
                  {header('name', 'Name')}
                  {columns.map((c) => <span key={c}>{header(c, COLUMN_TITLES[c] ?? c)}</span>)}
                </div>
                <ul>
                  {rows.map((r) => (
                    <li key={`${r.kind}:${r.id}`} className="border-t border-line py-2 text-[0.8125rem]">
                      <TextLink to={sourceHref(r.id)}>{r.name || 'a source'}</TextLink>
                      <span className="ml-2 text-fg-3">{r.kind === 'voice' ? `voice · ${r.channels} channels` : r.platform}</span>
                      <dl className="mt-1 grid grid-cols-2 gap-x-3 text-fg-2">
                        {columns.map((c) => (
                          <div key={c} className="flex justify-between gap-2">
                            <dt className="text-fg-3">{COLUMN_TITLES[c] ?? c}</dt>
                            <dd className="tabular-nums">{cellText(c, r.stats[c])}</dd>
                          </div>
                        ))}
                      </dl>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      </PageHeader>
    </Page>
  );
}
