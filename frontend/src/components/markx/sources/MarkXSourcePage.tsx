import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';

import { Button, Page, PageHeader, Tabs, TabsContent, TabsList, TabsTrigger, TextLink } from '../../ui';
import { ErrorState, LoadingState } from '../../states';
import { useApi } from '../../../services/ApiContext';
import {
  markxSourcesApi, type MarkxEvidencePost, type MarkxSourceCard, type MarkxSourcePage as PageData,
  type MarkxSourceSignal, type MarkxSourceTab, type MarkxStanceAnswer,
} from '../../../services/api';
import { num, sourceHref, valueText } from './format';

const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';
const SIGNAL_TITLES: Record<string, string> = {
  channels: 'Channels', role: 'Role', own_share: 'Own share', forwards: 'Undeclared forwards', root_share: 'Story roots',
  perspectives: 'Perspectives', first_to_report: 'First to report', solo_share: 'Covered by nobody else',
  news_yield: 'News yield', cited_by: 'Cited by', kinds: 'Reading kinds', languages: 'Languages',
  media_only: 'Media only', per_week: 'Posts a week', age: 'First stored post', audience: 'Audience',
  followers: 'Subscribers or followers',
  reputation: 'Reputation', stance: 'Patterns',
};

type Ev = Record<string, unknown>;
const list = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

function PostLink({ post }: { post: MarkxEvidencePost }) {
  return (
    <li className="flex min-w-0 gap-2">
      <TextLink to={`/posts/${encodeURIComponent(post.id)}`} className="min-w-0 truncate">{post.title || 'a post'}</TextLink>
      {post.at ? <span className="shrink-0 text-fg-3">{post.at.slice(0, 10)}</span> : null}
    </li>
  );
}

function Posts({ posts, label }: { posts: unknown; label?: string }) {
  const ps = list<MarkxEvidencePost>(posts);
  if (!ps.length) return null;
  return (
    <div className="mt-1">
      {label ? <p className="text-fg-3">{label}</p> : null}
      <ul className="space-y-0.5">{ps.map((p) => <PostLink key={p.id} post={p} />)}</ul>
    </div>
  );
}

