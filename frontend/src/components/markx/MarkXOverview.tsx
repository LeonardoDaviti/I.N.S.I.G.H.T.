import { useState, type ReactElement } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type {
  MarkxEntitiesGuide, MarkxEntityInvariants, MarkxJob, MarkxOverview, MarkxSettings, MarkxStoryWindow,
} from '../../services/markx';
import { request } from '../../lib/request';   // 0133
import { Button, TextLink } from '../ui';
import { EmptyState, ErrorState, LoadingState } from '../states';
import { feedFullTime, postBylineTime } from '../../lib/dates';
import { formatCount, plural } from '../../lib/format';
import { errorMessage } from '../../lib/apiError';
import { usd } from '../../lib/markx';

const OVERVIEW_KEY = ['markx-overview'] as const;

function useOverview() {
  const api = useApi();
  return useQuery({
    queryKey: [...OVERVIEW_KEY], queryFn: () => api.getMarkxOverview(), staleTime: 30_000,
    // while a decision run runs or is waited for, the page follows it
    refetchInterval: (q) => {
      const job = q.state.data?.worker.jobs?.decide;
      return job && (job.running || job.wanted_at) ? 5_000 : false;
    },
  });
}

/** The decision job's state (issue 0112 Decided 12): running with its stage; else asked for, and under it how the
 *  last run stopped (a stopped run is always asked again, so the stop line must not wait for the ask to clear:
 *  issue 0124, the v10.0.2 review's W6). */
export function DecisionJob({ job }: { job: MarkxJob | undefined }) {
  if (!job) return null;
  const lines: string[] = [];
  if (job.running) {
    lines.push(`Deciding now: ${job.stage ?? 'starting'}${job.started_at ? ` · started ${postBylineTime(job.started_at)}` : ''}`);
  } else {
    if (job.wanted_at) lines.push('A decision run is asked for: it starts within a few minutes.');
    if (job.last && job.last.ok === false && job.last.error) {
      lines.push(`The last decision run stopped: ${job.last.error}. It runs again within 5 minutes.`);
    }
  }
  if (!lines.length) return null;
  return (
    <>
      {lines.map((text) => <p key={text} className="mt-2 text-[0.8125rem] tabular-nums text-fg-2" role="status">{text}</p>)}
    </>
  );
}

function Loaded({ children }: { children: (data: MarkxOverview) => ReactElement }) {
  const query = useOverview();
  if (query.isPending) return <LoadingState label="Loading" rows={4} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  return children(query.data);
}

const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';

