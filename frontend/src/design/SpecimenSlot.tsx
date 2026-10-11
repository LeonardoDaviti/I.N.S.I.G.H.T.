/**
 * The specimen under a page doc (D4): the real page, in a frame, on fixtures
 * for one state, at a width and a theme. This is the mount point slice S3
 * fills with the chromeless `/design/frame/:page/:state` iframe and its
 * fixture transport; until then it holds the frame's place and says so.
 * Keep the props: the Handbook (and later Wall and Bench) drive it with them.
 */
import type { SpecimenSlotProps, SpecimenWidth } from './specimen';

export type { SpecimenSlotProps, SpecimenTheme, SpecimenWidth } from './specimen';

/** A desktop window and a phone, as the frames will be. */
const FRAME_HEIGHT: Record<SpecimenWidth, number> = { 1400: 860, 390: 844 };

export default function SpecimenSlot({ page, state, width, theme }: SpecimenSlotProps) {
  return (
    <figure aria-label={`${page} · ${state} · ${width} · ${theme}`} className="mx-auto min-w-0" style={{ maxWidth: width }}>
      <figcaption className="mb-2 flex items-baseline justify-between gap-3 font-mono text-[0.75rem] text-fg-3">
        <span className="min-w-0 truncate">{page} / {state}</span>
        <span className="shrink-0 tabular-nums">{width}px · {theme}</span>
      </figcaption>
      <div
        className="flex w-full flex-col items-center justify-center gap-1 rounded-md border border-dashed border-line-strong bg-surface px-6 text-center"
        style={{ aspectRatio: `${width} / ${FRAME_HEIGHT[width]}`, maxHeight: '70dvh' }}
      >
        <p className="text-[0.875rem] text-fg-2">The {page} page at “{state}” renders here.</p>
        <p className="text-[0.8125rem] text-fg-3">Frames on fixtures arrive with slice S3; nothing here calls the live API.</p>
      </div>
    </figure>
  );
}
