/**
 * Bench mode's address (verdict C): what is compared lives in the URL, so a
 * comparison can be linked, reloaded and screenshotted (D9).
 *
 *   ?mode=bench&subject=<prototype id | page>   what is on the bench
 *   &state=<s>              a prototype's state, shared by both panes
 *   &left=<s>&right=<s>     a page's two states, state against state
 *   &width=1400|390|320     &theme=dark|light   shared by both panes
 *   &data=live              both panes on the real API, read-only (fixtures by default)
 *   &doc=hide               the drawer folded away
 */
import { SPECIMEN_THEMES, SPECIMEN_WIDTHS, type SpecimenTheme } from './specimen';
import { isOpen, type Prototype } from './prototypes';
import type { FrameData } from './frame/transport';

export const BENCH_DATA: readonly FrameData[] = ['fixtures', 'live'];

/** Bench opened on a subject: a prototype id or a page doc's name. */
export function benchHref(subject: string): string {
  return `/design?${new URLSearchParams({ mode: 'bench', subject }).toString()}`;
}

/** A desktop window, a phone, the narrowest phone: the last is where a wrap or a top bar breaks first. */
export const BENCH_WIDTHS: readonly number[] = [...SPECIMEN_WIDTHS, 320];

export interface BenchPage {
  /** The page doc's name: `post`. */
  name: string;
  title: string;
  /** Its `states:`, in the doc's order. */
  states: readonly string[];
}

export interface BenchSubject {
  id: string;
  label: string;
}

export interface BenchSubjectGroup {
  label: string;
  subjects: BenchSubject[];
}

const byId = (a: Prototype, b: Prototype) => a.id.localeCompare(b.id);
const asSubject = (prototype: Prototype): BenchSubject => ({ id: prototype.id, label: `${prototype.slug} (${prototype.status})` });

/** The subject picker: open prototypes first, oldest first, then the pages; closed prototypes last, while their folder lasts. */
export function benchSubjects(prototypes: readonly Prototype[], pages: readonly BenchPage[]): BenchSubjectGroup[] {
  const closed = prototypes.filter((prototype) => !isOpen(prototype)).sort(byId);
  return [
    { label: 'open prototypes', subjects: prototypes.filter(isOpen).sort(byId).map(asSubject) },
    { label: 'pages', subjects: pages.map((page) => ({ id: page.name, label: page.title })) },
    ...(closed.length ? [{ label: 'closed prototypes', subjects: closed.map(asSubject) }] : []),
  ].filter((group) => group.subjects.length > 0);
}

export interface BenchView {
  subject: string;
  /** Set when a prototype is on the bench: the right pane shows it. */
  prototype?: string;
  page: string;
  states: readonly string[];
  left: string;
  right: string;
  widths: number[];
  width: number;
  theme: SpecimenTheme;
  data: FrameData;
  /** The drawer with the hypothesis, principles, status and decision. */
  drawer: boolean;
}

export interface BenchCatalog {
  prototypes: readonly Prototype[];
  pages: readonly BenchPage[];
  /** A state's own viewport width (the 320px top bar), when it has one. */
  widthOf: (page: string, state: string) => number | undefined;
}

/** What Bench shows for an address; anything unknown falls back to the default. */
export function parseBench(params: URLSearchParams, { prototypes, pages, widthOf }: BenchCatalog): BenchView {
  const requested = params.get('subject');
  const prototype = prototypes.find((candidate) => candidate.id === requested)
    ?? (pages.some((page) => page.name === requested) ? undefined : [...prototypes].filter(isOpen).sort(byId)[0]);
  const page = prototype ? undefined : pages.find((candidate) => candidate.name === requested) ?? pages[0];
  const pageName = prototype?.page ?? page?.name ?? '';
  const states = prototype?.states ?? page?.states ?? [];
  const pick = (key: string, fallback: string) => states.find((state) => state === params.get(key)) ?? fallback;

  const left = prototype ? pick('state', states[0] ?? '') : pick('left', states[0] ?? '');
  const right = prototype ? left : pick('right', states[1] ?? states[0] ?? '');
  const own = states.map((state) => widthOf(pageName, state)).filter((width): width is number => width !== undefined);
  const widths = [...new Set<number>([...BENCH_WIDTHS, ...own])];

  return {
    subject: prototype?.id ?? page?.name ?? '',
    prototype: prototype?.id,
    page: pageName,
    states,
    left,
    right,
    widths,
    width: widths.find((width) => String(width) === params.get('width')) ?? widths[0],
    theme: SPECIMEN_THEMES.find((theme) => theme === params.get('theme')) ?? SPECIMEN_THEMES[0],
    data: BENCH_DATA.find((data) => data === params.get('data')) ?? BENCH_DATA[0],
    drawer: params.get('doc') !== 'hide',
  };
}
