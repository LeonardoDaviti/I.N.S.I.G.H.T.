/**
 * The one HTTP call the API client makes. Every failure throws an `ApiError` with a screen-fit sentence: status 0
 * when unreachable; a non-2xx's status and `detail`; a 2xx `{success: false, error}`'s status and `error`. An
 * abort rejects with the `AbortError`. Pure, so `node --test` can exercise it.
 */
import { ApiError, apiErrorFromResponse, cleanErrorMessage, isAbortError, toApiError } from './apiError.ts';

/** The `{success, error}` envelope most endpoints wrap their answer in. */
export interface Envelope {
  success?: boolean;
  error?: string;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
}

// Relative by default (the Vite dev proxy forwards /api to the backend). VITE_API_URL overrides it.
const API_BASE_URL: string = (import.meta as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL || '';

/** An API path as a link or a download opens it. */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      method: options.method ?? 'GET',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw toApiError(error);
  }
  if (!response.ok) throw await apiErrorFromResponse(response);

  const body = (await response.json()) as T;
  const envelope = body as Envelope | null;
  if (envelope && typeof envelope === 'object' && envelope.success === false) {
    const message = typeof envelope.error === 'string' ? cleanErrorMessage(envelope.error) : '';
    throw new ApiError(response.status, message || 'The request failed', body);
  }
  return body;
}

/** For screens that read `{success: false, error}` instead of catching: any failure resolves as that envelope
 *  alone (no other fields). An abort still rejects. */
export async function settle<T extends Envelope>(call: Promise<T>): Promise<T> {
  try {
    return await call;
  } catch (error) {
    if (isAbortError(error)) throw error;
    return { success: false, error: toApiError(error).message } as T;
  }
}
