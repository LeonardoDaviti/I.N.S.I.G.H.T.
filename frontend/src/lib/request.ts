/**
 * The one HTTP call the API client makes (services/api.ts). Every failure throws
 * an `ApiError` whose message is a sentence fit for the screen:
 *
 * - the backend can't be reached: status 0;
 * - a non-2xx answer: its status and the server's `detail`;
 * - a 2xx answer with the `{success: false, error}` envelope: its status and `error`.
 *
 * An abort is not converted: it rejects with the `AbortError`.
 *
 * Pure (no DOM, no React) so `node --test` can exercise it directly.
 */
import { ApiError, apiErrorFromResponse, cleanErrorMessage, isAbortError, toApiError } from './apiError.ts';

/** The `{success, error}` envelope most endpoints wrap their answer in. */
export interface Envelope {
  success?: boolean;
  error?: string;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  /** Sent as JSON. */
  body?: unknown;
  signal?: AbortSignal;
}

// Relative by default (the Vite dev proxy forwards /api to the backend). VITE_API_URL overrides it.
const API_BASE_URL: string = (import.meta as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL || '';

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
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

/**
 * For the screens that read `{success: false, error}` instead of catching: any
 * failure resolves as that envelope (and only that: the answer's other fields are
 * absent). An abort still rejects.
 */
export async function settle<T extends Envelope>(call: Promise<T>): Promise<T> {
  try {
    return await call;
  } catch (error) {
    if (isAbortError(error)) throw error;
    return { success: false, error: toApiError(error).message } as T;
  }
}
