import { describe, expect, it } from 'vitest';

import { SITE_EDGES, siteNode } from './siteMap';
import { WALK, initialWalk, walkReducer, type WalkState } from './walk';

describe('the walk script', () => {
  it('is the journey the owner asked for, in order', () => {
    expect(WALK.map((step) => step.at)).toEqual([
      'feed', 'post', 'feed', 'source-feed', 'source-sheet', 'sources', 'track-feed', 'feed',
    ]);
  });

  it('moves only along edges of the site map, into the page each edge leads to', () => {
    for (const step of WALK.slice(1)) {
      expect(siteNode(step.at), step.id).toBeDefined();
      const edge = SITE_EDGES.find((candidate) => candidate.id === step.edge);
      expect(edge, step.id).toBeDefined();
      expect(edge!.to, step.id).toBe(step.at);
    }
  });
});

const run = (state: WalkState, ...actions: Parameters<typeof walkReducer>[1][]) => actions.reduce(walkReducer, state);

describe('the walk controls', () => {
  it('step runs the next step and waits for the frame before the one after', () => {
    const started = run(initialWalk, { type: 'ready' }, { type: 'step' });
    expect(started).toMatchObject({ current: 0, running: true });
    expect(run(started, { type: 'step' }).current).toBe(0);
    expect(run(started, { type: 'done', ok: true }, { type: 'step' })).toMatchObject({ current: 1, running: true });
  });

  it('does nothing until the frame says it is ready', () => {
    expect(run(initialWalk, { type: 'step' })).toMatchObject({ current: -1, running: false });
  });

  it('play keeps going until the last step, then stops', () => {
    let state = run(initialWalk, { type: 'ready' }, { type: 'play' });
    expect(state).toMatchObject({ playing: true, current: 0, running: true });
    for (let i = 0; i < WALK.length - 1; i += 1) state = run(state, { type: 'done', ok: true }, { type: 'step' });
    state = run(state, { type: 'done', ok: true });
    expect(state).toMatchObject({ current: WALK.length - 1, playing: false, running: false });
  });

  it('pause stops after the step in flight; a failed step stops and says why', () => {
    const paused = run(initialWalk, { type: 'ready' }, { type: 'play' }, { type: 'pause' });
    expect(paused).toMatchObject({ playing: false, running: true });
    const failed = run(initialWalk, { type: 'ready' }, { type: 'play' }, { type: 'done', ok: false, error: 'no a' });
    expect(failed).toMatchObject({ playing: false, running: false, error: 'no a' });
  });

  it('restart reloads the frame at the feed; play at the end starts over', () => {
    const restarted = run(initialWalk, { type: 'ready' }, { type: 'step' }, { type: 'restart' });
    expect(restarted).toMatchObject({ current: -1, running: false, ready: false, epoch: 1 });
    let ended = run(initialWalk, { type: 'ready' });
    for (let i = 0; i < WALK.length; i += 1) ended = run(ended, { type: 'step' }, { type: 'done', ok: true });
    expect(run(ended, { type: 'play' })).toMatchObject({ current: -1, ready: false, playing: true, epoch: 1 });
  });
});
