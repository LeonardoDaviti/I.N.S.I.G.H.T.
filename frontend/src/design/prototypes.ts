/**
 * Prototypes (Design Studio D6), as pure functions over their README text, so
 * the coverage test and the studio read them the same way.
 *
 * A prototype is a folder `prototypes/<yyyy-mm-dd>-<slug>/` with a README.md
 * that opens with a `meta` block:
 *   hypothesis: one sentence the comparison should prove or disprove
 *   principles: the P-numbers it serves (P1, P4)
 *   page: the page doc it compares against (post)
 *   states: the states to compare on, the first is the default (long-title, article)
 *   status: draft | review | accepted | rejected
 *   created: yyyy-mm-dd, the folder's date
 * and an index.tsx whose default export wraps the real page in its frame.
 */
import { parseDoc, type DesignDoc } from './coverage';

export const PROTOTYPE_STATUSES = ['draft', 'review', 'accepted', 'rejected'] as const;
export type PrototypeStatus = (typeof PROTOTYPE_STATUSES)[number];

export interface Prototype {
  /** The folder name, `2026-10-10-title-wrap`. */
  id: string;
  /** The id without its date, `title-wrap`. */
  slug: string;
  /** The README's `# ` heading, else the slug. */
  title: string;
  hypothesis: string;
  principles: number[];
  page: string;
  states: string[];
  /** As written; `prototypeProblems` flags a value outside PROTOTYPE_STATUSES. */
  status: string;
  created: string;
  readme: string;
  /** A unified diff of the page doc, when the prototype ships one (`doc.diff`). */
  docDiff?: string;
}

const ID = /^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)$/;

export function parsePrototype(id: string, readme: string, docDiff?: string): Prototype {
  const { meta } = parseDoc(`prototypes/${id}/README.md`, readme);
  const one = (key: string) => (meta[key] ?? []).join(', ');
  const slug = ID.exec(id)?.[2] ?? id;
  return {
    id,
    slug,
    title: /^# (.+?)\s*$/m.exec(readme)?.[1] ?? slug,
    hypothesis: one('hypothesis'),
    principles: (meta.principles ?? []).map((value) => Number(/^P(\d+)$/.exec(value)?.[1] ?? NaN)),
    page: one('page'),
    states: meta.states ?? [],
    status: one('status'),
    created: one('created'),
    readme,
    ...(docDiff ? { docDiff } : {}),
  };
}

export interface KnownDesign {
  /** The P-numbers principles.md defines. */
  principles: ReadonlySet<number>;
  /** True when the page has this state (a page doc state with a frame scenario). */
  hasState: (page: string, state: string) => boolean;
}

/** What keeps a prototype from rendering in Bench or reading honestly in the registry. */
export function prototypeProblems(prototype: Prototype, known: KnownDesign): string[] {
  const at = `prototypes/${prototype.id}`;
  const problems: string[] = [];
  const date = ID.exec(prototype.id)?.[1];
  if (!date) problems.push(`${at}: the folder is not named <yyyy-mm-dd>-<slug>`);
  if (!(PROTOTYPE_STATUSES as readonly string[]).includes(prototype.status)) {
    problems.push(`${at}: status "${prototype.status}" is not draft, review, accepted or rejected`);
  }
  if (prototype.created !== date) {
    problems.push(`${at}: created ${prototype.created || '(none)'} does not match the folder date`);
  }
  if (!prototype.hypothesis) problems.push(`${at}: no one-sentence hypothesis`);
  if (!prototype.principles.length) problems.push(`${at}: serves no principle`);
  for (const number of prototype.principles) {
    if (!known.principles.has(number)) problems.push(`${at}: cites P${number}, which principles.md does not define`);
  }
  if (!prototype.page) problems.push(`${at}: names no page to compare against`);
  if (!prototype.states.length) problems.push(`${at}: names no state to compare on`);
  if (prototype.page) {
    for (const state of prototype.states) {
      if (!known.hasState(prototype.page, state)) problems.push(`${at}: ${prototype.page}/${state} has no page doc state or frame scenario`);
    }
  }
  return problems;
}

/** Draft and review are open; accepted and rejected wait for their folder to be deleted. */
export function isOpen(prototype: Pick<Prototype, 'status'>): boolean {
  return prototype.status === 'draft' || prototype.status === 'review';
}

const DAY = 24 * 60 * 60 * 1000;

/** Whole calendar days since `created`, in the reader's time zone: `today`, `1 day`, `14 days`. */
export function prototypeAge(prototype: Pick<Prototype, 'created'>, now: Date): string {
  const [year, month, day] = prototype.created.split('-').map(Number);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const days = Math.max(0, Math.round((today - new Date(year, month - 1, day).getTime()) / DAY));
  if (!Number.isFinite(days)) return 'undated';
  return days === 0 ? 'today' : days === 1 ? '1 day' : `${days} days`;
}

/** Accept and reject are not browser writes (docs are files): the studio shows what to tell the agent. */
export function acceptInstruction(id: string): string {
  return `accept prototype ${id}`;
}

export function rejectInstruction(id: string, reason: string): string {
  return `reject prototype ${id}: ${reason.trim() || '<reason>'}`;
}

/** Each principle's short title, from its bold label: `**P4 Posts in one centred column.**`. */
export function principleTitles(principles: DesignDoc): Map<number, string> {
  return new Map(
    [...principles.text.matchAll(/^\s*[-*]?\s*\*\*P(\d+)\s+(.+?)\.?\*\*/gm)].map((match) => [Number(match[1]), match[2]] as const),
  );
}
