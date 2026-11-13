import type { Api } from '../services/api';

/**
 * A fake `Api` for `<ApiProvider value={...}>`: only the methods a test provides
 * exist. Calling anything else throws, naming the method, so a component that
 * reaches for an unexpected endpoint fails loudly instead of hitting the network.
 */
export function makeFakeApi(methods: Partial<Record<keyof Api, unknown>>): Api {
  return new Proxy(methods as object, {
    get(target, prop) {
      if (prop in target) return (target as Record<PropertyKey, unknown>)[prop];
      // Issue 0195: the running jobs are the overview's recent jobs; a test that serves the overview serves them.
      if (prop === 'getRunningJobs' && 'getOperationsOverview' in target) {
        return (target as Record<string, unknown>).getOperationsOverview;
      }
      if (prop === 'then' || typeof prop === 'symbol') return undefined;
      return () => {
        throw new Error(`fakeApi: ${String(prop)} was called but the test did not provide it`);
      };
    },
  }) as Api;
}