/** Each signal's evidence: the posts, stories, voices or rows it counted. */
function Evidence({ s, tab }: { s: MarkxSourceSignal; tab: MarkxSourceTab }) {
  const ev = s.evidence as Ev;
  switch (s.signal) {
    case 'channels': {
      const chans = list<{ id: string; name: string; kind: string; enabled: boolean; posts: number }>(ev.channels);
      const twice = list<{ other: string; other_name: string; other_enabled: boolean; address: string }>(ev.same_channel_twice);
      const related = list<{ voice: string; name: string | null; kind: string }>(ev.related);
      return (
        <div className="space-y-1">
          <ul>{chans.map((c) => (
            <li key={c.id}>{c.name} <span className="text-fg-3">{c.kind} · {num(c.posts)} posts{c.enabled ? '' : ' · off'}</span></li>
          ))}</ul>
          {twice.map((t) => (
            <p key={t.other} className="text-fg-2">The same channel twice: <TextLink to={sourceHref(t.other)}>{t.other_name}</TextLink>
              {' '}({t.address}{t.other_enabled ? '' : ', off'}). Disable one?</p>
          ))}
          {related.length ? <p className="text-fg-2">Related: {related.map((r) => r.name ?? 'a voice').join(', ')}</p> : null}
        </div>
      );
    }
    case 'role':
      return (
        <div>
          <p className="text-fg-2">{String(ev.line ?? '')}</p>
          {ev.needs_bio ? <p className="text-fg-2">Needs a bio: the stored posts can&apos;t tell staff from a beat writer.</p> : null}
          <Posts posts={ev.posts} />
        </div>
      );
    case 'own_share': {
      const who = list<{ author: string; posts: number }>(ev.reposted);
      return (
        <div>
          {ev.kind !== 'x' ? <p className="text-fg-3">Meaningful on X (and Telegram forwards when kept).</p> : null}
          {who.length ? <p className="text-fg-2">Reposts of {who.map((w) => `@${w.author} (${w.posts})`).join(', ')}</p> : null}
          <Posts posts={ev.posts} />
        </div>
      );
    }
    case 'forwards':
      return (
        <ul className="space-y-1">{list<MarkxEvidencePost & { original: MarkxEvidencePost; hours_later: number }>(ev.posts).map((p) => (
          <li key={p.id}><PostLink post={p} /> <span className="text-fg-3">{num(p.hours_later)} h after </span>
            <TextLink to={`/posts/${encodeURIComponent(p.original.id)}`} muted>{p.original.source ?? 'another source'}</TextLink></li>
        ))}</ul>
      );
    case 'first_to_report': {
      const st = list<{ story: string; title: string; first: boolean; next: string | null; first_voice: string | null; hours: number; post: string }>(ev.stories);
      return (
        <div>
          {ev.aggregator ? <p className="text-fg-2">Its posts carry the original page&apos;s date (an aggregator): first says little.</p> : null}
          <ul className="space-y-0.5">{st.map((x) => (
            <li key={x.story} className="min-w-0 truncate">
              <TextLink to={`/posts/${encodeURIComponent(x.post)}`}>{x.title || 'a story'}</TextLink>{' '}
              <span className="text-fg-3">{x.first ? `first; ${x.next ?? 'the next'} ${num(x.hours)} h later`
                : `${x.first_voice ?? 'another voice'} ${num(x.hours)} h earlier`}</span>
            </li>
          ))}</ul>
        </div>
      );
    }
    case 'solo_share':
      return <><Posts posts={ev.posts} label="Nobody else in your sources covered:" /><Posts posts={ev.covered} label="Covered by others:" /></>;
    case 'news_yield':
      return (
        <div>
          {ev.new_source ? <p className="text-fg-2">New source: added under 30 days ago.</p> : null}
          <p className="text-fg-3">{ev.news === 'markx' ? 'Mark X News' : 'News'}{ev.since ? ` since ${String(ev.since).slice(0, 10)}` : ''}</p>
          <Posts posts={ev.rows} />
        </div>
      );
    case 'cited_by': {
      const vs = list<{ voice: string; posts: number; example: MarkxEvidencePost }>(ev.voices);
      const cl = list<{ url: string; title: string; voices: number }>(ev.classic_rows);
      return (
        <div className="space-y-1">
          <ul className="space-y-0.5">{vs.map((v) => (
            <li key={v.voice} className="min-w-0 truncate">{v.voice} <span className="text-fg-3">{num(v.posts)} posts, e.g. </span>
              <TextLink to={`/posts/${encodeURIComponent(v.example.id)}`}>{v.example.title || 'a post'}</TextLink></li>
          ))}</ul>
          <p className="text-fg-2">{num(ev.classics)} Classics point at it{cl.length ? ':' : '.'}</p>
          {cl.length ? <ul>{cl.map((c) => <li key={c.url} className="truncate">{c.title || c.url} <span className="text-fg-3">{num(c.voices)} voices</span></li>)}</ul> : null}
          <p className="text-fg-3">{String(ev.bias ?? '')}</p>
        </div>
      );
    }
    case 'kinds': {
      const by = (ev.posts ?? {}) as Record<string, MarkxEvidencePost[]>;
      return <>{Object.entries(by).map(([k, ps]) => <Posts key={k} posts={ps} label={k} />)}</>;
    }
    case 'age':
      return (
        <p className="text-fg-2">
          Added {String(ev.added ?? '').slice(0, 10) || '—'}
          {ev.before_platform ? ' · its first date is before its platform existed: a bad date in the feed' : ''}
          {ev.new_source ? ' · new source' : ''}
        </p>
      );
    case 'audience':
      return <p className="text-fg-3">{String(ev.what ?? 'no audience data')}</p>;
    case 'followers': {
      // 0132 C2: each channel's profile count, as last fetched
      const chans = list<{ source: string; name: string; followers: number | null; label: string | null; fetched_at: string | null }>(ev.channels);
      if (!chans.length) return <p className="text-fg-3">{String(ev.what ?? 'no audience data')}</p>;
      return (
        <ul>{chans.map((c) => (
          <li key={c.source}>{c.name}{' '}
            <span className="text-fg-3">
              {c.followers === null ? 'its profile shows no count' : `${num(c.followers)} ${c.label ?? 'followers'}`}
              {c.fetched_at ? ` · read ${c.fetched_at.slice(0, 10)}` : ''}
            </span>
          </li>
        ))}</ul>
      );
    }
    case 'reputation':
      return <p className="text-fg-3">Inside your sources only.</p>;
    case 'stance':
      return <Stance s={s} tab={tab} />;
    case 'media_only':
    case 'root_share':
      return <Posts posts={ev.posts} />;
    default:
      return null;
  }
}

