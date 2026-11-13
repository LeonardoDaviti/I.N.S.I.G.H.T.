import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Button, ExternalLink, Page, PageHeader, TextLink, Textarea } from '../components/ui';
import { ErrorState, LoadingState } from '../components/states';
import { folderReadPath } from '../lib/feedContext';
import { plural } from '../lib/format';
import { bylineText } from '../lib/byline';
import { scoutLine, unreadLine } from '../services/scout';
import {
  accountLine, referencesLine, researchApi, researchHref, seedWords, statusLine,
  type ResearchChannel, type ResearchPage as Data, type ResearchPaper, type ResearchPostRow,
} from '../services/research';

const H2 = 'border-b border-line pb-1 text-[0.8125rem] font-semibold text-fg-2';
const pageKey = (id: string) => ['markx-research', id] as const;

function Section({ label, count, children }: { label: string; count?: number; children: ReactNode }) {
  return (
    <section aria-label={label} className="mb-6">
      <h2 className={H2}>{label}{count !== undefined ? <span className="font-normal text-fg-3"> · {count}</span> : null}</h2>
      {children}
    </section>
  );
}

const New = ({ on }: { on?: boolean }) => (on ? <span className="ml-1 text-[0.6875rem] font-semibold uppercase text-fg">new</span> : null);

function PostRow({ p }: { p: ResearchPostRow }) {
  return (
    <li className="py-1 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
      <TextLink to={`/posts/${encodeURIComponent(p.post_id)}`}>{p.title || '(no title)'}</TextLink>
      <span className="text-fg-3">{[bylineText(p.byline, p.source), p.at ? new Date(p.at).toLocaleDateString() : null, p.why].filter(Boolean).map((x) => ` · ${x}`).join('')}</span>
      <New on={p.new} />
    </li>
  );
}

function PaperRow({ p }: { p: ResearchPaper }) {
  return (
    <li className="py-0.5 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
      {p.held ? <TextLink to={`/posts/${encodeURIComponent(p.held)}`}>{p.title || p.ref}</TextLink>
        : p.url ? <ExternalLink href={p.url}>{p.title || p.ref}</ExternalLink> : <span>{p.title || p.ref}</span>}
      <span className="text-fg-3">{[p.ref, p.date, p.held ? 'in INSIGHT' : 'not in INSIGHT', p.why].filter(Boolean).map((x) => ` · ${x}`).join('')}</span>
      <New on={p.new} />
    </li>
  );
}

function Channel({ runId, c, onDone }: { runId: string; c: ResearchChannel; onDone: () => void }) {
  const follow = useMutation({ mutationFn: () => researchApi.follow(runId, c.id), onSuccess: onDone });
  const not = useMutation({ mutationFn: () => researchApi.notThis(runId, c.id), onSuccess: onDone });
  const done = c.answer ?? (follow.isSuccess ? 'followed' : not.isSuccess ? 'not' : null);
  return (
    <li className="border-b border-line py-2" data-research-channel={c.id}>
      <p className="text-[0.8125rem] leading-5 text-fg [overflow-wrap:anywhere]" title={c.follow_address ?? c.address}>{scoutLine(c)}</p>
      {c.why ? <p className="text-[0.75rem] leading-5 text-fg-3">{c.why}</p> : null}
      <div className="mt-1 flex items-center gap-1" role="group" aria-label={`Follow ${c.name}?`}>
        {done ? <span className="text-[0.75rem] text-fg-2">{done === 'not' ? 'Not this one' : 'Followed'}</span> : (
          <>
            <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={follow.isPending || not.isPending}
              onClick={() => follow.mutate()}>Follow</Button>
            <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={follow.isPending || not.isPending}
              onClick={() => not.mutate()}>Not this one</Button>
          </>
        )}
        {follow.isError || not.isError ? <span role="alert" className="text-[0.75rem] text-fg">× not saved</span> : null}
      </div>
    </li>
  );
}

