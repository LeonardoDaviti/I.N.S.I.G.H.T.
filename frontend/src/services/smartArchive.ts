// The smart archiver's calls and shapes (issue 0143), beside createApi's: their own module, as the voices' are.
import { request } from '../lib/request';

/** settings.archive's coverage line (GET /api/archive/{id}/status `archive.coverage`, the catalog's `coverage`):
 *  what the smart archiver measured of a feed's site. */
export interface ArchiveCoverage {
  stored: number;
  /** The site's posts, the largest trustworthy estimate (an API's total, the sitemap's, a listing's); null unknown. */
  estimate: number | null;
  /** The platform it is built with: wordpress, blogger, ghost, newsletter, bearblog, hugo, jekyll, … or unknown. */
  platform: string | null;
  /** The first strategy that found more: feed_pages, api, sitemap, listing, web_archive; null none. */
  strategy: string | null;
  found_more: boolean;
  /** Every strategy that found more has run to its end. */
  exhausted: boolean;
  /** Each other strategy's outcome: why the rest is not stored (no_sitemap, listing_unread, api_refused:403, …). */
  reasons: Record<string, string>;
  /** Posts each strategy gave, the last archive. */
  worked?: Record<string, number>;
  /** The Web Archive's index is this source's last resort (opt-in). */
  web_archive?: boolean;
}

export interface DiscoveredSite {
  key: string;
  site: string;
  platform: boolean;
  state: 'open' | 'followed' | 'hidden';
  /** Voices Discover counts linking it (this source among them). */
  voices: number;
  articles: number | null;
  addresses: number | null;
  first_linked: string | null;
  followed_source: { id: string; name: string; added_at: string | null } | null;
}

export interface SourceDiscoveries {
  source_id: string;
  sites: DiscoveredSite[];
  /** Sources you added after this one linked them (inferred: nothing records where a follow came from). */
  followed_from_here: Array<{ id: string; name: string; added_at: string | null; key: string }>;
  originals: Array<{ kind: string; url: string; outcome: string; post_id: string | null; story_id: string | null;
    asked_at: string | null; title: string | null }>;
  entities: Array<{ id: string; name: string; type: string | null; post_id: string | null; at: string | null;
    post_title: string | null }>;
  counts: Record<string, number>;
  /** Discover has counted (its story job keeps the counts); before that no site can be listed. */
  discover_counted: boolean;
}

export const smartArchiveApi = {
  discoveries: (sourceId: string) =>
    request<SourceDiscoveries>(`/api/sources/${encodeURIComponent(sourceId)}/discoveries`),
  setWebArchive: (sourceId: string, on: boolean) =>
    request<{ on: boolean }>(`/api/archive/${encodeURIComponent(sourceId)}/web-archive`, { method: 'PUT', body: { on } }),
};
