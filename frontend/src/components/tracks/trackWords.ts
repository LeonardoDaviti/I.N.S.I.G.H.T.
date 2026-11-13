// The track page's lines in words (issue 0145): pure, so they are tested apart.
import type { TrackCalibration, TrackItem, TrackPage, TrackSuggestion, TrackWhy } from '../../services/tracks';
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
  classifier: 'classifier',
};

/** 0147: "found by: example post, entity, domain" (null for an active source's item, which every post is). */
export function foundByLine(item: Pick<TrackItem, 'found_by'>): string | null {
  const got = (item.found_by ?? []).map((f) => FINDER_WORDS[f] ?? f);
  return got.length ? `found by: ${got.join(', ')}` : null;
}

export function suggestionLine(s: TrackSuggestion): string {
  return `${s.source}: ${s.n} of your ${s.track_name} in 30 days — make it active?`;
}

export function footerLine(f: NonNullable<TrackPage['footer']>, counts: TrackPage['counts']): string {
  return [`$${f.cost_usd.toFixed(2)} so far`, `$${f.cost_per_day.toFixed(2)} a day`,
    `${f.items_per_day} items a day`, plural(f.tasks, 'question'),
    counts.out ? `${plural(counts.out, 'post')} judged out (kept)` : null].filter(Boolean).join(' · ');
}

const NOT_ASKED: Record<string, string> = {
  not_a_topic: 'this track has no description, so nothing is judged',
  labelled: 'your label places it',
  not_planned: 'its source is in this track; Haiku asks it at the next run',
  not_embedded: 'not embedded yet, so no finder could read it',
  no_profile: 'the track’s finders have not run yet',
  history_pending: 'older than the description, and the history pass has not reached it yet',
};

/** Issue 0185: one line on where a post stands in the track and why, from Haiku's stored verdict. */
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
    case 'out':
      return (w.label === 'out' ? 'Out: your ✗' : `Out: Haiku says it doesn’t belong${conf}${said}`) + older;
    case 'waiting':
      return 'Asked, waiting for Haiku’s answer';
    default:
      if (w.reason === 'outside_window') return `Not asked: its source is in this track, but it is older than the reading window (${plural(w.days ?? 0, 'day')})`;
      if (w.reason === 'below_bar') return `Not asked: its source is not in this track, and the finders did not put it up${w.bar != null ? ` (bar ${w.bar.toFixed(2)})` : ''}`;
      return `Not asked: ${NOT_ASKED[w.reason ?? ''] ?? 'never judged for this track'}`;
  }
}
