/**
 * The specimen under a page doc (D4): the real page, in a frame, on fixtures
 * for one state, at a width and a theme (`frame/Frame.tsx`). The Handbook only
 * shows it for a state with a frame scenario.
 */
import Frame from './frame/Frame';
import { frameScenario } from './fixtures/scenarios';
import type { SpecimenSlotProps } from './specimen';

export default function SpecimenSlot({ page, state, width, theme }: SpecimenSlotProps) {
  const scenario = frameScenario(page, state);
  return (
    <figure aria-label={`${page} · ${state} · ${width} · ${theme}`} className="mx-auto min-w-0" style={{ maxWidth: width }}>
      <figcaption className="mb-2 flex items-baseline justify-between gap-3 font-mono text-[0.75rem] text-fg-3">
        <span className="min-w-0 truncate">{page} / {state}{scenario ? ` · ${scenario.label}` : ''}</span>
        <span className="shrink-0 tabular-nums">{width}px · {theme}</span>
      </figcaption>
      <Frame
        key={`${page}/${state}/${width}/${theme}`}
        page={page}
        state={state}
        width={width}
        theme={theme}
        className="rounded-md border border-line-strong"
      />
    </figure>
  );
}