type Pattern = { pattern: string; kind: string | null; quotes: { post: number; quote: string; post_id: string | null }[] };

function Stance({ s, tab }: { s: MarkxSourceSignal; tab: MarkxSourceTab }) {
  const api = markxSourcesApi(useApi());
  const client = useQueryClient();
  const ev = s.evidence as Ev;
  const [labels, setLabels] = useState<Record<string, string>>((ev.labels ?? {}) as Record<string, string>);
  const tap = useMutation({
    mutationFn: ({ i, a }: { i: number; a: MarkxStanceAnswer }) => api.labelMarkxStance(String(ev.task), i, a),
    onSuccess: (got) => { setLabels(got.labels); void client.invalidateQueries({ queryKey: ['markx-source'] }); },
  });
  const patterns = list<Pattern>(ev.patterns);
  if (!ev.task) return <p className="text-fg-3">Not asked yet: the worker answers it monthly.</p>;
  if (!patterns.length) return <p className="text-fg-3">No pattern with 2 exact quotes from 2 posts.</p>;
  return (
    <ul className="space-y-3" data-tab={tab.id}>
      {patterns.map((p, i) => {
        const mine = labels[String(i)];
        const button = (a: 'right' | 'wrong', words: string) => (
          <Button size="sm" variant="ghost" aria-pressed={mine === a} disabled={tap.isPending}
            onClick={() => tap.mutate({ i, a: mine === a ? 'undo' : a })} className="text-[0.75rem]">{words}</Button>
        );
        return (
          <li key={i}>
            <p className="text-fg">{p.pattern}{p.kind ? <span className="text-fg-3"> · {p.kind}</span> : null}</p>
            <ul className="mt-1 space-y-0.5 border-l border-line pl-3 text-fg-2">
              {p.quotes.map((q, j) => (
                <li key={j}>“{q.quote}”{q.post_id ? <> <TextLink to={`/posts/${encodeURIComponent(q.post_id)}`} muted>post {q.post}</TextLink></> : <span className="text-fg-3"> post {q.post}</span>}</li>
              ))}
            </ul>
            <span className="mt-1 flex gap-2" role="group" aria-label="Is the pattern right?">
              {button('right', '✓ right')}{button('wrong', '✗ wrong')}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function SignalBlock({ s, tab }: { s: MarkxSourceSignal; tab: MarkxSourceTab }) {
  return (
    <div className="text-[0.8125rem]" data-signal={s.signal}>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-semibold text-fg">{SIGNAL_TITLES[s.signal] ?? s.signal}</span>
        {s.too_few ? (
          <span className="text-fg-2">too few to tell <span className="text-fg-3">({num(s.n)} {s.counts}; {s.min} needed)</span></span>
        ) : (
          <span className="tabular-nums text-fg">{s.signal === 'cited_by' ? `${num(s.value)} voices` : s.signal === 'forwards' ? num(s.value)
            : valueText(s.signal, s.value)} <span className="text-fg-3">· n {num(s.n)} {s.counts}</span></span>
        )}
      </div>
      <p className="text-[0.75rem] text-fg-3">{s.formula}</p>
      {!s.too_few ? <div className="mt-1"><Evidence s={s} tab={tab} /></div> : null}
    </div>
  );
}

export function SourceCard({ card, tab }: { card: MarkxSourceCard; tab: MarkxSourceTab }) {
  return (
    <section aria-label={card.title} data-card={card.card}>
      <h2 className={H2}>{card.title}{card.experimental ? <span className="ml-2 font-normal text-fg-3">Experimental</span> : null}</h2>
      <div className="mt-2 space-y-3">{card.signals.map((s) => <SignalBlock key={s.signal} s={s} tab={tab} />)}</div>
    </section>
  );
}

function TabBody({ tab }: { tab: MarkxSourceTab }) {
  return (
    <div className="space-y-6">
      {!tab.computed ? <p className="text-[0.8125rem] text-fg-2">Not computed yet: the stats job runs nightly and after a regroup.</p> : null}
      {tab.cards.map((c) => <SourceCard key={c.card} card={c} tab={tab} />)}
    </div>
  );
}

/**
 * A voice's or a source's analysis (0132 B, `/markx/sources/<id>`): a tab per channel (a voice's own first), one card
 * per signal, each with its number, a one-line formula, clickable evidence posts, and "too few to tell" below its
 * threshold. Rows only: the page computes nothing.
 */
export default function MarkXSourcePage() {
  const { sourceId = '' } = useParams();
  const api = markxSourcesApi(useApi());
  const query = useQuery({ queryKey: ['markx-source', sourceId], queryFn: () => api.getMarkxSource(sourceId), staleTime: 60_000 });
  if (query.isPending) return <Page><LoadingState label="Loading" rows={8} /></Page>;
  if (query.isError) return <Page><ErrorState error={query.error} onRetry={() => query.refetch()} /></Page>;
  const d: PageData = query.data;
  const role = d.tabs[0]?.cards.find((c) => c.card === 'who')?.signals.find((s) => s.signal === 'role');
  return (
    <Page>
      <PageHeader title={d.subject.name || 'A source'}
        meta={`${d.subject.kind === 'voice' ? `voice · ${d.tabs.length - 1} channels` : d.tabs[0]?.platform ?? 'source'}${role && !role.too_few ? ` · ${valueText('role', role.value)}` : ''}`}>
        <div className="space-y-6">
          <p className="text-[0.8125rem] text-fg-2">
            <TextLink to="/markx/sources" muted>Sources</TextLink>
            {d.subject.voice ? <> · a channel of <TextLink to={sourceHref(d.subject.voice.id)}>{d.subject.voice.name ?? 'its voice'}</TextLink></> : null}
            {d.computed_at ? ` · computed ${d.computed_at.slice(0, 16).replace('T', ' ')} UTC` : ''}
          </p>
          {d.tabs.length > 1 ? (
            <Tabs defaultValue={d.tabs[0].id}>
              <TabsList aria-label="Channels">
                {d.tabs.map((t) => <TabsTrigger key={t.id} value={t.id}>{t.kind === 'voice' ? 'All channels' : t.name}</TabsTrigger>)}
              </TabsList>
              {d.tabs.map((t) => <TabsContent key={t.id} value={t.id}><TabBody tab={t} /></TabsContent>)}
            </Tabs>
          ) : d.tabs[0] ? <TabBody tab={d.tabs[0]} /> : null}
          <p className="text-[0.75rem] text-fg-3">No overall score: each number stands with its formula and its evidence.</p>
        </div>
      </PageHeader>
    </Page>
  );
}
