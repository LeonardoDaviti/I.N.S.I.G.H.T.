// The track page's lines in words (issue 0145): pure, so they are tested apart.
import type { TrackCalibration, TrackItem, TrackPage, TrackSuggestion } from '../../services/tracks';
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

export function suggestionLine(s: TrackSuggestion): string {
  return `${s.source}: ${s.n} of your ${s.track_name} in 30 days — make it active?`;
}

export function footerLine(f: NonNullable<TrackPage['footer']>, counts: TrackPage['counts']): string {
  return [`$${f.cost_usd.toFixed(2)} so far`, `$${f.cost_per_day.toFixed(2)} a day`,
    `${f.items_per_day} items a day`, plural(f.tasks, 'question'),
    counts.out ? `${plural(counts.out, 'post')} judged out (kept)` : null].filter(Boolean).join(' · ');
}
