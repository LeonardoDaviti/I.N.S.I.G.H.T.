import type { FeedStory, SuggestedSource } from '../services/api';
import { plural } from './format.ts';
import { sourceLabel } from './sourceLabel.ts';

/** The names a folded story's row shows before "+N" (issue 0050). */
const NAMES_SHOWN = 2;

/** "covered by 3 · Anthropic, Simon Willison, +1": every source of the story, in the order they covered it. */
export function coveredBy(story: FeedStory): string {
  const names = story.sources.map((source) => sourceLabel(source.name));
  const shown = names.slice(0, NAMES_SHOWN).join(', ');
  const more = names.length - NAMES_SHOWN;
  return `covered by ${names.length} · ${shown}${more > 0 ? `, +${more}` : ''}`;
}

/** The names a suggestion's reason shows before "+N". */
const VOICES_SHOWN = 3;

/** Discover: "linked by 6 of your sources (Simon Willison, Anthropic, One Useful Thing, +3) · 9 articles". */
export function suggestionReason(s: SuggestedSource): string {
  const names = s.voice_names.map((name) => sourceLabel(name));
  const more = names.length - VOICES_SHOWN;
  const who = `${names.slice(0, VOICES_SHOWN).join(', ')}${more > 0 ? `, +${more}` : ''}`;
  return `linked by ${s.voices} of your sources (${who}) · ${plural(s.article_count, 'article')}`;
}