function Run({ runId }: { runId: string }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: pageKey(runId), queryFn: () => researchApi.page(runId), staleTime: 5_000,
    refetchInterval: (q) => (q.state.data?.run.status === 'running' ? 5_000 : q.state.data?.run.status === 'waiting' ? 30_000 : false),
  });
  const refresh = () => void client.invalidateQueries({ queryKey: pageKey(runId) });
  const rerun = useMutation({ mutationFn: () => researchApi.rerun(runId), onSuccess: (r) => navigate(researchHref(r.id)) });
  const watch = useMutation({ mutationFn: () => researchApi.watch(runId), onSuccess: refresh });
  const these = useMutation({
    mutationFn: ({ entity, ids, answer }: { entity: string; ids: string[]; answer: 'yes' | 'no' }) =>
      researchApi.answerSources(entity, ids, answer),
    onSuccess: refresh,
  });
  if (query.isPending) return <LoadingState label="Loading the research" rows={6} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Could not load the research" />;
  const d: Data = query.data;
  const seed = d.run.seed.length > 120 ? `${d.run.seed.slice(0, 117)}…` : d.run.seed;
  const entities = d.held.filter((h) => h.entity);
  const linking = d.held.filter((h) => h.post_id);
  const these_are = d.maker.these_are;
  const cannot = [...d.channels.cannot];
  return (
    <>
      <PageHeader
        title={<span className="[overflow-wrap:anywhere]">Research: {seed}</span>}
        meta={`From ${seedWords(d.run.seed_kind)} · ${statusLine(d)}`}
        actions={(
          <>
            {d.run.track_id ? <TextLink to={`${folderReadPath(d.run.track_id)}?view=topic`}>Watching it</TextLink>
              : <Button size="sm" variant="secondary" disabled={watch.isPending} onClick={() => watch.mutate()}>Watch this</Button>}
            <Button size="sm" variant="ghost" disabled={rerun.isPending} onClick={() => rerun.mutate()}>Run again</Button>
          </>
        )}
      />
      <Section label="In INSIGHT" count={entities.reduce((n, e) => n + (e.posts ?? 0), 0) + linking.length}>
        {entities.length || linking.length ? (
          <>
            {entities.map((h) => (
              <div key={h.key} className="mt-2">
                <p className="text-[0.875rem] text-fg">
                  <TextLink to={`/markx/entities/${encodeURIComponent(h.entity!.id)}`}>{h.entity!.name}</TextLink>
                  <span className="text-[0.8125rem] text-fg-3"> · {plural(h.posts ?? 0, 'post')} · {plural(h.stories ?? 0, 'story', 'stories')} · {plural(h.voices ?? 0, 'voice')}</span>
                </p>
                <ul>{(h.newest ?? []).slice(0, 8).map((p) => <PostRow key={p.post_id} p={p} />)}</ul>
              </div>
            ))}
            {linking.length ? (
              <ul aria-label="Posts linking it" className="mt-2">{linking.map((h) => <PostRow key={h.key} p={h as unknown as ResearchPostRow} />)}</ul>
            ) : null}
          </>
        ) : <p className="mt-2 text-[0.8125rem] text-fg-2">INSIGHT holds nothing of it yet.</p>}
        {d.entities.length ? (
          <ul aria-label="Names that may be one thing" className="mt-2 text-[0.75rem] text-fg-3">
            {d.entities.map((x) => (
              <li key={x.id ?? x.name}>
                {x.proposed ? `${x.name}: ${x.why}` : <>{x.id ? <TextLink to={`/markx/entities/${encodeURIComponent(x.id)}`} muted>{x.name}</TextLink> : x.name}: may be the same thing ({x.why})</>}
              </li>
            ))}
          </ul>
        ) : null}
      </Section>
      {d.same_post.length ? (
        <Section label="The same announcement elsewhere" count={d.same_post.length}>
          <ul>{d.same_post.map((p) => <PostRow key={p.post_id} p={p} />)}</ul>
        </Section>
      ) : null}
      <Section label="The maker" count={d.maker.accounts.length}>
        {d.maker.accounts.length ? (
          <ul className="mt-1">
            {d.maker.accounts.map((a) => (
              <li key={a.key} className="py-0.5 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
                {a.address?.startsWith('http') ? <ExternalLink href={a.address}>{accountLine(a)}</ExternalLink> : accountLine(a)}<New on={a.new} />
              </li>
            ))}
          </ul>
        ) : <p className="mt-2 text-[0.8125rem] text-fg-2">No maker found yet.</p>}
        {d.maker.asking.length ? (
          <p className="mt-1 text-[0.75rem] text-fg-3">
            Not sure yet: {d.maker.asking.map((a) => `${accountLine(a)}${a.same === 'pending' ? ' (asking Haiku)' : ''}`).join('; ')}
          </p>
        ) : null}
        {d.maker.not_same.length ? (
          <p className="mt-1 text-[0.75rem] text-fg-3">Not the maker: {d.maker.not_same.map((a) => accountLine(a)).join('; ')}</p>
        ) : null}
        {these_are?.proposed.length ? (
          <p className="mt-2 flex flex-wrap items-center gap-x-3 text-[0.8125rem] text-fg-2">
            <span>These are {these_are.entity.name}: {these_are.proposed.map((s) => s.name).join(', ')}?</span>
            <Button size="sm" variant="secondary" disabled={these.isPending}
              onClick={() => these.mutate({ entity: these_are.entity.id, ids: these_are.proposed.map((s) => s.id), answer: 'yes' })}>Yes</Button>
            <Button size="sm" variant="secondary" disabled={these.isPending}
              onClick={() => these.mutate({ entity: these_are.entity.id, ids: these_are.proposed.map((s) => s.id), answer: 'no' })}>No</Button>
          </p>
        ) : null}
      </Section>
      <Section label="Channels to follow" count={d.channels.to_follow.length}>
        {d.channels.to_follow.length ? (
          <ul>{d.channels.to_follow.map((c) => <Channel key={c.id} runId={runId} c={c} onDone={refresh} />)}</ul>
        ) : <p className="mt-2 text-[0.8125rem] text-fg-2">{d.channels.unread.length ? `${plural(d.channels.unread.length, 'channel')} to read.` : 'None found yet.'}</p>}
      </Section>
      {d.papers.seed.length ? (
        <Section label="Papers">
          <ul>{d.papers.seed.map((p) => <PaperRow key={`s${p.ref}`} p={p} />)}</ul>
          <h3 className="mt-3 text-[0.75rem] font-medium text-fg-3">{referencesLine(d.papers)}</h3>
          <ul>{[...d.papers.reference].sort((a, b) => Number(!!b.held) - Number(!!a.held)).map((p) => <PaperRow key={`r${p.ref}`} p={p} />)}</ul>
          {d.papers.citing.length ? <><h3 className="mt-3 text-[0.75rem] font-medium text-fg-3">Citing it · {d.papers.citing.length}</h3>
            <ul>{d.papers.citing.map((p) => <PaperRow key={`c${p.ref}`} p={p} />)}</ul></> : null}
          {d.papers.newer.length ? <><h3 className="mt-3 text-[0.75rem] font-medium text-fg-3">Its authors’ newer papers · {d.papers.newer.length}</h3>
            <ul>{d.papers.newer.map((p) => <PaperRow key={`n${p.ref}`} p={p} />)}</ul></> : null}
        </Section>
      ) : null}
      <Section label="Discussion found" count={d.discussion.length}>
        {d.discussion.length ? (
          <ul>
            {d.discussion.map((x) => (
              <li key={x.url} className="py-0.5 text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
                <ExternalLink href={x.url}>{x.title || x.url}</ExternalLink>
                <span className="text-fg-3"> · {x.where} · {x.why}</span><New on={x.new} />
              </li>
            ))}
          </ul>
        ) : <p className="mt-2 text-[0.8125rem] text-fg-2">No discussion found that names it exactly.</p>}
      </Section>
      {d.unread.length || cannot.length ? (
        <Section label="What could not be read" count={d.unread.length + cannot.length}>
          <ul className="mt-1 text-[0.75rem] leading-5 text-fg-3">
            {cannot.map((c) => <li key={c.id} className="[overflow-wrap:anywhere]">{unreadLine(c)}</li>)}
            {d.unread.map((u) => <li key={u.key} className="[overflow-wrap:anywhere]">{u.url ?? u.ref ?? u.query ?? u.key}: {u.why}</li>)}
          </ul>
        </Section>
      ) : null}
    </>
  );
}

