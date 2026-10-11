import { useLayoutEffect, useRef, useState } from 'react';
import Section from './Section';

/** The type steps (system/typography.md), as the literal Tailwind classes the app uses. */
const STEPS = [
  { step: 'display', className: 'text-display', sample: 'A new feature for my blog, built with my voice' },
  { step: 'title', className: 'text-title', sample: 'Sources' },
  { step: 'heading', className: 'text-heading', sample: 'Connections' },
  { step: 'body', className: 'text-body', sample: 'Every state is a glyph plus a word.' },
  { step: 'reading', className: 'text-reading', sample: 'I added a small feature to my blog this morning.' },
  { step: 'small', className: 'text-small', sample: 'Simon Willison / Oct 10' },
  { step: 'micro', className: 'text-micro', sample: 'last run 14:20' },
] as const;

function Step({ step, className, sample }: (typeof STEPS)[number]) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [measure, setMeasure] = useState('');
  useLayoutEffect(() => {
    if (!ref.current) return;
    const style = getComputedStyle(ref.current);
    setMeasure(style.fontSize ? `${style.fontSize} / ${style.lineHeight} · ${style.fontWeight}` : '');
  }, []);
  return (
    <li className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-baseline gap-x-4 gap-y-1 border-b border-line py-3 last:border-b-0 sm:grid-cols-[5.5rem_minmax(0,1fr)_auto]">
      <span className="font-mono text-[0.75rem] text-fg-3">{step}</span>
      <p ref={ref} className={`${className} min-w-0 truncate text-fg`}>{sample}</p>
      <span className="col-start-2 font-mono text-[0.75rem] tabular-nums text-fg-3 sm:col-start-auto">{measure}</span>
    </li>
  );
}

/** The type scale, measured from the rendered samples (P3): hierarchy is size, weight and space. */
export default function TypeScale({ rules }: { rules?: string }) {
  return (
    <Section title="Type scale" rules={rules}>
      <ul>
        {STEPS.map((step) => <Step key={step.step} {...step} />)}
      </ul>
    </Section>
  );
}
