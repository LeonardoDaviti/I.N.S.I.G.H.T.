import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';

import { Page, PageHeader, TextLink } from '../components/ui';
import { ErrorState, LoadingState } from '../components/states';
import { Accuracy, EntityPostLine, QueueItem, SurgeMark, entityHref, entityMeta } from '../components/markx/MarkXEntities';
import { useApi } from '../services/ApiContext';
import { plural } from '../lib/format';

const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';

/**
 * An entity's page, `/markx/entities/<id>` (0119 A3, 0115 Decided 3): every post naming it in every role, grouped by
 * its Mark X stories (most voices first), the posts in no story last; every source with its counts; its family and
 * versions as links. Read posts stay, dimmed. A merged entity's id opens its group's page. 0133: a document shows who
 * published it and the posts citing it as evidence or recommending it; an org or person, what it published.
 */
export default function MarkXEntityPage() {
  const { entityId = '' } = useParams();
  const api = useApi();
  const query = useQuery({ queryKey: ['markx-entity', entityId], queryFn: () => api.getMarkxEntity(entityId), staleTime: 30_000 });
  if (query.isPending) return <Page><LoadingState label="Loading" rows={6} /></Page>;
  if (query.isError) return <Page><ErrorState error={query.error} onRetry={() => query.refetch()} /></Page>;
  const d = query.data;
  const e = d.entity;
  return (
    <Page>
      <PageHeader title={e.name} meta={`${entityMeta(e)} · ${plural(d.voices, 'source')} · ${plural(d.posts, 'post')}`}>
        <div className="space-y-8">
          <p className="text-[0.8125rem] text-fg-2">
            <TextLink to="/markx?tab=entities" muted>Mark X entities</TextLink>
            {d.maker ? <> · by <TextLink to={entityHref(d.maker.id)}>{d.maker.name}</TextLink></> : null}
            {d.family ? <> · family <TextLink to={entityHref(d.family.id)}>{d.family.name}</TextLink></> : null}
            {d.published_by?.length ? <> · published by {d.published_by.map((p, n) => (
              <span key={p.id}>{n ? ', ' : ''}<TextLink to={entityHref(p.id)}>{p.name}</TextLink></span>))}</> : null}
            {d.aliases.length > 1 ? ` · also written ${d.aliases.filter((a) => a !== e.name).join(', ')}` : ''}
            {' '}<SurgeMark surges={d.surges} />
          </p>
          <Accuracy accuracy={d.accuracy} />
          {d.versions.length ? (
            <section aria-label="Versions">
              <h2 className={H2}>{d.family ? 'Other versions of the family' : 'Versions'}</h2>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
                {d.versions.map((v) => (
                  <li key={v.id}>{v.id === e.id ? <span className="font-semibold text-fg">{v.name}</span>
                    : <TextLink to={entityHref(v.id)}>{v.name}</TextLink>}</li>
                ))}
              </ul>
            </section>
          ) : null}
          {d.published?.length ? (
            <section aria-label="Published">
              <h2 className={H2}>Published</h2>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
                {d.published.map((w) => <li key={w.id}><TextLink to={entityHref(w.id)}>{w.name}</TextLink></li>)}
              </ul>
            </section>
          ) : null}
          {d.citing?.length ? (
            <section aria-label="Cited as evidence">
              <h2 className={H2}>Cited as evidence · {plural(d.citing.length, 'post')}</h2>
              <ul className="mt-2 space-y-1">{d.citing.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
            </section>
          ) : null}
          {d.recommending?.length ? (
            <section aria-label="Recommended">
              <h2 className={H2}>Recommended · {plural(d.recommending.length, 'post')}</h2>
              <ul className="mt-2 space-y-1">{d.recommending.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
            </section>
          ) : null}
          {d.queue.length ? (
            <section aria-label="To review">
              <h2 className={H2}>To review</h2>
              <ul>{d.queue.map((item) => <QueueItem key={item.id} item={item} />)}</ul>
            </section>
          ) : null}
          {d.stories.map((s) => (
            <section key={s.story} aria-label={s.headline ?? 'A Mark X story'}>
              <h2 className={H2}>{s.headline ?? 'A Mark X story'} · {plural(s.voices, 'source')}</h2>
              <ul className="mt-2 space-y-1">{s.posts.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
            </section>
          ))}
          {d.loose.length ? (
            <section aria-label="In no story">
              <h2 className={H2}>In no Mark X story · {plural(d.loose.length, 'post')}</h2>
              <ul className="mt-2 space-y-1">{d.loose.map((p) => <EntityPostLine key={p.id} post={p} />)}</ul>
            </section>
          ) : null}
          <section aria-label="Sources">
            <h2 className={H2}>Sources</h2>
            <ul className="mt-2 text-[0.8125rem] text-fg-2">
              {d.sources.map((s) => (
                <li key={s.id} className="flex gap-3 border-t border-line py-1.5">
                  <span className="min-w-0 flex-1 truncate text-fg">{s.name ?? 'a source'}</span>
                  <span className="tabular-nums">{plural(s.posts, 'post')}{s.reports ? ` · ${s.reports} about it` : ''}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </PageHeader>
    </Page>
  );
}