function Start() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [seed, setSeed] = useState(params.get('seed') ?? '');
  const runs = useQuery({ queryKey: ['markx-research-runs'], queryFn: () => researchApi.runs(), staleTime: 30_000 });
  const start = useMutation({ mutationFn: () => researchApi.start(seed), onSuccess: (r) => navigate(researchHref(r.id)) });
  return (
    <>
      <PageHeader title="Research" meta="A link, a name, a post you paste or a question: INSIGHT finds what it has, the maker, its channels, its papers and who discusses it." />
      <form className="mb-8" onSubmit={(e) => { e.preventDefault(); if (seed.trim()) start.mutate(); }}>
        <label htmlFor="research-seed" className="text-[0.8125rem] text-fg-2">What to research</label>
        <Textarea id="research-seed" value={seed} onChange={(e) => setSeed(e.target.value)} className="mt-1 w-full"
          placeholder="https://… or a name, a pasted post, a question" />
        <Button type="submit" size="sm" className="mt-2" disabled={!seed.trim() || start.isPending}>Research this</Button>
        {start.isError ? <p role="alert" className="mt-1 text-[0.8125rem] text-fg">× {(start.error as Error).message}</p> : null}
      </form>
      {runs.data?.length ? (
        <Section label="Earlier research" count={runs.data.length}>
          <ul>
            {runs.data.map((r) => (
              <li key={r.id} className="py-0.5 text-[0.8125rem] text-fg-2 [overflow-wrap:anywhere]">
                <TextLink to={researchHref(r.id)}>{r.seed.length > 90 ? `${r.seed.slice(0, 87)}…` : r.seed}</TextLink>
                <span className="text-fg-3"> · {seedWords(r.seed_kind)} · {r.status}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </>
  );
}

/**
 * Research (issue 0162, Mark X): `/research` starts one (a textarea: a link, a name, a pasted post or a question;
 * `?seed=` fills it), `/research/:runId` is a run's page, kept: In INSIGHT, the same announcement elsewhere, the
 * maker (with "These are <name>: yes / no"), channels to follow (Follow / Not this one), papers, discussion found, and
 * what could not be read and why; Watch this makes a track of it; Run again shows what is new.
 */
export default function ResearchPage() {
  const { runId } = useParams();
  return <Page width="reading">{runId ? <Run runId={runId} /> : <Start />}</Page>;
}
