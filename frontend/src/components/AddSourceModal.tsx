import React, { useState, useEffect } from 'react';
import { Plus } from 'lucide-react';
import { useApi } from '../services/ApiContext';
import { Button, Dialog, DialogContent, DialogFooter, FilterChip, Input } from './ui';
import { SubstackHowTo, cookieValue, isSubstackUrl, useConnections, useSaveCredential } from './connections';
import { errorMessage } from '../lib/apiError';
import { localDateISO, toDate } from '../lib/dates';
import type { FeedFinding, FoundFeed, PageWatchPreview } from '../services/api';

type SourceState = 'enabled' | 'disabled' | 'error';

interface Template {
  id: string;
  name: string;
  platform: string;
  variableName: string;
  defaultVariableValue?: string;
  // An empty variable still builds a source (GitHub Trending: all languages).
  optionalVariable?: boolean;
  variableLabel?: string;
  placeholder?: string;
  helperText?: string;
  buildHandle: (value: string) => string;
  buildDisplayName?: (value: string) => string;
  defaultSettings: {
    fetch_delay_seconds: number;
    priority: number;
    max_posts_per_fetch: number;
  };
}

// Hardcoded templates
const TEMPLATES: Template[] = [
  {
    id: 'nitter',
    name: 'Nitter',
    platform: 'rss',
    variableName: 'username',
    variableLabel: 'Username',
    placeholder: 'Enter username...',
    helperText: 'Creates a source like https://nitter.local/{username}/rss',
    buildHandle: (value) => `https://nitter.local/${value.replace(/^@/, '').trim()}/rss`,
    buildDisplayName: (value) => value.replace(/^@/, '').trim(),
    defaultSettings: {
      fetch_delay_seconds: 10,
      priority: 999,
      max_posts_per_fetch: 50,
    },
  },
  {
    id: 'telegram-rss',
    name: 'Telegram RSS',
    platform: 'rss',
    variableName: 'username',
    variableLabel: 'Channel Username',
    placeholder: 'Enter channel username...',
    helperText: 'Creates a source like https://telegram.local/rss/seeallochnaya?limit=50',
    buildHandle: (value) => `https://telegram.local/rss/${value.replace(/^@/, '').trim()}?limit=50`,
    buildDisplayName: (value) => value.replace(/^@/, '').trim(),
    defaultSettings: {
      fetch_delay_seconds: 5,
      priority: 999,
      max_posts_per_fetch: 50,
    },
  },
  {
    id: 'lesswrong',
    name: 'LessWrong',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'lesswrong',
    variableLabel: 'Archive Scope',
    placeholder: 'Main LessWrong archive',
    helperText: 'Uses the custom LessWrong adapter for live fetch plus deep archive through GraphQL.',
    buildHandle: () => 'https://www.lesswrong.com/feed.xml',
    buildDisplayName: () => 'LessWrong',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 20,
    },
  },
  {
    id: 'gwern',
    name: 'Gwern',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'gwern',
    variableLabel: 'Archive Scope',
    placeholder: 'Main Gwern archive',
    helperText: 'Uses the custom Gwern adapter for sitemap-backed archive depth and newest-page live fetch.',
    buildHandle: () => 'https://gwern.net',
    buildDisplayName: () => 'Gwern',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 20,
    },
  },
  {
    id: 'dario-amodei',
    name: 'Dario Amodei Blog',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'dario',
    variableLabel: 'Archive Scope',
    placeholder: 'Dario Amodei personal site',
    helperText: 'Uses the custom Dario adapter for essays and posts from darioamodei.com.',
    buildHandle: () => 'https://darioamodei.com',
    buildDisplayName: () => 'Dario Amodei',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 10,
    },
  },
  {
    id: 'pipecraft',
    name: 'Pipecraft (Tornike Gomareli)',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'pipecraft',
    variableLabel: 'Archive Scope',
    placeholder: 'Tornike Gomareli personal site',
    helperText: 'Uses the custom Pipecraft adapter for posts and essays from pipecraft.me, read in full from its own API.',
    buildHandle: () => 'https://www.pipecraft.me/',
    buildDisplayName: () => 'Pipecraft',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 5,
    },
  },
  {
    id: 'github-trending',
    name: 'GitHub Trending',
    platform: 'rss',
    variableName: 'language',
    variableLabel: 'Language',
    optionalVariable: true,
    placeholder: 'All languages',
    helperText: 'Today\'s trending repositories, each a post with its README, from the GitHubTrendingRSS feed (github.com has none). Leave empty for all languages. For the week or the month, change daily/ to weekly/ or monthly/ in the URL.',
    buildHandle: (value) => {
      const language = value.trim().toLowerCase().replace(/\s+/g, '-');
      return `https://mshibanami.github.io/GitHubTrendingRSS/daily/${encodeURIComponent(language || 'all')}.xml`;
    },
    buildDisplayName: (value) => (value.trim() ? `GitHub Trending · ${value.trim()}` : 'GitHub Trending'),
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 25,
    },
  },
  {
    id: 'deeplearning-batch',
    name: 'DeepLearning.AI The Batch',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'the-batch',
    variableLabel: 'Archive Scope',
    placeholder: 'The Batch newsletter',
    helperText: 'Uses the custom The Batch adapter with sitemap-backed issue discovery and full newsletter archive.',
    buildHandle: () => 'https://www.deeplearning.ai/the-batch/',
    buildDisplayName: () => 'DeepLearning.AI The Batch',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 10,
    },
  },
  {
    id: 'philschmid-cloud-attention',
    name: 'Cloud Attention',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'cloud-attention',
    variableLabel: 'Archive Scope',
    placeholder: 'Phil Schmid newsletter archive',
    helperText: 'Uses the custom Cloud Attention adapter for paginated issue discovery and full issue ingestion.',
    buildHandle: () => 'https://www.philschmid.de/cloud-attention',
    buildDisplayName: () => 'Phil Schmid Cloud Attention',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 10,
    },
  },
  {
    id: 'ztm-ml-monthly',
    name: 'ZTM AI & ML Monthly',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'machine-learning-monthly',
    variableLabel: 'Archive Scope',
    placeholder: 'Zero To Mastery monthly AI newsletter',
    helperText: 'Uses the custom ZTM adapter for full AI & ML Monthly archive discovery and post hydration.',
    buildHandle: () => 'https://zerotomastery.io/newsletters/machine-learning-monthly/1/',
    buildDisplayName: () => 'Zero To Mastery AI & ML Monthly',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 10,
    },
  },
  {
    id: 'youtube-handle',
    name: 'YouTube',
    platform: 'youtube',
    variableName: 'channel',
    variableLabel: 'Channel Handle',
    placeholder: 'Enter channel handle...',
    helperText: 'Use the YouTube @handle. Example: LAWRENCESYSTEMS',
    buildHandle: (value) => `https://www.youtube.com/@${value.replace(/^@/, '').trim()}`,
    buildDisplayName: (value) => `@${value.replace(/^@/, '').trim()}`,
    defaultSettings: {
      fetch_delay_seconds: 2,
      priority: 999,
      max_posts_per_fetch: 5,
    },
  },
];

