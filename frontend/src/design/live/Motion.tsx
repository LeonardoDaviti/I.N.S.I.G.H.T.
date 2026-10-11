import { useRef } from 'react';
import Button from '../../components/ui/Button';
import { rootCustomProperties, rootValue, useReducedMotion, useRootClass } from './liveStyle';
import Section from './Section';

/** `120ms` / `0.2s` → milliseconds. */
function toMs(value: string): number {
  const number = parseFloat(value);
  return value.trim().endsWith('ms') ? number : number * 1000;
}

/** What each duration moves in the app (system/motion.md), so the replay shows it doing that. */
const KEYFRAMES: Record<string, Keyframe[]> = {
  '--dur-press': [{ transform: 'scale(0.97)' }, { transform: 'scale(1)' }],
  '--dur-hover': [{ opacity: 0.45 }, { opacity: 1 }],
  '--dur-sheet': [{ transform: 'translateX(100%)' }, { transform: 'translateX(0)' }],
};
const ENTER: Keyframe[] = [{ opacity: 0, transform: 'scale(0.97)' }, { opacity: 1, transform: 'scale(1)' }];

/** Under reduced motion, every surface becomes a 150ms fade (system/motion.md). */
const REDUCED: Keyframe[] = [{ opacity: 0 }, { opacity: 1 }];
const REDUCED_MS = 150;

/**
 * The motion tokens, read live, with a replay (P12). The replay is the one
 * thing here that moves, and only when asked; under reduced motion it plays
 * what the app plays then: a short fade.
 */
export default function Motion({ rules }: { rules?: string }) {
  useRootClass();
  const reduced = useReducedMotion();
  const easing = rootValue('--ease-out');
  const durations = rootCustomProperties('--dur-').map((name) => ({ name, value: rootValue(name) }));
  const blocks = useRef(new Map<string, HTMLElement>());

  const replay = () => {
    for (const { name, value } of durations) {
      const block = blocks.current.get(name);
      if (!block || typeof block.animate !== 'function') continue;
      if (reduced) block.animate(REDUCED, { duration: REDUCED_MS, easing: 'linear' });
      else block.animate(KEYFRAMES[name] ?? ENTER, { duration: toMs(value), easing: easing || 'ease-out' });
    }
  };

  return (
    <Section title="Motion" rules={rules}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 text-[0.875rem] text-fg-2">
          One easing, <code className="font-mono text-[0.8125rem] text-fg">{easing || '× --ease-out not defined'}</code>.
          {reduced ? ' Reduced motion is on: the replay fades only, as the app does.' : null}
        </p>
        <Button size="sm" onClick={replay}>Replay</Button>
      </div>
      <ul className="rounded-md border border-line">
        {durations.map(({ name, value }) => (
          <li key={name} className="flex items-center gap-4 border-b border-line px-3 py-2.5 last:border-b-0">
            <span className="w-28 shrink-0 font-mono text-[0.75rem] text-fg">{name}</span>
            <span className="w-14 shrink-0 font-mono text-[0.75rem] tabular-nums text-fg-2">{value}</span>
            <span className="relative h-6 min-w-0 flex-1 overflow-hidden">
              <span
                ref={(element) => {
                  if (element) blocks.current.set(name, element);
                  else blocks.current.delete(name);
                }}
                aria-hidden="true"
                className="absolute inset-y-0 right-0 w-16 rounded-sm bg-inverse"
              />
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}
