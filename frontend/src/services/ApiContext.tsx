import { createContext, useContext, type ReactNode } from 'react';
import { createApi, type Api } from './api';

/** The API seam: screens and hooks call `useApi()`, so a test can render them in `<ApiProvider value={fakeApi}>`. */
const realApi = createApi();
const ApiContext = createContext<Api>(realApi);

export function ApiProvider({ value = realApi, children }: { value?: Api; children: ReactNode }) {
  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- the hook belongs with its provider
export function useApi(): Api {
  return useContext(ApiContext);
}
