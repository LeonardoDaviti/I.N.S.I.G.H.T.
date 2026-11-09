/**
 * A feed's coverage in words (issue 0143): "stored 19 of ~34", the platform its site is built with, how the
 * rest was found, and why what is missing is missing. Pure.
 */
import type { ArchiveCoverage, DiscoveredSite } from '../services/smartArchive';
import { formatCount } from './format.ts';

const PLATFORMS: Record<string, string> = {
  wordpress: 'WordPress', blogger: 'Blogger', ghost: 'Ghost', newsletter: 'a newsletter platform', bearblog: 'Bear Blog',
  hugo: 'Hugo', jekyll: 'Jekyll', medium: 'Medium', writeas: 'Write.as', 'micro.blog': 'Micro.blog', tumblr: 'Tumblr',
};

const STRATEGIES: Record<string, string> = {
  feed_pages: "the feed's older pages",
  api: "the platform's archive API",
  sitemap: 'the sitemap',
  listing: 'the listing pages',
  web_archive: "the Web Archive's index",
};

const OUTCOMES: Record<string, string> = {
  no_paging: 'the feed has no older pages',
  paging_same: 'its older pages repeat the feed',
  paging_unread: 'its older pages could not be read',
  no_api: 'no archive API on this platform',
  api_no_more: 'the API lists nothing more',
  no_sitemap: 'no sitemap',
  sitemap_no_posts: 'the sitemap lists no more posts',
  listing_unread: 'no listing page could be read',
  listing_no_posts: 'the listing pages show no more posts',
  listing_no_shape: "the feed's items give no address shape",
  web_archive_no_posts: 'the Web Archive lists no more',
};

export function platformName(platform: string | null | undefined): string | null {
  if (!platform || platform === 'unknown') return null;
  return PLATFORMS[platform] ?? platform;
}

export function strategyName(strategy: string | null | undefined): string | null {
  return strategy ? STRATEGIES[strategy] ?? strategy : null;
}

/** "api_refused:403" -> "refused (HTTP 403)", "blocked:429" -> "blocked (HTTP 429)", a known code in words. */
export function outcomeWords(outcome: string): string {
  const [code, detail] = outcome.split(':', 2);
  if (OUTCOMES[outcome]) return OUTCOMES[outcome];
  if (code === 'api_refused' || code === 'paging_refused') return `refused${detail ? ` (${/^\d+$/.test(detail) ? `HTTP ${detail}` : detail.replace(/_/g, ' ')})` : ''}`;
  if (code === 'blocked') return `blocked${detail ? ` (HTTP ${detail})` : ''}`;
  if (code === 'error') return `could not be read${detail ? ` (${detail})` : ''}`;
  return outcome.replace(/_/g, ' ');
}

/** "Stored 19 of ~34" (the estimate, a guess, rounded as the source counts), or "Stored 19" with no estimate. */
export function coverageFigure(coverage: ArchiveCoverage): string {
  const stored = formatCount(coverage.stored);
  return coverage.estimate ? `Stored ${stored} of ~${formatCount(coverage.estimate)}` : `Stored ${stored}`;
}

/** The coverage line and its notes, as the archive section shows them. */
export function describeCoverage(coverage: ArchiveCoverage): { figure: string; how: string | null; reasons: string[] } {
  const platform = platformName(coverage.platform);
  const strategy = strategyName(coverage.strategy);
  const parts: string[] = [];
  if (platform) parts.push(`Built with ${platform}`);
  if (strategy && coverage.found_more) {
    parts.push(`${parts.length ? 'the' : 'The'} rest ${coverage.exhausted ? 'was' : 'is'} read from ${strategy}`);
  } else {
    parts.push(`${parts.length ? 'every' : 'Every'} way to find older posts was tried`);
  }
  const how = parts.length ? `${parts.join('; ')}.` : null;
  const reasons = Object.entries(coverage.reasons ?? {})
    .map(([name, outcome]) => `${strategyName(name) ?? name}: ${outcomeWords(outcome)}`);
  return { figure: coverageFigure(coverage), how, reasons };
}

/** The catalog's "19 of ~34 stored", or null when the smart archiver has not measured the source. */
export function catalogCoverage(coverage: ArchiveCoverage | null | undefined): string | null {
  if (!coverage) return null;
  return coverage.estimate
    ? `${formatCount(coverage.stored)} of ~${formatCount(coverage.estimate)} stored`
    : `${formatCount(coverage.stored)} stored`;
}

/** "followed · 4 voices · 12 articles" for a discovered site's line. */
export function discoveredLine(site: DiscoveredSite): string {
  const parts: string[] = [site.state === 'followed' ? 'followed' : site.state === 'hidden' ? 'hidden' : 'not followed'];
  parts.push(`${site.voices} voice${site.voices === 1 ? '' : 's'}`);
  if (site.articles) parts.push(`${formatCount(site.articles)} article${site.articles === 1 ? '' : 's'} linked`);
  return parts.join(' · ');
}
