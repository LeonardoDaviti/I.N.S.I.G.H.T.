import type { FeedStory, NewsScore } from '../services/api';
import { plural } from './format.ts';
import { coveredNames } from './story.ts';

// News (issue 0051): kept apart from lib/story.ts, which the feed row (the reader's initial JS)
// imports; only the News view reads these.

/** What a News story's score is made of, in words: "4 sources · 1 share · in 1 roundup". */
export function newsWords(news: Pick<NewsScore, 'reports' | 'shares' | 'mentions'>): string {
  return [
    news.reports ? plural(news.reports, 'source') : null,
    news.shares ? plural(news.shares, 'share') : null,
    news.mentions ? `in ${plural(news.mentions, 'roundup')}` : null,
  ].filter(Boolean).join(' · ');
}

/** A News row's line: its score in words, then who covered it, the first reporter first. */
export function newsLine(news: NewsScore, story: FeedStory): string {
  return `${newsWords(news)} · ${coveredNames(story)}`;
}
