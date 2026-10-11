import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Check, Copy } from 'lucide-react';

import Button from '../../components/ui/Button';
import { Input, Select } from '../../components/ui/Input';
import TextLink from '../../components/ui/TextLink';
import { writeToClipboard } from '../../lib/clipboard';
import { cn } from '../../lib/utils';
import Segmented from '../Segmented';
import Frame from '../frame/Frame';
import { frameScenario } from '../fixtures/scenarios';
import { DOCS, PRINCIPLES, PROTOTYPES, prototypeById } from '../library';
import { BENCH_DATA, benchSubjects, parseBench, type BenchPage, type BenchView } from '../bench';
import { acceptInstruction, isOpen, prototypeAge, rejectInstruction, type Prototype } from '../prototypes';
import { docSlug } from '../coverage';
import { docTitle, pageDocsInOrder } from '../studio';

const PAGES: BenchPage[] = pageDocsInOrder(DOCS).map((doc) => ({ name: docSlug(doc), title: docTitle(doc), states: doc.meta.states ?? [] }));
const CATALOG = { prototypes: PROTOTYPES, pages: PAGES, widthOf: (page: string, state: string) => frameScenario(page, state)?.width };
const SUBJECTS = benchSubjects(PROTOTYPES, PAGES);

/**
 * Bench mode (verdict C), the checkout for every new design feature: two
 * large frames side by side on the same fixtures, the current page against a
 * prototype (or one state of a page against another), with a shared state,
 * width, theme and data (fixtures, or the real API read-only). The drawer holds what the comparison is for and how it
 * ends; accept and reject are instructions to the agent, never browser
 * writes, because the docs are files (D6). On phones the panes stack.
 */
export default function BenchMode() {
  const [params, setParams] = useSearchParams();
  const view = parseBench(params, CATALOG);
  const prototype = view.prototype ? prototypeById(view.prototype) : undefined;

  /** One key of the address; a default value leaves the URL clean. */
  const set = (key: string, value: string, fallback: string) => setParams((current) => {
    const next = new URLSearchParams(current);
    if (value === fallback) next.delete(key);
    else next.set(key, value);
    return next;
  }, { replace: true });

  const chooseSubject = (subject: string) => setParams((current) => {
    const next = new URLSearchParams(current);
    for (const key of ['state', 'left', 'right', 'width']) next.delete(key);
    next.set('subject', subject);
    return next;
  });

  const widths = view.widths.map(String);

  return (
    <section aria-label="Bench" className="mx-auto w-full max-w-[120rem] px-4 pb-16 pt-5 sm:px-6">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <Select
          aria-label="On the bench"
          value={view.subject}
          onChange={(event) => chooseSubject(event.target.value)}
          className="w-full sm:w-auto sm:min-w-[16rem]"
        >
          {SUBJECTS.map((group) => (
            <optgroup key={group.label} label={group.label}>
              {group.subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.label}</option>)}
            </optgroup>
          ))}
        </Select>
        {prototype ? (
          <Segmented size="sm" label="State" value={view.left} options={view.states} onChange={(value) => set('state', value, view.states[0])} />
        ) : null}
        <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
          <Segmented size="sm" label="Width" value={String(view.width)} options={widths} onChange={(value) => set('width', value, widths[0])} />
          <Segmented size="sm" label="Data" value={view.data} options={BENCH_DATA} onChange={(value) => set('data', value, BENCH_DATA[0])} />
          <Segmented size="sm" label="Theme" value={view.theme} options={['dark', 'light']} onChange={(value) => set('theme', value, 'dark')} />
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={view.drawer}
            aria-controls="bench-drawer"
            onClick={() => set('doc', view.drawer ? 'hide' : 'show', 'show')}
          >
            Notes
          </Button>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-x-6 gap-y-8 md:grid-cols-2">
        {prototype ? (
          <>
            <Pane name="current" heading="current" detail={`${view.page} / ${view.left}`} view={view}>
              <Frame page={view.page} state={view.left} width={view.width} theme={view.theme} data={view.data} />
            </Pane>
            <Pane name="prototype" heading={`prototype · ${prototype.slug}`} detail={`${view.page} / ${view.left}`} view={view}>
              <Frame page={view.page} prototype={prototype.id} state={view.left} width={view.width} theme={view.theme} data={view.data} />
            </Pane>
          </>
        ) : (
          <>
            <Pane name="left" heading={view.page} view={view} control={
              <Segmented size="sm" label="Left state" value={view.left} options={view.states} onChange={(value) => set('left', value, view.states[0])} />
            }>
              <Frame page={view.page} state={view.left} width={view.width} theme={view.theme} data={view.data} />
            </Pane>
            <Pane name="right" heading={view.page} view={view} control={
              <Segmented size="sm" label="Right state" value={view.right} options={view.states} onChange={(value) => set('right', value, view.states[1] ?? view.states[0])} />
            }>
              <Frame page={view.page} state={view.right} width={view.width} theme={view.theme} data={view.data} />
            </Pane>
          </>
        )}
      </div>

      {view.drawer ? (
        <section id="bench-drawer" aria-label="About this comparison" className="mt-8 rounded-lg border border-line bg-surface px-5 py-5 sm:px-6">
          {prototype ? <PrototypeNotes prototype={prototype} /> : <PageNotes view={view} />}
        </section>
      ) : null}
    </section>
  );
}

