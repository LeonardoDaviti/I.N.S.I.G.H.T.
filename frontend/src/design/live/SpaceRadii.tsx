import { useLayoutEffect, useRef, useState } from 'react';
import Section from './Section';

/** The 0.25rem grid, as the literal classes (Tailwind only emits what it can read). */
const SPACES = [
  ['1', 'w-1'], ['2', 'w-2'], ['3', 'w-3'], ['4', 'w-4'], ['6', 'w-6'], ['8', 'w-8'], ['10', 'w-10'], ['16', 'w-16'],
] as const;

const RADII = [
  ['rounded-sm', 'chips, kbd'],
  ['rounded-md', 'rows, inputs, buttons'],
  ['rounded-lg', 'dialogs, sheets'],
  ['rounded-full', 'switch track'],
] as const;

/** A measured CSS value of the element, once it has rendered. */
function useMeasured<T extends HTMLElement>(read: (style: CSSStyleDeclaration) => string) {
  const ref = useRef<T>(null);
  const [value, setValue] = useState('');
  useLayoutEffect(() => {
    if (ref.current) setValue(read(getComputedStyle(ref.current)));
  }, [read]);
  return [ref, value] as const;
}

const readWidth = (style: CSSStyleDeclaration) => style.width;
/** A pill's radius is a huge number; call it what it is. */
const readRadius = (style: CSSStyleDeclaration) => (parseFloat(style.borderTopLeftRadius) >= 999 ? 'full' : style.borderTopLeftRadius);

function Space({ step, className }: { step: string; className: string }) {
  const [ref, width] = useMeasured<HTMLSpanElement>(readWidth);
  return (
    <li className="flex items-center gap-4 py-1.5">
      <span className="w-14 font-mono text-[0.75rem] text-fg-3">{step}</span>
      <span ref={ref} aria-hidden="true" className={`${className} block h-3 rounded-[1px] bg-fg`} />
      <span className="font-mono text-[0.75rem] tabular-nums text-fg-3">{width}</span>
    </li>
  );
}

function Radius({ className, use }: { className: string; use: string }) {
  const [ref, radius] = useMeasured<HTMLSpanElement>(readRadius);
  return (
    <li className="flex flex-col gap-2">
      <span ref={ref} aria-hidden="true" className={`${className} block h-14 w-full border border-line-strong bg-surface`} />
      <span className="font-mono text-[0.75rem] text-fg">{className}</span>
      <span className="text-[0.75rem] text-fg-3">{radius ? `${radius} · ` : ''}{use}</span>
    </li>
  );
}

/** Spacing and radii, measured live (P3): rem only, so 200% zoom holds. */
export default function SpaceRadii({ rules }: { rules?: string }) {
  return (
    <Section title="Space and radii" rules={rules}>
      <ul aria-label="Spacing">{SPACES.map(([step, className]) => <Space key={step} step={step} className={className} />)}</ul>
      <ul aria-label="Radii" className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {RADII.map(([className, use]) => <Radius key={className} className={className} use={use} />)}
      </ul>
    </Section>
  );
}
