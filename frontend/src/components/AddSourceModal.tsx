import React, { useState, useEffect } from 'react';
import { Plus } from 'lucide-react';
import { useApi } from '../services/ApiContext';
import { Button, Dialog, DialogContent, DialogFooter, FilterChip, Input } from './ui';
import { SubstackHowTo, cookieValue, isSubstackUrl, useConnections, useSaveCredential } from './connections';
import { errorMessage } from '../lib/apiError';
import { localDateISO, toDate } from '../lib/dates';
import type { FeedFinding, FoundFeed, PageOffer, PageWatchPreview } from '../services/api';
import BookmarkletHint from './BookmarkletHint';
import AddSeveralSources, { type AddedSource } from './AddSeveralSources';
import { HOMEPAGE_WARNING, sameAddress, shortAddress, siteName, withScheme } from '../lib/addresses';

interface Template {
  id: string;
  name: string;
  // None: the template always builds one address (Pipecraft, Gwern…), so there is no field.
  variableName?: string;
  // An empty variable still builds a source (GitHub Trending: all languages).
  optionalVariable?: boolean;
  variableLabel?: string;
  placeholder?: string;
  helperText: string;
  buildHandle: (value: string) => string;
  buildDisplayName: (value: string) => string;
  /** A field value as "Added: …" names it under the field; the value itself when unset. */
  addedName?: (value: string) => string;
  // Seconds to wait after fetching it; 1 when unset.
  fetchDelay?: number;
}

// Hardcoded templates
const TEMPLATES: Template[] = [
  {
    id: 'nitter',
    name: 'Nitter',
    variableName: 'username',
    variableLabel: 'Username',
    placeholder: 'Enter username...',
    helperText: 'Creates a source like https://nitter.local/{username}/rss',
    buildHandle: (value) => `https://nitter.local/${value.replace(/^@/, '').trim()}/rss`,
    buildDisplayName: (value) => value.replace(/^@/, '').trim(),
    fetchDelay: 10,
  },
  {
    id: 'telegram-rss',
    name: 'Telegram RSS',
    variableName: 'username',
    variableLabel: 'Channel Username',
    placeholder: 'Enter channel username...',
    helperText: 'Creates a source like https://telegram.local/rss/seeallochnaya?limit=50',
    buildHandle: (value) => `https://telegram.local/rss/${value.replace(/^@/, '').trim()}?limit=50`,
    buildDisplayName: (value) => value.replace(/^@/, '').trim(),
    fetchDelay: 5,
  },
  {
    id: 'lesswrong',
    name: 'LessWrong',
    helperText: 'LessWrong\'s posts; the archive reaches far back.',
    buildHandle: () => 'https://www.lesswrong.com/feed.xml',
    buildDisplayName: () => 'LessWrong',
  },
  {
    id: 'gwern',
    name: 'Gwern',
    helperText: 'Gwern\'s essays from gwern.net; the archive reaches every page.',
    buildHandle: () => 'https://gwern.net',
    buildDisplayName: () => 'Gwern',
  },
  {
    id: 'dario-amodei',
    name: 'Dario Amodei Blog',
    helperText: 'Dario Amodei\'s essays and posts from darioamodei.com.',
    buildHandle: () => 'https://darioamodei.com',
    buildDisplayName: () => 'Dario Amodei',
  },
  {
    id: 'pipecraft',
    name: 'Pipecraft (Tornike Gomareli)',
    helperText: 'Tornike Gomareli\'s posts and essays from pipecraft.me, read in full.',
    buildHandle: () => 'https://www.pipecraft.me/',
    buildDisplayName: () => 'Pipecraft',
  },
  {
    id: 'github-trending',
    name: 'GitHub Trending',
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
    addedName: (value) => (value === 'all' ? 'All languages' : value.charAt(0).toUpperCase() + value.slice(1).replace(/-/g, ' ')),
  },
  {
    id: 'deeplearning-batch',
    name: 'DeepLearning.AI The Batch',
    helperText: 'Every issue of The Batch newsletter; the archive reaches its first issue.',
    buildHandle: () => 'https://www.deeplearning.ai/the-batch/',
    buildDisplayName: () => 'DeepLearning.AI The Batch',
  },
  {
    id: 'philschmid-cloud-attention',
    name: 'Cloud Attention',
    helperText: 'Every issue of Phil Schmid\'s Cloud Attention newsletter, read in full.',
    buildHandle: () => 'https://www.philschmid.de/cloud-attention',
    buildDisplayName: () => 'Phil Schmid Cloud Attention',
  },
  {
    id: 'ztm-ml-monthly',
    name: 'ZTM AI & ML Monthly',
    helperText: 'Every issue of Zero To Mastery\'s AI & ML Monthly newsletter, read in full.',
    buildHandle: () => 'https://zerotomastery.io/newsletters/machine-learning-monthly/1/',
    buildDisplayName: () => 'Zero To Mastery AI & ML Monthly',
  },
];

/** The address a template always builds, whatever its field (Pipecraft, Gwern…); null when the
 *  field changes it (Nitter, GitHub Trending), so it can be added once per value. */
