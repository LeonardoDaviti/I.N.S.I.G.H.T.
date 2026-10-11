import type { Dispatch, MutableRefObject, ReactNode } from 'react';
import { Pause, Play, RotateCcw, SkipForward, X } from 'lucide-react';

import { cn } from '../../lib/utils';
import { iconButtonClass } from '../../components/ui/styles';
import Frame from '../frame/Frame';
import type { FrameTheme } from '../frame/frameUrl';
import { WALK, type WalkAction, type WalkState } from './walk';

/** The walk plays on a laptop-sized page, so the panel shows it large. */
const WALK_VIEWPORT = { width: 1280, height: 800 };

function Control({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled} className={cn(iconButtonClass, 'disabled:opacity-40')}>
      {children}
    </button>
  );
}

function status({ current, running, ready, error }: WalkState): string {
  const step = WALK[current];
  if (error) return `✕ step ${current + 1} failed: ${error}`;
  if (!ready) return '◌ loading the feed';
  if (current < 0) return `○ ready · ${WALK.length} steps`;
  if (running) return `● ${step.label}`;
  return current === WALK.length - 1 ? `✓ walked all ${WALK.length} steps` : `✓ step ${current + 1} of ${WALK.length}`;
}

/**
 * The walk (prototype verdict B): one large interactive frame replaying the
 * journey at real speed, with play / pause / step / restart and the steps
 * listed, the one shown marked. It runs on fixtures, whatever the Wall shows:
 * the script clicks fixture pages.
 */
export default function WalkPanel({
  state, dispatch, frame, theme, onClose,
}: {
  state: WalkState;
  dispatch: Dispatch<WalkAction>;
  frame: MutableRefObject<HTMLIFrameElement | null>;
  theme: FrameTheme;
  onClose: () => void;
}) {
  const atEnd = state.current >= WALK.length - 1;
  return (
    <section aria-label="Walk" className="flex min-h-0 w-[52%] shrink-0 flex-col overflow-y-auto border-l border-line bg-bg">
      <div className="flex items-center gap-1 px-4 pb-2 pt-3">
        <h2 className="mr-auto text-[0.8125rem] lowercase text-fg-3">walk · fixtures</h2>
        <Control label="Restart" onClick={() => dispatch({ type: 'restart' })}><RotateCcw className="h-4 w-4" aria-hidden="true" /></Control>
        {state.playing ? (
          <Control label="Pause" onClick={() => dispatch({ type: 'pause' })}><Pause className="h-4 w-4" aria-hidden="true" /></Control>
        ) : (
          <Control label="Play" onClick={() => dispatch({ type: 'play' })}><Play className="h-4 w-4" aria-hidden="true" /></Control>
        )}
        <Control label="Step" onClick={() => dispatch({ type: 'step' })} disabled={!state.ready || state.running || atEnd}>
          <SkipForward className="h-4 w-4" aria-hidden="true" />
        </Control>
        <span aria-hidden="true" className="mx-1 h-4 w-px bg-line" />
        <Control label="Close walk" onClick={onClose}><X className="h-4 w-4" aria-hidden="true" /></Control>
      </div>
      <div className="px-4">
        <Frame
          key={state.epoch}
          page="reader"
          state="normal"
          width={WALK_VIEWPORT.width}
          height={WALK_VIEWPORT.height}
          theme={theme}
          interactive
          walk
          iframeRef={frame}
          className="rounded-md border border-line"
        />
      </div>
      <p role="status" className={cn('px-4 pt-3 text-[0.8125rem] tabular-nums', state.error ? 'font-semibold text-fg' : 'text-fg-2')}>
        {status(state)}
      </p>
      <ol className="grid grid-flow-col grid-rows-4 gap-x-6 gap-y-1 px-4 pb-6 pt-3 text-[0.8125rem]">
        {WALK.map((step, index) => {
          const current = index === state.current;
          return (
            <li
              key={step.id}
              aria-current={current ? 'step' : undefined}
              className={cn('flex items-baseline gap-2', current ? 'font-semibold text-fg' : index < state.current ? 'text-fg-2' : 'text-fg-3')}
            >
              <span
                aria-hidden="true"
                className={cn('inline-flex h-[1.125rem] w-[1.125rem] shrink-0 items-center justify-center rounded-sm text-[0.6875rem] tabular-nums', current ? 'bg-inverse text-inverse-fg' : 'border border-line')}
              >
                {index + 1}
              </span>
              {step.label}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
