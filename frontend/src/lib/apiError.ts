/**
 * The one error type the API client throws. `message` is always a human sentence (the server's `detail`, else
 * one for the status), never the url or an "API request failed:" prefix. `status` is 0 when the backend was
 * unreachable. Pure, so `node --test` can exercise it.
 */
export class ApiError extends Error {
  readonly status: number;
  /** The parsed error body when there was one (JSON object or text), for debugging. */
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

const STATUS_MESSAGES: Record<number, string> = {
  0: 'Could not reach the backend. Check that it is running.',
  400: 'The request was not valid',
  401: 'Not authorised',
  403: 'Not allowed',
  404: 'Not found',
  408: 'The request timed out',
  409: 'That conflicts with the current state',
  422: 'The request was not valid',
  429: 'Too many requests. Try again shortly.',
  500: 'The backend hit an internal error',
  502: 'The backend is unavailable. Try again shortly.',
  503: 'The backend is unavailable. Try again shortly.',
  504: 'The backend took too long to answer',
};

export function statusMessage(status: number): string {
  return STATUS_MESSAGES[status] ?? `Request failed (${status})`;
}

/** Strip the old "API request failed: <status> " prefix and " | url=..." suffix from an error message. */
export function cleanErrorMessage(raw: string): string {
  let text = String(raw ?? '');
  const urlIndex = text.indexOf(' | url=');
  if (urlIndex >= 0) text = text.slice(0, urlIndex);
  text = text.replace(/^\s*API request failed:\s*/i, '');
  text = text.replace(/^\d{3}\s+(?=\S)/, '');
  return text.replace(/\s+/g, ' ').trim();
}

/** Reduce a non-JSON error body to something short and readable. */
export function normalizeErrorText(text: string, contentType: string): string | null {
  const raw = text.trim();
  if (!raw) return null;
  if (contentType.includes('text/html')) {
    const titleMatch = raw.match(/<title>(.*?)<\/title>/is);
    const headingMatch = raw.match(/<h1[^>]*>(.*?)<\/h1>/is);
    const best = titleMatch?.[1] || headingMatch?.[1] || raw;
    const stripped = best.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    return stripped.slice(0, 180) || null;
  }
  return raw.replace(/\s+/g, ' ').trim().slice(0, 240);
}

/** FastAPI sends `detail` as a string, or as a list of validation errors. */
function messageFromBody(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null;
  const record = body as Record<string, unknown>;
  const candidate = record.detail ?? record.error ?? record.message;
  if (typeof candidate === 'string' && candidate.trim()) return cleanErrorMessage(candidate);
  if (Array.isArray(candidate) && candidate.length) {
    const parts = candidate.map((item) => {
      if (item && typeof item === 'object') {
        const entry = item as { loc?: unknown; msg?: unknown };
        const loc = Array.isArray(entry.loc) ? entry.loc.filter((p) => p !== 'body' && p !== 'query') : [];
        const field = loc.length ? `${loc.join('.')}: ` : '';
        return `${field}${String(entry.msg ?? '')}`.trim();
      }
      return String(item);
    });
    const joined = parts.filter(Boolean).join('; ');
    return joined || null;
  }
  return null;
}

/** Build an ApiError from a non-2xx fetch Response. Never throws. */
export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  const status = response.status;
  let text = '';
  try {
    text = await response.text();
  } catch {
    text = '';
  }
  if (text.trim()) {
    try {
      const body: unknown = JSON.parse(text);
      const message = messageFromBody(body);
      if (message) return new ApiError(status, message, body);
      return new ApiError(status, statusMessage(status), body);
    } catch {
      const contentType = response.headers.get('content-type') || '';
      const normalized = normalizeErrorText(text, contentType);
      if (normalized) return new ApiError(status, normalized, text);
    }
  }
  return new ApiError(status, statusMessage(status), null);
}

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === 'object' && (error as { name?: unknown }).name === 'AbortError');
}

/** Normalise anything thrown into an ApiError; a fetch network failure (TypeError) is status 0. An AbortError
 *  is not converted: check `isAbortError` first if that matters. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof TypeError) return new ApiError(0, statusMessage(0), error.message);
  if (error instanceof Error) return new ApiError(-1, cleanErrorMessage(error.message) || 'Unknown error', error);
  if (typeof error === 'string' && error.trim()) return new ApiError(-1, cleanErrorMessage(error), error);
  return new ApiError(-1, 'Unknown error', error ?? null);
}

/** A clean, human message for anything thrown. */
export function errorMessage(error: unknown): string {
  return toApiError(error).message;
}

/** Worth retrying: unreachable, timed out, throttled or a 5xx. Client errors (4xx) and aborts are not. */
export function isTransientError(error: unknown): boolean {
  if (isAbortError(error)) return false;
  if (error instanceof TypeError) return true;
  if (error instanceof ApiError) {
    return error.status === 0 || error.status === 408 || error.status === 429 || error.status >= 500;
  }
  return false;
}

export { isAbortError };
