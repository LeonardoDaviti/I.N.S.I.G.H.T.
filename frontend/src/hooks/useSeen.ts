import { createContext, useContext } from 'react';

import { seenTracker, type SeenSurface } from '../services/reading';

/** The surface a list's rows are seen on (News, a track page, a feed list); null: not counted (search results). */
export const SeenSurfaceContext = createContext<SeenSurface | null>(null);

type SeenRef = (node: Element | null) => (() => void) | undefined;
const refs = new Map<string, SeenRef>();
const none: SeenRef = () => undefined;

/**
 * A callback ref that counts the row as seen once it is half on screen for a second (services/reading's
 * SeenTracker). One stable function per post and surface, so a re-render does not restart the second; usable in a
 * `.map` where a hook is not. No post or no surface: nothing is counted.
 */
export function seenRef(postId: string | null | undefined, surface: SeenSurface | null): SeenRef {
  if (!postId || !surface) return none;
  const key = `${surface}|${postId}`;
  let ref = refs.get(key);
  if (!ref) {
    ref = (node) => (node ? seenTracker.watch(node, postId, surface) : undefined);
    refs.set(key, ref);
  }
  return ref;
}

/** seenRef on the nearest SeenSurfaceContext's surface (a feed list's or News's row). */
export function useSeen(postId: string | null | undefined): SeenRef {
  return seenRef(postId, useContext(SeenSurfaceContext));
}
