/**
 * `npm run design:shots` (Design Studio D9), its pure half: the arguments and
 * the shot list. The state matrix comes from the frame scenarios and the
 * prototype registry; this file only crosses it with widths and themes and
 * applies the filters. scripts/design-shots.mjs drives the browser.
 */
import { frameUrl, prototypeFrameUrl, type FrameTheme } from '../design/frame/frameUrl.ts';

export const SHOT_WIDTHS = [1400, 390] as const;
export const SHOT_THEMES: readonly FrameTheme[] = ['dark', 'light'];
export const DEFAULT_PORT = 5198;

export interface ShotFilters {
  page?: string[];
  state?: string[];
  theme?: string[];
  width?: string[];
}

export interface ShotArgs {
  baseUrl?: string;
  port: number;
  filters: ShotFilters;
}

const FILTERS = ['page', 'state', 'theme', 'width'] as const;

/** `--page reader,post --width=390 --base-url http://…`; a filter is a comma list. Throws on anything else. */
export function parseShotArgs(argv: readonly string[]): ShotArgs {
  const args: ShotArgs = { port: DEFAULT_PORT, filters: {} };
  for (let i = 0; i < argv.length; i += 1) {
    const match = /^--([a-z-]+)(?:=(.*))?$/s.exec(argv[i]);
    if (!match) throw new Error(`unexpected argument "${argv[i]}"`);
    const name = match[1];
    const value = match[2] ?? argv[++i];
    if (!value) throw new Error(`--${name} needs a value`);
    if (name === 'base-url') args.baseUrl = value.replace(/\/+$/, '');
    else if (name === 'port') args.port = Number(value);
    else if ((FILTERS as readonly string[]).includes(name)) {
      args.filters[name as (typeof FILTERS)[number]] = value.split(',').map((part) => part.trim()).filter(Boolean);
    } else throw new Error(`unknown flag --${name} (use --page, --state, --theme, --width, --base-url, --port)`);
  }
  if (!Number.isInteger(args.port) || args.port <= 0) throw new Error(`--port must be a port number`);
  return args;
}

export interface Shot {
  /** The folder under .design-shots: the page, or `prototypes/<id>`. */
  page: string;
  state: string;
  width: number;
  theme: FrameTheme;
  /** The frame path, without the origin. */
  url: string;
  /** `<page>/<state>.<width>.<theme>.png`. */
  file: string;
  /** A studio page (`/design…`), not a frame: it has frames inside instead of being one. */
  studio?: boolean;
}

export interface ShotMatrix {
  /** `width`: a state's own viewport (the 320px top bar), shot as well as the usual two. */
  scenarios: readonly { page: string; state: string; width?: number }[];
  prototypes: readonly { id: string; states: readonly string[] }[];
}

const allows = (list: string[] | undefined, value: string) => !list?.length || list.includes(value);
/** `--page prototypes` takes every prototype, `--page <id>` one of them. */
const allowsPage = (list: string[] | undefined, page: string, id?: string) =>
  allows(list, page) || (id !== undefined && (list!.includes('prototypes') || list!.includes(id)));

/** The studio's own pages, at the desktop width: its home, the Wall fitted, Bench on the first prototype. */
function studioSubjects(prototypes: ShotMatrix['prototypes']): { state: string; url: (theme: FrameTheme) => string }[] {
  const seed = [...prototypes].sort((a, b) => a.id.localeCompare(b.id))[0];
  const bench = seed ? `subject=${encodeURIComponent(seed.id)}&` : '';
  return [
    { state: 'handbook', url: () => '/design' },
    { state: 'wall', url: (theme) => `/design?mode=wall&theme=${theme}` },
    { state: 'bench', url: (theme) => `/design?mode=bench&${bench}theme=${theme}` },
  ];
}

/**
 * Every page × state, then every prototype × its states, each at both widths
 * (and a state's own) and both themes; then the studio's pages. Filtered.
 */
export function shotList(matrix: ShotMatrix, filters: ShotFilters = {}): Shot[] {
  const subjects = [
    ...matrix.scenarios.map(({ page, state, width }) => ({ page, state, width, id: undefined as string | undefined })),
    ...matrix.prototypes.flatMap(({ id, states }) => states.map((state) => ({ page: `prototypes/${id}`, state, width: undefined as number | undefined, id }))),
  ];
  const shots: Shot[] = [];
  for (const { page, state, width: own, id } of subjects) {
    if (!allowsPage(filters.page, page, id) || !allows(filters.state, state)) continue;
    const widths = own === undefined || (SHOT_WIDTHS as readonly number[]).includes(own) ? SHOT_WIDTHS : [...SHOT_WIDTHS, own];
    for (const width of widths) {
      if (!allows(filters.width, String(width))) continue;
      for (const theme of SHOT_THEMES) {
        if (!allows(filters.theme, theme)) continue;
        const url = id ? prototypeFrameUrl(id, state, { theme }) : frameUrl(page, state, { theme });
        shots.push({ page, state, width, theme, url, file: `${page}/${state}.${width}.${theme}.png` });
      }
    }
  }
  const width = SHOT_WIDTHS[0];
  if (allows(filters.page, 'studio') && allows(filters.width, String(width))) {
    for (const { state, url } of studioSubjects(matrix.prototypes)) {
      if (!allows(filters.state, state)) continue;
      for (const theme of SHOT_THEMES) {
        if (!allows(filters.theme, theme)) continue;
        shots.push({ page: 'studio', state, width, theme, url: url(theme), file: `studio/${state}.${width}.${theme}.png`, studio: true });
      }
    }
  }
  return shots;
}
