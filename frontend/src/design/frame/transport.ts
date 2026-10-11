/**
 * The fixture transport (Design Studio D4): a `fetch` that answers the app's
 * API calls from fixtures, so a frame renders the real page on sample data.
 * Installed on the frame's own window only; the studio's `fetch` is never
 * touched. Every API call in the app goes through `fetch` (services/api.ts,
 * services/trackApi.ts), so the page code doesn't change.
 *
 * - A GET answers from the first route whose method and path match.
 * - A GET with no route is reported (`unmocked`) and answered 501, or, with
 *   `data: 'live'`, passed through to the real API.
 * - A write (POST, PUT, PATCH, DELETE) never reaches the network, in either
 *   mode: it is reported (`write`) and answered by its route or a fake OK.
 * - Anything outside `/api/` passes through untouched.
 */

export type FrameData = 'fixtures' | 'live';

export interface FixtureRequest {
  method: string;
  /** The URL path, e.g. `/api/feed`. */
  path: string;
  query: URLSearchParams;
  /** The `:name` segments of a string route, or the named groups of a RegExp route. */
  params: Record<string, string>;
  /** The JSON body of a write, when it has one. */
  body: unknown;
}

/**
 * A route answers with a `Response` (status, never-resolving promise, …) or with
 * any other value, which is sent as a 200 JSON body.
 */
export interface FixtureRoute {
  /** GET when omitted. */
  method?: string;
  /** `/api/posts/item/:postId` (exact, `:name` matches one segment) or a RegExp on the path. */
  path: string | RegExp;
  respond: (request: FixtureRequest) => unknown;
}

export interface TransportEvent {
  kind: 'unmocked' | 'write';
  method: string;
  /** The path with its query, e.g. `/api/feed?scope=all`. */
  path: string;
}

export interface TransportOptions {
  routes: readonly FixtureRoute[];
  data: FrameData;
  /** The window's own fetch, for live reads and anything outside the API. */
  realFetch: typeof fetch;
  onEvent: (event: TransportEvent) => void;
  /** Resolves relative URLs; defaults to the window's origin. */
  origin?: string;
}

const READS = new Set(['GET', 'HEAD']);

/** A 200 JSON response. */
export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

/** The loading state: a response that never arrives. */
export function pending(): Promise<Response> {
  return new Promise<Response>(() => {});
}

/** The error state: a server error with the backend's `detail` message. */
export function serverError(detail: string, status = 500): Response {
  return json({ detail }, status);
}

function pathPattern(path: string): RegExp {
  const source = path
    .split('/')
    .map((segment) => (segment.startsWith(':')
      ? `(?<${segment.slice(1)}>[^/]+)`
      : segment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
    .join('/');
  return new RegExp(`^${source}$`);
}

function match(route: FixtureRoute, method: string, path: string): Record<string, string> | null {
  if ((route.method ?? 'GET').toUpperCase() !== method) return null;
  const pattern = typeof route.path === 'string' ? pathPattern(route.path) : route.path;
  const found = pattern.exec(path);
  if (!found) return null;
  const params: Record<string, string> = {};
  for (const [name, value] of Object.entries(found.groups ?? {})) {
    if (value !== undefined) params[name] = decodeURIComponent(value);
  }
  return params;
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') return undefined;
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

export function createFixtureTransport(options: TransportOptions): typeof fetch {
  const { routes, data, realFetch, onEvent } = options;
  const origin = options.origin ?? (typeof window === 'undefined' ? 'http://localhost' : window.location.origin);

  return async function fixtureFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const request = input instanceof Request ? input : null;
    const url = new URL(request ? request.url : String(input), origin);
    const method = (init?.method ?? request?.method ?? 'GET').toUpperCase();
    if (url.origin !== new URL(origin).origin || !url.pathname.startsWith('/api/')) {
      return realFetch(input, init);
    }

    const path = url.pathname;
    const shown = `${path}${url.search}`;
    const isRead = READS.has(method);
    for (const route of routes) {
      const params = match(route, method, path);
      if (!params) continue;
      if (!isRead) onEvent({ kind: 'write', method, path: shown });
      const answer = await route.respond({ method, path, query: url.searchParams, params, body: parseBody(init?.body) });
      return answer instanceof Response ? answer : json(answer);
    }

    if (!isRead) {
      onEvent({ kind: 'write', method, path: shown });
      return json({ success: true });
    }
    if (data === 'live') return realFetch(input, init);
    onEvent({ kind: 'unmocked', method, path: shown });
    return json({ detail: `unmocked request: ${method} ${shown}` }, 501);
  };
}
