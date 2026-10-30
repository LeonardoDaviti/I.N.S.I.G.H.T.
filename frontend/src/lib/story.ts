import type { FeedStory, SuggestedSource } from '../services/api';
import { plural } from './format.ts';
import { sourceLabel } from './sourceLabel.ts';

/** The names a folded story's row shows before "+N" (issue 0050), and a News row (issue 0051). */
const NAMES_SHOWN = 2;

/** "Anthropic, Simon Willison, +1": a story's sources in the order they covered it, two named. */
export function coveredNames(story: FeedStory): string {
  const all = story.sources.map((source) => sourceLabel(source.name));
  const more = all.length - NAMES_SHOWN;
  return `${all.slice(0, NAMES_SHOWN).join(', ')}${more > 0 ? `, +${more}` : ''}`;
}

/** "covered by 3 · Anthropic, Simon Willison, +1": every source of the story, in the order they covered it. */
export function coveredBy(story: FeedStory): string {
  return `covered by ${story.sources.length} · ${coveredNames(story)}`;
}

/** The names a suggestion's reason shows before "+N". */
const VOICES_SHOWN = 3;

/** Discover: "linked by 6 of your sources (Simon Willison, Anthropic, One Useful Thing, +3) · 9 articles",
 *  and " · 2 classics" when it holds some (issue 0051). */
export function suggestionReason(s: SuggestedSource): string {
  const names = s.voice_names.map((name) => sourceLabel(name));
  const more = names.length - VOICES_SHOWN;
  const who = `${names.slice(0, VOICES_SHOWN).join(', ')}${more > 0 ? `, +${more}` : ''}`;
  const classics = s.classics ? ` · ${plural(s.classics, 'classic')}` : '';
  return `linked by ${s.voices} of your sources (${who}) · ${plural(s.article_count, 'article')}${classics}`;
}
