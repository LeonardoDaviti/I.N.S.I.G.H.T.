// The track page's lines in words: pure, so they are tested apart.
import type {
  ShadowMeasure, TrackCalibration, TrackItem, TrackPage, TrackSection, TrackSeen, TrackSuggestion, TrackTool, TrackWhy,
} from '../../services/tracks';
import { plural } from '../../lib/format';

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** "your labels: 18 of 20 right (90%)", or that none are labelled yet. */
export function precisionLine(cal: TrackCalibration | null): string {
  if (!cal || !cal.labels) return 'no Discover match labelled yet';
  return `your labels: ${cal.right} of ${cal.labels} right (${pct(cal.precision ?? 0)})`;
}

/** The auto-join bar and where the track stands against it. */
export function joinLine(cal: TrackCalibration | null): string {
  if (!cal) return '';
  const bar = `joins by itself at ${pct(cal.bar.precision)} (lower bound ${pct(cal.bar.lower)}) with ${cal.bar.labels}+ labels`;
  if (cal.join_edge !== null) return `${bar}: on, from confidence ${cal.join_edge.toFixed(1)}`;
  return `${bar}: not yet, matches wait in Discover`;
}

/** Discover's rank in words: calibrated once 10+ labels, else the judge's confidence. */
export function rankWords(item: TrackItem): string {
  return item.calibrated ? `~${pct(item.rank)} precise at this confidence` : `confidence ${pct(item.confidence ?? 0)}`;
}

const FINDER_WORDS: Record<string, string> = {
  probe: 'example post', entity: 'entity', domain: 'domain', word: 'words', source: 'source', story: 'story',
  classifier: 'classifier', tool: 'tool in use', linked: 'linked by its sources', saved: 'you saved it',
};

/** "found by: example post, entity, domain" (null for an active source's item, which every post is). */
export function foundByLine(item: Pick<TrackItem, 'found_by'>): string | null {
  const got = (item.found_by ?? []).map((f) => FINDER_WORDS[f] ?? f);
  return got.length ? `found by: ${got.join(', ')}` : null;
}

export function suggestionLine(s: TrackSuggestion): string {
  if (s.of) return `${s.source}: ${s.n} of its ${s.of} posts in 30 days are your ${s.track_name} — make it active?`;
  return `${s.source}: ${s.n} of your ${s.track_name} in 30 days — make it active?`;
}

/** The moment a section's "new" counts from: its own last look, else the track's look before this visit. */
export function baseline(seen: TrackSeen | null | undefined, sectionId: string | null): string | null {
  if (!seen) return null;
  return (sectionId && seen.subtopics[sectionId]) || seen.track;
}

/** How many posts joined after the look (none before any look: the first look sets the baseline). */
export function newSince(joined: number[] | undefined, since: string | null): number {
  if (!since || !joined?.length) return 0;
  const t = Date.parse(since) / 1000;
  if (Number.isNaN(t)) return 0;
  let n = 0;
  for (const j of joined) if (j > t) n += 1;
  return n;
}

/** Whether one post joined after the look. */
export function isNew(item: Pick<TrackItem, 'joined_at'>, since: string | null): boolean {
  if (!since || !item.joined_at) return false;
  return Date.parse(item.joined_at) > Date.parse(since);
}

/** "12 new since you looked" for the whole track (its sections' counts added). */
export function trackNewLine(page: Pick<TrackPage, 'sections'>, seen: TrackSeen | null | undefined): string | null {
  if (!seen?.track) return null;
  const n = page.sections.reduce((acc, s) => acc + newSince(s.joined, seen.track), 0);
  return n ? `${plural(n, 'post')} new since you looked` : 'nothing new since you looked';
}

/** A sub-topic's state in words: found this week, or quiet (nothing new in 30 days). */
export function stateWords(s: Pick<TrackSection, 'state'>): string | null {
  if (s.state === 'new') return 'new this week';
  if (s.state === 'quiet') return 'quiet';
  return null;
}

/** A Shadow feature's label: "Shadow: 79% of posts in the right sub-topic (157 of 200 checked)". */
export function shadowLine(m: ShadowMeasure | undefined): string | null {
  if (!m || m.on) return null;
  return `Shadow: ${pct(m.right / m.of)} of ${m.what} (${m.right} of ${m.of} checked)`;
}

