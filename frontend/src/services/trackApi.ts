/**
 * Track (folder) edits the Sources page makes from a track header: rename and
 * the main-digest switch. Kept out of api.ts on purpose (that file has other
 * owners right now); same error contract as the Mark IX calls there: a non-2xx
 * or `success: false` throws, so callers show one message.
 */
import { apiErrorFromResponse, toApiError } from '../lib/apiError';

const API_BASE_URL = (import.meta as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL || '';

async function put(path: string, body: unknown, fallback: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (error) {
    throw toApiError(error);
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  const json = (await response.json()) as { success?: boolean; error?: string };
  if (json.success === false) throw new Error(json.error || fallback);
}

export function renameTrack(folderId: string, name: string): Promise<void> {
  return put(`/api/folders/${encodeURIComponent(folderId)}`, { name }, 'Could not rename the track');
}

/** Every source in the track in (true) or out of (false) the main feed and digest. */
export function setTrackMainDigest(folderId: string, inMainDigest: boolean): Promise<void> {
  return put(
    `/api/folders/${encodeURIComponent(folderId)}/main-digest`,
    { in_main_digest: inMainDigest },
    'Could not change the main-digest setting',
  );
}
