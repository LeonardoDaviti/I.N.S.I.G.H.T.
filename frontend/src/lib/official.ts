// Discover's "Official channels" lines (issue 0196): what each row says, from the server's row. Pure.
import type {
  OfficialFilter, OfficialFrom, OfficialJudge, OfficialKind, OfficialProof, OfficialResponse, OfficialRow, OfficialState,
} from '../services/api';
import { formatCount, plural } from './format.ts';

/** The groups, in the order shown; `collapsed` ones start behind a "Show N …" button. */
export interface OfficialGroup {
  id: string;
  title: string;
  states: OfficialState[];
  collapsed: boolean;
  /** "Show 3 refused". */
  noun: string;
}
export const OFFICIAL_GROUPS: OfficialGroup[] = [
  { id: 'added', title: 'Added automatically', states: ['added'], collapsed: false, noun: 'added' },
  { id: 'would_add', title: 'Would add', states: ['would_add'], collapsed: false, noun: 'would add' },
  { id: 'checking', title: 'Being checked', states: ['candidate', 'proven'], collapsed: false, noun: 'being checked' },
  { id: 'covered', title: 'Already followed', states: ['covered'], collapsed: true, noun: 'already followed' },
  { id: 'refused', title: 'Refused', states: ['refused'], collapsed: true, noun: 'refused' },
  { id: 'undone', title: 'Undone', states: ['undone'], collapsed: true, noun: 'undone' },
];

/** The rows of each group, in the groups' order; empty groups are left out. */
export function groupRows(rows: OfficialRow[]): { group: OfficialGroup; rows: OfficialRow[] }[] {
  return OFFICIAL_GROUPS
    .map((group) => ({ group, rows: rows.filter((row) => group.states.includes(row.state)) }))
    .filter((entry) => entry.rows.length > 0);
}

/** The job's mode in words. */
export function modeLine(data: Pick<OfficialResponse, 'mode' | 'cap' | 'added_today'>): string {
  if (data.mode === 'shadow') return 'Shadow: nothing is added, it shows what would be';
  if (data.mode === 'on') {
    return `On: official channels are added automatically, at most ${formatCount(data.cap)} a day `
      + `(${formatCount(data.added_today)} today)`;
  }
  return 'Off';
}

const KIND_LABELS: Record<OfficialKind, string> = {
  x: 'X account',
  telegram: 'Telegram channel',
  youtube: 'YouTube channel',
  section: 'site section',
  releases: 'releases',
};
export function kindLabel(kind: OfficialKind | string): string {
  return KIND_LABELS[kind as OfficialKind] ?? kind;
}

const FROM_LABELS: Record<OfficialFrom, string> = {
  own_page: 'its own page in a story',
  code_address: 'its code repository',
  handle: 'its handle',
  web_search: 'a web search',
  web_announcement: 'the announcement the web search found',
};
/** "Found from its code repository"; null when the server didn't say. */
export function fromLine(from: OfficialFrom | string | null | undefined): string | null {
  if (!from) return null;
  return `Found from ${FROM_LABELS[from as OfficialFrom] ?? from.replace(/_/g, ' ')}`;
}

/** "12 dated items read via feed; holds 2 of the event's pages". */
export function proofLine(proof: OfficialProof | null | undefined): string | null {
  if (!proof) return null;
  return `${plural(proof.dated, 'dated item')} read via ${proof.via}; holds ${formatCount(proof.holds)} of the event's pages`;
}

/** "Worker: follow · fits your topics: yes · reason one; reason two". */
export function judgeLine(judge: OfficialJudge | null | undefined, reasons = 2): string | null {
  if (!judge || (!judge.verdict && judge.fits === null && !judge.reasons.length)) return null;
  const parts: string[] = [];
  if (judge.verdict) parts.push(judge.verdict);
  if (judge.fits !== null) parts.push(`fits your topics: ${judge.fits ? 'yes' : 'no'}`);
  const why = judge.reasons.slice(0, reasons).join('; ');
  if (why) parts.push(why);
  return `Worker: ${parts.join(' · ')}`;
}

/** "Hides: replies (^@)" per rule, and "3 hidden". */
export function filterLine(filter: OfficialFilter | null | undefined, hidden: number): string | null {
  if (!filter || !filter.hide.length) return null;
  const rules = filter.hide.map((rule) => `${rule.why} (${rule.regex})`).join('; ');
  return `Hides: ${rules} · ${formatCount(hidden)} hidden`;
}

/** The "Show N refused" button of a collapsed group. */
export function showLabel(group: OfficialGroup, count: number): string {
  return `Show ${formatCount(count)} ${group.noun}`;
}
