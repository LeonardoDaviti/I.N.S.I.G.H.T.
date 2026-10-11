import { useId, useState, type ReactNode } from 'react';
import { Button, ExternalLink } from '../components/ui';
import { cn } from '../lib/utils';

/*
 * The blog's building blocks. Monochrome like the rest of the app
 * (plan/INSIGHT_mark_ix_design.md): hierarchy by weight, size and space, never hue.
 */

/** A section heading with an anchor, so a paragraph can be linked to. */
export function H2({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} className="mt-14 scroll-mt-20 text-[1.375rem] font-semibold leading-[1.25] tracking-[-0.02em] text-fg">
      <a href={`#${id}`} className="hover:underline">{children}</a>
    </h2>
  );
}

export function H3({ children }: { children: ReactNode }) {
  return <h3 className="mt-8 text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">{children}</h3>;
}

/** Body text at the reading step (1.125rem / 1.7). */
export function P({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn('mt-5 text-[1.125rem] leading-[1.7] text-fg', className)}>{children}</p>;
}

export function List({ children }: { children: ReactNode }) {
  return <ul className="mt-5 list-disc space-y-2 pl-6 text-[1.125rem] leading-[1.7] text-fg marker:text-fg-3">{children}</ul>;
}

export function C({ children }: { children: ReactNode }) {
  return <code className="rounded-sm bg-raised px-[0.3em] py-[0.1em] font-mono text-[0.875em] text-fg [overflow-wrap:anywhere]">{children}</code>;
}

/** A citation: an external link with a small superscript-free marker, read as "source". */
export function Cite({ href, children }: { href: string; children: ReactNode }) {
  return <ExternalLink href={href}>{children}</ExternalLink>;
}

/** A real code excerpt, with where it lives. */
export function Code({ caption, children }: { caption?: ReactNode; children: string }) {
  return (
    <figure className="mt-6">
      {caption ? <figcaption className="mb-1.5 font-mono text-[0.75rem] text-fg-3">{caption}</figcaption> : null}
      <pre className="overflow-x-auto rounded-md border border-line bg-surface p-4 font-mono text-[0.8125rem] leading-[1.6] text-fg">
        <code>{children.replace(/^\n/, '').replace(/\s+$/, '')}</code>
      </pre>
    </figure>
  );
}

/** Two excerpts side by side on wide screens, stacked on narrow ones. */
export function Compare({
  before,
  after,
  beforeLabel = 'before',
  afterLabel = 'after',
}: {
  before: string;
  after: string;
  beforeLabel?: string;
  afterLabel?: string;
}) {
  return (
    <div className="mt-6 grid gap-3 lg:-mx-24 lg:grid-cols-2">
      {[{ label: beforeLabel, code: before, loud: false }, { label: afterLabel, code: after, loud: true }].map(({ label, code, loud }) => (
        <div key={label} className="min-w-0">
          <span
            className={cn(
              'inline-block rounded-sm px-1.5 py-0.5 text-[0.75rem] font-medium lowercase',
              loud ? 'bg-inverse text-inverse-fg' : 'border border-line text-fg-2',
            )}
          >
            {label}
          </span>
          <pre className="mt-1.5 overflow-x-auto rounded-md border border-line bg-surface p-4 font-mono text-[0.8125rem] leading-[1.6] text-fg">
            <code>{code.replace(/^\n/, '').replace(/\s+$/, '')}</code>
          </pre>
        </div>
      ))}
    </div>
  );
}

/** A numbered figure: the visual, then a caption that says what to see. */
export function Figure({ n, caption, children, wide = false }: { n: number; caption: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <figure className={cn('mt-8', wide && 'lg:-mx-24')}>
      <div className="rounded-md border border-line bg-surface p-4 sm:p-6">{children}</div>
      <figcaption className="mt-2 text-[0.8125rem] leading-[1.45] text-fg-2">
        <span className="font-semibold text-fg">Figure {n}.</span> {caption}
      </figcaption>
    </figure>
  );
}

/** A quiet aside: the one thing to remember from a section. */
export function Takeaway({ children }: { children: ReactNode }) {
  return (
    <aside className="mt-6 border-l-2 border-fg pl-4 text-[1rem] leading-[1.6] text-fg">
      <span className="mr-1.5 font-semibold">Takeaway.</span>
      {children}
    </aside>
  );
}

export interface QuizQuestion {
  prompt: ReactNode;
  options: string[];
  answer: number;
  /** Why the answer is right; shown after checking, whatever was picked. */
  why: ReactNode;
}

/**
 * Retrieval practice: answer from memory, check, read why. Nothing is stored;
 * "try again" resets the question so it can be retrieved again later.
 */
export function Quiz({ questions }: { questions: QuizQuestion[] }) {
  return (
    <ol className="mt-6 space-y-6">
      {questions.map((q, i) => (
        <QuizItem key={i} index={i} question={q} />
      ))}
    </ol>
  );
}

function QuizItem({ index, question }: { index: number; question: QuizQuestion }) {
  const name = useId();
  const [picked, setPicked] = useState<number | null>(null);
  const [checked, setChecked] = useState(false);
  const right = checked && picked === question.answer;

  return (
    <li className="rounded-md border border-line bg-surface p-4">
      <fieldset>
        <legend className="text-[1rem] font-semibold leading-[1.5] text-fg">
          <span className="mr-1.5 tabular-nums text-fg-3">{index + 1}.</span>
          {question.prompt}
        </legend>
        <div className="mt-3 space-y-1.5">
          {question.options.map((option, i) => (
            <label
              key={option}
              className={cn(
                'flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-[0.9375rem] leading-[1.5]',
                checked && i === question.answer ? 'border-fg font-semibold text-fg' : 'border-line text-fg-2',
                !checked && 'hover:border-line-strong hover:text-fg',
              )}
            >
              <input
                type="radio"
                name={name}
                className="mt-1 accent-current"
                checked={picked === i}
                disabled={checked}
                onChange={() => setPicked(i)}
              />
              {option}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {checked ? (
          <Button size="sm" variant="ghost" onClick={() => { setPicked(null); setChecked(false); }}>
            Try again
          </Button>
        ) : (
          <Button size="sm" disabled={picked === null} onClick={() => setChecked(true)}>
            Check
          </Button>
        )}
        {checked ? (
          <p role="status" className="text-[0.875rem] font-semibold text-fg">
            {right ? '● Right.' : '× Not quite.'}
          </p>
        ) : null}
      </div>
      {checked ? <p className="mt-2 text-[0.9375rem] leading-[1.6] text-fg-2">{question.why}</p> : null}
    </li>
  );
}
