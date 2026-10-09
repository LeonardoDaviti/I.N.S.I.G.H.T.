import type { ReactElement, ReactNode } from 'react';
import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Toaster } from 'sonner';

import { ApiProvider } from '../services/ApiContext';
import type { Api } from '../services/api';

/** A QueryClient for tests: no retries (an error renders at once), no cache sharing. */
export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

/** Render inside the app's providers: a fake API, a fresh QueryClient, a MemoryRouter and a Toaster. */
export function renderWithProviders(
  ui: ReactElement,
  { api, route = '/', queryClient = makeTestQueryClient() }: { api: Api; route?: string; queryClient?: QueryClient },
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ApiProvider value={api}>
          <MemoryRouter initialEntries={[route]}>
            {children}
            <Toaster />
          </MemoryRouter>
        </ApiProvider>
      </QueryClientProvider>
    );
  }
  return { queryClient, ...render(ui, { wrapper: Wrapper }) };
}