/** The address a template always builds, whatever its field (Pipecraft, Gwern…); null when the
 *  field changes it (Nitter, YouTube, GitHub Trending), so it can be added once per value. */
function fixedHandle(template: Template): string | null {
  const handle = template.buildHandle('a');
  return handle === template.buildHandle('b') ? handle : null;
}

/** An address compared loosely: no scheme, www. or trailing slash, any case. */
function sameAddress(address: string): string {
  return address.trim().toLowerCase().replace(/^https?:\/\/(www\.)?/, '').replace(/\/+$/, '');
}

/** A path as the server keeps it: "news" -> "/news/"; "" stays "" (the server infers it). */
function normalisePath(path: string): string {
  const inner = path.trim().replace(/^\/+|\/+$/g, '');
  return path.trim() ? (inner ? `/${inner}/` : '/') : '';
}

/** A preview item's local calendar date; "" without one. */
function calendarDate(value: string | null): string {
  const date = toDate(value);
  return date ? localDateISO(date) : '';
}

/** An address as a line shows it: no scheme. */
function shortAddress(address: string): string {
  return address.replace(/^https?:\/\//, '');
}

interface AddSourceModalProps {
  platform: string;
  /** The addresses already in the sources: a one-address template among them is not offered. */
  existingAddresses?: readonly string[];
  onClose: () => void;
  onAdd: (source: {
    handle_or_url: string;
    display_name: string;
    fetch_delay_seconds: number;
    priority: number;
    max_posts_per_fetch: number;
    state: SourceState;
    page_watch?: { prefix: string };
  }) => void;
}

export default function AddSourceModal({ platform, existingAddresses = [], onClose, onAdd }: AddSourceModalProps) {
  const api = useApi();
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [templateVariable, setTemplateVariable] = useState('');
  const [handleOrUrl, setHandleOrUrl] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [displayNameManuallyEdited, setDisplayNameManuallyEdited] = useState(false);
  const [fetchDelay, setFetchDelay] = useState(1);
  const [priority, setPriority] = useState(999);
  const [maxPosts, setMaxPosts] = useState(50);
  const [isResolvingChannel, setIsResolvingChannel] = useState(false);
  const [resolvedChannelName, setResolvedChannelName] = useState<string | null>(null);
  // A Substack URL offers the paid-subscription cookie; it saves to Connections, shared by every Substack source.
  const substack = isSubstackUrl(handleOrUrl);
  const connections = useConnections(substack);
  const substackSid = connections.data?.providers.find((p) => p.provider === 'substack')?.fields.find((f) => f.key === 'sid');
  const [sid, setSid] = useState('');
  const [sidError, setSidError] = useState<string | null>(null);
  const saveSid = useSaveCredential();
  
  const youtubeLookupValue = selectedTemplate?.id === 'youtube-handle'
    ? (templateVariable.trim() ? selectedTemplate.buildHandle(templateVariable.trim()) : '')
    : (platform === 'youtube' ? handleOrUrl.trim() : '');

  // Get templates for this platform, less the one-address ones already added (Pipecraft, Gwern…).
  const added = new Set(existingAddresses.map(sameAddress));
  const availableTemplates = TEMPLATES.filter((t) => {
    const fixed = fixedHandle(t);
    return t.platform === platform && !(fixed && added.has(sameAddress(fixed)));
  });

  // Update URL when template variable changes
  useEffect(() => {
    if (selectedTemplate && (templateVariable || selectedTemplate.optionalVariable)) {
      const normalized = templateVariable.trim();
      const sourceValue = selectedTemplate.buildHandle(normalized);
      setHandleOrUrl(sourceValue);
      
      // Auto-fill display name if user hasn't manually edited it
      if (!displayNameManuallyEdited) {
        setDisplayName(selectedTemplate.buildDisplayName?.(normalized) || normalized);
      }
    }
  }, [selectedTemplate, templateVariable, displayNameManuallyEdited]);

  useEffect(() => {
    if (platform !== 'youtube' || !youtubeLookupValue) {
      setIsResolvingChannel(false);
      setResolvedChannelName(null);
      return;
    }

    let cancelled = false;
    setIsResolvingChannel(true);

    const timeout = window.setTimeout(async () => {
      const preview = await api.listYouTubeChannelVideos(youtubeLookupValue, 1);
      if (cancelled) return;

      const channelTitle = preview.videos?.[0]?.channel_title?.trim();
      if (channelTitle) {
        setResolvedChannelName(channelTitle);
        if (!displayNameManuallyEdited) {
          setDisplayName(channelTitle);
        }
      } else {
        setResolvedChannelName(null);
      }
      setIsResolvingChannel(false);
    }, 450);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [api, platform, youtubeLookupValue, displayNameManuallyEdited]);

  // A typed address that is not a feed: after a pause (or on leaving the field) the finder
  // looks for the page's feed, and the field becomes it (issue 0026). Add waits meanwhile.
  const address = handleOrUrl.trim();
  const findsFeed = platform === 'rss' && !selectedTemplate;
  const [lookup, setLookup] = useState('');
  const [finding, setFinding] = useState<(FeedFinding & { for: string }) | null>(null);
  const foundFeeds = finding?.feeds ?? [];
  const settled = !!finding && (finding.for === address || foundFeeds.some((feed) => feed.url === address));
  const looking = findsFeed && !!address && !settled;
  const alreadyAdded = !!address && added.has(sameAddress(address));

  useEffect(() => {
    if (!findsFeed || !address) return;
    const timeout = window.setTimeout(() => setLookup(address), 600);
    return () => window.clearTimeout(timeout);
  }, [findsFeed, address]);

  useEffect(() => {
    if (!lookup || (finding && (finding.for === lookup || (finding.feeds ?? []).some((feed) => feed.url === lookup)))) return;
    let cancelled = false;
    void api.findFeed(lookup).then((result) => {
      if (cancelled) return;
      setFinding({ ...result, for: lookup });
      const first = result.status === 'feed' || result.status === 'found' ? result.feeds?.[0] : undefined;
      if (first) {
        setHandleOrUrl(first.url);
        if (!displayNameManuallyEdited && first.title) setDisplayName(first.title);
      }
    });
    return () => { cancelled = true; };
  }, [api, lookup, finding, displayNameManuallyEdited]);

  const chooseFeed = (feed: FoundFeed) => {
    setHandleOrUrl(feed.url);
    if (!displayNameManuallyEdited && feed.title) setDisplayName(feed.title);
  };

  const feedNote = !findsFeed || !address ? null
    : looking ? 'Looking for a feed…'
      : alreadyAdded ? null
        : finding?.success === false ? 'Could not look for a feed; the address is added as typed.'
          : finding?.status === 'direct' ? 'INSIGHT reads this site directly'
            : finding?.status === 'none' ? 'No feed found on this page'
              : finding?.status === 'found' && foundFeeds.length === 1 ? `Found the feed for this page: ${shortAddress(foundFeeds[0].url)}`
                : null;
  // No feed: the page itself can be followed, its articles read from its links and the
  // sitemap (issue 0028). The preview is asked again when the path changes.
  const [followFor, setFollowFor] = useState<string | null>(null);
  const [path, setPath] = useState('');
  const [pagePreview, setPagePreview] = useState<(PageWatchPreview & { for: string; asked: string }) | null>(null);
  const following = findsFeed && settled && finding?.status === 'none' && followFor === address;
  const askedPath = normalisePath(path);
  const previewed = !!pagePreview && pagePreview.for === address
    && (!askedPath || askedPath === pagePreview.asked || askedPath === pagePreview.prefix);
  const pageItems = previewed ? pagePreview?.items ?? [] : [];

  useEffect(() => {
    if (!following || previewed) return;
    let cancelled = false;
    const timeout = window.setTimeout(() => {
      void api.previewPageWatch(address, askedPath || undefined).then((result) => {
        if (cancelled) return;
        setPagePreview({ ...result, for: address, asked: askedPath });
        if (!askedPath && result.prefix) setPath(result.prefix);
      });
    }, askedPath ? 600 : 0);
    return () => { cancelled = true; window.clearTimeout(timeout); };
  }, [api, following, previewed, address, askedPath]);

  const pageNote = !following ? null
    : !previewed ? 'Looking for articles…'
      : pagePreview?.success === false ? `Could not read this page: ${pagePreview.error ?? 'unknown error'}`
        : pageItems.length === 0 ? 'This page\'s articles can\'t be read without a browser (it builds them with JavaScript).'
          : `Found ${pagePreview?.found} article${pagePreview?.found === 1 ? '' : 's'} under ${pagePreview?.prefix}${pagePreview?.sitemap ? ' (from the sitemap)' : ''}`;
  const canFollow = following && previewed && pageItems.length > 0;

  const canAdd = !!address && !saveSid.isPending && !looking && !alreadyAdded
    && !(findsFeed && finding?.status === 'none' && !canFollow);

  const handleTemplateClick = (template: Template) => {
    setSelectedTemplate(template);
    setFetchDelay(template.defaultSettings.fetch_delay_seconds);
    setPriority(template.defaultSettings.priority);
    setMaxPosts(template.defaultSettings.max_posts_per_fetch);
    // Clear previous values
    const initialValue = template.defaultVariableValue || '';
    setTemplateVariable(initialValue);
    const builds = Boolean(initialValue || template.optionalVariable);
    setHandleOrUrl(builds ? template.buildHandle(initialValue) : '');
    setDisplayName(builds ? (template.buildDisplayName?.(initialValue) || initialValue) : '');
    setDisplayNameManuallyEdited(false); // Reset manual edit flag
    setIsResolvingChannel(false);
    setResolvedChannelName(null);
  };

  const handleAdd = async () => {
    if (!handleOrUrl.trim()) {
      return;
    }
    const cookie = substack ? cookieValue(sid) : '';
    if (cookie) {
      setSidError(null);
      try {
        await saveSid.mutateAsync({ provider: 'substack', key: 'sid', value: cookie });
        setSid('');
      } catch (err) {
        setSidError(errorMessage(err));
        return;
      }
    }

    onAdd({
      // A followed page is read as an address: it needs its scheme.
      handle_or_url: canFollow && !/^https?:\/\//i.test(address) ? `https://${address}` : address,
      display_name: displayName.trim(),
      fetch_delay_seconds: fetchDelay,
      priority,
      max_posts_per_fetch: maxPosts,
      state: 'enabled',
      ...(canFollow && pagePreview?.prefix ? { page_watch: { prefix: pagePreview.prefix } } : {}),
    });

    onClose();
  };

  const hint = 'mt-1 text-[0.75rem] text-fg-3';
  const label = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent title="Add source" className="w-[min(32rem,calc(100vw-2rem))]">
        <form
          className="mt-4 space-y-5"
          onSubmit={(event) => { event.preventDefault(); if (canAdd) void handleAdd(); }}
        >
          {availableTemplates.length > 0 && (
            <div>
              <span className={label}>Start from a template</span>
              <div className="flex flex-wrap gap-2">
                {availableTemplates.map((template) => (
                  <FilterChip
                    key={template.id}
                    selected={selectedTemplate?.id === template.id}
                    onClick={() => handleTemplateClick(template)}
                  >
                    {template.name}
                  </FilterChip>
                ))}
              </div>
            </div>
          )}

          {selectedTemplate && (
            <div className="rounded-md border border-line bg-surface p-3">
              <label htmlFor="template-var" className={label}>
                {(selectedTemplate.variableLabel || selectedTemplate.variableName.charAt(0).toUpperCase() + selectedTemplate.variableName.slice(1))} (for {selectedTemplate.name})
              </label>
              <Input
                id="template-var"
                value={templateVariable}
                onChange={(e) => setTemplateVariable(e.target.value)}
                placeholder={selectedTemplate.placeholder || `Enter ${selectedTemplate.variableName}…`}
              />
              <p className="mt-1.5 font-mono text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]">
                → {selectedTemplate.buildHandle(templateVariable || (selectedTemplate.optionalVariable ? '' : `{${selectedTemplate.variableName}}`))}
              </p>
              {selectedTemplate.helperText && <p className={hint}>{selectedTemplate.helperText}</p>}
              {platform === 'youtube' && youtubeLookupValue && (
                <p className="mt-2 text-[0.75rem] text-fg-2">
                  {isResolvingChannel
                    ? 'Resolving channel title…'
                    : resolvedChannelName
                      ? `Resolved channel: ${resolvedChannelName}`
                      : 'Could not resolve the channel title yet. The handle still works as a source.'}
                </p>
              )}
            </div>
          )}

          {availableTemplates.length > 0 && (
            <div className="flex items-center gap-3" aria-hidden="true">
              <div className="flex-1 border-t border-line" />
              <span className="text-[0.75rem] text-fg-3">or enter it yourself</span>
              <div className="flex-1 border-t border-line" />
            </div>
          )}

          <div>
            <label htmlFor="handle_or_url" className={label}>Feed URL or handle</label>
            <Input
              id="handle_or_url"
              value={handleOrUrl}
              onChange={(e) => setHandleOrUrl(e.target.value)}
              placeholder="https://example.com/feed.xml"
              disabled={!!selectedTemplate && !!templateVariable}
              autoComplete="off"
              onBlur={() => { if (findsFeed && address) setLookup(address); }}
            />
            {alreadyAdded && !looking ? <p role="status" className={hint}>This feed is already in your sources</p> : null}
            {feedNote ? <p role="status" className={hint}>{feedNote}</p> : null}
            {findsFeed && settled && finding?.status === 'none' && !alreadyAdded && !following ? (
              <Button size="sm" className="mt-2" onClick={() => setFollowFor(address)}>Follow this page instead</Button>
            ) : null}
            {following ? (
              <div className="mt-2 space-y-3 rounded-md border border-line p-3" data-testid="page-watch">
                <p role="status" className="text-[0.8125rem] text-fg-2">{pageNote}</p>
                {pageItems.length > 0 ? (
                  <ul className="space-y-1">
                    {pageItems.map((item) => (
                      <li key={item.url} className="flex gap-2 text-[0.8125rem] text-fg">
                        <span className="min-w-0 flex-1 truncate">{item.title}</span>
                        <span className="shrink-0 tabular-nums text-fg-3">{calendarDate(item.published_at)}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <div>
                  <label htmlFor="page_watch_path" className={label}>Path <span className="font-normal text-fg-3">(optional)</span></label>
                  <Input
                    id="page_watch_path"
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                    placeholder="/news/"
                    autoComplete="off"
                    spellCheck={false}
                    className="font-mono"
                  />
                  <p className={hint}>Only the site&apos;s pages under this path are followed.</p>
                </div>
              </div>
            ) : null}
            {findsFeed && settled && finding?.status === 'found' && foundFeeds.length > 1 ? (
              <fieldset className="mt-2">
                <legend className={hint}>This page has {foundFeeds.length} feeds</legend>
                <div className="mt-1.5 space-y-1.5">
                  {foundFeeds.map((feed) => (
                    <label key={feed.url} className="flex cursor-pointer items-start gap-2.5 text-[0.8125rem] text-fg">
                      <input
                        type="radio"
                        name="found_feed"
                        className="mt-1 accent-current"
                        checked={address === feed.url}
                        onChange={() => chooseFeed(feed)}
                      />
                      <span className="min-w-0">
                        {feed.title || shortAddress(feed.url)}
                        <span className="block font-mono text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">{shortAddress(feed.url)}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ) : null}
          </div>

          {substack ? (
            <div className="space-y-2 rounded-md border border-line p-3" data-testid="substack-sid">
              {substackSid?.set ? (
                <p className="text-[0.8125rem] text-fg-2">
                  Paid posts: your Substack session is set in Connections
                  {substackSid.last4 ? <span className="font-mono"> (••••{substackSid.last4})</span> : null}. Every Substack source shares it.
                </p>
              ) : (
                <>
                  <label htmlFor="substack_sid" className={label}>
                    Paid subscription? Add your substack.sid <span className="font-normal text-fg-3">(optional)</span>
                  </label>
                  <Input
                    id="substack_sid"
                    type="password"
                    value={sid}
                    onChange={(e) => setSid(e.target.value)}
                    placeholder="Paste the substack.sid cookie"
                    autoComplete="off"
                    spellCheck={false}
                    aria-invalid={sidError ? true : undefined}
                    className="font-mono"
                  />
                  <p className={hint}>Saved to Connections and shared by every Substack source. Without it, paid posts arrive as teasers.</p>
                  <SubstackHowTo />
                  {sidError ? (
                    <p role="alert" className="text-[0.75rem] text-fg [overflow-wrap:anywhere]">
                      <span aria-hidden="true" className="mr-1 font-semibold">×</span>{sidError}
                    </p>
                  ) : null}
                </>
              )}
            </div>
          ) : null}

          <div>
            <label htmlFor="display_name" className={label}>Name</label>
            <Input
              id="display_name"
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                setDisplayNameManuallyEdited(true);
              }}
              placeholder="Optional; derived from the URL when empty"
            />
          </div>

          <details className="group">
            <summary className="cursor-pointer select-none text-[0.8125rem] text-fg-2 hover:text-fg">Advanced</summary>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="fetch_delay" className={label}>Fetch delay (seconds)</label>
                <Input
                  id="fetch_delay"
                  type="number"
                  min="0"
                  max="60"
                  value={fetchDelay}
                  onChange={(e) => setFetchDelay(parseInt(e.target.value) || 1)}
                  className="tabular-nums"
                />
                <p className={hint}>Wait after fetching this source.</p>
              </div>
              <div>
                <label htmlFor="priority" className={label}>Priority</label>
                <Input
                  id="priority"
                  type="number"
                  min="1"
                  max="9999"
                  value={priority}
                  onChange={(e) => setPriority(parseInt(e.target.value) || 999)}
                  className="tabular-nums"
                />
                <p className={hint}>Lower is fetched first.</p>
              </div>
              <div>
                <label htmlFor="max_posts" className={label}>Max posts per fetch</label>
                <Input
                  id="max_posts"
                  type="number"
                  min="1"
                  max="200"
                  value={maxPosts}
                  onChange={(e) => setMaxPosts(parseInt(e.target.value) || 50)}
                  className="tabular-nums"
                  disabled
                />
                <p className={hint}>Not enforced yet.</p>
              </div>
            </div>
          </details>

          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={!canAdd}>
              <Plus aria-hidden="true" /> Add source
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