function fixedHandle(template: Template): string | null {
  return template.variableName ? null : template.buildHandle('');
}

/** The field values of a template already among the addresses (GitHub Trending: All languages, Python). */
function addedValues(template: Template, addresses: readonly string[]): string[] {
  const marker = 'insightvalue';
  const [head, tail = ''] = sameAddress(template.buildHandle(marker)).split(marker);
  return addresses.map(sameAddress)
    .filter((address) => address.length > head.length + tail.length && address.startsWith(head) && address.endsWith(tail))
    .map((address) => decodeURIComponent(address.slice(head.length, address.length - tail.length)))
    .map((value) => template.addedName?.(value) ?? value);
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

interface AddSourceModalProps {
  /** The addresses already in the sources: a one-address template among them is not offered. */
  existingAddresses?: readonly string[];
  onClose: () => void;
  onAdd: (source: {
    handle_or_url: string;
    display_name: string;
    fetch_delay_seconds: number;
    page_watch?: { prefix: string };
  }) => void;
  /** Several sources were added at once (issue 0035): fetch them; close when all were added. */
  onAddMany?: (added: AddedSource[], close: boolean) => void;
}

export default function AddSourceModal({ existingAddresses = [], onClose, onAdd, onAddMany }: AddSourceModalProps) {
  const api = useApi();
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [templateVariable, setTemplateVariable] = useState('');
  const [handleOrUrl, setHandleOrUrl] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [displayNameManuallyEdited, setDisplayNameManuallyEdited] = useState(false);
  const [fetchDelay, setFetchDelay] = useState(1);
  const [several, setSeveral] = useState(false);
  // A Substack URL offers the paid-subscription cookie; it saves to Connections, shared by every Substack source.
  const substack = isSubstackUrl(handleOrUrl);
  const connections = useConnections(substack);
  const substackSid = connections.data?.providers.find((p) => p.provider === 'substack')?.fields.find((f) => f.key === 'sid');
  const [sid, setSid] = useState('');
  const [sidError, setSidError] = useState<string | null>(null);
  const saveSid = useSaveCredential();
  
  // The templates, less the one-address ones already added (Pipecraft, Gwern…).
  const added = new Set(existingAddresses.map(sameAddress));
  const availableTemplates = TEMPLATES.filter((t) => {
    const fixed = fixedHandle(t);
    return !(fixed && added.has(sameAddress(fixed)));
  });

  // Update URL when template variable changes
  useEffect(() => {
    if (selectedTemplate && (templateVariable || selectedTemplate.optionalVariable)) {
      const normalized = templateVariable.trim();
      const sourceValue = selectedTemplate.buildHandle(normalized);
      setHandleOrUrl(sourceValue);
      
      // Auto-fill display name if user hasn't manually edited it
      if (!displayNameManuallyEdited) {
        setDisplayName(selectedTemplate.buildDisplayName(normalized));
      }
    }
  }, [selectedTemplate, templateVariable, displayNameManuallyEdited]);

  // A typed address that is not a feed: after a pause (or on leaving the field) the finder
  // looks for the page's feed, and the field becomes it (issue 0026). Add waits meanwhile.
  const address = handleOrUrl.trim();
  const findsFeed = !selectedTemplate;
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

  // Typing on drops the lookup in flight: its answer would replace what is typed now.
  useEffect(() => {
    if (!lookup || address !== lookup
      || (finding && (finding.for === lookup || (finding.feeds ?? []).some((feed) => feed.url === lookup)))) return;
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
  }, [api, lookup, address, finding, displayNameManuallyEdited]);

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
  // sitemap (issue 0028). The preview is asked again when the path changes. For a site's home
  // page, the finder offers the site's own blog or news pages instead (issue 0041).
  const [follow, setFollow] = useState<{ for: string; page: string } | null>(null);
  const [path, setPath] = useState('');
  const [pagePreview, setPagePreview] = useState<(PageWatchPreview & { for: string; asked: string }) | null>(null);
  const noFeed = findsFeed && settled && finding?.status === 'none';
  const offers = noFeed ? finding?.pages ?? [] : [];
  const following = noFeed && follow?.for === address;
  const followed = following && follow ? follow.page : address;
  const followsHome = !!finding?.homepage && followed === address;
  const askedPath = normalisePath(path);
  const previewed = !!pagePreview && pagePreview.for === followed
    && (!askedPath || askedPath === pagePreview.asked || askedPath === pagePreview.prefix);
  const pageItems = previewed ? pagePreview?.items ?? [] : [];

  useEffect(() => {
    if (!following || previewed) return;
    let cancelled = false;
    const timeout = window.setTimeout(() => {
      void api.previewPageWatch(followed, askedPath || undefined).then((result) => {
        if (cancelled) return;
        setPagePreview({ ...result, for: followed, asked: askedPath });
        if (!askedPath && result.prefix) setPath(result.prefix);
      });
    }, askedPath ? 600 : 0);
    return () => { cancelled = true; window.clearTimeout(timeout); };
  }, [api, following, previewed, followed, askedPath]);

  // An offered page comes with its preview: following it asks nothing more.
  const followOffer = (offer: PageOffer) => {
    setPagePreview({ success: true, ...offer, for: offer.url, asked: '' });
    setPath(offer.prefix);
    setFollow({ for: address, page: offer.url });
  };
  const offerLabel = (offer: PageOffer) => `Follow ${siteName(offer.url)}: ${offer.found} article${offer.found === 1 ? '' : 's'}`;
  const otherOffers = offers.filter((offer) => offer.url !== (following ? followed : offers[0]?.url));

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
    setFetchDelay(template.fetchDelay ?? 1);
    // Clear previous values
    setTemplateVariable('');
    const builds = !template.variableName || Boolean(template.optionalVariable);
    setHandleOrUrl(builds ? template.buildHandle('') : '');
    setDisplayName(builds ? template.buildDisplayName('') : '');
    setDisplayNameManuallyEdited(false); // Reset manual edit flag
  };

  const handleAdd = async () => {
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
      handle_or_url: canFollow ? withScheme(followed) : address,
      // A site's blog followed keeps the pasted address as its name ("stripe.com").
      display_name: displayName.trim() || (canFollow && followed !== address ? siteName(address) : ''),
      fetch_delay_seconds: fetchDelay,
      ...(canFollow && pagePreview?.prefix ? { page_watch: { prefix: pagePreview.prefix } } : {}),
    });

    onClose();
  };

  const hint = 'mt-1 text-[0.75rem] text-fg-3';
  const label = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';
  const templateAdded = selectedTemplate?.variableName ? addedValues(selectedTemplate, existingAddresses) : [];

  if (several && onAddMany) {
    return (
      <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
        <DialogContent title="Add several sources" className="w-[min(40rem,calc(100vw-2rem))]">
          <AddSeveralSources existingAddresses={existingAddresses} onBack={() => setSeveral(false)} onClose={onClose} onAdded={onAddMany} />
        </DialogContent>
      </Dialog>
    );
  }

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
              {selectedTemplate.variableName ? (
                <>
                  <label htmlFor="template-var" className={label}>
                    {selectedTemplate.variableLabel} (for {selectedTemplate.name})
                  </label>
                  <Input
                    id="template-var"
                    value={templateVariable}
                    onChange={(e) => setTemplateVariable(e.target.value)}
                    placeholder={selectedTemplate.placeholder}
                  />
                  <p className="mt-1.5 font-mono text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]">
                    → {selectedTemplate.buildHandle(templateVariable || (selectedTemplate.optionalVariable ? '' : `{${selectedTemplate.variableName}}`))}
                  </p>
                  {templateAdded.length ? <p className={hint}>Added: {templateAdded.join(', ')}</p> : null}
                </>
              ) : null}
              <p className={selectedTemplate.variableName ? hint : 'text-[0.8125rem] text-fg-2'}>{selectedTemplate.helperText}</p>
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
            <div className="flex items-baseline justify-between gap-3">
              <label htmlFor="handle_or_url" className={label}>Feed URL or handle</label>
              {onAddMany ? (
                <button type="button" className="text-[0.8125rem] text-fg-2 underline underline-offset-2 hover:text-fg" onClick={() => setSeveral(true)}>
                  Add several…
                </button>
              ) : null}
            </div>
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
            {noFeed && !alreadyAdded && !following && offers.length > 0 ? (
              <Button size="sm" className="mt-2" onClick={() => followOffer(offers[0])}>{offerLabel(offers[0])}</Button>
            ) : noFeed && !alreadyAdded && !following ? (
              <>
                {finding?.homepage ? <p className={hint}>{HOMEPAGE_WARNING}</p> : null}
                <Button size="sm" className="mt-2" onClick={() => setFollow({ for: address, page: address })}>Follow this page instead</Button>
              </>
            ) : null}
            {noFeed && !alreadyAdded && otherOffers.length > 0 ? (
              <details className="mt-2">
                <summary className="cursor-pointer select-none text-[0.8125rem] text-fg-2 hover:text-fg">Other pages on this site</summary>
                <ul className="mt-1.5 space-y-1">
                  {otherOffers.map((offer) => (
                    <li key={offer.url}>
                      <button type="button" className="text-[0.8125rem] text-fg-2 underline underline-offset-2 hover:text-fg" onClick={() => followOffer(offer)}>
                        {offerLabel(offer)}
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
            {following ? (
              <div className="mt-2 space-y-3 rounded-md border border-line p-3" data-testid="page-watch">
                {followed !== address ? <p className="text-[0.8125rem] text-fg">Following {siteName(followed)}</p> : null}
                {followsHome ? <p className="text-[0.8125rem] text-fg-2">{HOMEPAGE_WARNING}</p> : null}
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
            <div className="mt-3 sm:w-1/2">
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
          </details>

          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={!canAdd}>
              <Plus aria-hidden="true" /> Add source
            </Button>
          </DialogFooter>
          {/* One page rather than a whole site (issue 0031). */}
          <div className="border-t border-line pt-3"><BookmarkletHint /></div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
