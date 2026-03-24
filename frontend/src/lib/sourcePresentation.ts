export type SourcePresentationItem = {
  id: string;
  platform: string;
  handle_or_url?: string | null;
  display_name?: string | null;
  settings?: {
    display_name?: string | null;
  } | null;
};

export type SourcePresentationGroup<T extends SourcePresentationItem> = {
  platform: string;
  totalCount: number;
  sources: T[];
};

export type SourceAvatarModel = {
  displayName: string;
  fallback: string;
  faviconUrl: string | null;
  platformKey: string;
  platformLabel: string;
};

const PLATFORM_LABELS: Record<string, string> = {
  reddit: 'Reddit',
  rss: 'RSS',
  telegram: 'Telegram',
  youtube: 'YouTube',
};

function cleanText(value?: string | null): string {
  return (value || '').trim();
}

function looksLikeUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

function shortenMiddle(value: string, maxLength = 42): string {
  if (value.length <= maxLength) {
    return value;
  }

  const headLength = Math.max(14, Math.floor((maxLength - 1) * 0.65));
  const tailLength = Math.max(8, maxLength - headLength - 1);
  return `${value.slice(0, headLength)}…${value.slice(-tailLength)}`;
}

function compactUrlLabel(value: string): string {
  try {
    const parsed = new URL(value);
    const host = parsed.host.replace(/^www\./i, '');
    const path = parsed.pathname.replace(/\/+$/g, '');
    const query = parsed.search || '';
    const compact = `${host}${path}${query}` || host;
    return shortenMiddle(compact, 44);
  } catch {
    return value.replace(/^https?:\/\//i, '').replace(/\/+$/g, '');
  }
}

function presentSourceText(value?: string | null): string {
  const text = cleanText(value);
  if (!text) {
    return '';
  }
  return looksLikeUrl(text) ? compactUrlLabel(text) : text;
}

export function getPlatformLabel(platform?: string | null): string {
  const key = cleanText(platform).toLowerCase();
  return PLATFORM_LABELS[key] || (key ? key.charAt(0).toUpperCase() + key.slice(1) : 'Source');
}

export function getSourceDisplayName(source: SourcePresentationItem): string {
  return (
    presentSourceText(source.display_name)
    || presentSourceText(source.settings?.display_name)
    || presentSourceText(source.handle_or_url)
    || presentSourceText(source.id)
    || 'Unknown source'
  );
}

export function getSourceHandleLabel(source: SourcePresentationItem): string {
  return presentSourceText(source.handle_or_url) || presentSourceText(source.id) || 'Unknown source';
}

function sourceSearchText(source: SourcePresentationItem): string {
  return [
    getPlatformLabel(source.platform),
    cleanText(source.platform),
    getSourceDisplayName(source),
    cleanText(source.handle_or_url),
    cleanText(source.id),
  ]
    .join(' ')
    .toLowerCase();
}

function normalizeInitialsSeed(value: string): string {
  return value
    .replace(/^https?:\/\//i, '')
    .replace(/^www\./i, '')
    .replace(/^r\//i, '')
    .trim();
}

function pickFallback(seed: string): string {
  const normalized = normalizeInitialsSeed(seed);
  const uppercase = normalized.replace(/[^A-Z]/g, '');
  if (uppercase.length >= 2) {
    return uppercase.slice(0, 2);
  }

  const parts = normalized.split(/[^A-Za-z0-9]+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  const compact = (parts[0] || normalized).replace(/[^A-Za-z0-9]/g, '');
  if (!compact) {
    return '??';
  }
  return compact.slice(0, 2).toUpperCase();
}

function getFaviconUrl(source: SourcePresentationItem): string | null {
  const candidate = cleanText(source.handle_or_url);
  if (!candidate) {
    return null;
  }

  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return null;
    }
    return `https://www.google.com/s2/favicons?sz=64&domain_url=${encodeURIComponent(parsed.origin)}`;
  } catch {
    return null;
  }
}

export function getSourceAvatarModel(source: SourcePresentationItem): SourceAvatarModel {
  return {
    displayName: getSourceDisplayName(source),
    fallback: pickFallback(getSourceDisplayName(source)),
    faviconUrl: getFaviconUrl(source),
    platformKey: cleanText(source.platform).toLowerCase(),
    platformLabel: getPlatformLabel(source.platform),
  };
}

export function filterSourceGroups<T extends SourcePresentationItem>(
  groups: Array<SourcePresentationGroup<T>>,
  query: string,
): Array<SourcePresentationGroup<T>> {
  const term = cleanText(query).toLowerCase();
  if (!term) {
    return groups;
  }

  return groups.flatMap((group) => {
    const platformMatch = [
      cleanText(group.platform).toLowerCase(),
      getPlatformLabel(group.platform).toLowerCase(),
    ].some((value) => value.includes(term));

    if (platformMatch) {
      return [group];
    }

    const sources = group.sources.filter((source) => sourceSearchText(source).includes(term));
    if (!sources.length) {
      return [];
    }

    return [{
      ...group,
      sources,
    }];
  });
}
