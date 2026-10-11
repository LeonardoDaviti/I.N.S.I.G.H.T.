/**
 * The names of the Sources page's dev-only `?data=` fixtures. Kept apart from the
 * fixtures themselves, so a production build bundles the names (a few bytes)
 * but never the fixture data: SourcesConfig imports the data lazily, in dev only.
 */
export type HealthFixtureName = 'worst' | 'empty' | 'one' | 'huge';
export const HEALTH_FIXTURE_NAMES: readonly HealthFixtureName[] = ['worst', 'empty', 'one', 'huge'];

export function isHealthFixtureName(value: string | null | undefined): value is HealthFixtureName {
  return HEALTH_FIXTURE_NAMES.includes(value as HealthFixtureName);
}