/** Today's briefing (F12), each line with the Mark X stories it cites. */
export function MarkXBriefing() {
  return (
    <Loaded>
      {({ briefing }) => {
        const latest = briefing.briefings[0];
        if (!latest) {
          return <EmptyState title="No briefing yet"
            description="Haiku writes one each day after 20:00, from the day's top Mark X News rows, once the worker answers it." />;
        }
        return (
          <section aria-label="Briefing">
            <p className="text-[0.8125rem] text-fg-2">
              {briefing.day} · {latest.guide ?? 'briefing'} · written {postBylineTime(latest.created_at)}
            </p>
            <ol className="mt-4 space-y-3">
              {latest.lines.map((line, n) => (
                <li key={n} className="text-[0.9375rem] leading-[1.55] text-fg [overflow-wrap:anywhere]">
                  {line.text}
                  {line.rows?.length ? (
                    <span className="ml-1 text-[0.75rem] text-fg-3">
                      {line.rows.map((row, k) => (
                        <a key={row} href={`#mx-${row}`} className="ml-1 underline decoration-fg-3/60 underline-offset-2 hover:text-fg">
                          {line.keys[k] ?? `s${k + 1}`}
                        </a>
                      ))}
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
          </section>
        );
      }}
    </Loaded>
  );
}

/** The main-subject entities (F7, a first look; pages and timelines are 0090). */
export function MarkXEntities() {
  return (
    <Loaded>
      {({ entities }) => (
        <div className="grid gap-8 lg:grid-cols-2">
          {(['today', 'week'] as const).map((when) => (
            <section key={when} aria-label={when === 'today' ? 'Today' : 'This week'}>
              <h2 className={H2}>{when === 'today' ? 'Today' : 'This week'}</h2>
              {entities[when].length === 0 ? (
                <p className="mt-3 text-[0.8125rem] text-fg-3">No main subject read {when === 'today' ? 'today' : 'this week'}.</p>
              ) : (
                <ul>
                  {entities[when].map((e) => (
                    <li key={`${e.key}|${e.version ?? ''}`} className="border-b border-line py-2.5">
                      <span className="flex flex-wrap items-baseline gap-x-2">
                        <span className="text-[0.9375rem] font-semibold text-fg [overflow-wrap:anywhere]">{e.name}</span>
                        <span className="text-[0.75rem] text-fg-3">{e.type}{e.version ? ` · ${e.version}` : ''}</span>
                        <span className="ml-auto text-[0.8125rem] tabular-nums text-fg-2">
                          {plural(e.voices, 'source')} · {plural(e.posts, 'post')}
                        </span>
                      </span>
                      <ul className="mt-1 space-y-0.5">
                        {e.examples.slice(0, 3).map((p) => (p.id ? (
                          <li key={p.id} className="min-w-0 truncate text-[0.8125rem] text-fg-2">
                            <TextLink to={`/posts/${encodeURIComponent(p.id)}`} muted>{p.title || '(no title)'}</TextLink>
                            <span className="text-fg-3"> · {p.source}</span>
                          </li>
                        ) : null))}
                      </ul>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}
    </Loaded>
  );
}

const STATUSES = ['open', 'leased', 'answered', 'failed'] as const;

const WINDOWS: { label: string; days: number | null }[] = [
  { label: '30 days', days: 30 }, { label: '120 days', days: 120 }, { label: 'everything', days: null },
];

/** The read, entities and embed planners' window (issue 0112): 30 days, 120, everything, or a number of days. It counts
 *  from the next planner run, with no restart; `markx-worker cycle --days` reads any other window on its own leases. */
function ReadingWindow({ days }: { days: number | null }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [own, setOwn] = useState('');
  const save = useMutation({
    mutationFn: (d: number | null) => api.setMarkxReadingWindow(d),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: [...OVERVIEW_KEY] }); },
  });
  const chosen = save.isPending ? save.variables : days;
  const custom = chosen !== null && chosen !== undefined && !WINDOWS.some((w) => w.days === chosen);
  const n = Number(own);
  const valid = Number.isInteger(n) && n >= 1 && n <= 36500;
  return (
    <section aria-label="Reading window">
      <h2 className={H2}>Reading window</h2>
      <p className="mt-3 text-[0.8125rem] text-fg-2">
        The worker reads {chosen === null ? 'every post' : `the last ${plural(chosen ?? 30, 'day')}`}: readings, entities and
        embeddings. A change counts from the next lease. The decisions follow the story window.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[0.8125rem]" role="radiogroup" aria-label="Reading window">
        {WINDOWS.map((w) => (
          <label key={w.label} className="flex items-center gap-1.5 text-fg">
            <input type="radio" name="markx-window" checked={chosen === w.days} disabled={save.isPending}
                   onChange={() => save.mutate(w.days)} />
            {w.label}
          </label>
        ))}
        <span className="flex items-center gap-1.5 text-fg">
          <input type="number" min={1} max={36500} step={1} inputMode="numeric" aria-label="days" value={own}
                 placeholder={custom ? String(chosen) : 'days'} onChange={(e) => setOwn(e.target.value)}
                 className="w-20 rounded border border-line bg-transparent px-1.5 py-0.5 tabular-nums" />
          <Button size="sm" variant="secondary" disabled={!valid || save.isPending} onClick={() => { save.mutate(n); setOwn(''); }}>
            set
          </Button>
        </span>
        {save.isError ? <span className="text-fg">× {errorMessage(save.error)}</span> : null}
      </div>
    </section>
  );
}

const STORY_WINDOWS: { label: string; days: number | null }[] = [
  { label: '30 days', days: 30 }, { label: '120 days', days: 120 }, { label: '365 days', days: 365 }, { label: 'everything', days: null },
];
type SetStoryWindow = (days: number | null) => Promise<MarkxSettings>;
/** The story window's call, here (in this tab's chunk) and not in api.ts; a test's fake api may provide it. */
function storyWindowApi(api: object): { setMarkxStoryWindow: SetStoryWindow } {
  const got = (api as { setMarkxStoryWindow?: unknown }).setMarkxStoryWindow;
  return { setMarkxStoryWindow: typeof got === 'function' ? (got as SetStoryWindow)
    : (days) => request('/api/markx/settings/story-window', { method: 'POST', body: { days } }) };
}
const pctOf = (p: number | null) => (p === null ? '–' : `${Math.round(p * 100)}%`);

/** 0144 A: how far back the decision run makes Mark X's own stories: 30 days, 120, 365 or everything. Past 30 days the
 *  window grows back a week a run, newest first, once that week's candidates are found and its questions asked; News
 *  keeps its own window. With everything, the old stories' precision (labelled on the entity pages) must stay at 97%
 *  or the window falls back, and says why. */
export function StoryWindow({ state }: { state: MarkxStoryWindow }) {
  const api = storyWindowApi(useApi());
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (d: number | null) => api.setMarkxStoryWindow(d),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: [...OVERVIEW_KEY] }); },
  });
  const chosen = save.isPending ? save.variables : state.days;
  const { old, recent } = state.precision;
  return (
    <section aria-label="Story window">
      <h2 className={H2}>Story window</h2>
      <p className="mt-3 text-[0.8125rem] text-fg-2">
        Mark X makes its own stories over {chosen === null ? 'every post' : `the last ${plural(chosen ?? 30, 'day')}`}.
        {' '}A run decides the last {plural(state.run_days, 'day')}{state.reached ? `, back to ${state.reached}` : ''};
        past 30 days it reaches a week further back a run, newest first. News keeps its own window.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[0.8125rem]" role="radiogroup" aria-label="Story window">
        {STORY_WINDOWS.map((w) => (
          <label key={w.label} className="flex items-center gap-1.5 text-fg">
            <input type="radio" name="markx-story-window" checked={chosen === w.days} disabled={save.isPending}
                   onChange={() => save.mutate(w.days)} />
            {w.label}
          </label>
        ))}
        {save.isError ? <span className="text-fg">× {errorMessage(save.error)}</span> : null}
      </div>
      <p className="mt-2 text-[0.8125rem] tabular-nums text-fg-2">
        Stories older than 30 days: {pctOf(old.precision)} right ({old.right} of {old.right + old.wrong}{old.missed ? `, ${old.missed} missed a post` : ''})
        {' '}· newer: {pctOf(recent.precision)} ({recent.right} of {recent.right + recent.wrong}) · everything needs {pctOf(state.keep)} on {state.min_labels}+
      </p>
      {state.fallback ? <p className="mt-1 text-[0.8125rem] text-fg">Back to {plural(state.fallback.days, 'day')}: {state.fallback.why}.</p> : null}
    </section>
  );
}

/** 0133: which guide new entities tasks are asked under. ent-v3 (1,500 characters) is the default; ent-v4 reads 6,000
 *  with the citation rule, and stays disabled while it is the lab's placeholder. A new guide plans new tasks for the
 *  reading window, newest first; the old answers stay, and each post shows the newest. */
type SetGuide = (guide: string) => Promise<{ entities_guide: MarkxEntitiesGuide }>;
/** The switch's call, here (in this tab's chunk) and not in api.ts (the feed route's bundle): a test's fake api may
 *  provide it. A placeholder guide is refused (409) until the lab's frozen guide replaces it. */
function markxEntitiesGuideApi(api: object): { setMarkxEntitiesGuide: SetGuide } {
  const got = (api as { setMarkxEntitiesGuide?: unknown }).setMarkxEntitiesGuide;
  return { setMarkxEntitiesGuide: typeof got === 'function' ? (got as SetGuide)
    : (guide) => request('/api/markx/settings/entities-guide', { method: 'POST', body: { guide } }) };
}

function EntitiesGuide({ state }: { state: MarkxEntitiesGuide }) {
  const api = markxEntitiesGuideApi(useApi());
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (g: string) => api.setMarkxEntitiesGuide(g),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: [...OVERVIEW_KEY] }); },
  });
  const chosen = save.isPending ? save.variables : state.guide;
  return (
    <section aria-label="Entities guide">
      <h2 className={H2}>Entities guide</h2>
      <p className="mt-3 text-[0.8125rem] text-fg-2">
        New entities tasks are asked under {chosen}. A change plans new tasks for the reading window; old answers stay.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[0.8125rem]" role="radiogroup" aria-label="Entities guide">
        {state.arms.map((a) => (
          <label key={a.guide} className="flex items-center gap-1.5 text-fg">
            <input type="radio" name="markx-entities-guide" checked={chosen === a.guide} disabled={save.isPending || !a.ready}
                   onChange={() => save.mutate(a.guide)} />
            {a.guide} · {a.chars.toLocaleString('en-US')} characters{a.rule ? ' · citation rule' : ''}
            {a.ready ? '' : ' · waiting for the lab’s guide'}{a.note ? ` · ${a.note}` : ''}
          </label>
        ))}
        {save.isError ? <span className="text-fg">× {errorMessage(save.error)}</span> : null}
      </div>
      {state.labels ? <Precision got={state.labels} /> : null}
    </section>
  );
}

const pct = (x: number | null) => (x == null ? '–' : `${Math.round(x * 100)}%`);

/** 0133 v4.2: the running precision of ent-v4.2's new entities from the owner's labels (Wilson 95%), the second
 *  question's alone, the lab's stated line and the bar for leaving Shadow. */
function Precision({ got }: { got: NonNullable<MarkxEntitiesGuide['labels']> }) {
  return (
    <section aria-label={`${got.guide} precision`} className="mt-2 text-[0.8125rem] text-fg-2">
      <p>
        {got.guide}, the owner’s labels: {got.labelled
          ? `${got.right} of ${got.labelled} new entities right: ${pct(got.precision)} (95% from ${pct(got.low)} to ${pct(got.high)})`
          : 'no new entity labelled yet (✓ / ✗ on the post panel)'}
        {got.q2.labelled ? ` · second question: ${got.q2.right} of ${got.q2.labelled} right: ${pct(got.q2.precision)}` : ''}
      </p>
      <p className="text-fg-3">
        {got.lab} · leaves Shadow at {got.leave_at.labelled}+ labelled with the lower bound ≥ {pct(got.leave_at.low)}
      </p>
    </section>
  );
}

/** 0164 C: the entity invariants the last run counted; a warning when a group holds a product family and an org. */
export function EntityInvariants({ state }: { state: MarkxEntityInvariants | null | undefined }) {
  const got = state?.family_org;
  if (!got || got.count === 0) return null;
  const held = got.held ? ` (${plural(got.held, 'group')} held together by your own merges)` : '';
  return (
    <div className="mt-3 text-[0.8125rem] text-fg" role="alert" aria-label="Entity invariant">
      <p className="[overflow-wrap:anywhere]">
        ⚠ {plural(got.count, 'entity group')} hold{got.count === 1 ? 's' : ''} both a product family and an org{held}; it should be none.
      </p>
      <ul className="mt-1 text-fg-2">
        {got.clusters.map((c) => (
          <li key={c.id} className="border-t border-line py-1 [overflow-wrap:anywhere]">
            <TextLink to={`/markx/entities/${encodeURIComponent(c.id)}`}>{c.name ?? c.id}</TextLink>
            {' · '}family {c.family.join(', ')} · org {c.org.join(', ')}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The worker's side: the queue by kind, answers per day, tokens and their API price, failures, contacts, the last run. */
export function MarkXWorker() {
  const api = useApi();
  const queryClient = useQueryClient();
  const run = useMutation({
    mutationFn: () => api.runMarkxDecisions(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [...OVERVIEW_KEY] });
      void queryClient.invalidateQueries({ queryKey: ['markx-news'] });
    },
  });
  return (
    <Loaded>
      {({ worker, reading_window: readingWindow, story_window: storyWindow, entities_guide: entitiesGuide,
         entity_invariants: entityInvariants }) => {
        const kinds = Object.keys(worker.queue).sort();
        const counts = worker.last_run?.counts as Record<string, unknown> | null | undefined;
        return (
          <div className="space-y-10">
            <ReadingWindow days={readingWindow ? readingWindow.days : 30} />
            {storyWindow ? <StoryWindow state={storyWindow} /> : null}
            {entitiesGuide ? <EntitiesGuide state={entitiesGuide} /> : null}
            <section aria-label="Queue">
              <h2 className={H2}>Queue</h2>
              {kinds.length === 0 ? <p className="mt-3 text-[0.8125rem] text-fg-3">No task yet.</p> : (
                <div className="overflow-x-auto">
                  <table className="mt-2 w-full min-w-[26rem] text-left text-[0.8125rem] tabular-nums">
                    <thead className="text-fg-3">
                      <tr><th className="py-1.5 font-medium">kind</th>{STATUSES.map((s) => <th key={s} className="py-1.5 text-right font-medium">{s}</th>)}</tr>
                    </thead>
                    <tbody>
                      {kinds.map((kind) => (
                        <tr key={kind} className="border-t border-line">
                          <td className="py-1.5 text-fg">{kind}</td>
                          {STATUSES.map((s) => <td key={s} className="py-1.5 text-right text-fg-2">{formatCount(worker.queue[kind][s] ?? 0)}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            <section aria-label="Answers">
              <h2 className={H2}>Answers and tokens</h2>
              <p className="mt-3 text-[0.8125rem] tabular-nums text-fg-2">
                {plural(worker.tokens.calls, 'answer')} · {formatCount(worker.tokens.tokens_in)} tokens in, {formatCount(worker.tokens.tokens_out)} out ·
                {' '}{usd(worker.tokens.api_usd)} on the API (Haiku 5.5){worker.tokens.paid_usd ? ` · ${usd(worker.tokens.paid_usd)} reported` : ''}
              </p>
              {worker.days.length ? (
                <ul className="mt-2 text-[0.8125rem] tabular-nums text-fg-2">
                  {worker.days.map((d) => (
                    <li key={d.day} className="flex gap-3 border-t border-line py-1.5">
                      <span className="w-24 shrink-0 text-fg">{d.day}</span>
                      <span>{d.valid} valid of {d.calls}</span>
                      <span className="ml-auto">{usd(d.api_usd)}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
            <section aria-label="Failures">
              <h2 className={H2}>Failures</h2>
              {worker.failed.length === 0 && worker.invalid.length === 0 ? (
                <p className="mt-3 text-[0.8125rem] text-fg-3">None.</p>
              ) : (
                <ul className="mt-2 text-[0.8125rem] text-fg-2">
                  {worker.failed.map((f, n) => (
                    <li key={`f${n}`} className="border-t border-line py-1.5 [overflow-wrap:anywhere]">
                      <span className="text-fg">{f.kind}</span> · {plural(f.tasks, 'task')} failed · {f.error}
                    </li>
                  ))}
                  {worker.invalid.map((f, n) => (
                    <li key={`i${n}`} className="border-t border-line py-1.5 [overflow-wrap:anywhere]">
                      <span className="text-fg">{f.kind}</span> · invalid {postBylineTime(f.at)} · {f.error}
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-label="Workers and runs">
              <h2 className={H2}>Workers and the last decision run</h2>
              <ul className="mt-2 text-[0.8125rem] text-fg-2">
                {worker.workers.length === 0 ? <li className="py-1.5 text-fg-3">No worker has called since the API started.</li> : null}
                {worker.workers.map((w) => (
                  <li key={w.worker} className="border-t border-line py-1.5">
                    <span className="text-fg">{w.worker}</span> · last contact {w.last_contact ? postBylineTime(w.last_contact) : 'not since the start'}
                    {w.leased ? ` · ${plural(w.leased, 'task')} leased` : ''}
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-[0.8125rem] tabular-nums text-fg-2" title={worker.last_run ? feedFullTime(worker.last_run.started_at) : undefined}>
                {worker.last_run ? (
                  <>
                    Last run {postBylineTime(worker.last_run.started_at)} ({worker.last_run.code_version})
                    {counts ? ` · ${String(counts.stories ?? 0)} stories · ${String(counts.answered ?? 0)} answers read` : ''}
                  </>
                ) : 'No decision run yet.'}
              </p>
              <DecisionJob job={worker.jobs?.decide} />
              <EntityInvariants state={entityInvariants} />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button size="sm" variant="secondary" onClick={() => run.mutate()} disabled={run.isPending} aria-busy={run.isPending || undefined}>
                  {run.isPending ? 'asking…' : 'run the decisions now'}
                </Button>
                {run.isError ? <span className="text-[0.8125rem] text-fg">× {errorMessage(run.error)}</span> : null}
                {run.isSuccess ? <span className="text-[0.8125rem] text-fg-2">asked</span> : null}
              </div>
            </section>
          </div>
        );
      }}
    </Loaded>
  );
}
