import { createContext, useContext, type ReactNode } from 'react';
import { apiService, type Api } from './api';

/**
 * The API seam for components (Mark IX §3). New components call `useApi()` and
 * never import `apiService` directly, so a test can render them inside
 * `<ApiProvider value={fakeApi}>`. The default value is the real singleton, so a
 * component rendered without a provider (and the Mark VIII files that import
 * `apiService` directly) keep working unchanged.
 */
const ApiContext = createContext<Api>(apiService);

export function ApiProvider({ value = apiService, children }: { value?: Api; children: ReactNode }) {
  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- the hook belongs with its provider
export function useApi(): Api {
  return useContext(ApiContext);
}
