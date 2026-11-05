// Mark X Shadow's words (issue 0086 E): why a post is in a Mark X story, what Mark IX did with it, a tag's meaning.
// Used by the Mark X page and the post page's panel only (their own chunks).

export type Why = {
  role: string;
  reason: string;
  p: number | null;
  relation: string | null;
  words?: string | null;
};

const RELATIONS: Record<string, string> = {
  same_event: 'same event',
  development: 'development',
  reaction: 'reaction',
  mention: 'mention',
  digest_item: 'digest item',
  different: 'different',
  cant_tell: "can't tell",
  follows_up: 'follows up',
  background: 'background',
  related: 'related',
};

const RULES: Record<string, string> = {
  none: 'first post',
  link: 'shared link',
  citation: 'citation',
  quote: 'quote',
  thread: 'thread',
  copy: 'copy',
  title: 'same title',
  text: 'same text',
  address: 'its own page',
  time: 'posted together',
  repost: 'repost',
};

export function relationWords(relation: string | null | undefined): string {
  if (!relation) return '';
  return RELATIONS[relation] ?? relation.replace(/_/g, ' ');
}

/** A probability as the page shows it: two decimals ("0.92"). */
export function pWords(p: number | null | undefined): string {
  return typeof p === 'number' && Number.isFinite(p) ? p.toFixed(2) : '';
}

/** "Haiku: same event 0.92" (no words: the caller shows them). */
export function judged(relation: string | null | undefined, p: number | null | undefined): string {
  const rel = relationWords(relation);
  const prob = pWords(p);
  return `Haiku: ${rel || 'answered'}${prob ? ` ${prob}` : ''}`;
}

/** Why a post is where it is in Mark X: Mark IX's rule, the judge's join or pair, a merge, a check's mention. */
export function whyWords(why: Why | null | undefined): string {
  if (!why) return 'not in this Mark X story';
  if (why.reason.startsWith('rule:')) {
    const rule = why.reason.slice(5);
    return `Mark IX's rule: ${RULES[rule] ?? rule.replace(/_/g, ' ')}`;
  }
  if (why.reason === 'merge') return 'merged in with its story (Haiku: same event)';
  if (why.reason === 'judge:check') {
    const as = why.role === 'digest_item' ? 'a digest item' : 'a mention';
    return `kept as ${as} (${judged(why.relation, why.p)})`;
  }
  if (why.reason === 'judge:pair') return `${judged(why.relation, why.p)}, a story Mark IX doesn't have`;
  if (why.reason === 'judge:join') return `joined: ${judged(why.relation, why.p)}`;
  return why.reason;
}

export type MarkxTagName = 'NEW' | 'MERGED' | 'SPLIT' | 'CHANGED' | 'SAME';

/** What a tag says, for its title and the legend. */
export const TAG_WORDS: Record<MarkxTagName, string> = {
  NEW: 'a story Mark IX has no News row for',
  MERGED: 'two or more Mark IX rows made one',
  SPLIT: 'one Mark IX row split into two or more',
  CHANGED: 'the same row, other posts',
  SAME: 'the same posts as Mark IX',
};

/** What Mark IX did with a line's post. */
export function ixWords(ix: { title: string | null; same_row: boolean } | null | undefined): string {
  if (!ix) return "Mark IX: not in its News";
  if (ix.same_row) return 'Mark IX: same row';
  return `Mark IX: in “${ix.title ?? 'another row'}”`;
}

/** The labels' one-tap answers (0086 F), as the buttons say them. */
export const ANSWER_WORDS: Record<string, string> = {
  same_event: 'same event',
  follow_up: 'follow-up',
  related: 'related',
  different: 'different',
  unsure: 'unsure',
  right: 'right',
  wrong: 'wrong',
  wrong_story: 'wrong story',
  not_about: 'not about this',
};

/** A share as a whole percent ("86%"), or an en dash when there is none. */
export function percent(share: number | null | undefined): string {
  return typeof share === 'number' && Number.isFinite(share) ? `${Math.round(share * 100)}%` : '–';
}

/** "86% (63–95%)": a precision with its interval. */
export function withInterval(share: number | null | undefined, lo: number | null | undefined, hi: number | null | undefined): string {
  if (typeof share !== 'number') return '–';
  return typeof lo === 'number' && typeof hi === 'number'
    ? `${percent(share)} (${Math.round(lo * 100)}–${percent(hi)})`
    : percent(share);
}

/** USD to two significant places past the cent ("$0.0123", "$1.20"). */
export function usd(value: number): string {
  if (!Number.isFinite(value)) return '';
  return value >= 1 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`;
}
