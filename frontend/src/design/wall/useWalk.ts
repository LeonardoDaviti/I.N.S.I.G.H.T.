import { useEffect, useReducer, useRef } from 'react';

import { WALK, WALK_MESSAGE, initialWalk, walkReducer } from './walk';

/** While playing, the beat on each page before the next move: long enough to look. */
export const DWELL_MS = 1200;

/**
 * The walk's controls, wired to its frame: the studio posts `run` for each
 * step it starts and listens for the frame's `ready` and `done`, only from
 * that frame's window on this origin. Playing, it moves on after a beat.
 */
export function useWalk() {
  const [state, dispatch] = useReducer(walkReducer, initialWalk);
  const frame = useRef<HTMLIFrameElement | null>(null);

  useEffect(() => {
    const origin = window.location.origin;
    const onMessage = (event: MessageEvent) => {
      const source = frame.current?.contentWindow;
      if (event.origin !== origin || !source || event.source !== source) return;
      const data = (event.data ?? {}) as { type?: string; ok?: boolean; error?: string };
      if (data.type === WALK_MESSAGE.ready) dispatch({ type: 'ready' });
      else if (data.type === WALK_MESSAGE.done) dispatch({ type: 'done', ok: data.ok === true, error: data.error });
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const { current, running, playing, ready, error } = state;

  useEffect(() => {
    if (running && current >= 0) frame.current?.contentWindow?.postMessage({ type: WALK_MESSAGE.run, step: current }, window.location.origin);
  }, [current, running]);

  useEffect(() => {
    if (!playing || !ready || running || error || current >= WALK.length - 1) return undefined;
    const timer = setTimeout(() => dispatch({ type: 'step' }), current < 0 ? 0 : DWELL_MS);
    return () => clearTimeout(timer);
  }, [playing, ready, running, error, current]);

  return { state, dispatch, frame };
}
