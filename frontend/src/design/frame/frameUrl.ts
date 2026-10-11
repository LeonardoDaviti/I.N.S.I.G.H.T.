/**
 * The chromeless frame route (Design Studio D4): `/design/frame/:page/:state`
 * with `?theme=dark|light` and `?data=fixtures|live`. It is not a `<Route>` in
 * App.tsx: the frame needs its own router and providers, set up after its
 * `fetch` is replaced, so App renders it instead of the app when the path
 * starts with the prefix.
 */
import type { FrameData } from './transport';

export const FRAME_PREFIX = '/design/frame/';

export type FrameTheme = 'dark' | 'light';

export interface FrameLocation {
  page: string;
  state: string;
  theme: FrameTheme;
  data: FrameData;
  /** `?walk=1`: the frame takes walk steps from the studio (the Wall's walk). */
  walk?: boolean;
}

export function isFramePath(pathname: string): boolean {
  return pathname.startsWith(FRAME_PREFIX);
}

export function frameUrl(page: string, state: string, { theme = 'dark', data = 'fixtures', walk = false }: Partial<Pick<FrameLocation, 'theme' | 'data' | 'walk'>> = {}): string {
  const query = new URLSearchParams({ theme, data });
  if (walk) query.set('walk', '1');
  return `${FRAME_PREFIX}${encodeURIComponent(page)}/${encodeURIComponent(state)}?${query.toString()}`;
}

/** The frame a URL asks for; a missing state is `normal`, unknown values fall back to dark and fixtures. */
export function parseFrameLocation(pathname: string, search: string): FrameLocation | null {
  if (!isFramePath(pathname)) return null;
  const [page = '', state = 'normal'] = pathname.slice(FRAME_PREFIX.length).split('/').filter(Boolean).map(decodeURIComponent);
  if (!page) return null;
  const query = new URLSearchParams(search);
  return {
    page,
    state,
    theme: query.get('theme') === 'light' ? 'light' : 'dark',
    data: query.get('data') === 'live' ? 'live' : 'fixtures',
    walk: query.get('walk') === '1',
  };
}
