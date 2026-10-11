/**
 * The specimen under a page doc (D4): the real page, in a frame, on fixtures
 * for one state, at a width and a theme (`frame/Frame.tsx`, slice S3). A state
 * with no fixture scenario yet (a parked page) keeps a quiet placeholder.
 * Keep the props: the Handbook (and later Wall and Bench) drive it with them.
 */
import Frame from './frame/Frame';
import { frameScenario } from './fixtures/scenarios';
import type { SpecimenSlotProps, SpecimenWidth } from './specimen';

export type { SpecimenSlotProps, SpecimenTheme, SpecimenWidth } from './specimen';

/** A desktop window and a phone. */
const FRAME_HEIGHT: Record<SpecimenWidth, number> = { 1400: 860, 390: 844 };

export default function SpecimenSlot({ page, state, width, theme }: SpecimenSlotProps) {
  const scenario = frameScenario(page, state);
  return (
    <figure aria-label={`${page} · ${state} · ${width} · ${theme}`} className="mx-auto min-w-0" style={{ maxWidth: width }}>
      <figcaption className="mb-2 flex items-baseline justify-between gap-3 font-mono text-[0.75rem] text-fg-3">
        <span className="min-w-0 truncate">{page} / {state}{scenario ? ` · ${scenario.label}` : ''}</span>
        <span className="shrink-0 tabular-nums">{width}px · {theme}</span>
      </figcaption>
      {scenario ? (
        <Frame
          key={`${page}/${state}/${width}/${theme}`}
          page={page}
          state={state}
          width={width}
          height={FRAME_HEIGHT[width]}
          theme={theme}
          className="rounded-md border border-line-strong"
        />
      ) : (
        <div
          className="flex w-full flex-col items-center justify-center gap-1 rounded-md border border-dashed border-line-strong bg-surface px-6 text-center"
          style={{ aspectRatio: `${width} / ${FRAME_HEIGHT[width]}`, maxHeight: '70dvh' }}
        >
          <p className="text-[0.875rem] text-fg-2">No fixture scenario for {page} / {state} yet.</p>
          <p className="text-[0.8125rem] text-fg-3">Add one in design/fixtures/scenarios.ts; nothing here calls the live API.</p>
        </div>
      )}
    </figure>
  );
}
