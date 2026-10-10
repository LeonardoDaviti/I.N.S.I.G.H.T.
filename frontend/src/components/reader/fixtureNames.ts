/**
 * The names of the reader's dev-only `?data=` fixtures. Kept apart from the
 * fixtures themselves, so a production build bundles the names (a few bytes)
 * but never the fixture data: ReaderPage imports the data lazily, in dev only.
 */
export type FeedFixtureName = 'worst' | 'empty' | 'one' | 'huge';
export const FEED_FIXTURE_NAMES: readonly FeedFixtureName[] = ['worst', 'empty', 'one', 'huge'];

export function isFeedFixtureName(value: string | null | undefined): value is FeedFixtureName {
  return FEED_FIXTURE_NAMES.includes(value as FeedFixtureName);
}