/** One tool's line: who discusses it and how recently. */
export function toolLine(t: TrackTool): string {
  return [plural(t.voices, 'voice'), plural(t.posts, 'post'), t.recent ? `${t.recent} in 30 days` : null]
    .filter(Boolean).join(' · ');
}

export function footerLine(f: NonNullable<TrackPage['footer']>, counts: TrackPage['counts']): string {
  return [`$${f.cost_usd.toFixed(2)} so far`, `$${f.cost_per_day.toFixed(2)} a day`,
    `${f.items_per_day} items a day`, plural(f.tasks, 'question'),
    counts.out ? `${plural(counts.out, 'post')} judged out (kept)` : null,
    counts.checked_out ? `${plural(counts.checked_out, 'post')} taken out by the blind check` : null].filter(Boolean).join(' · ');
}

const NOT_ASKED: Record<string, string> = {
  not_a_topic: 'this track has no description, so nothing is judged',
  labelled: 'your label places it',
  not_planned: 'its source is in this track; Haiku asks it at the next run',
  not_embedded: 'not embedded yet, so no finder could read it',
  no_profile: 'the track’s finders have not run yet',
  history_pending: 'older than the description, and the history pass has not reached it yet',
};

/** One line on where a post stands in the track and why, from Haiku's stored verdict. */
export function whyLine(w: TrackWhy): string {
  const conf = w.confidence != null ? ` (confidence ${pct(w.confidence)})` : '';
  const said = w.why ? `: “${w.why}”` : '';
  const older = w.current === false ? ' — judged under an earlier description' + (w.waiting_again ? ', asked again' : '') : '';
  if (w.label && w.reason === 'labelled') return w.label === 'in' ? 'In: your ✓' : 'Out: your ✗';
  switch (w.state) {
    case 'in':
      return (w.label === 'in' ? 'In: your ✓' : `In: Haiku says it belongs${conf}${said}`) + older;
    case 'joined':
      return `In (joined by INSIGHT): Haiku says it belongs${conf}${said}${older}`;
    case 'discover': {
      const at = w.position && w.of ? `, ${w.position} of ${w.of}` : '';
      const cut = w.shown === false && w.cut ? ` — below the Discover cut (the page shows ${w.cut})` : '';
      return `In Discover${at}: Haiku says it belongs${conf}, but its source is not in this track${said}${cut}${older}`;
    }
    case 'checked_out':
      return `Out (the blind check): Haiku said it belongs${conf}${said}, and the second, blind check said it doesn’t`;
    case 'checking':
      return `Waiting for the blind check: Haiku says it belongs${conf}${said}, past this week’s Discover picks; the check joins it or takes it out`;
    case 'out':
      return (w.label === 'out' ? 'Out: your ✗' : `Out: Haiku says it doesn’t belong${conf}${said}`) + older;
    case 'waiting':
      return 'Asked, waiting for Haiku’s answer';
    case 'invalid':
      return 'Asked, but Haiku’s answers named nothing of the post (asked twice): not judged';
    default:
      if (w.reason === 'not_planned' && w.found_by?.length) return `Not asked yet: ${foundByLine(w)} — Haiku asks it at the next run`;
      if (w.reason === 'outside_window') return `Not asked: its source is in this track, but it is older than the reading window (${plural(w.days ?? 0, 'day')})`;
      if (w.reason === 'below_bar') return `Not asked: its source is not in this track, and the finders did not put it up${w.bar != null ? ` (bar ${w.bar.toFixed(2)})` : ''}`;
      return `Not asked: ${NOT_ASKED[w.reason ?? ''] ?? 'never judged for this track'}`;
  }
}

/** Discover's line: each recent week's best picks for review; the rest the blind check decides. */
export function discoverLine(counts: { discover?: number; checking?: number }, perWeek = 25, weeks = 4): string {
  const rest = counts.checking ? ` · ${plural(counts.checking, 'more post')} waiting for the blind check, which joins them or takes them out` : '';
  return `Posts from your other sources that look like this track: each week’s ${perWeek} best of the last ${plural(weeks, 'week')}, for your review. ✓ takes one in; ✗ teaches it what doesn’t belong.${rest}`;
}
