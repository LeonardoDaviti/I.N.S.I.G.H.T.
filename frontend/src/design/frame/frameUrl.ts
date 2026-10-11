/**
 * The chromeless frame route (Design Studio D4): `/design/frame/:page/:state`
 * with `?theme=dark|light` and `?data=fixtures|live`; a prototype (D6) renders
 * at `/design/frame/prototype/:id/:state`, on its page's fixtures for that state. It is not a `<Route>` in
 * App.tsx: the frame needs its own router and providers, set up after its
 * `fetch` is replaced, so App renders it instead of the app when the path
 * starts with the prefix.
 */
import type { FrameData } from './transport';

export const FRAME_PREFIX = '/design/frame/';

/** The first segment that marks a prototype frame; no page doc is named so. */
const PROTOTYPE_SEGMENT = 'prototype';

export type FrameTheme = 'dark' | 'light';

export interface FrameLocation {
  /** The page doc; for a prototype, empty until the registry names its page. */
  page: string;
  /** The prototype rendered around (or instead of) the page, by its folder name. */
  prototype?: string;
  state: string;
  theme: FrameTheme;
  data: FrameData;
}

export function isFramePath(pathname: string): boolean {
  return pathname.startsWith(FRAME_PREFIX);
}

type FrameOptions = Partial<Pick<FrameLocation, 'theme' | 'data'>>;

function address(segments: readonly string[], { theme = 'dark', data = 'fixtures' }: FrameOptions): string {
  const query = new URLSearchParams({ theme, data });
  return `${FRAME_PREFIX}${segments.map(encodeURIComponent).join('/')}?${query.toString()}`;
}

export function frameUrl(page: string, state: string, options: FrameOptions = {}): string {
  return address([page, state], options);
}

/** A prototype in a frame, on the fixtures of its page's `state`. */
export function prototypeFrameUrl(id: string, state: string, options: FrameOptions = {}): string {
  return address([PROTOTYPE_SEGMENT, id, state], options);
}

/** The frame a URL asks for; a missing state is `normal`, unknown values fall back to dark and fixtures. */
export function parseFrameLocation(pathname: string, search: string): FrameLocation | null {
  if (!isFramePath(pathname)) return null;
  const segments = pathname.slice(FRAME_PREFIX.length).split('/').filter(Boolean).map(decodeURIComponent);
  const query = new URLSearchParams(search);
  const look = {
    theme: query.get('theme') === 'light' ? 'light' : 'dark',
    data: query.get('data') === 'live' ? 'live' : 'fixtures',
  } as const;
  if (segments[0] === PROTOTYPE_SEGMENT) {
    const [, prototype = '', state = 'normal'] = segments;
    return prototype ? { page: '', prototype, state, ...look } : null;
  }
  const [page = '', state = 'normal'] = segments;
  return page ? { page, state, ...look } : null;
}
