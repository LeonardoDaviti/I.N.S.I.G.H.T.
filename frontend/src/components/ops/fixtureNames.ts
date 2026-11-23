/** The names of the Sources page's dev-only `?data=` fixtures, apart from the data so a production build bundles
 *  only the names (SourcesConfig imports the data lazily, in dev only). */
export type HealthFixtureName = 'worst' | 'empty' | 'one' | 'huge';
export const HEALTH_FIXTURE_NAMES: readonly HealthFixtureName[] = ['worst', 'empty', 'one', 'huge'];

export function isHealthFixtureName(value: string | null | undefined): value is HealthFixtureName {
  return HEALTH_FIXTURE_NAMES.includes(value as HealthFixtureName);
}