/** One side of the bench: a caption, an optional control, the frame. */
function Pane({ name, heading, detail, control, view, children }: {
  name: string;
  heading: string;
  detail?: string;
  control?: ReactNode;
  view: BenchView;
  children: ReactNode;
}) {
  return (
    <figure aria-label={name} className="min-w-0">
      <figcaption className="mb-2.5 flex min-h-[1.875rem] flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <span className="min-w-0 truncate text-[0.8125rem] font-semibold text-fg">
          {heading}
          {detail ? <span className="ml-2 font-mono text-[0.75rem] font-normal text-fg-3">{detail}</span> : null}
        </span>
        {control ?? <span className="font-mono text-[0.75rem] tabular-nums text-fg-3">{view.width}px · {view.theme}</span>}
      </figcaption>
      <div className="flex justify-center">{children}</div>
    </figure>
  );
}

const LABEL = 'text-[0.8125rem] lowercase text-fg-3';

function PrototypeNotes({ prototype }: { prototype: Prototype }) {
  return (
    <div className="grid gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div className="min-w-0">
        <h2 className={LABEL}>hypothesis</h2>
        <p className="mt-1.5 max-w-reading text-pretty text-[1.0625rem] leading-[1.5] text-fg">{prototype.hypothesis}</p>
        <p className="mt-3 text-[0.8125rem] text-fg-3">
          <span className="text-fg-2">{`${prototype.status} · ${prototypeAge(prototype, new Date())}`}</span>
          {' · '}
          <TextLink to={`/design/prototypes/${prototype.id}`} muted>README</TextLink>
        </p>
        {prototype.docDiff ? (
          <div className="mt-7">
            <h2 className={LABEL}>page doc, if accepted</h2>
            <DocDiff diff={prototype.docDiff} />
          </div>
        ) : null}
      </div>
      <div className="min-w-0 space-y-7">
        <div>
          <h2 className={LABEL}>serves</h2>
          <ul className="mt-1.5 space-y-1">
            {prototype.principles.map((number) => (
              <li key={number}>
                <Link to="/design" className="text-link text-[0.9375rem] text-fg">
                  <span className="font-mono text-[0.8125rem] text-fg-3">P{number}</span> {PRINCIPLES.find((principle) => principle.n === number)?.title ?? 'unknown principle'}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        {isOpen(prototype) ? <Decide id={prototype.id} /> : (
          <p className="text-[0.875rem] text-fg-2">
            {prototype.status}: the agent deletes this folder and logs the decision (D6).
          </p>
        )}
      </div>
    </div>
  );
}

/** The page doc's states side by side, and the way to the doc. */
function PageNotes({ view }: { view: BenchView }) {
  const label = (state: string) => frameScenario(view.page, state)?.label ?? state;
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-10 gap-y-4">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[0.9375rem]">
        <dt className={LABEL}>left</dt><dd className="text-fg"><span className="font-mono text-[0.8125rem] text-fg-3">{view.left}</span> {label(view.left)}</dd>
        <dt className={LABEL}>right</dt><dd className="text-fg"><span className="font-mono text-[0.8125rem] text-fg-3">{view.right}</span> {label(view.right)}</dd>
      </dl>
      <TextLink to={`/design/pages/${view.page}`}>Read the {view.page} doc</TextLink>
    </div>
  );
}

/** A unified diff in one tone family (P2): added lines in the text colour, removed ones in the third tone. */
function DocDiff({ diff }: { diff: string }) {
  return (
    <pre className="mt-2 max-h-[22rem] overflow-auto rounded-md border border-line bg-bg px-4 py-3 font-mono text-[0.75rem] leading-[1.6]">
      {diff.trimEnd().split('\n').map((line, index) => {
        const head = /^(---|\+\+\+|@@)/.test(line);
        return (
          <span
            key={index}
            className={cn(
              'block whitespace-pre-wrap [overflow-wrap:anywhere]',
              head ? 'text-fg-3' : line.startsWith('+') ? 'font-semibold text-fg' : line.startsWith('-') ? 'text-fg-3' : 'text-fg-2',
            )}
          >
            {line || ' '}
          </span>
        );
      })}
    </pre>
  );
}

/** Accept or reject, as the exact words to give the agent (D6). */
function Decide({ id }: { id: string }) {
  const [reason, setReason] = useState('');
  return (
    <div>
      <h2 className={LABEL}>decide</h2>
      <p className="mt-1.5 text-[0.8125rem] leading-[1.5] text-fg-3">
        The docs are files, so the studio writes nothing. Give the agent one of these lines.
      </p>
      <Instruction name="accept" text={acceptInstruction(id)} ready />
      <label htmlFor="bench-reason" className="mt-5 block text-[0.8125rem] text-fg-2">Why reject it</label>
      <Input
        id="bench-reason"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="the reason the log keeps"
        className="mt-1.5 w-full"
      />
      <Instruction name="reject" text={rejectInstruction(id, reason)} ready={reason.trim().length > 0} />
    </div>
  );
}

const COPIED_MS = 1600;

/** One instruction, selectable, with a copy button that answers at once. */
function Instruction({ name, text, ready }: { name: string; text: string; ready: boolean }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => setState('idle'), [text]);

  const copy = async () => {
    window.clearTimeout(timer.current);
    try {
      await writeToClipboard(text);
      setState('copied');
    } catch {
      setState('failed');
    }
    timer.current = window.setTimeout(() => setState('idle'), COPIED_MS);
  };

  return (
    <div className="mt-2 flex items-stretch gap-2">
      <code className={cn(
        'min-w-0 flex-1 select-all rounded-md border border-line bg-bg px-3 py-1.5 font-mono text-[0.8125rem] leading-[1.5] [overflow-wrap:anywhere]',
        ready ? 'text-fg' : 'text-fg-3',
      )}>
        {text}
      </code>
      <Button
        size="sm"
        variant={name === 'accept' ? 'primary' : 'secondary'}
        aria-label={`Copy the ${name} instruction`}
        disabled={!ready}
        onClick={() => void copy()}
        className="w-[5.75rem] shrink-0"
      >
        {state === 'copied' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        <span aria-live="polite">{state === 'copied' ? 'Copied' : state === 'failed' ? 'Select it' : name}</span>
      </Button>
    </div>
  );
}
